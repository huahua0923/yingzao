// 「图纸」视图 —— 把**图纸原来画的样子**和**系统认出来的样子**并排摆出来给人核。
//
// 路由（hash，零依赖，可分享）：
//     #/drawings              没给楼号 → 取清单第一栋，并把 hash 补全
//     #/drawings/<楼号>        该栋的逐层对照
//
// 为什么要有这一屏：整条链路的错误（墙配对错、房间漏、轮廓多圈、层错位…）
// 最终都只能在一件事上看出来 —— **原图和识别图放在一起看**。
// 所以这里一个判据都不算（和 checks.js 同一条规矩）：它只负责把两路图、
// 以及那层产物自己的计数摆到同一行上，差异由人眼合。
//
// ★★ 三条「不许静默」写在这里一次（本仓最贵的一类失败都在这三条上）：
//   1. 图取不到 ⇒ 那一格必须**说出是哪一格取不到**，不许留白。
//      空白和"图本身是空白的"在屏幕上长得一模一样（memory: silent-failure-needs-a-voice）。
//   2. 后端没起 ⇒ 明说连不上，**不画空网格**。空网格会被读成"这一栋没有图"。
//   3. 「图纸有、识别产物没有」必须**显眼地说出来** —— 这一档在库里是躺着不报错的：
//      floors/ 里没有 floorN.json，floors_summary 就根本不列这一层，于是
//      "图上画着东西、系统没这层数据"在逐层表里**不会出现**。所以这里除了逐层表，
//      还要拿产物清单的**张数**（artifacts 里 cad/plan 的 count）去对层数，
//      对不上就摆一条横幅 —— 这是这一屏唯一能看见那一档的地方。
import { el, add, mount } from '../dom.js';
import { fmtInt } from '../fmt.js';
import { API, ApiError } from '../api.js';

export const label = '图纸';

// 楼号与后端的 BuildingName 同一条约束（^[A-Za-z0-9_-]{1,32}$）。
// 前端先拦一道，是为了不让带斜杠的串进到 URL 里拼路径。
const NAME_RE = /^[A-Za-z0-9_-]{1,32}$/;

// 两路图的说法集中在这里 —— 屏幕上同一个东西只有一种叫法。
const SIDES = [
  { key: 'cad', api: 'cad', label: 'CAD 原图', why: '图纸原来画的样子' },
  { key: 'plan', api: 'plan', label: '识别结果图', why: '系统认出来的样子' },
];

const state = {
  buildings: null,      // 95 栋清单（取到就留着，切楼不重取）
  buildingsErr: null,   // 清单没取到的原因 —— 要显示，不能拿空清单冒充
  caps: null,           // 能力：用来判断"源 DXF 这台机器有没有"
  abort: null,
};
let disposed = false;

export function dispose() {
  disposed = true;
  state.abort?.abort();
  state.abort = null;
  // 覆盖层挂在 body 上，不是挂在 root 里 —— 切视图不关它，它会留在屏幕上挡着下一屏。
  closeOverlay();
}

// ── 通用小块 ────────────────────────────────────────────────────

function busyPanel(text) {
  return el('div', { class: 'dw-busy' }, el('span', { class: 'dw-spin' }), text);
}

/**
 * 取数失败 / 接口不可用。说得比空屏多 —— 空屏会被读成"这一栋没有图"。
 * @param {Error} err
 * @param {{onRetry?:Function, note?:string}} [opts]
 */
