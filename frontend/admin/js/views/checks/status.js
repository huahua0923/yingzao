// 检查结论的状态词汇表 —— 全前端**只在这一处**定义措辞与样式类。
//
// 引擎那边有一份权威定义：backend/checks/findings.py 的 Status
// （pass / watch / gap / unavailable / na）。这里不新增、不改写任何状态，
// 只是把它的五个值翻译成人话和颜色。
//
// ★★ 这一屏最严重的一类错，是**把 UNAVAILABLE 显示成绿色**。
//   「没量成」和「全对」在汇总里长得一模一样，于是 45 栋交付 0 间房能安静地
//   待在库里没人发现（memory: gauge-coverage-invisible-in-summary）。
//   所以这里的规矩是硬的：
//     · UNAVAILABLE 用**空心虚线**（斜纹/描边，没有实心填充）—— 形状本身就是
//       「没有结论」，它不继承绿色，也不许被压成 PASS 的样式；
//     · na（不适用）用最弱的灰，并且必须带「不适用」三个字 —— 它不是「过」；
//     · 前端**只读** status，不自己下结论。下面这些计数全是"数出来的"，
//       不是"判出来的"（不替引擎做 rollup）。
import { el } from '../../dom.js';
import { fmtInt } from '../../fmt.js';

export const STATUS = {
  gap: {
    key: 'gap', label: 'GAP', cn: '不合规', cls: 'st-gap',
    // needsLook = 这一格要不要人来看。与引擎 fleet 墙的分组口径一致：
    // GAP / WATCH / UNAVAILABLE 三类都算"要看的"，其中 UNAVAILABLE 是
    // 「还不知道」，GAP 是「确定不对」—— 两者都要看，但不是一回事。
    needsLook: true, why: '量过，确定不合规',
  },
  watch: {
    key: 'watch', label: 'WATCH', cn: '可疑', cls: 'st-watch',
    needsLook: true, why: '量过，可疑（接近门槛或有已知合理解释，需人拍板）',
  },
  unavailable: {
    key: 'unavailable', label: '未量成', cn: '没量成', cls: 'st-unavail',
    needsLook: true, why: '没量成（缺依赖 / 缺输入 / 量具自己崩了）—— 不等于通过',
  },
  na: {
    key: 'na', label: 'N/A', cn: '不适用', cls: 'st-na',
    needsLook: false, why: '本来就不该量（例如单层楼没有"上下贯通"这回事）',
  },
  pass: {
    key: 'pass', label: 'PASS', cn: '通过', cls: 'st-pass',
    needsLook: false, why: '量过，合规',
  },
};

/** 想让人看见的顺序：越该被看见的越靠前（UNAVAILABLE 排在 PASS 之前）。 */
export const STATUS_ORDER = ['gap', 'watch', 'unavailable', 'na', 'pass'];

/** 引擎的报告结论（Report.rollup 的四个值）。 */
export const VERDICT = {
  fail: { label: 'FAIL', cn: '不合格', cls: 'vd-fail' },
  watch: { label: 'WATCH', cn: '可疑', cls: 'vd-watch' },
  incomplete: {
    label: 'INCOMPLETE', cn: '未完成',
    cls: 'vd-incomplete',
    // 这一条是整屏最容易读反的：它不是「通过」，也不是「失败」。
    why: '有项目没量成 —— 没量成会压掉绿灯，所以它不是「通过」',
  },
  pass: { label: 'PASS', cn: '通过', cls: 'vd-pass' },
};

export function statusOf(key) {
  return STATUS[key] || { key, label: String(key ?? '?'), cn: '未知状态',
                          cls: 'st-unknown', needsLook: true,
                          why: '引擎报了一个前端不认识的状态值 —— 别当它是通过' };
}

export function verdictOf(key) {
  return VERDICT[key] || { label: String(key ?? '?'), cn: '未知结论', cls: 'vd-unknown' };
}

/** 状态徽标。`n` 给了就带上计数（墙上一格一数）。 */
export function statusPill(key, n = null, opts = {}) {
  const s = statusOf(key);
  return el('span', {
    class: `chk-pill ${s.cls}${opts.solid ? ' solid' : ''}`,
    title: s.why,
    'aria-label': `${s.label}（${s.cn}）：${s.why}`,
  }, el('b', { text: s.label }), n === null ? null : el('i', { text: fmtInt(n) }));
}

/** 只数，不判：给定 findings / 状态数组 → {gap: n, watch: n, ...}。 */
export function tally(statuses) {
  const out = {};
  for (const s of statuses) out[s] = (out[s] || 0) + 1;
  return out;
}

/** 有结论的状态里，最该被看见的那个（仅用于**排序与配色**，不是结论）。 */
export function worst(counts) {
  return STATUS_ORDER.find((k) => (counts[k] || 0) > 0) || null;
}

/**
 * 状态分布条：一段一格，宽度按比数。
 * ★ UNAVAILABLE 那一格画成**斜纹**（见 checks.css 的 .st-unavail）：
 *   屏幕上「一条斜纹」读作"这里没数据"，不会被误读成"这里通过了"。
 */
export function statusBar(counts, total) {
  const n = total || STATUS_ORDER.reduce((a, k) => a + (counts[k] || 0), 0);
  if (!n) return el('span', { class: 'chk-bar chk-bar-empty', text: '无结论' });
  return el('span', {
    class: 'chk-bar',
    role: 'img',
    'aria-label': STATUS_ORDER.filter((k) => counts[k])
      .map((k) => `${statusOf(k).cn} ${counts[k]}`).join('，'),
  }, STATUS_ORDER.filter((k) => counts[k]).map((k) =>
    el('i', {
      class: statusOf(k).cls,
      style: { flexGrow: String(counts[k]) },
      title: `${statusOf(k).label} · ${counts[k]}（${statusOf(k).why}）`,
    })));
}
