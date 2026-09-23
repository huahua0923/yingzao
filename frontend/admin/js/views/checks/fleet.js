// 全库级结论面板 —— 检查引擎**对整个库跑一次**的那份报告（fleet.json）。
//
// ★★ 为什么单栋墙之外还要有这一块：墙上每个格子的**分母是"有产物的那几栋"**
//   （本机实测 6 栋），而这一份的分母是**全库**（95 栋）。两个分母不同的数
//   摆在同一屏上、又都不写分母，就会被读成同一个数 —— 本仓栽过多次
//   （memory: gauge-coverage-invisible-in-summary）。所以这一块的头一行
//   必须写清"分母是全库 N 栋"，而且要说它和下面那块不是一回事。
//
// ★ 与前端其它地方一样：**一个判据都不算**。这里显示的每一条状态、每一个数字
//   都是产物里的原文，前端只做归类、排序和排版（用户明令：前端只显示引擎的结论）。
import { el, mount } from '../../dom.js';
import { API, ApiError } from '../../api.js';
import { statusPill, statusBar, statusOf, verdictOf } from './status.js';

/** 把 findings 分成两类：全库级判据行（fleet.check.<编号>）与逐栋汇总行（fleet.<楼>）。 */
function splitFindings(findings) {
  const checks = [];
  const buildings = [];
  for (const f of findings || []) {
    const id = String(f.check || '');
    if (id.startsWith('fleet.check.')) checks.push(f);
    else if (id.startsWith('fleet.')) buildings.push(f);
  }
  return { checks, buildings };
}

/** 编号 A1 / B3 —— 排序按字母+数字，别让 A10 排在 A2 前面。 */
const idNum = (s) => {
  const m = String(s).match(/^([A-Za-z]+)(\d+)$/);
  return m ? [m[1], Number(m[2])] : [String(s), 0];
};
const byId = (a, b) => {
  const [la, na] = idNum(a.id);
  const [lb, nb] = idNum(b.id);
  return la === lb ? na - nb : la.localeCompare(lb);
};

/** 一行判据。状态分布按**栋**数（这一份产物的分母就是栋）。 */
function checkRow(f, onOpenBuilding) {
  const ev = f.evidence || {};
  const dist = ev.dist || {};
  const total = Object.values(dist).reduce((a, n) => a + n, 0);
  // 原因归并：同一个原因串下面的楼号列一起 —— 这才是可下手的形状。
  const groups = Object.entries(ev.affected || {})
    .map(([reason, names]) => ({ reason, names: Array.isArray(names) ? names : [] }))
    .sort((a, b) => b.names.length - a.names.length);

  const id = String(f.check).replace('fleet.check.', '');
  const row = el('tr', { class: `chk-fleet-row st-row-${statusOf(f.status).key}` },
    el('td', { class: 'num', text: id }),
    el('td', { text: f.title || '' }),
    el('td', { text: f.measure || '' }),
    el('td', {}, statusPill(f.status)),
    el('td', { class: 'chk-fleet-dist' },
      statusBar(dist, total),
      el('span', { class: 'dim num', text: ` ${total} 栋` })),
    el('td', { class: 'chk-fleet-who' },
      groups.length
        ? el('ul', { class: 'chk-fleet-reasons' }, groups.map((g) => el('li', {},
            el('b', { class: 'num', text: `${g.names.length} 栋` }),
            el('span', { class: 'chk-fleet-reason', text: g.reason }),
            el('span', { class: 'chk-fleet-names' }, g.names.map((n) => el('a', {
              href: `#/checks/${encodeURIComponent(n)}`,
              text: n,
              title: `${n} 的逐层验收单`,
              onclick: (e) => { if (onOpenBuilding) { e.preventDefault(); onOpenBuilding(n); } },
            }))))))
        : el('span', { class: 'dim', text: '无异常' })));
  row.title = f.detail || '';
  return row;
}

/**
 * 全库面板。`env` 是 `GET /api/checks/fleet` 的信封。
 * @param {{env:object, onOpenBuilding?:Function}} opts
 */