function panicPanel(err, opts = {}) {
  const e = err instanceof ApiError ? err : new ApiError('unknown', String(err));
  const down = e.code === 'network' || e.status === 0;
  return el('div', { class: `dw-panic${down ? ' down' : ''}` },
    el('h2', { class: 'dw-panic-h', text: down ? '连不上后端' : `取数失败：${e.code}` }),
    el('p', { class: 'dw-panic-msg', text: e.message || String(err) }),
    down
      ? el('div', {},
        el('p', {}, el('b', { text: '这一屏现在一张图都没有 —— 所以这里不画网格。' }),
          '空网格会被读成「这一栋本来就没有图纸」，而实际是「一张都没取到」。'),
        el('p', { class: 'dim' },
          '后端地址：', el('code', { text: window.GYM3D_API_BASE || '同源（当前页所在主机）' }),
          '；启动命令：', el('code', { text: 'python -u backend/api/run_api.py' })))
      : el('p', { class: 'dim', text: '后端回了错误信封，下面是它给的原话。' }),
    opts.note ? el('p', { class: 'dim', text: opts.note }) : null,
    e.detail ? el('details', { class: 'dw-details' },
      el('summary', { text: '后端给的细节（原样）' }),
      el('pre', { class: 'dw-ev', text: JSON.stringify(e.detail, null, 2) })) : null,
    opts.onRetry ? el('div', { class: 'dw-toolbar' },
      el('button', { class: 'dw-btn primary', type: 'button', text: '重试', onclick: opts.onRetry })) : null);
}

/** 一个「量到了」的计数格：标签 + 值，可选加一个"这是零，值得看一眼"的样式。 */
function stat(k, v, cls) {
  return el('span', { class: `dw-stat${cls ? ` ${cls}` : ''}` },
    el('span', { class: 'k', text: k }), el('b', { class: 'v', text: v }));
}

// ── 覆盖层（纯 DOM+CSS 的看大图，不引任何库）─────────────────────

let overlayClose = null;   // 当前覆盖层的关闭函数（没有就是没开）

function closeOverlay() {
  if (overlayClose) { const f = overlayClose; overlayClose = null; f(); }
}

/**
 * 看大图。
 * @param {string} src
 * @param {string} title 标题（楼号 · 层 · 哪一路）
 * @param {string} srcPath 请求路径（原样显示，方便直接 curl 核）
 */
function openOverlay(src, title, srcPath) {
  closeOverlay();          // 只允许一层
  const img = el('img', { class: 'dw-lb-img', src, alt: title });
  const bar = el('div', { class: 'dw-lb-bar' },
    el('b', { text: title }),
    el('code', { text: srcPath }),
    el('span', { class: 'dw-lb-hint dim', text: '点背景或按 Esc 关闭' }),
    el('button', { class: 'dw-btn', type: 'button', text: '关闭', onclick: () => closeOverlay() }));
  // 图自己取不到时，覆盖层里也要说话 —— 大图区空白比小图区空白更误导。
  img.addEventListener('error', () => {
    mount(bodyBox, el('div', { class: 'dw-lb-dead' },
      el('p', { text: '这张图取不到（请求失败或这一层本来没有这张图）。' }),
      el('code', { text: srcPath })));
  });
  const bodyBox = el('div', { class: 'dw-lb-body' }, img);
  const box = el('div', { class: 'dw-lb-box' }, bar, bodyBox);
  // 点背景关（点在图上不关）—— 这是覆盖层最常见的关法，先接上再问人。
  const ov = el('div', {
    class: 'dw-lb', role: 'dialog', 'aria-modal': 'true', 'aria-label': title,
    onclick: (ev) => { if (ev.target === ov) closeOverlay(); },
  }, box);

  const onKey = (ev) => { if (ev.key === 'Escape') closeOverlay(); };
  document.addEventListener('keydown', onKey);
  document.body.appendChild(ov);
  overlayClose = () => {
    document.removeEventListener('keydown', onKey);
    ov.remove();
  };
  ov.querySelector('.dw-btn')?.focus();
}

// ── 一张图（或"没有这张图"）─────────────────────────────────────

/**
 * 一格图。
 * @param {string} name 楼号
 * @param {number} f 层号
 * @param {{key:string,label:string,why:string}} side
 * @param {boolean|null} exists 后端说有/没有这张图；null = **不知道**（候选层，要试）
 * @param {string} titlePrefix 覆盖层标题的前缀（候选层要标明"这一层没有产物"）
 */
