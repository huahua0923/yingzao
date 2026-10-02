// 汇总：**「是不是通用问题」** —— 用户第一句话的落点。
//
// ── 为什么是两个轴，而不是一个「共 N 个问题」────────────────────
//
// 盘上有两套完全不同的"问题"记录，它们连坐标系都不是一套：
//
//   轴 A（人圈的）：`_qa/annotations.json`
//       键 type × kind。`box` 是 **0..1 的图幅比例** —— 相对某张 PNG。
//   轴 B（机器找的）：`_qa/defects.json`
//       键 code × group。`pos` 是**米制工程坐标**（x∈[−66.95, 221.73]）——
//       相对那栋楼的 DXF 局部系。
//
// 两者之间还差一个「图幅 ↔ 工程坐标」的变换，而那正是同一个锚点问题。
// ⇒ **不许相加**。加出来的那个数没有任何含义，而它会是最像结论的一个数。
//   本页把它们**并排摆**，并且把这句话印在页上（`why_not_merged` 原样显示）。
//
// 顺带：轴 A 是**这一版才接上的**。`annotate_defects.py` 从 2026-09-14 起
// 就在写这个文件，30 条、10 栋 —— 而它全仓没有第二个读者。
// 没有读者就永远回答不了「是不是通用问题」。

import { API } from '/site/js/api.js';
import { el, mount, rich } from '/site/js/dom.js';

const N = (v, d = 0) => (v == null ? '—'
  : Number(v).toLocaleString('zh-CN', { minimumFractionDigits: d, maximumFractionDigits: d }));

// ★ 判词（通用/苗头/孤例）走**服务端原话**，但 DOM 上的 class 名走 ASCII。
//   把中文当 class 名不是语法错误，可它一旦进了选择器就再也 grep 不动了 ——
//   本仓的样式表全 ASCII，保持一条规则好过"这一处特殊"。
// ★ 强调记号（服务端判词里的 `**…**`）由 `dom.js` 的 `rich()` 渲染成 <b>，
//   不照原样印 —— 第一版把星号一起印到了屏幕上，而判据全绿。
//   那份说明跟着函数走，见 `/site/js/dom.js` 里 `rich()` 的注释。
const GUESS_CLASS = { 通用: 'g-common', 苗头: 'g-hint', 孤例: 'g-single' };

let _dlg = null;

export function openSummary() {
  if (!_dlg) {
    _dlg = el('dialog', { class: 'sum-dlg', 'aria-label': '问题汇总' });
    document.body.append(_dlg);
    // 点背板关掉（dialog 自己的 ::backdrop 不接事件，得自己算边界）。
    _dlg.addEventListener('click', (e) => { if (e.target === _dlg) _dlg.close(); });
  }
  mount(_dlg, el('div', { class: 'loading', text: '正在汇总…' }));
  _dlg.showModal();
  load(_dlg);
  return _dlg;
}

async function load(dlg) {
  let d;
  try {
    d = await API.annSummary();
  } catch (e) {
    return mount(dlg, frame(
      el('p', { class: 'site-miss' },
        el('b', { text: '汇总取不到。' }),
        el('p', { class: 'dim' }, el('code', { text: e?.message ?? String(e) })))));
  }
  render(dlg, d);
}

function frame(...body) {
  return el('div', { class: 'sum-wrap' }, ...body);
}

