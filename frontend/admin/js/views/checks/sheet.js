// 逐层验收单 —— 一栋楼，一层一行，列出该层**没过**的判据。
//
// 屏幕上的样子（这是这一屏的核心读写单位）：
//     F3    ✗ A2(可疑)、B3(不合规)   ∅ A5(没量成)     通过 6 · 不适用 2
//
// ★★ 三种结局必须分得开，混一次就出事：
//     ✗ = 量到了问题（GAP 红 / WATCH 琥珀）
//     ∅ = **没量成**（斜纹，不带颜色）—— 它不是"过"，也不是"错"
//     · 不适用 = 本来就不该量（最弱的灰，且必须带字）
//   把 ∅ 画成绿色是本项目最贵的一类错：45 栋交付 0 间房就是这样在库里躺着的
//   （memory: gauge-coverage-invisible-in-summary）。
//
// ★ 前端不做 rollup：每层的行首配色只是把引擎给的状态排了一次序，格子里的
//   状态值一律原样来自产物（report.findings[].status）。整栋结论只显示引擎
//   算好的 report.verdict —— 尤其是 INCOMPLETE：它**不是**通过。
import { el, add, table } from '../../dom.js';
import { fmtInt, fmtBytes, fmtTime } from '../../fmt.js';
import { STATUS_ORDER, statusOf, statusPill, statusBar, verdictOf, tally, worst } from './status.js';

const isBad = (f) => statusOf(f.status).needsLook;
const BAD_ORDER = ['gap', 'watch', 'unavailable'];

/** 一条 finding 的完整卡片（详情用）。 */
function findingCard(f) {
  const s = statusOf(f.status);
  const ev = f.evidence && Object.keys(f.evidence).length
    ? JSON.stringify(f.evidence, null, 2) : null;
  return el('div', { class: `chk-find ${s.cls}` },
    el('div', { class: 'chk-find-h' },
      el('span', { class: 'mono cid', text: f.check }),
      el('span', { class: 'ftitle', text: f.title || '' }),
      statusPill(f.status),
      el('span', { class: 'dim ffloor', text: f.floor === null || f.floor === undefined ? '整栋' : `F${f.floor}` })),
    el('div', { class: 'chk-find-d', text: f.detail || '（引擎没给说明）' }),
    el('dl', { class: 'chk-find-meta' },
      f.measure ? el('dt', { text: '计量口径' }) : null,
      f.measure ? el('dd', { text: f.measure }) : null,
      f.blocked_by ? el('dt', { text: '为什么没量成' }) : null,
      f.blocked_by ? el('dd', { class: 'warn', text: f.blocked_by }) : null,
      ev ? el('dt', { text: '数值证据（供逐位核对）' }) : null,
      ev ? el('dd', {}, el('pre', { class: 'chk-ev', text: ev })) : null));
}

/** 一层里的判据清单（三种结局分开写）。 */
function criteriaCell(fs) {
  if (!fs.length) return el('span', { class: 'dim', text: '本层无结论' });
  const bad = fs.filter((f) => f.status === 'gap' || f.status === 'watch');
  const un = fs.filter((f) => f.status === 'unavailable');
  const na = fs.filter((f) => f.status === 'na');
  const ok = fs.filter((f) => f.status === 'pass');
  return el('span', { class: 'chk-crit' },
    bad.length ? el('span', { class: 'c-bad' },
      el('b', { text: '✗ ' }),
      bad.map((f) => el('span', {
        class: `c-item ${statusOf(f.status).cls}`,
        title: `${f.title || ''}｜${statusOf(f.status).cn}：${statusOf(f.status).why}\n${f.detail || ''}`,
      }, `${f.check}(${statusOf(f.status).cn})`))) : null,
    un.length ? el('span', { class: 'c-un' },
      el('b', { text: '∅ ' }),
      un.map((f) => el('span', {
        class: 'c-item st-unavail',
        title: `${f.title || ''}｜没量成：${f.blocked_by || f.detail || ''}`,
      }, `${f.check}(没量成)`))) : null,
    !bad.length && !un.length
      ? el('span', { class: 'c-ok', text: '本层没有要看的判据' }) : null,
    el('span', { class: 'c-tail dim' },
      `通过 ${fmtInt(ok.length)}`,
      na.length ? ` · 不适用 ${fmtInt(na.length)}` : null));
}

/** 逐层表：整栋级（floor=null）排第一行，然后 F0、F1… */
function byFloor(report) {
  const groups = new Map();
  for (const f of report.findings || []) {
    const k = f.floor === null || f.floor === undefined ? null : f.floor;
    if (!groups.has(k)) groups.set(k, []);
    groups.get(k).push(f);
  }
  const keys = [...groups.keys()].sort((a, b) => (a === null ? -1 : b === null ? 1 : a - b));
  return keys.map((k) => ({ floor: k, fs: groups.get(k) }));
}