function shotCell(name, f, side, exists, titlePrefix) {
  const cell = el('div', { class: 'dw-shot' });
  const path = side.key === 'cad' ? API.url.cad(name, f) : API.url.plan(name, f);
  const head = el('div', { class: 'dw-shot-h' },
    el('b', { text: side.label }),
    el('span', { class: 'why', text: side.why }));

  /** 这一格没有图时的替身。**带标题**，所以和"有图那格"仍是同一副骨架。 */
  const deadBlock = (title, why) => el('div', { class: 'dw-dead' },
    el('p', { class: 'dw-dead-h', text: title }),
    el('p', { class: 'dim', text: why }),
    el('code', { text: path }));

  if (exists === false) {
    // 后端清单已经说了没有 —— 不发这个请求，直接说没有。
    add(cell, head, deadBlock(`这一层没有${side.label}`,
      '（后端产物清单里这一层的这张图就是缺的，不是加载失败）'));
    return cell;
  }

  const img = el('img', {
    // 刻意不写 loading="lazy"：这一屏的价值就在"哪一格挂了要立刻说"，
    // 懒加载会把 error 推迟到滚动到那一格才发生 —— 截图上会是一格空白。
    src: path, alt: `${name} F${f} ${side.label}`, decoding: 'async',
    title: '点开看大图',
  });
  const hold = el('div', { class: 'dw-hold' }, img);
  img.addEventListener('error', () => {
    // ★ 图挂了必须说话。留白 = 看起来"这一层本来就没画东西"。
    //   换掉的是**整个格子**（head 也一起重画），不能只换图框里面：
    //   只换图框会把 head 挪进那个白色框里，标题跑到格子中间去 —— 实测踩过。
    mount(cell, head, deadBlock(`这一层没有这张图（${side.label}）`,
      '请求没有取到图 —— 可能是这一层没有这张图，也可能是后端这次没给。'
      + '这一格不代表图纸上是空的。'));
  });
  img.addEventListener('click', () => openOverlay(
    path, `${titlePrefix}${name} F${f} · ${side.label}`, path));
  add(cell, head, hold);
  return cell;
}

/** 一层：一条元信息 + 两张同高的图。 */
function floorBlock(name, row, opts = {}) {
  const f = row ? row.floor : opts.floor;
  const c = (row && row.counts) || {};
  const blocks = el('div', { class: 'dw-floor' + (opts.candidate ? ' candidate' : '') });

  // ── 元信息行 ──────────────────────────────────────────────
  const head = el('div', { class: 'dw-floor-h' },
    el('span', { class: 'dw-fh', text: `F${f}` }),
    row
      ? el('span', { class: 'dw-flag ok', text: `产物 floors/floor${f}.json 在` })
      : el('span', { class: 'dw-flag bad', text: `没有 floors/floor${f}.json` }));

  if (row) {
    const area = Number(row.outline_area_m2 || 0);
    const parts = c.outline_parts || 0;
    add(head,
      stat('房间', fmtInt(row.rooms),
        // 0 间房是这一仓的老毛病（45 栋交付 0 间房在库里躺过），值 0 时要说出来。
        row.rooms ? null : 'zero'),
      // 轮廓这一格有个坑：`outline_parts` 只有**一部分楼**填了 —— 全库 437 层里
      // 有 298 层面积是真的、段数字段是空的。写成 `${parts} 段 · ${area} ㎡` 会印出
      // 「0 段 · 3,393 ㎡」，看着像"有面积却没轮廓"的缺陷，其实只是这一个字段没被填。
      // （屏幕上看不出来，是量出来的：area==0 的层全库 0 层，parts==0 的有 298 层。）
      // 所以：段数**只在真有的时候说**；没有就只说面积，并在 title 里交代少了个数。
      el('span', {
        class: `dw-stat${area > 0 ? '' : ' zero'}`,
        title: area > 0
          ? (parts > 0
            ? '轮廓面积与段数都取自 floors/floorN.json'
            : '这一层的产物里只有轮廓面积，没有分段数（outline_parts 没填）—— 不是「0 段」。')
          : '产物里这一层的轮廓是空的（面积 0）。',
      },
        el('span', { class: 'k', text: '轮廓' }),
        el('b', {
          class: 'v',
          text: area > 0
            ? `${area.toLocaleString('en-US')} ㎡${parts > 0 ? `（${parts} 段）` : ''}`
            : '没有（面积 0）',
        })),
      stat('层高', row.layer_height == null ? '—' : `${row.layer_height} m`),
      stat('墙', fmtInt(c.walls), c.walls ? null : 'zero'),
      stat('柱', fmtInt(c.columns), c.columns ? null : 'zero'),
      stat('门', fmtInt(c.doors), c.doors ? null : 'zero'),
      stat('窗', fmtInt(c.windows)),
      stat('梯', fmtInt(c.stairs), c.stairs ? null : 'zero'),
      stat('电梯', fmtInt(c.elevators)));
  } else {
    // 候选层：图可能有、产物确定没有。这就是简报里"图纸有、识别产物没有"那一档。
    add(head, el('span', { class: 'dw-flag bad', text: '这一层不在 floors[] 里 —— 系统没有它的数据' }));
  }
  add(blocks, head);

  // ── 两路图并排 ────────────────────────────────────────────
  const pair = el('div', { class: 'dw-pair' },
    SIDES.map((s) => shotCell(
      name, f, s,
      row ? (row[s.key]?.exists ?? null) : null,
      opts.candidate ? '候选层 · ' : '')));

  if (opts.candidate) {
    add(blocks, el('p', { class: 'dw-cand-why' },
      '按**张数对不上**推出来的候选层：图可能画到了这一层，但系统没有它的逐层数据。',
      '这不是猜 —— 下面两格会当场试取：取到了就说明「图纸有、识别产物没有」，',
      '取不到那一格自己会说是没有。'));
  }
  add(blocks, pair);
  return blocks;
}

