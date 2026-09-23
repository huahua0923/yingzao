// 数字与时间的写法 —— 集中一处，免得同一个数在两屏上长得不一样。
//
// ★ 数字一律等宽显示（见 app.css 的注释）：这一屏上每个数都要逐位对比。
// ★ 「不知道」的写法是**空**，不是 0、也不是 undefined。后端没给时间戳就回 null，
//   这里必须回一个看着就是"没有"的东西（—），而不是让模板串把 undefined 印上去。

/** 千分位整数。null/undefined/NaN → 「—」。 */
export function fmtInt(n) {
  if (n === null || n === undefined || Number.isNaN(Number(n))) return '—';
  return Number(n).toLocaleString('en-US');
}

/** 字节数。 */
export function fmtBytes(n) {
  if (typeof n !== 'number') return '—';
  const u = ['B', 'KB', 'MB', 'GB'];
  let i = 0;
  let v = n;
  while (v >= 1024 && i < u.length - 1) { v /= 1024; i += 1; }
  return `${i === 0 ? v : v.toFixed(1)} ${u[i]}`;
}

/** 后端给的就是本地时间字符串（YYYY-MM-DD HH:MM:SS），原样显示；没有就「—」。 */
export function fmtTime(s) {
  return s || '—';
}

/** 截断长文本（判据说明动辄两三百字，列表里只显示前一段）。 */
export function ellipsis(s, n = 160) {
  const t = String(s ?? '');
  return t.length > n ? `${t.slice(0, n)}…` : t;
}