function floorsTable(report) {
  const rows = byFloor(report).map(({ floor, fs }) => {
    const counts = tally(fs.map((f) => f.status));
    const sev = worst(counts);
    const label = floor === null ? '整栋' : `F${floor}`;
    const tr = el('tr', { class: `chk-frow ${sev ? `sev-${sev}` : 'sev-none'}` });

    const toggle = el('button', {
      class: 'chk-row-toggle', type: 'button', 'aria-expanded': 'false',
      title: '展开这一层的每一条结论',
      onclick: (ev) => {
        const next = tr.nextElementSibling;
        const open = next && next.classList.contains('chk-fdetail') ? next : null;
        const wasOpen = !!open;
        if (open) open.remove();
        else tr.parentNode.insertBefore(el('tr', { class: 'chk-fdetail' },
          el('td', { colspan: '4' }, el('div', { class: 'chk-fdetail-in' },
            fs.map(findingCard)))), tr.nextSibling);
        ev.currentTarget.setAttribute('aria-expanded', String(!wasOpen));
      },
    }, el('span', { class: 'caret', text: '▸' }), label);

    add(tr,
      el('td', { class: 'mono fh' }, toggle),
      el('td', {}, criteriaCell(fs)),
      el('td', { class: 'chk-dist' }, statusBar(counts, fs.length)),
      el('td', { class: 'mono dim', text: `${fmtInt(counts.gap || 0)} / ${fmtInt(counts.watch || 0)} / ${fmtInt(counts.unavailable || 0)}` }));
    return tr;
  });
  // 行是**已经建好的 <tr>**（每行要挂展开事件、要按最严状态加 class），
  // 直接把节点交给 table —— 它会原样放进 tbody。别再包成 [tr]：
  // 那会被当成"一格"，得到 <tr><tr>…，浏览器不报错但渲染错乱。
  return table(
    [{ label: '层' }, { label: '没过的判据（✗ 量到了问题 · ∅ 没量成）' },
      { label: '分布' }, { label: '红 / 琥珀 / 未量', cls: 'num' }],
    rows, { cls: 'chk-table chk-floors' });
}

/** 陈旧/新鲜横幅 —— 「跑过」不等于「此刻还对」。 */
function artifactState(data) {
  const { state, staleness: st } = data;
  const cls = state === 'stale' ? 'bad' : 'ok';
  const box = el('div', { class: `chk-note ${cls}` },
    el('b', { text: state === 'stale' ? '产物陈旧' : '产物新鲜' }),
    el('span', { class: 'stamp', text: `产物生成于 ${fmtTime(st.report_generated_iso)}，文件 mtime ${fmtTime(st.artifact_mtime_iso)}` }),
    el('div', { class: 'dim', text: '「新鲜」的含义只是「没有任何输入比它新」—— 引擎原文：fresh 不等于「它此刻一定对」。' }));

  if (st.reasons?.length) {
    add(box, el('ul', { class: 'chk-ul' }, st.reasons.map((r) =>
      el('li', {}, el('b', { text: r.kind }), ` ${r.why}`))));
  }
  if (st.warnings?.length) {
    add(box, el('div', { class: 'chk-warnblock' },
      el('b', { text: '要注意（不是错误，是口径）' }),
      el('ul', { class: 'chk-ul' }, st.warnings.map((w) =>
        el('li', {}, el('b', { text: w.kind }), ` ${w.why}`)))));
  }
  add(box, el('details', { class: 'chk-details' },
    el('summary', { text: '陈旧判据原文（引擎写的，后台不替你下结论）' }),
    el('p', { class: 'dim', text: st.criterion || '（引擎没给判据原文）' })));
  return box;
}

/** 引擎有这条判据、这份产物里却没有它的结论。 */
function missingChecks(report, registry) {
  const present = new Set((report.findings || []).map((f) => f.check));
  const absent = (registry?.checks || []).filter((c) => !present.has(c.id));
  if (!absent.length) return null;
  return el('div', { class: 'chk-note warn' },
    el('b', { text: `${absent.length} 条判据在这份产物里没有结论：` }),
    absent.map((c) => el('span', { class: 'chk-absent', title: c.why || '', text: c.id })),
    el('div', { class: 'dim', text: '产物比判据注册表旧（或这条判据没为这栋落结论）时会出现。它们不是「通过」，是「没量」—— 重跑一次就有了。' }));
}

function artifactMeta(meta) {
  const a = meta?.artifact || {};
  return el('dl', { class: 'chk-meta' },
    el('dt', { text: '产物文件' }), el('dd', { class: 'mono', text: a.file || '—' }),
    el('dt', { text: '大小' }), el('dd', { class: 'mono', text: fmtBytes(a.bytes) }),
    el('dt', { text: '产物层' }), el('dd', { class: 'mono', text: `${a.layer ?? '—'}${a.heavy ? '（heavy=true，含 B 层）' : '（heavy=false，只跑了 A 层）'}` }),
    el('dt', { text: '读取来源' }), el('dd', { class: 'dim', text: meta?.source || '—' }),
    meta?.omitted?.length ? el('dt', { text: '被后端省略的字段' }) : null,
    meta?.omitted?.length ? el('dd', { class: 'dim', text: meta.omitted.map((o) => `${o.field}：${o.why}`).join('；') }) : null);
}