// ── 一致性横幅：数对不上就是"图纸有、产物没有"的唯一可见处 ───────

function consistencyNote(floors, arts) {
  const by = {};
  for (const r of arts || []) by[r.key] = r;
  const cad = by.cad?.count ?? null;
  const plan = by.plan?.count ?? null;
  const js = floors.length;
  const planSrc = by.plan?.source || null;
  const boxes = [];

  boxes.push(el('div', { class: 'dw-counts' },
    stat('逐层产物 floors/*.json', fmtInt(js)),
    stat('CAD 原图（逐层）', fmtInt(cad)),
    stat('识别结果图（逐层）', fmtInt(plan)),
    el('span', { class: 'dw-stat' }, el('span', { class: 'k', text: '识别图来源' }),
      el('b', { class: 'v', text: planSrc || '无' }))));

  if (plan === 0) {
    // 45 栋是这样：只跑过 CAD 忠实渲染，没跑过识别图。右栏会全空 —— 必须说清是"没跑过"。
    boxes.push(el('div', { class: 'dw-note warn' },
      el('b', { text: '这一栋没有识别结果图' }),
      ' —— 右栏会整列是「没有这张图」，那不是加载失败，是这套产物（dxf_plan_recog）',
      '在这栋楼上还没出过。左栏的 CAD 原图照常可看，两路对照在这栋上做不了。'));
  }
  if (plan !== null && plan > js) {
    boxes.push(el('div', { class: 'dw-note bad' },
      el('b', { text: '图纸有、识别产物没有：' }),
      `识别结果图 ${fmtInt(plan)} 张，逐层产物只有 ${fmtInt(js)} 个 —— 多出的 ${fmtInt(plan - js)} 张`,
      '对应的楼层在 floors/ 里没有 floorN.json，所以**逐层表里根本不会出现这一层**。',
      '下面就按最大层号往后**试取**了这几层（见候选层）。'));
  }
  if (cad !== null && cad > js) {
    boxes.push(el('div', { class: 'dw-note bad' },
      el('b', { text: '图纸有、识别产物没有：' }),
      `CAD 原图 ${fmtInt(cad)} 张，逐层产物只有 ${fmtInt(js)} 个 —— 多出的 ${fmtInt(cad - js)} 张同一回事。`));
  }
  if (cad !== null && cad < js) {
    boxes.push(el('div', { class: 'dw-note warn' },
      el('b', { text: '有几层没有 CAD 原图：' }),
      `逐层产物 ${fmtInt(js)} 个，CAD 原图只有 ${fmtInt(cad)} 张 —— 缺的那几层左栏会是「没有这张图」。`));
  }
  if (plan !== null && plan < js && plan > 0) {
    boxes.push(el('div', { class: 'dw-note warn' },
      el('b', { text: '有几层没有识别结果图：' }),
      `逐层产物 ${fmtInt(js)} 个，识别结果图只有 ${fmtInt(plan)} 张。`));
  }
  if (cad === js && plan === js && js > 0) {
    boxes.push(el('div', { class: 'dw-note ok' },
      el('b', { text: '三样张数一致：' }),
      `逐层产物 ${fmtInt(js)} · CAD 原图 ${fmtInt(cad)} · 识别结果图 ${fmtInt(plan)}。`,
      ' 一致只说明**张数**对得上，不说明每张都对得上 —— 还得逐层看。'));
  }
  return boxes;
}

