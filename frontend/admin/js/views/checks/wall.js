// 全库红绿灯墙 —— 每条判据一行（A1…A9、B1…B3），显示状态分布与「哪几栋」。
//
// ★ 为什么必须**按判据压成一行**，而不是逐栋列：一条判据在 95 栋上全亮时，
//   逐栋列等于没有信息量 —— 屏幕上永远是一片红，人就学会不看了
//   （memory: append-only-ledger-whole-table-assertion）。按编号压成一行，
//   才能看出「A6 亮 4 栋、A3 亮 13 栋」这种**有形状**的分布。
//
// ★★ 每行必须同时说清三件事，缺一个就会读错：
//     ① 有产物几栋 —— 分母。只跑了 6 栋时，"全过"不是结论，是**没数据**。
//     ② 栋数 / 条数 / 层数 分列 —— "×48" 不说是栋还是层，会读出完全不同的规模。
//     ③ 红的**形状** —— 归并后的原因原文（引擎给的 detail）。只有"×45 栋"
//        看不出红在哪，也就无从下手。
//
// ★ 前端不下结论：这里的「最严」只是把引擎给的状态按"谁更该被看见"排了一次序，
//   用于行首配色；每一格的状态值本身原样来自产物。
import { el, add } from '../../dom.js';
import { fmtInt } from '../../fmt.js';
import { STATUS_ORDER, statusOf, statusPill, statusBar, worst } from './status.js';

/** 一行判据的「最严」状态 —— 仅用于排序与配色，不是结论。 */
function rowSeverity(entry) {
  return worst(Object.fromEntries(Object.entries(entry.by).map(([s, c]) => [s, c.who.size])));
}

/** 该判据统计里某个状态的格子（缺就回 0）。 */
const cell = (entry, s) => entry.by[s] || { who: new Set(), findings: 0, floors: 0 };

/** 一列楼号按钮。「哪几栋」要能点进去看那一栋的逐层验收单。 */
function buildingChips(names, onOpen, limit = 10) {
  const list = [...names].sort();
  const shown = list.slice(0, limit);
  const rest = list.length - shown.length;
  return el('span', { class: 'chk-chips' },
    shown.map((n) => el('button', {
      class: 'chk-chip', type: 'button', title: `打开 ${n} 的逐层验收单`,
      onclick: () => onOpen(n),
    }, n)),
    rest > 0 ? el('span', { class: 'chk-chip more', text: `+${rest}` }) : null);
}

/** 数量写法：栋数必有；条数/层数与之不同才写出来，并且**带上单位**。 */
function unitsText(c) {
  const parts = [`${fmtInt(c.who.size)} 栋`];
  if (c.findings !== c.who.size) parts.push(`${fmtInt(c.findings)} 条`);
  if (c.floors) parts.push(`${fmtInt(c.floors)} 层`);
  return parts.join(' · ');
}

/** 判据这一行的分布摘要（人话，按状态分组）。 */
function distributionLine(entry) {
  const out = [];
  for (const s of STATUS_ORDER) {
    const c = cell(entry, s);
    if (!c.who.size) continue;
    out.push({ s, text: `${statusOf(s).cn} ${unitsText(c)}` });
  }
  return out;
}

/** 一条原因：原文 + 它落在哪几栋。 */
function reasonRow(r, onOpen) {
  const sts = STATUS_ORDER.filter((s) => r.by[s])
    .map((s) => `${statusOf(s).label}×${r.by[s]}`).join(' ');
  return el('li', { class: 'chk-reason' },
    el('div', { class: 'rt' },
      el('span', { class: 'rst', text: sts }),
      el('span', { class: 'rn', text: `${fmtInt(r.who.size)} 栋` })),
    el('div', { class: 'rd', text: r.text || '（引擎没给原因原文）' }),
    buildingChips(r.who, onOpen, 14));
}

