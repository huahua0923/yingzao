// 「检查」视图 —— 引擎逐层验收单的前端。
//
// 路由（hash，零依赖，可分享）：
//     #/checks             全库红绿灯墙（按判据一行）
//     #/checks/<楼号>       该栋的逐层验收单
//
// 这一层只做四件事：取数、分派、把错误说清楚、把不该静默的状态摆出来。
// **一个判据都不算** —— 墙上每一格的状态、验收单上每一条结论都原样来自产物
// （用户明令：前端只显示引擎给的结论；智能体/前端都不许自己判）。
//
// ★★ 三条「不许静默」的规矩，写在这里一次：
//   1. 接口没起来 ⇒ 明确画「接口不可用」，**不画空表**。
//      空表会被读成「全都没问题」（memory: gauge-coverage-invisible-in-summary）。
//   2. 「没量成」不是「通过」—— 见 status.js 与 sheet.js 的措辞。
//   3. 只有一部分楼有产物 ⇒ 墙面上必须写明分母，别让"没跑"变成"绿的"。
import { el, add, mount } from '../dom.js';
import { API, ApiError } from '../api.js';
import { renderWall, renderLegend } from './checks/wall.js';
import { renderSheet } from './checks/sheet.js';
import { renderRunPanel } from './checks/run.js';
import { scanFleet, listBuildings } from './checks/scan.js';
import { paintFleet } from './checks/fleet.js';

export const label = '检查';

// 模块内的共享状态：注册表/楼栋清单/能力只取一次；墙的扫描结果也留着，
// 从某栋回墙时不必重扫。
const state = {
  registry: null, registryMeta: null,
  buildings: null, caps: null,
  fleet: null, progress: null,
  onlyProblem: false,
  abort: null,
};
// 路由切走时把上一轮的扫描停掉（否则回来的路上会往一个已经不在的节点里写）。
let disposed = false;

export function dispose() {
  disposed = true;
  state.abort?.abort();
  state.abort = null;
}

/** 接口不可用 / 出错的统一面板 —— 说得比空表多。 */
function errorPanel(err, opts = {}) {
  const e = err instanceof ApiError ? err : new ApiError('unknown', String(err));
  const down = e.code === 'network' || e.status === 0;
  const box = el('div', { class: `chk-panic${down ? ' down' : ''}` },
    el('h2', { class: 'chk-panic-h', text: down ? '接口不可用' : `取数失败：${e.code}` }),
    el('p', { class: 'chk-panic-msg', text: e.message || String(err) }));
  add(box, el('div', { class: 'chk-panic-body' },
    down
      ? el('div', {},
        el('p', {}, el('b', { text: '这一屏现在什么都没有 —— 所以这里不画表。' }),
          '空表会被读成「全都没问题」，而实际是「一条都没量」。'),
        el('p', { class: 'dim' },
          '后端地址：', el('code', { text: window.GYM3D_API_BASE || '同源（当前页所在主机）' }),
          '；启动命令：', el('code', { text: 'python -u backend/api/run_api.py' })))
      : el('p', { class: 'dim', text: '后端回了错误信封，下面是它给的原话。' }),
    opts.note ? el('p', { class: 'dim', text: opts.note }) : null,
    e.detail ? el('details', { class: 'chk-details' },
      el('summary', { text: '后端给的细节（原样）' }),
      el('pre', { class: 'chk-ev', text: JSON.stringify(e.detail, null, 2) })) : null,
    opts.onRetry ? el('div', { class: 'chk-toolbar' },
      el('button', { class: 'chk-btn primary', type: 'button', text: '重试', onclick: opts.onRetry })) : null));
  return box;
}

function busyPanel(text) {
  return el('div', { class: 'chk-busy' }, el('span', { class: 'spin' }), text);
}

/** 共享数据：注册表 / 楼栋清单 / 能力。**取不到就抛**，由调用方画错误面板。 */
async function bootShared() {
  const jobs = [];
  if (!state.registry) jobs.push(API.checksRegistry().then((env) => {
    state.registry = env.data; state.registryMeta = env.meta;
  }));
  if (!state.buildings) jobs.push(listBuildings().then((rows) => { state.buildings = rows; }));
  if (!state.caps) jobs.push(API.capabilities().then((d) => { state.caps = d; })
    // 能力问不到不该挡住看结论 —— 只是写按钮会保守地禁掉。
    .catch(() => { state.caps = null; }));
  await Promise.all(jobs);
}

