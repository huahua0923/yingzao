// 首页右屏第三模式：「外形稽核」—— 全库一次扫完，**一条一条摆出来给人判**。
//
// ── 这一页要解决的问题 ──────────────────────────────────────────
//
// 前面两格是「看一栋」：三维看整栋、实景校核看某一栋贴得准不准。
// 这一格是「看全库」：**哪些栋自己跟自己不自洽**。
//
// 量的是**模型自己身上两个数之差**，两个数都指同一个量 —— 这栋楼有多高：
//   A 路 `floors/floor*.json` 的 Σ层高（地上部分）
//   B 路 GLB 里 POSITION 的 Y 跨度
// B 是 A 堆出来的 ⇒ 本该只差一个屋面常数。差得多 ⇒ 堆叠那一步漏了/多了东西。
// ★ 因为量的是**差**，GLB 是 Y-up 还是 Z-up、局部零点摆在哪，都不影响结论。
//
// ── 三条不许省 ──────────────────────────────────────────────────
//
// ① 参照值**从全库实测算出来**，页面上必须写清它是算出来的、不是手打的。
//    手打一个 0.900，就把「我的声明错了」和「这栋楼错了」变成屏幕上同一行字。
// ② **三态分开**：`off`（量到了、有差）/ `ok`（量到了、一致）
//    / `na`+`failed`（**做不了**）。第三档**不是**「没问题」——
//    「做不了」印成「一致」是本仓最有名的那类错，所以它单独一块、单独计数。
// ③ 口径写在每个数旁边：`floor < 0`（地下层）不算地上。

import { API, ApiError } from '/site/js/api.js';
import { el, mount, add, rich, clear } from '/site/js/dom.js';

const N = (v, d = 0) => (v == null ? '—'
  : Number(v).toLocaleString('zh-CN', { minimumFractionDigits: d, maximumFractionDigits: d }));

const STATE_LABEL = {
  ok: '一致', off: '有差', na: '做不了', failed: '读坏了',
};

let _data = null;        // 全库快照：只取一次，换楼不重取
let _err = null;
let _sel = null;         // 当前选中的楼号
let _cur = 0;            // 「要判的」那一列里的游标

export async function loadAudit() {
  if (_data || _err) return { data: _data, err: _err };
  try { _data = await API.shapeAudit(); } catch (e) { _err = e; }
  return { data: _data, err: _err };
}

export function auditPane({ head }) {
  const cap = el('p', { class: 'h-cap', id: 'au-cap' });
  const host = el('div', { class: 'h-sheet au-sheet', id: 'au-host' });
  const bar = el('div', { class: 'h-bar' },
    el('span', { class: 'h-bar-k', text: '全库' }),
    el('span', { class: 'au-bar-note', id: 'au-bar-note', text: '正在扫全库…' }),
    el('button', {
      class: 'h-tab', type: 'button', title: '重新扫一遍（服务端按目录 mtime 缓存，改了模型这页会自己变）',
      onclick: () => { _data = null; _err = null; _sel = null; _cur = 0; load(host, cap); },
    }, '重扫'));
  const pane = el('section', { class: 'h-pane' }, head, bar, host, cap);
  load(host, cap);
  return pane;
}

async function load(host, cap) {
  mount(host, el('p', { class: 'loading', text: '正在扫全库的模型与层表…（首次要把每栋的层表读一遍，约几秒）' }));
  mount(cap, el('span', { class: 'dim', text: '扫描中' }));
  const { data, err } = await loadAudit();
  if (err) return paintErr(host, cap, err);
  paint(host, cap, data);
}