/** 展开后的详情行。 */
function detailRow(entry, reg, opts) {
  const { onOpen } = opts;
  const known = !!reg;
  return el('tr', { class: 'chk-detail' }, el('td', { colspan: '7' },
    el('div', { class: 'chk-detail-in' },
      el('dl', {},
        el('dt', { text: '这条判据为什么存在（引擎注册表原文）' }),
        el('dd', { text: known ? reg.why : '注册表里没有这一条 —— 产物里却报了它，先查注册表与引擎是不是同一份' }),
        el('dt', { text: '层与跑法' }),
        el('dd', { text: known
          ? `${reg.tier_label}；${reg.per_building ? '逐栋出结论' : '全库出结论'}`
          : '—' }),
        el('dt', { text: '本机今天能不能跑' }),
        el('dd', { text: !known ? '—'
          : reg.runnable_today ? '能跑'
            : `跑不动：${reg.blocked_by}` })),
      el('h4', { text: '按状态分列（栋数 / 条数 / 层数）' }),
      el('div', { class: 'chk-byst' }, STATUS_ORDER.filter((s) => cell(entry, s).who.size)
        .map((s) => {
          const c = cell(entry, s);
          return el('div', { class: 'chk-byst-col' },
            el('div', { class: 'h' }, statusPill(s), el('span', { text: unitsText(c) })),
            el('div', { class: 'bsub', text: statusOf(s).why }),
            buildingChips(c.who, onOpen, 200));
        })),
      el('h4', { text: '红的形状：按引擎给的原因原文归并' }),
      entry.reasons.length
        ? el('ol', { class: 'chk-reasons' }, entry.reasons.map((r) => reasonRow(r, onOpen)))
        : el('p', { class: 'dim', text: '这条判据没有任何结论落到产物里（没有原因可归并）。' }))));
}

/** 空结论行：产物里一条都没报这条判据。 */
function noConclusionNote(cid, reg, totalHasArtifact) {
  return el('div', { class: 'chk-none' },
    el('span', { class: 'wid', text: cid }),
    el('span', { text: `本轮 ${totalHasArtifact} 栋产物里，没有任何一栋给出这条判据的结论` }),
    el('span', { class: 'dim', text: reg?.title ? `（${reg.title}）` : '' }),
    el('span', { class: 'warn', text: ' —— 这不是「通过」，是「没量」' }));
}

/**
 * 画整面墙。
 * @param {{fleet:object, registry:object, buildings:Array, onlyProblem:boolean,
 *          onToggleOnly:Function, onOpenBuilding:Function, onRescan:Function}} opts
 */