// ── 楼栋选择器 ──────────────────────────────────────────────────

/**
 * @param {Array} list 全部楼栋
 * @param {string} current
 * @param {Function} onPick
 */
function buildingPicker(list, current, onPick) {
  const box = el('div', { class: 'dw-pick' });
  const input = el('input', {
    type: 'search', placeholder: `搜楼号或中文名（共 ${fmtInt(list.length)} 栋）`,
    'aria-label': '搜楼栋',
  });
  const listBox = el('div', { class: 'dw-pick-list', role: 'list' });

  const paint = (q) => {
    const needle = (q || '').trim().toLowerCase();
    const hit = list.filter((b) => !needle
      || b.name.toLowerCase().includes(needle)
      || String(b.title || '').toLowerCase().includes(needle));
    mount(listBox, hit.length
      ? hit.map((b) => el('button', {
        class: 'dw-pick-item', type: 'button', role: 'listitem',
        'aria-current': b.name === current ? 'true' : null,
        title: `${b.name}｜${b.title || ''}`,
        onclick: () => onPick(b.name),
      },
      el('span', { class: 'n', text: b.name }),
      el('span', { class: 't', text: b.title || '（清单里没给中文名）' }),
      el('span', { class: 'tags' },
        el('span', { class: 'tag dim', text: `${fmtInt(b.floor_count)} 层` }),
        // plan_source 是清单里现成的字段 —— 不必为 95 栋各打一次 artifacts
        // 就能在选楼时看出"这栋有没有识别图"。
        el('span', {
          class: `tag ${b.plan_source ? 'good' : 'warn'}`,
          text: b.plan_source ? '有识别图' : '无识别图',
        }),
        b.rooms ? null : el('span', { class: 'tag bad', text: '0 间房' }))))
      // 搜不到 != 这一栋不存在：要说清是筛掉了多少。
      : el('p', { class: 'dim dw-pick-none' },
        `没有楼号/中文名含 ${JSON.stringify(q)} 的楼（清单里共 ${fmtInt(list.length)} 栋）。`));
    const n = hit.length;
    count.textContent = `显示 ${fmtInt(n)} / ${fmtInt(list.length)} 栋`;
  };
  const count = el('span', { class: 'dw-pick-count dim' });
  input.addEventListener('input', () => paint(input.value));

  add(box, el('div', { class: 'dw-pick-bar' },
    el('span', { class: 'k', text: '选楼' }), input, count), listBox);
  paint('');
  return box;
}

// ── 主画面 ──────────────────────────────────────────────────────

/** 楼栋清单取一次就留着；取不到时**记下原因**（不能拿空清单冒充 0 栋）。 */
async function ensureBuildings() {
  if (state.buildings) return state.buildings;
  try {
    const rows = await API.buildings();
    state.buildings = rows || [];
    state.buildingsErr = null;
  } catch (e) {
    state.buildingsErr = e;
    throw e;
  } finally {
    if (!state.caps) API.capabilities().then((c) => { state.caps = c; }).catch(() => {});
  }
  return state.buildings;
}