/**
 * 画一栋楼的验收单。
 * @param {{env:{data:object,meta:object}, info:object, registry:object,
 *          onOpenBuilding:Function, runPanel:Node}} opts
 */
export function renderSheet(opts) {
  const { env, info, registry } = opts;
  const data = env.data || {};
  const report = data.report || {};
  const counts = report.counts || tally((report.findings || []).map((f) => f.status));
  const vd = verdictOf(report.verdict);
  const root = el('div', { class: 'chk-sheet' });

  // ── 抬头 ────────────────────────────────────────────────────
  add(root, el('div', { class: 'chk-head' },
    el('h1', {}, `${data.building || info?.name}`,
      el('span', { class: 'sub', text: info?.title ? ` ${info.title}` : '' })),
    el('div', { class: 'chk-head-tags' },
      el('span', { class: `chk-verdict ${vd.cls}`, title: vd.why || '' },
        el('b', { text: vd.label }), vd.cn),
      el('span', { class: `tag ${report.deliverable ? 'good' : 'bad'}`,
        text: report.deliverable ? '不拦交付' : `拦交付 ${(report.blockers || []).length} 项` }),
      el('span', { class: 'tag info', text: `产物 ${data.state}` }),
      el('span', { class: 'tag dim', text: `层 ${env.meta?.artifact?.layer ?? '—'}` }),
      el('button', { class: 'chk-btn', type: 'button', text: '← 回全库红绿灯墙',
        onclick: () => { window.location.hash = '#/checks'; } }))));

  add(root, el('p', { class: 'lede' },
    '这栋楼的每一条结论都来自引擎产物，前端一个判据都不算。',
    el('b', { text: '「没量成」不是「通过」' }), '，', el('b', { text: '「不拦交付」也不是「全过」' }),
    '（WATCH 与未量成都只提示、不拦）。'));

  // ── 产物状态 ────────────────────────────────────────────────
  add(root, artifactState(data));

  // 拦交付 ≠ 全过 —— 这一句必须写在最显眼处，否则「不拦交付」会被读成绿灯。
  if (report.deliverable && (counts.unavailable || counts.watch)) {
    add(root, el('div', { class: 'chk-note warn' },
      el('b', { text: '注意：这栋「不拦交付」，但并不全过' }),
      `—— 还有 可疑 ${fmtInt(counts.watch || 0)} 条、没量成 ${fmtInt(counts.unavailable || 0)} 条。`,
      '引擎只让 GAP 拦交付；「不拦」是交付口径，不是结论口径。'));
  }

  // ── 计数 KPI（全是数出来的） ────────────────────────────────
  add(root, el('div', { class: 'chk-kpis' },
    STATUS_ORDER.map((s) => el('div', { class: `chk-kpi ${statusOf(s).cls}` },
      el('span', { class: 'k', text: `${statusOf(s).label} · ${statusOf(s).cn}` }),
      el('b', { class: 'v', text: fmtInt(counts[s] || 0) }),
      el('span', { class: 'n', text: statusOf(s).why }))),
    el('div', { class: 'chk-kpi' }, el('span', { class: 'k', text: '结论总条数' }),
      el('b', { class: 'v', text: fmtInt((report.findings || []).length) }),
      el('span', { class: 'n', text: `${(report.findings || []).length} 条 = 逐层结论 + 整栋结论` }))));

  // ── 逐层验收单 ──────────────────────────────────────────────
  add(root, el('h2', { text: '逐层验收单' }),
    el('p', { class: 'dim', text: '一层一行，列出这一层**没过**的判据。点层号展开每一条的原话、口径与数值证据。' }),
    el('div', { class: 'chk-legend-inline' },
      el('span', {}, el('b', { class: 'c-bad', text: '✗' }), ' 量到了问题（GAP 不合规 / WATCH 可疑）'),
      el('span', {}, el('b', { class: 'c-un', text: '∅' }), ' 没量成（缺依赖 / 缺输入 / 量具崩了）—— 不等于通过'),
      el('span', { class: 'dim' }, '· 不适用 = 本来就不该量')),
    floorsTable(report));

  const absent = missingChecks(report, registry);
  if (absent) add(root, absent);

  // ── 产物信息 ────────────────────────────────────────────────
  add(root, el('h2', { text: '这份产物是什么' }), artifactMeta(env.meta));

  // ── 跑一次 ──────────────────────────────────────────────────
  if (opts.runPanel) add(root, el('h2', { text: '跑一次' }), opts.runPanel);

  return root;
}