function render(dlg, d) {
  const a = d.axis_a ?? {};
  const b = d.axis_b ?? {};

  const head = el('header', { class: 'sum-head' },
    el('h2', { text: '问题汇总 · 两个轴' }),
    el('p', { class: 'dim', text:
      '「是不是通用问题」= 同一个毛病在「几栋楼」上出现。两轴各自聚合，互不相加。' }),
    el('button', { class: 'sum-x', type: 'button', text: '关闭', onclick: () => dlg.close() }));

  // ── 两个总数并排摆。N2 就钉在这两个数上：它们必须等于独立数出来的条数。
  const big = el('div', { class: 'sum-big' },
    el('div', { class: 'sum-axis sum-axis-a' },
      el('span', { class: 'sum-k', text: '人圈的（flag 轴）' }),
      el('span', { class: 'sum-n', text: N(a.n) }, el('span', { class: 'sum-u', text: '条' })),
      el('span', { class: 'sum-sub', text: `${N(a.n_buildings)} 栋` }),
      el('code', { class: 'sum-src', text: a.source ?? '' })),
    // ★ 中间这一格是**禁止符**，不是装饰：它是"这两列不许相加"的实物。
    el('div', { class: 'sum-plus', 'aria-hidden': 'true' }, '≠'),
    el('div', { class: 'sum-axis sum-axis-b' },
      el('span', { class: 'sum-k', text: '机器找的（code 轴）' }),
      el('span', { class: 'sum-n', text: b.n == null ? '读不出来' : N(b.n) }),
      el('span', { class: 'sum-u', text: b.n == null ? '' : '条' }),
      el('span', { class: 'sum-sub', text: b.n == null ? String(b.n) : '' }),
      el('code', { class: 'sum-src', text: b.source ?? '' })));

  mount(dlg, frame(
    head,
    // ★ 这里**不再自己加一句「两个轴不许相加：」** —— 服务端那句话本来就以此开头，
    //   两句叠起来屏幕上会读成「两个轴不许相加：两个轴不许相加：…」（第一版就是）。
    el('p', { class: 'sum-warn' }, rich(d.why_not_merged)),
    big,
    axisA(a),
    b.rows?.length ? axisB(b) : null));
}

function axisA(a) {
  const rows = el('table', { class: 'sum-tbl' },
    el('thead', {}, el('tr', {},
      el('th', { text: '问题类型' }),
      el('th', { class: 'num', text: '次数' }),
      el('th', { class: 'num', text: '楼数' }),
      el('th', { class: 'num', text: '层数' }),
      el('th', { text: 'src / recog' }),
      el('th', { text: '判' }))),
    el('tbody', {}, (a.rows ?? []).map((r) => el('tr', { class: r.common_guess === '通用' ? 'is-common' : null },
      el('td', {}, el('b', { text: r.label }), el('code', { class: 'sum-code', text: r.type })),
      el('td', { class: 'num', text: N(r.n) }),
      el('td', { class: 'num', text: N(r.n_buildings) }),
      el('td', { class: 'num', text: N(r.n_floors) }),
      el('td', { text: `${r.kinds?.src ?? 0} / ${r.kinds?.recog ?? 0}` }),
      el('td', {}, el('span', {
        class: `sum-guess ${GUESS_CLASS[r.common_guess] ?? 'g-single'}`,
        text: r.common_guess,
      }))))));

  return el('section', { class: 'sum-sec sum-sec-a' },
    el('h3', {}, '轴 A · 人圈的（这张表就是「通用问题」的答案）'),
    rows,
    el('p', { class: 'dim', text:
      '「判」那一列的门槛是三分档：3 栋及以上 = 通用、2 栋 = 苗头、1 栋 = 孤例。'
      + '门槛是人定的，页上只给「几栋楼」这个数 —— 它是硬的，门槛是软的。'
      + '「楼数」比「次数」重要：同一栋同一层圈了十遍，那是一处问题，不是十处。' }));
}

function axisB(b) {
  return el('section', { class: 'sum-sec sum-sec-b' },
    el('h3', {}, '轴 B · 机器找的（建模判据在几栋楼上响）'),
    el('table', { class: 'sum-tbl' },
      el('thead', {}, el('tr', {},
        el('th', { text: '判据码' }), el('th', { text: '组' }),
        el('th', { class: 'num', text: '条数' }), el('th', { class: 'num', text: '楼数' }),
        el('th', { text: '严重度分布' }))),
      el('tbody', {}, b.rows.map((r) => el('tr', {},
        el('td', {}, el('code', { text: r.code })),
        el('td', { text: r.group ?? '—' }),
        el('td', { class: 'num', text: N(r.n) }),
        el('td', { class: 'num', text: N(r.n_buildings) }),
        el('td', { text: Object.entries(r.sev ?? {}).map(([k, v]) => `${k}:${v}`).join(' · ') }))))),
    el('p', { class: 'dim', text:
      '这一轴来自 `_qa/defects.json`，它的既有读者是知识图谱那一侧（`kb/derive.py`）。'
      + '本页只是把它并排摆上来，不重算、不改它。' }));
}