// ── 全库红绿灯墙 ────────────────────────────────────────────────

async function paintWall(root) {
  mount(root, busyPanel('正在读注册表与楼栋清单…'));
  try {
    await bootShared();
  } catch (e) {
    if (!disposed) mount(root, errorPanel(e));
    return;
  }
  if (disposed) return;

  const total = state.buildings.length;
  // 有缓存就直接画（从某栋回来时不该重扫一遍）。
  if (state.fleet) { paintWallBody(root, total); return; }

  // 真正要发出去的请求数：清单说没有产物的那些不发。进度说"正在取 N 栋"，
  // 不说"正在取 95 栋" —— 分母写成一个永远到不了的数，看着就像卡住了。
  const toAsk = state.buildings.filter((b) => b.hasCheck !== false).length;
  state.progress = { done: 0, total: toAsk };
  const prog = el('div', { class: 'chk-busy' },
    el('span', { class: 'spin' }),
    el('span', { class: 'ptext', text: `正在取产物 0/${toAsk}…` }),
    el('div', { class: 'chk-progbar' }, el('i', {})));
  mount(root, prog);

  state.abort = new AbortController();
  try {
    const fleet = await scanFleet(state.buildings, {
      concurrency: 6,
      signal: state.abort.signal,
      onProgress: ({ done, total: t, name }) => {
        if (disposed || !prog.isConnected) return;
        prog.querySelector('.ptext').textContent = `正在逐栋取产物 ${done}/${t}（${name}）…`;
        prog.querySelector('.chk-progbar i').style.width = `${Math.round((done / t) * 100)}%`;
      },
    });
    if (disposed) return;
    if (!fleet) return;            // 被切走时中止
    state.fleet = fleet;
  } catch (e) {
    if (disposed) return;
    const partial = state.fleet;
    mount(root, errorPanel(e, {
      note: '扫描中途断了 —— 已经取到的部分不完整，**不当结论用**。'
        + (partial ? '（上一轮完整的扫描结果仍留在内存里，重试后会刷新）' : ''),
    }));
    return;
  } finally {
    state.abort = null;
  }
  if (disposed) return;
  paintWallBody(root, total);
}

function paintWallBody(root, total) {
  const fleet = state.fleet;
  const rerender = () => paintWallBody(root, total);
  // 全库那份单开一个容器，自己异步填 —— 它取不到不该挡住下面那块逐栋墙。
  const fleetHolder = el('div', { class: 'chk-fleet-holder', id: 'fleet-panel' });
  const body = el('div', {},
    el('h1', { text: '检查 · 全库红绿灯墙' },
      el('span', { class: 'sub', text: ' 判据长在系统里，前端只显示引擎的结论' })),
    fleetHolder,
    el('p', { class: 'lede' },
      '每条判据一行。这一屏回答的是**「哪条判据在几栋上是什么状态」**，'
      + '而不是逐栋罗列 —— 一条判据在几十栋上全亮时，逐栋清单等于没有信息量。',
      el('br'),
      '前端一个判据都不算：下面是 '
      + `${fleet.totals.has_artifact} 栋产物里的 `
      + `${fleet.totals.findings} 条结论**数出来的**分布。`),
    renderLegend(),
    renderWall({
      fleet,
      registry: state.registry,
      onlyProblem: state.onlyProblem,
      onToggleOnly: (v) => { state.onlyProblem = v; rerender(); },
      onOpenBuilding: (n) => { window.location.hash = `#/checks/${n}`; },
      onRescan: async () => { state.fleet = null; await paintWall(root); },
    }),
    el('p', { class: 'dim' },
      `共 ${total} 栋 · 注册表来源：${state.registryMeta?.source || '—'}。`,
      ` 扫描先取一次清单（\`GET /api/checks/manifest\`）问哪几栋有产物，`
      + `只对那 ${fleet.totals.probed} 栋发 \`GET /api/checks/{楼}\`（并发 6）—— `
      + `其余 ${fleet.totals.no_artifact_by_manifest} 栋清单已说没有产物，不发请求`
      + `（发过去只会回来一串 404 红字，而红字多了就没人当真了）。`
      + ' 后端不现跑检查，只读产物。'));
  mount(root, body);
  // 挂完再填：全库那份是**另一个分母**的另一份产物，各取各的。
  paintFleet(fleetHolder, { onOpenBuilding: (n) => { window.location.hash = `#/checks/${n}`; } });
}