// ── 出错：网络断 / 服务端坏了 —— **不是**「全库都没问题」（铁律 166）──
function paintErr(host, cap, e) {
  const net = e instanceof ApiError && e.code === 'network';
  mount(host, el('div', { class: 'site-miss' },
    el('b', { text: net ? '连不上后端。' : '稽核接口取不到。' }),
    el('p', { text: net
      ? '8140 上的 API 没在跑，或者地址不对 —— 与「全库模型都自洽」不是一回事。'
      : '这是服务端这一侧的问题，不是「这一库没有问题」。' }),
    el('p', { class: 'dim' }, el('span', { text: '服务端原话：' }),
      el('code', { text: e?.message ?? String(e) }))));
  mount(cap, el('span', { class: 'warn', text: `取不到 · ${net ? '网络' : `HTTP ${e?.status ?? '?'}`}` }));
}

function paint(host, cap, d) {
  // ★ 起手先清空 —— 这不是"顺手"，是 2026-10-02 量出来的一个真缺陷：
  //   `load()` 走的是 `mount(host, 正在扫…)`，而这一函数下面全是 `add(host, …)`
  //   ⇒ 那行"正在扫"**从来没有被摘掉**，一直挂在最上面当地一个孩子。
  //   实测（切进这一格后只画一次）：`#au-host` 6 个孩子、首个 = `p.loading`。
  //   它在第一张截图里"没有"，只是因为那张截图之前点过「下一条」，
  //   那一步走 `load2()` → `mount(host)` 才把它冲掉 ——
  //   ⇒ **两趟不同的动作画出两种版面，而两边都不报错**（铁律 183 的同族：
  //     不许拿"我这一眼看见的"代替"它每次都会这样"）。
  clear(host);
  const c = d.counts;
  const ref = d.reference;
  const off = d.off || [];
  const bad = d.items.filter((it) => it.state === 'na' || it.state === 'failed');
  const okItems = d.items.filter((it) => it.state === 'ok');

  const note = document.getElementById('au-bar-note');
  if (note) {
    note.textContent = `量了 ${c.ok + c.off} 栋 · 一致 ${c.ok} · 有差 ${c.off} · 做不了 ${c.na + c.failed}`;
  }

  // ── 参照值 / 门槛 / 分布 ────────────────────────────────────────
  // ★ 这一块不是装饰：**判据的刻度必须和它的结论印在一起**（否则"偏离 4.2 m"
  //   读的人不知道 4.2 算大还是算小），而参照值的**出处**决定了读的人
  //   该不该信它 —— 它是全库算出来的，不是谁写死在源码里的。
  const maxN = Math.max(1, ...d.dist.map((x) => x.n));
  add(host, el('div', { class: 'au-head' },
    el('div', { class: 'au-ref' },
      el('span', { class: 'au-ref-k', text: '参照值' }),
      // ★ 符号要**先问有没有值**：`null >= 0` 在 JS 里是 true（null 折成 0），
      //   照原样写会印出「+— m」——一个不存在的量的正号。服务端一栋都没量到
      //   时 `m` 是 null，那时该显示的就只是「—」。
      el('span', { class: 'au-ref-v', text: ref.m == null ? '— m'
        : `${ref.m >= 0 ? '+' : ''}${N(ref.m, 3)} m` }),
      el('span', { class: 'au-ref-s' }, rich(
        `= ${ref.how}；量了 ${ref.n_measured} 栋，其中 ${ref.n_agree} 栋落在同一档，`
        + `MAD ${N(ref.mad_m, 3)} m，极差 [${N(ref.min_m, 2)}, ${N(ref.max_m, 2)}] m`))),
    el('div', { class: 'au-ref' },
      el('span', { class: 'au-ref-k', text: '判「有差」的门槛' }),
      el('span', { class: 'au-ref-v', text: `±${N(d.tol_m, 2)} m` }),
      el('span', { class: 'au-ref-s' }, rich(d.tol_why))),
    el('div', { class: 'au-dist' },
      el('span', { class: 'au-ref-s', text: '残差分布（0.5 m 一档）：' }),
      ...d.dist.map((x) => el('div', { class: 'au-dist-row' },
        el('code', { text: `${x.m >= 0 ? '+' : ''}${N(x.m, 1)}` }),
        // ★ 条宽要有一个**看得见的下限**：实测 −3.5 那一档 n=1、按比例算出 1 px，
        //   屏上它与"没有这一档"完全一样，而旁边写着「1 栋」—— 一个真有的数
        //   画成了没有（`n === 0` 才该是 0 宽；服务端不吐空档）。
        el('span', {
          class: 'au-dist-bar',
          style: { width: `${x.n > 0 ? Math.max(4, Math.round(120 * x.n / maxN)) : 0}px` },
        }),
        el('span', { text: `${x.n} 栋` }))))));

  // ── ① 要判的：一条一条摆 ────────────────────────────────────────
  if (_cur >= off.length) _cur = 0;
  if (_sel && !d.items.some((x) => x.name === _sel)) _sel = null;
  const focus = _sel ? d.items.find((x) => x.name === _sel)
    : (off[_cur] ?? okItems[0] ?? d.items[0]);

  add(host, el('div', { class: 'au-sec' },
    el('div', { class: 'au-sec-h' },
      el('b', { text: `要判的：${off.length} 条` }),
      off.length ? el('span', { class: 'au-stepper' },
        el('button', { class: 'h-tab', type: 'button', onclick: () => step(-1, off, host, cap, d) }, '上一条'),
        el('span', { text: `${_cur + 1} / ${off.length}` }),
        el('button', { class: 'h-tab', type: 'button', onclick: () => step(1, off, host, cap, d) }, '下一条'))
        : el('span', { class: 'dim', text: '（这一趟一条都没有）' })),
    el('p', { class: 'au-why-not' }, rich(
      '★ 这一层量的是**模型自己自洽不自洽**，不是模型对不对 —— '
      + '两边一起错（图纸错、输入错）它照样全绿。所以「一致」不等于「外形对」。')),
    off.length === 0
      ? el('p', { class: 'dim', text: '没有「量到了但有差」的。上面那句仍然成立：这不代表模型都对。' })
      : null,
    focus ? cardFor(focus, d) : null));

  // ── ② 做不了的 —— **单独一块，不并进上面那个数** ────────────────
  if (bad.length) {
    add(host, el('div', { class: 'au-sec au-sec-bad' },
      el('div', { class: 'au-sec-h' }, el('b', { text: `做不了的：${bad.length} 条` })),
      el('p', { class: 'au-why-not' }, rich(
        '★ 这一档**不是**「没问题」—— 是**没量过**。'
        + '把它读成「一致」会把一个坏掉的管道印成全绿。')),
      ...bad.map((it) => el('div', { class: 'au-row au-row-na' },
        el('code', { text: it.name }),
        el('span', { class: 'au-tag au-tag-na', text: STATE_LABEL[it.state] }),
        el('span', { text: it.why || '（没写原因）' })))));
  } else {
    // ★ 「查过是 0」与「本模块不分这一档」必须**印得不一样**（铁律 146）：
    //   这里印的是前者 —— 全库每一栋都量到了，且这个数是数出来的（c.na + c.failed）。
    add(host, el('p', { class: 'dim',
      text: `做不了的：0 条（全库 ${c.total} 栋都量到了 —— 这是数出来的，不是没查）。` }));
  }

  // ── ③ 一致的：计数 + 可展开的全表 ───────────────────────────────
  const tbody = el('tbody');
  let open = false;
  const table = el('div', { class: 'au-table-wrap', style: { display: 'none' } },
    el('table', { class: 'au-table' },
      el('thead', {}, el('tr', {},
        el('th', { text: '楼号' }), el('th', { text: '层数（地上/全部）' }),
        el('th', { text: 'GLB Y 跨度' }), el('th', { text: 'Σ层高（地上）' }),
        el('th', { text: '残差' }), el('th', { text: '偏离参照值' }), el('th', { text: '档' }))),
      tbody));
  const rowsFor = (list) => list.map((it) => el('tr', {
    class: `au-tr au-tr-${it.state}`,
    tabindex: '0',
    title: '点一下看它的出处',
    onclick: () => { _sel = it.name; load2(host, cap, d); },
  },
  el('td', {}, el('code', { text: it.name })),
  // ★ 这一列原先是 `` `${it.n_above} / ${it.n_floors}` `` —— 模板串**不认 `N()`
  //   那套空值处理**，`做不了` 的行上这两个字段是 `undefined`
  //   ⇒ 屏幕上是字面的「undefined / undefined」。实测：展开全表那一趟，
  //   `c006pub` 那一行整行读作 `undefined / undefined — — — — 做不了`。
  //   同一个页面里 `N()` 就在手边、别的列都用了它，唯独这一列漏了 ——
  //   **漏的那一列恰好只在一行上出声**（铁律 174：手打的串挨着一张已经列对的清单）。
  el('td', { text: it.n_above == null ? '—'
    : `${N(it.n_above)} / ${N(it.n_floors)}` + (it.has_basement ? '（有地下）' : '') }),
  el('td', { text: N(it.glb_h_m, 2) }),
  el('td', { text: N(it.sum_above_m, 2) }),
  el('td', { text: it.resid_above_m == null ? '—'
    : `${it.resid_above_m >= 0 ? '+' : ''}${N(it.resid_above_m, 2)}` }),
  el('td', { text: it.dev_m == null ? '—'
    : `${it.dev_m >= 0 ? '+' : ''}${N(it.dev_m, 2)} m（${N(it.dev_layers, 2)} 层）` }),
  el('td', {}, el('span', { class: `au-tag au-tag-${it.state}`, text: STATE_LABEL[it.state] }))));
  add(tbody, ...rowsFor(d.items));

  // ★ 标题上的数（一致的 90）与这张表的行数（92）**不是同一个数**，不许让它们
  //   长得像同一个：表是**全库一览**（含做不了的那几栋，它们的行上没有数），
  //   而上面那句是对 ok 的**计数**。两个数都是数出来的，但一个来自后端 counts、
  //   一个来自 items.length；手打「92 栋」这种字一个都不留（铁律 174）。
  const invLabel = `展开全库一览（${N(d.items.length)} 栋）`;
  const invOpen = `收起全库一览`;
  add(host, el('div', { class: 'au-sec' },
    el('div', { class: 'au-sec-h' },
      el('b', { text: `一致的：${c.ok} 条` }),
      el('button', {
        class: 'h-tab', type: 'button',
        onclick: (e) => {
          open = !open;
          table.style.display = open ? '' : 'none';
          e.target.textContent = open ? invOpen : invLabel;
          // ★ 展开之后**必须把表带进视口**：实测这一格在 1440×1000 下，
          //   全表落在**折线以下** —— 点一下"什么都没发生"（页面只是变长了
          //   一屏）。★ 铁律 190：「在屏幕上」是三个条件，我原先只量了第②条
          //   （祖先没裁），量到"表里有 15 行"就收工了，而**它在视口外面**。
          //   不用 `behavior:'smooth'`：平滑滚动下同步读 `getBoundingClientRect()`
          //   拿到的是**动画前**的位置（memory: browser-read-stale-...）。
          if (open) table.scrollIntoView({ block: 'nearest' });
        },
      }, invLabel)),
    el('p', { class: 'dim' }, rich(bad.length
      ? `这一张是**全库一览**，${N(d.items.length)} 栋都在里面 —— 含**做不了的 ${bad.length} 栋**`
        + `（它们那几行上没有数，只有「做不了」）。行数比上面那个 ${c.ok} 多，是**对的**。`
      : `这一张是全库一览，${N(d.items.length)} 栋都在里面，与上面那个数一致。`)),
    table));

  // ── 底：口径 + 出处 ─────────────────────────────────────────────
  add(host, el('p', { class: 'au-read' },
    el('b', { text: '读法 ' }),
    el('span', { text: `GLB：${d.read.glb}；层表：${d.read.floors}` }), el('br'),
    el('span', { class: 'dim' }, rich(d.read.why_this_works))));
  mount(cap, el('span', { class: 'warn', text: d.caveat ? '★ 自洽 ≠ 对' : '' }),
    el('span', { class: 'dim', text: ' 判定结果本页不写盘（先走一遍，改哪几条由人来定）' }));
}