export function renderWall(opts) {
  const { fleet, registry, onlyProblem, onToggleOnly, onOpenBuilding } = opts;
  const t = fleet.totals;
  const reg = new Map((registry?.checks || []).map((c) => [c.id, c]));

  // 注册表顺序（源码里的书写顺序）为准；产物里多出来的编号排在后面并明确标出。
  const ids = (registry?.checks || []).map((c) => c.id);
  const extra = fleet.order.filter((id) => !reg.has(id)).sort();
  const allIds = [...ids, ...extra];

  const root = el('div', { class: 'chk-wall' });

  // ── KPI：全部是「数出来的」，不是「判出来的」 ────────────────
  add(root, el('div', { class: 'chk-kpis' },
    el('div', { class: 'chk-kpi' }, el('span', { class: 'k', text: '楼栋总数' }),
      el('b', { class: 'v', text: fmtInt(t.buildings) })),
    el('div', { class: 'chk-kpi' }, el('span', { class: 'k', text: '有检查产物' }),
      el('b', { class: 'v', text: fmtInt(t.has_artifact) }),
      el('span', { class: 'n', text: '墙面只由这几栋数出来' })),
    el('div', { class: `chk-kpi${t.no_artifact ? ' warn' : ''}` },
      el('span', { class: 'k', text: '还没跑过检查' }),
      el('b', { class: 'v', text: fmtInt(t.no_artifact) }),
      el('span', { class: 'n', text: '它们在墙上是空格子' })),
    el('div', { class: `chk-kpi${t.error ? ' bad' : ''}` },
      el('span', { class: 'k', text: '没扫成' }),
      el('b', { class: 'v', text: fmtInt(t.error) }),
      el('span', { class: 'n', text: '不知道，不是没事' })),
    el('div', { class: 'chk-kpi' }, el('span', { class: 'k', text: '结论条数' }),
      el('b', { class: 'v', text: fmtInt(t.findings) }),
      el('span', { class: 'n', text: '引擎写的 findings 总数' }))));

  // ── 覆盖口径：这一段是整面墙最容易被读错的地方，所以单独说 ──────
  if (t.no_artifact > 0) {
    add(root, el('div', { class: 'chk-note' },
      el('b', { text: `${fmtInt(t.buildings)} 栋里只有 ${fmtInt(t.has_artifact)} 栋有检查产物` }),
      `，其余 ${fmtInt(t.no_artifact)} 栋在这些判据下**没有格子**。`,
      '墙上的「没报问题」只对那几栋成立，对没跑的楼什么都不说明 —— ',
      '要它们有结论，得对每栋跑一次（POST /api/checks/{楼}/run）。'));
  }
  if (t.error > 0) {
    add(root, el('div', { class: 'chk-note bad' },
      el('b', { text: `${fmtInt(t.error)} 栋没扫成` }),
      '（网络或后端出错）—— 这几栋是「不知道」，不是「没问题」。重新扫一次。'));
  }
  if (t.has_artifact === 0 && t.buildings > 0) {
    add(root, el('div', { class: 'chk-note bad' },
      el('b', { text: '一栋产物都没有' }),
      '，所以下面每一行都是「无结论」。这一屏现在证明不了任何事。'));
  }

  // ── 注册表与本机可跑性：B 层常常是「本机跑不动」，要说出来 ──────
  const dep = registry?.dependencies;
  if (dep) {
    const missing = Object.entries(dep.heavy_deps || {})
      .filter(([, ok]) => !ok).map(([m]) => m);
    add(root, el('div', { class: `chk-note${dep.heavy_ready ? '' : ' warn'}` },
      el('b', { text: `B 层（B1…B3）本机${dep.heavy_ready ? '可跑' : '跑不动'}：` }),
      dep.heavy_ready
        ? 'ezdxf/shapely 找得到、compute 开着、源 DXF 配了。'
        : `缺 ${missing.length ? missing.join('、') : 'compute 开关或源 DXF 目录'}。`
          + 'B 层的检查会以 UNAVAILABLE 落进产物 —— 那是「没量成」，不是「通过」。',
      el('span', { class: 'dim', text: `（判据：${dep.caveat}）` })));
  }

  // ── 工具条 ──────────────────────────────────────────────────
  add(root, el('div', { class: 'chk-toolbar' },
    el('label', { class: 'chk-check' },
      el('input', { type: 'checkbox', checked: onlyProblem, onchange: (e) => onToggleOnly(e.target.checked) }),
      '只看要看的（有 GAP / WATCH / 没量成）'),
    el('span', { class: 'dim', text: `扫描于 ${fleet.scannedAt.toLocaleTimeString('zh-CN')}，并发 6` }),
    el('button', { class: 'chk-btn', type: 'button', text: '重新扫一遍', onclick: opts.onRescan })));

  // ── 墙本体 ──────────────────────────────────────────────────
  const head = ['编号', '判据', '层', '最严', '状态分布（栋·条·层）', '有产物', '哪几栋'];
  const rows = [];
  const noConc = [];

  for (const id of allIds) {
    const e = fleet.perCheck.get(id) || { id, by: {}, reasons: [] };
    const info = reg.get(id);
    const sev = rowSeverity(e);
    const bad = STATUS_ORDER.filter((s) => statusOf(s).needsLook)
      .reduce((a, s) => a + cell(e, s).who.size, 0);
    const hasAny = Object.keys(e.by).length > 0;

    if (!hasAny) noConc.push({ id, info });

    // 「只看要看的」：把既没有要看的、也没有结论的行藏起来（默认全显示）。
    if (onlyProblem && !bad && hasAny) continue;

    const affected = STATUS_ORDER.filter((s) => statusOf(s).needsLook)
      .flatMap((s) => [...cell(e, s).who]);
    const dist = distributionLine(e);
    // ★ 分母：这条判据到底在几栋上量过。占了绝大多数就是「全库普遍」——
    //   这种红不是"某一栋出事了"，是判据本身在这个库上的常态，修法不一样。
    const seen = new Set(Object.keys(e.by).flatMap((s) => [...e.by[s].who]));
    const universal = t.has_artifact > 0 && bad / Math.max(1, seen.size) >= 0.8 && bad >= 3;

    const tr = el('tr', {
      class: `chk-row${sev ? ` sev-${sev}` : ' sev-none'}`,
    },
    el('td', { class: 'mono id' },
      el('button', {
        class: 'chk-row-toggle', type: 'button', 'aria-expanded': 'false',
        title: '展开：按原因归并的形状',
        onclick: (ev) => {
          const next = tr.nextElementSibling;
          const open = next && next.classList.contains('chk-detail') ? next : null;
          const wasOpen = !!open;
          if (open) open.remove();
          else tr.parentNode.insertBefore(detailRow(e, info, opts), tr.nextSibling);
          ev.currentTarget.setAttribute('aria-expanded', String(!wasOpen));
        },
      }, el('span', { class: 'caret', text: '▸' }), id, info ? null : el('span', { class: 'unknown', title: '注册表里没有这条判据', text: '?' }))),
    el('td', { class: 'name' }, info ? info.title : '（注册表里没有）',
      universal ? el('span', { class: 'chk-univ', title: '几乎每一栋都亮 —— 这种红是"常态"，先查判据是不是过宽/白名单没加，别一栋一栋修', text: '全库普遍' }) : null),
    el('td', { class: 'mono dim', text: info ? info.tier : '—' }),
    el('td', {}, sev ? statusPill(sev) : el('span', { class: 'chk-pill st-none', text: '无结论' })),
    el('td', { class: 'chk-dist' },
      hasAny ? statusBar(Object.fromEntries(Object.keys(e.by).map((s) => [s, e.by[s].who.size])), null) : null,
      el('div', { class: 'chk-dist-list' },
        dist.length
          ? dist.map((d) => el('span', { class: `dl ${statusOf(d.s).cls}`, text: d.text }))
          : el('span', { class: 'dl dim', text: '这条判据没有任何结论' }))),
    el('td', { class: 'mono' }, el('span', { class: hasAny ? '' : 'dim', text: `${fmtInt(seen.size)} / ${fmtInt(t.has_artifact)}` })),
    el('td', {}, affected.length ? buildingChips(affected, onOpenBuilding) : el('span', { class: 'dim', text: '—' })));

    rows.push(tr);
  }

  if (!rows.length) {
    add(root, el('div', { class: 'chk-note' }, el('b', { text: '没有一行可显示' }),
      '：要么产物为空，要么「只看要看的」把所有行都过滤掉了。取消勾选看全部。'));
  } else {
    add(root, (() => {
      const tbl = el('table', { class: 'chk-table' },
        el('thead', {}, el('tr', {}, head.map((h) => el('th', { scope: 'col', text: h })))),
        el('tbody', {}, rows));
      return tbl;
    })());
  }

  // ── 一条结论都没有的判据：单列出来，免得"没量"被读成"通过" ──────
  if (noConc.length) {
    add(root, el('h3', { class: 'chk-h3', text: `本轮一条结论都没有的判据（${noConc.length} 条）` }),
      el('p', { class: 'dim', text: '这些编号在产物里完全没出现。它们在墙上不是绿的，是空的。' }),
      el('div', {}, noConc.map(({ id, info }) => noConclusionNote(id, info, t.has_artifact))));
  }

  return root;
}

/** 图例（五态各是什么，尤其是"没量成"长什么样）。 */
export function renderLegend() {
  return el('div', { class: 'chk-legend' },
    STATUS_ORDER.map((s) => el('span', { class: 'chk-legend-item' },
      statusPill(s), el('span', { text: statusOf(s).why }))),
    el('span', { class: 'chk-legend-item' },
      el('span', { class: 'chk-pill st-none', text: '无结论' }),
      '产物里没有这条判据 —— 也是"没量"，不是过'),
    el('span', { class: 'chk-legend-item dim' },
      el('span', { class: 'chk-pill st-unknown', text: '?' }),
      '产物报了注册表里没有的编号，两处不是同一份'));
}