// ── 逐层验收单 ──────────────────────────────────────────────────

async function paintSheet(root, name) {
  mount(root, busyPanel(`正在读 ${name} 的产物…`));
  const back = el('button', { class: 'chk-btn', type: 'button', text: '← 回全库红绿灯墙',
    onclick: () => { window.location.hash = '#/checks'; } });
  try {
    // 楼栋清单用来显示中文名；取不到也不挡事（只少一个标题）。
    if (!state.buildings) { try { await bootShared(); } catch { /* 下面各自处理 */ } }
    const env = await API.checks(name);
    if (disposed) return;
    const info = (state.buildings || []).find((b) => b.name === name);
    const rerender = async () => {
      const fresh = await API.checks(name);
      mount(root, renderSheet({
        env: fresh, info, registry: state.registry, runPanel: runPanel(),
      }));
      state.fleet = null;   // 跑过之后墙上的分布不再可信，下次回墙重扫
    };
    const runPanel = () => renderRunPanel({
      building: name, caps: state.caps, registry: state.registry, onDone: rerender,
    });
    mount(root, el('div', {}, el('div', { class: 'chk-toolbar' }, back),
      renderSheet({ env, info, registry: state.registry, runPanel: runPanel() })));
  } catch (e) {
    if (disposed) return;
    // ★ 404 有两个不同的码，必须分开说：这栋楼没有产物 ≠ 没有这栋楼。
    if (e instanceof ApiError && e.code === 'check_artifact_missing') {
      mount(root, el('div', {},
        el('div', { class: 'chk-toolbar' }, back),
        el('div', { class: 'chk-panic' },
          el('h2', { class: 'chk-panic-h', text: `${name} 还没有检查产物` }),
          el('p', { class: 'chk-panic-msg', text: e.message }),
          el('p', { class: 'dim' },
            '这不是「没有这栋楼」，也不是「检查没发现问题」—— 是这份报告压根还没生成。'),
          e.detail ? el('details', { class: 'chk-details' },
            el('summary', { text: '后端给的细节（原样）' }),
            el('pre', { class: 'chk-ev', text: JSON.stringify(e.detail, null, 2) })) : null),
        (() => {
          const rerender = async () => paintSheet(root, name);
          return el('div', {}, el('h2', { text: '现在就跑一次' }),
            renderRunPanel({ building: name, caps: state.caps, registry: state.registry,
                             onDone: rerender }));
        })()));
      return;
    }
    mount(root, el('div', {}, el('div', { class: 'chk-toolbar' }, back),
      errorPanel(e, { onRetry: () => paintSheet(root, name) })));
  }
}

// ── 视图入口 ────────────────────────────────────────────────────

/**
 * @param {HTMLElement} root 挂载点（app.js 给的是 #main）
 * @param {string} sub 形如 '' 或 'c113'
 */
export async function render(root, sub) {
  disposed = false;
  const name = (sub || '').trim();
  if (!name) return paintWall(root);
  // 楼号与后端的 BuildingName 同一条约束（^[A-Za-z0-9_-]{1,32}$）——
  // 前端先拦一道，是为了不让一个带斜杠的串进到 URL 里拼路径。
  if (!/^[A-Za-z0-9_-]{1,32}$/.test(name)) {
    mount(root, el('div', { class: 'chk-panic' },
      el('h2', { class: 'chk-panic-h', text: '楼号不合法' }),
      el('p', { class: 'chk-panic-msg', text: `只接受字母数字与 -_（最多 32 位）：${JSON.stringify(name)}` }),
      el('div', { class: 'chk-toolbar' },
        el('button', { class: 'chk-btn', type: 'button', text: '← 回全库红绿灯墙',
          onclick: () => { window.location.hash = '#/checks'; } }))));
    return;
  }
  return paintSheet(root, name);
}