export function renderFleetPanel(opts) {
  const { env, onOpenBuilding } = opts;
  const rep = env?.data?.report || {};
  const meta = env?.meta || {};
  const art = meta.artifact || {};
  const { checks, buildings } = splitFindings(rep.findings);
  checks.sort(byId);

  const fleetTotal = buildings.length;          // ★ 分母：产物里逐栋汇总行的条数 = 全库跑了几栋

  // 逐栋汇总按状态分组。这里的教训要写在屏幕上：
  // 「没量成」会压掉绿灯 ⇒ 只要有一条判据在全库都"没量成"（本机 A5 就是），
  //   逐栋结论就永远不可能是 PASS。不说明的话，「0 栋通过」会被读成"全都不合格"。
  const byStatus = {};
  for (const b of buildings) (byStatus[b.status] = byStatus[b.status] || []).push(b);
  const univUnavail = checks.filter((c) => {
    const d = (c.evidence || {}).dist || {};
    return (d.unavailable || 0) + (d.na || 0) >= fleetTotal && (d.gap || 0) === 0;
  });

  // ★ 分布条只数**逐栋汇总**，不用 rep.counts —— 后者把 9 条判据行也算进去了
  //   （104 = 95 栋 + 9 条判据），画出来的条会有一条比 95 还长的分母。
  //   量具报了个对不上单位的数，比不报还坏（本仓的原话）。
  const bCounts = {};
  for (const b of buildings) bCounts[b.status] = (bCounts[b.status] || 0) + 1;

  const vd = verdictOf(rep.verdict);

  return el('section', { class: 'chk-fleet' },
    el('div', { class: 'chk-fleet-head' },
      el('h2', { class: 'sec-h', text: '全库结论（引擎一次跑完的那份）' }),
      el('p', { class: 'chk-fleet-src dim' },
        `产物 ${art.file || '—'} · 生成 ${art.generated_iso || '—'} · `
        + `层 ${art.heavy ? 'A+B' : 'A（不含 B 层重活）'} · `,
        // ★ 这里**不能**写成 `+ el(...)`：一元 `+` 会把节点拼成字符串，
        //   屏幕上就是字面的 `[object HTMLElement]`。节点要当孩子传，不能进串。
        el('b', { text: `分母 = 全库 ${fleetTotal} 栋` }))),

    el('p', { class: 'chk-fleet-warn' },
      el('b', { text: '这一块和下面那块的分母不一样。' }),
      ` 这块是引擎对整个库跑的那一次（分母 ${fleetTotal} 栋）；`
      + ` 下面「逐栋取产物」的墙，分母只有"有产物的那几栋"。`
      + ' 两个数不能互相对照，也不能相加。'),

    el('div', { class: 'chk-fleet-verdict' },
      el('span', { class: `chk-verdict ${vd.cls}`, text: vd.label }),
      el('span', { text: vd.cn }),
      rep.deliverable
        ? el('span', { class: 'dim', text: '交付拦阻：无' })
        : el('span', { class: 'dim', text: '交付拦阻：有（还有 GAP 未收口）' }),
      el('span', { class: 'chk-fleet-bar' }, statusBar(bCounts, fleetTotal))),

    el('table', { class: 'chk-fleet-table' },
      el('thead', {}, el('tr', {},
        el('th', { text: '编号' }), el('th', { text: '判据' }),
        el('th', { text: '口径' }), el('th', { text: '最严' }),
        el('th', { text: `分布（栋 / ${fleetTotal}）` }), el('th', { text: '哪几栋' }))),
      el('tbody', {}, checks.map((f) => checkRow(f, onOpenBuilding)))),

    // 逐栋汇总：59 栋 gap、36 栋没量成……这行是"现在全库什么状况"的一句话
    el('div', { class: 'chk-fleet-rollup' },
      el('h3', { text: '逐栋汇总' }),
      el('p', {},
        el('b', { text: `${fleetTotal} 栋` }), '里：',
        ['gap', 'unavailable', 'watch', 'pass'].map((k) => [
          el('span', { class: 'num', text: ` ${(byStatus[k] || []).length} ` }),
          el('span', { class: 'dim', text: `${statusOf(k).cn}  ` }),
        ])),
      univUnavail.length
        ? el('p', { class: 'chk-fleet-warn' },
            el('b', { text: '所以「通过 0 栋」不是"全都不合格"。' }),
            ` 有 ${univUnavail.length} 条判据在全库 ${fleetTotal} 栋上都是「没量成」`
            + `（${univUnavail.map((c) => String(c.check).replace('fleet.check.', '')).join('、')}）`
            + ' —— 没量成会压掉绿灯，于是每一栋的汇总都够不到 PASS。'
            + ' 这是**量具缺输入**，不是楼有问题；但那几栋该量的确实还**没量**。')
        : null,
      el('details', { class: 'chk-details' },
        el('summary', { text: `展开逐栋清单（${fleetTotal} 栋）` }),
        ['gap', 'unavailable', 'watch', 'pass'].map((k) => (byStatus[k] || []).length
          ? el('div', { class: 'chk-fleet-group' },
            el('h4', {}, statusPill(k, (byStatus[k] || []).length)),
            el('ul', {}, byStatus[k].map((b) => el('li', {},
              el('a', { href: `#/checks/${encodeURIComponent(b.title)}`, text: b.title }),
              b.detail ? el('span', { class: 'dim', text: ` — ${b.detail}` }) : null))))
          : null))));
}

/** 取不到全库产物时的面板 —— 明说"这一份还没有"，不画空表。 */
export function renderFleetMissing(err) {
  return el('section', { class: 'chk-fleet chk-fleet-missing' },
    el('h2', { class: 'sec-h', text: '全库结论' }),
    el('p', {},
      el('b', { text: '还没有全库级产物。' }),
      ' 这不是「全库都没问题」，也不是「取数失败」—— 是**对整个库跑一次**这件事还没做过。'),
    el('p', { class: 'dim', text: err?.message || '' }),
    el('p', { class: 'dim' },
      '逐栋跑（POST /api/checks/{楼}/run）**不会**生成这一份，它只写单栋产物。'),
    el('p', {}, el('code', { text: 'python -m backend.checks.runner' })));
}

/** 异步填坑：面板自己取数，取不到也要说话（调用方把容器先挂上即可）。 */
export async function paintFleet(holder, opts = {}) {
  let env;
  try {
    env = await API.checksFleet();
  } catch (e) {
    if (!holder.isConnected) return;
    // 404 = 这一份**还没跑过**（不是错，也不是"全库没问题"）—— 与其它错误分开说。
    mount(holder, e instanceof ApiError && e.status === 404
      ? renderFleetMissing(e)
      : el('section', { class: 'chk-fleet chk-fleet-missing' },
        el('h2', { class: 'sec-h', text: '全库结论取不到' }),
        el('p', { text: String(e?.message || e) }),
        el('p', { class: 'dim', text: '这一块没拿到，不代表下面的逐栋墙有问题。' })));
    return;
  }
  if (!holder.isConnected) return;   // 取数途中被切走了：别再往一个不在的节点里写
  mount(holder, renderFleetPanel({ env, onOpenBuilding: opts.onOpenBuilding }));
}