/** 选楼那一块：清单在就给选择器，清单没读出来就**说明为什么**（不留空）。 */
function pickerOrWhy(name, rerender) {
  if (state.buildings) {
    return buildingPicker(state.buildings, name, (n) => {
      location.hash = `#/drawings/${n}`;   // 改 hash 以便分享
    });
  }
  return el('div', { class: 'dw-note warn' },
    el('b', { text: '楼栋清单没读出来，选择器这一块给不了：' }),
    state.buildingsErr?.message || String(state.buildingsErr || '未知原因'),
    el('div', { class: 'dim' },
      '这一栋自己的图纸不受影响 —— 下面的内容照常。',
      el('button', { class: 'dw-btn', type: 'button', text: '重试取清单',
        onclick: async () => {
          state.buildings = null; state.buildingsErr = null;
          await rerender();
        } })));
}

async function paintOne(root, name) {
  mount(root, busyPanel(`正在读 ${name} 的逐层产物与图纸清单…`));
  // 楼栋清单挂了不该挡住看这一栋的图（只是选择器换成一句说明）。
  try { await ensureBuildings(); } catch { /* pickerOrWhy 会说 */ }

  const rerender = () => paintOne(root, name);
  // 选择器先建好，两条分支都带着它 —— 取数失败时也还能换一栋。
  const picker = pickerOrWhy(name, rerender);

  state.abort = new AbortController();
  const { signal } = state.abort;
  let floors; let arts;
  try {
    [floors, arts] = await Promise.all([
      API.floors(name),
      API.artifacts(name),
    ]);
  } catch (e) {
    if (disposed) return;
    mount(root, el('div', { class: 'dw-page' }, picker,
      panicPanel(e, {
        onRetry: rerender,
        note: `取的是 GET /api/buildings/${name}/floors 与 …/artifacts。`,
      })));
    return;
  } finally {
    state.abort = null;
  }
  if (disposed || signal.aborted) return;

  const rows = (floors || []).slice().sort((a, b) => a.floor - b.floor);
  const info = (state.buildings || []).find((b) => b.name === name);
  const page = el('div', { class: 'dw-page' }, picker);

  // ── 抬头 ────────────────────────────────────────────────
  add(page, el('div', { class: 'dw-head' },
    el('h1', {}, name, el('span', { class: 'sub', text: info?.title ? ` ${info.title}` : '' })),
    el('div', { class: 'dw-head-tags' },
      el('span', { class: 'tag dim', text: `${fmtInt(rows.length)} 层` }),
      info ? el('span', { class: 'tag dim', text: `分类器 ${info.classifier || '—'}` }) : null,
      info ? el('span', { class: 'tag dim', text: `层高 ${info.layer_height ?? '—'} m` }) : null,
      info ? el('span', { class: `tag ${info.has_model ? 'good' : 'warn'}`,
        text: info.has_model ? '有 GLB' : '无 GLB' }) : null,
      el('a', { class: 'tag info', href: `#/checks/${name}`, text: '看这栋的检查单 →' }))));

  add(page, el('p', { class: 'lede' },
    '左栏是图纸原来画的样子，右栏是系统认出来的样子 —— ',
    el('b', { text: '整条链路的错误最终只能在这两张图之间看出来' }),
    '。这一屏一个判据都不算，它只是把两路图和那层产物自己的计数摆到同一行上。'));

  // ── 张数对账（"图纸有、产物没有"唯一看得见的地方）─────────
  add(page, el('h2', { text: '张数对账' }));
  add(page, consistencyNote(rows, arts));

  // ── 源 DXF 下载 ─────────────────────────────────────────
  const dxfOk = state.caps ? state.caps.dxf_dir_configured !== false : true;
  add(page, el('h2', { text: '源图' }),
    el('div', { class: 'dw-src' },
      dxfOk
        ? el('a', { class: 'dw-btn', href: API.url.dxf(name), text: `下载这一栋的源 DXF（${name}.dxf）` })
        : el('span', { class: 'dw-flag bad', text: '这台机器上没有配源图目录（dxf_dir_configured=false），源 DXF 取不到' }),
      el('span', { class: 'dim', text: '源图是整栋一个文件，不分层 —— 层是靠图里画的层号分出来的。' })));

  // ── 逐层两图并排 ────────────────────────────────────────
  add(page, el('h2', { text: '逐层对照' }),
    el('p', { class: 'dim' },
      '一层一块，左 CAD 原图、右识别结果图，同高对齐；点任一图看大图（Esc 关）。'));

  if (!rows.length) {
    // ★ "真的没有产物"和"没读到"必须长得不一样。
    add(page, el('div', { class: 'dw-note bad' },
      el('b', { text: '这一栋没有任何逐层产物。' }),
      ` GET /api/buildings/${name}/floors 成功返回了，但里面是 0 条 —— 是**真的没有** floors/floorN.json，`,
      '不是没读到。（上面的张数对账会告诉你图有没有。既然是空的，下面没有逐层块可画。）'));
  }

  const seen = new Set();
  for (const row of rows) {
    seen.add(row.floor);
    add(page, floorBlock(name, row));
  }

  // ── 候选层：图比产物多出来的那几层 ───────────────────────
  const by = {};
  for (const r of arts || []) by[r.key] = r;
  const extra = Math.max((by.cad?.count ?? 0) - seen.size, (by.plan?.count ?? 0) - seen.size, 0);
  if (extra > 0) {
    const maxF = rows.length ? Math.max(...seen) : -1;
    add(page, el('h2', { text: `候选层（${fmtInt(extra)} 层）` }),
      el('p', { class: 'dim' },
        '下面这几层**不在**上面的清单里（没有 floorN.json），只是按「图比产物多」推出来试取的。',
        '不预先断定是哪一层：取到了就证明「图纸有、识别产物没有」，取不到那一格自己会说是没有。'));
    for (let i = 1; i <= extra; i += 1) {
      add(page, floorBlock(name, null, { floor: maxF + i, candidate: true }));
    }
  }

  mount(root, page);
}