function step(delta, off, host, cap, d) {
  if (!off.length) return;
  _cur = (_cur + delta + off.length) % off.length;
  _sel = off[_cur].name;
  load2(host, cap, d);
}

/** 选中的那一栋：把**判它需要的东西**全摆出来，一处不缺。 */
function cardFor(it, d) {
  const ref = d.reference;
  if (it.state === 'na' || it.state === 'failed') {
    return el('div', { class: 'au-card' },
      el('div', { class: 'au-card-h' },
        el('code', { text: it.name }), el('span', { class: `au-tag au-tag-${it.state}`, text: STATE_LABEL[it.state] })),
      el('p', { text: it.why || '（没写原因）' }));
  }
  const dev = it.dev_m ?? 0;
  const devL = it.dev_layers ?? 0;
  const toward = dev < 0 ? '比参照值**矮**' : '比参照值**高**';
  return el('div', { class: `au-card au-card-${it.state}` },
    el('div', { class: 'au-card-h' },
      el('code', { text: it.name }),
      el('span', { class: `au-tag au-tag-${it.state}`, text: STATE_LABEL[it.state] }),
      el('span', { class: 'au-card-title', text: it.title && it.title !== it.name ? it.title : '' })),
    el('div', { class: 'au-two' },
      kv('A 路 · Σ层高（地上）', `${N(it.sum_above_m, 2)} m`,
        `${it.n_above} 层 · 层高中位 ${N(it.layer_height_med_m, 2)} m`
        + (it.has_basement ? ' · **有地下层，没算进这一栏**' : '')
        + `　出处 ${it.floors_dir}`),
      kv('B 路 · GLB 的 Y 跨度', `${N(it.glb_h_m, 2)} m`,
        `${N(it.n_vert, 0)} 个顶点 · 文件 ${N(it.glb.mb, 1)} MB　出处 ${it.glb.path}`)),
    el('div', { class: 'au-verdict' },
      el('span', { class: 'au-verdict-k', text: '差' }),
      el('span', { class: 'au-verdict-v' }, rich(
        `相差 **${N(it.resid_above_m, 2)} m**，参照值是 **${ref.m >= 0 ? '+' : ''}${N(ref.m, 3)} m** ⇒ `
        + `这一栋${toward} **${N(Math.abs(dev), 2)} m = ${N(Math.abs(devL), 2)} 层**，`
        + `门槛是 ±${N(it.tol_m, 2)} m`))),
    el('p', { class: 'au-card-s' }, rich(
      '★ 两个数**同源**（GLB 是层表堆出来的）⇒ 差里没有外部基准，所以差多少就是差多少。'
      + '这一栋若真是**少堆了一层**，缺口会正好是它自己的层高 —— 上面那个「层」数就是干这个的。')));
}

function kv(k, v, sub) {
  return el('div', { class: 'au-kv' },
    el('span', { class: 'au-kv-k', text: k }),
    el('span', { class: 'au-kv-v', text: v }),
    sub ? el('span', { class: 'au-kv-s' }, rich(sub)) : null);
}

/** 只重画内容区（换选中项/换条目不重取数据）。 */
function load2(host, cap, d) {
  const keep = host.scrollTop;
  mount(host);
  paint(host, cap, d);
  host.scrollTop = keep;
}