// ── 视图入口 ────────────────────────────────────────────────────

/**
 * @param {HTMLElement} root 挂载点（app.js 给的是 #main）
 * @param {string} sub 形如 '' 或 'c113'
 */
export async function render(root, sub) {
  disposed = false;
  closeOverlay();   // 上一次渲染留下的覆盖层不该盖在新画面上
  const name = (sub || '').trim();

  if (!name) {
    // 没给楼号：取清单第一栋，并把 hash 补全（这样刷新/分享都落在同一栋上）。
    // 补 hash 会再触发一次 route → 这里只负责把"正在读清单"说出来，不自己画。
    mount(root, busyPanel('还没指定楼栋 —— 正在读楼栋清单，取第一栋…'));
    try {
      const list = await ensureBuildings();
      if (disposed) return;
      if (!list.length) {
        mount(root, el('div', { class: 'dw-page' }, panicPanel(
          new ApiError('empty_list', '后端回了 0 栋楼 —— 明细见下。', {
            hint: '数据目录里没有一栋带 profile.json 的楼，或者 GYM3D_DATA_DIR 指错了地方。',
          }, 200),
          { note: '这不是「连不上」，是连上了但清单是空的。',
            onRetry: () => render(root, '') })));
        return;
      }
      location.hash = `#/drawings/${list[0].name}`;
      return;
    } catch (e) {
      if (!disposed) {
        mount(root, el('div', { class: 'dw-page' },
          panicPanel(e, { onRetry: () => render(root, '') })));
      }
      return;
    }
  }

  if (!NAME_RE.test(name)) {
    mount(root, el('div', { class: 'dw-page' },
      panicPanel(new ApiError('bad_name',
        `楼号只接受字母数字与 -_（最多 32 位），收到 ${JSON.stringify(name)}`, null, 400)),
      el('div', { class: 'dw-toolbar' },
        el('a', { class: 'dw-btn', href: '#/drawings', text: '← 回楼栋清单' }))));
    return;
  }
  await paintOne(root, name);
}
