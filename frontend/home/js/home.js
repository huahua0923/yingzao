// 首页 —— 「原 DWG 图 ⇄ 三维模型 ⇄ 无人机正射」对比台。
//
// 三条口径**必须印在屏幕上**（见 cautionBand() 与舞台角注）：
//   ① 三维显示整栋，**不随**左侧楼层切换
//   ② 模型配色是建模通用配色，不是本楼实测外观
//   ③ 左边是「第 N 层」，右边是「整栋」—— 左右不是同一个口径
//
// 2026-10-02 加了两件事（用户：「指出问题，然后看是不是通用问题」
// / 「我指定无人机数据，你来分析，指出外形错误」/「整合到一个页面」）：
//   · 左屏长出一个**圈问题**图层（annotate.js）→ 落到 `_qa/annotations.json`
//   · 右屏多一个模式页签「实景校核」（sitecheck.js）→ 正射 ⊕ 模型足迹
//   · 数字条上那个「圈过 N 处」点开 = 汇总（summary.js）—— 那就是「通用问题」的答案
//
// ★ 三个 import 都是**根绝对**：本页文档 URL 是 `/`，而这三个文件住在
//   `/site/js/` 下。写成相对路径会解析到 `/js/*` —— 而 module 加载失败
//   **不弹窗、不报错**，页面只是静默地什么都不做（本仓记过这个形状）。

import { getEnv, get, API, ApiError } from '/site/js/api.js';
import { el, mount, add } from '/site/js/dom.js';
import { createViewer } from '/site/js/viewer.js';
import { createAnnotator } from './annotate.js';
import { sitePane, loadManifest } from './sitecheck.js';
import { auditPane, loadAudit } from './audit.js';
import { openSummary } from './summary.js';

const $boot = document.getElementById('boot');
const $summary = document.getElementById('summary');
const $rail = document.getElementById('rail');
const $stage = document.getElementById('stage');

const S = {
  rows: [], total: 0, shown: [], q: '',
  name: '', row: null,
  floors: [], floor: null, mode: 'cad',
  viewer: null, triangles: null,
  rmode: 'model',         // 右屏模式：model | site | audit
  half: 80,               // 正射窗口半幅（米）
  types: null,            // 问题类型清单（服务端给，前端不抄）
  anns: [],               // 本栋全部标注（`f` 是**字符串**，与服务端一致）
  draft: null,            // 正在写的那个框 {box, px}
  annArmed: false,
  annMsg: null,           // 写失败时**原样**显示服务端那句话
  seq: 0,                 // 竞态序号：连点两栋时，慢的那个不许覆盖快的
  pending: Promise.resolve(),
};

let ann = null;           // 圈选图层（每换一栋重建一次，旧的必须 destroy）

// ── 小工具 ────────────────────────────────────────────────────────
const N = (v, d = 0) => (v == null ? '—'
  : Number(v).toLocaleString('zh-CN', { minimumFractionDigits: d, maximumFractionDigits: d }));
const MB = (b) => (b == null ? '—' : b >= 1048576 ? `${(b / 1048576).toFixed(1)} MB`
  : b >= 1024 ? `${Math.round(b / 1024)} KB` : `${b} B`);
const SUM = (arr, f) => arr.reduce((a, x) => a + (f(x) || 0), 0);

// ── 启动 ──────────────────────────────────────────────────────────
S.pending = (async function boot() {
  let env;
  try {
    // ★ 走 getEnv 不走 API.buildings()：后者只回 data，而汇总条的分母
    //   「全库 N 栋」在 meta.total_on_disk 里 —— 两个数不同时，
    //   差别正是「你有权看的」与「盘上有的」，必须能分别印出来。
    env = await getEnv('/api/buildings');
  } catch (e) {
    return panic(e);
  }
  S.rows = env.data ?? [];
  S.total = env.meta?.total_on_disk ?? S.rows.length;
  $boot.remove();
  paintSummary();
  if (!S.rows.length) {
    return mount($stage, el('div', { class: 'loading', text: '这个库里一栋楼都没有（后端回的是一份空清单）。' }));
  }
  S.shown = S.rows;
  paintRail();

  const want = decodeURIComponent((location.hash.match(/^#\/(.+)$/) || [, ''])[1] || '');
  const first = S.rows.find((b) => b.name === want)
    ?? S.rows.find((b) => b.has_model)
    ?? S.rows[0];
  await select(first.name);
})();

// ── 汇总条 ────────────────────────────────────────────────────────
function paintSummary() {
  const nModel = S.rows.filter((b) => b.has_model).length;
  const nCad = S.rows.filter((b) => b.has_cad).length;
  const nFlr = SUM(S.rows, (b) => b.floor_count);
  const cell = (v, k, d) => el('div', { class: 'tally-cell' },
    el('span', { class: 'tally-v', text: N(v) }),
    el('span', { class: 'tally-k', text: k }),
    d && el('span', { class: 'tally-d', text: d }));

  mount($summary, el('div', { class: 'tally' },
    cell(nModel, '栋有三维模型', nModel < S.total ? `共 ${N(S.total)} 栋` : null),
    cell(nCad, '栋有 CAD 原图'),
    cell(nFlr, '层'),
    // 分母写出来。两个数相等时不必重复一遍，不等时必须说清差在哪。
    cell(S.total, '栋在盘上', S.total !== S.rows.length ? `本次可见 ${N(S.rows.length)} 栋` : null)));
}

// ── 楼栋带 ────────────────────────────────────────────────────────
function paintRail() {
  const rail = el('div', { class: 'h-rail' });
  for (const b of S.shown) rail.append(chip(b));
  // ★ 必须是 `{}` 不是 `null`：dom.js 的 `el(tag, props = {}, …)` 里，默认值
  //   只管 `undefined` —— 传 `null` 会走到 `'html' in props` 那一句上抛
  //   `TypeError: Cannot use 'in' operator … in null`。而它抛在 `paintRail()`
  //   里，整个 boot() 就此中断：目录带是空的、对比台也没开始画，
  //   屏幕上只是「一片没内容」——不会告诉你哪一行坏了。
  //   （2026-10-02 浏览器冒烟实测抓到的，静态检查看不出来。）
  const box = el('div', {}, rail);
  if (!S.shown.length) {
    rail.append(el('div', { class: 'h-empty', text: `没有楼号匹配「${S.q}」。` }));
  }
  mount($rail, box, searchBar());
}

function chip(b) {
  // ★ 只有**例外**挂文字角标：92 栋里 91 栋状态相同，给每一格都印「模型」
  //   只会把唯一那格淹掉，而这一带的全部信息量就在那一格上。
  //   （例外是**有字**的，color+text 双通道没被绕过。）
  const node = el('button', {
    class: 'h-chip', type: 'button', 'data-name': b.name,
    'aria-current': b.name === S.name ? 'true' : null,
    title: `${b.name} ${b.title || ''} · ${b.floor_count} 层 · `
      + (b.has_model ? '有三维模型' : '无三维模型'),
    onclick: () => select(b.name),
  },
  el('span', { class: 'h-code', text: b.name }),
  b.has_model ? el('span', { class: 'h-mark' })
    : el('span', { class: 'dot dot-no', text: '无模型' }));
  return node;
}

function searchBar() {
  const input = el('input', {
    type: 'search', value: S.q, placeholder: '楼号或楼名，如 c113 / 图书馆',
    'aria-label': '筛选楼栋',
    oninput: (e) => { S.q = e.target.value.trim(); refilter(); },
  });
  return el('div', { class: 'index-head' },
    el('label', { class: 'search' }, el('span', { class: 'search-k', text: '筛选' }), input),
    el('span', { class: 'index-count', text: `显示 ${N(S.shown.length)} / ${N(S.rows.length)} 栋` }));
}

function refilter() {
  const q = S.q.toLowerCase();
  S.shown = !q ? S.rows : S.rows.filter(
    (b) => b.name.toLowerCase().includes(q) || (b.title || '').toLowerCase().includes(q));
  const keep = document.activeElement;   // 别把焦点从搜索框上赶走
  paintRail();
  if (keep && keep.tagName === 'INPUT') $rail.querySelector('input')?.focus();
}

function markCurrent() {
  for (const c of $rail.querySelectorAll('.h-chip')) {
    if (c.dataset.name === S.name) {
      c.setAttribute('aria-current', 'true');
      // 只动 scrollLeft：整条带的横向定位不该顺带把页面纵向拽走。
      const rail = $rail.querySelector('.h-rail');
      if (rail) {
        rail.scrollLeft = Math.max(0, c.offsetLeft - (rail.clientWidth - c.offsetWidth) / 2);
      }
    } else c.removeAttribute('aria-current');
  }
}

// ── 选定一栋 ──────────────────────────────────────────────────────
async function select(name) {
  if (!S.rows.some((b) => b.name === name) || S.name === name) return;
  S.name = name;
  S.row = S.rows.find((b) => b.name === name);
  S.floors = []; S.floor = null; S.triangles = null;
  S.anns = []; S.draft = null; S.annMsg = null; S.annArmed = false;
  const want = `#/${encodeURIComponent(name)}`;
  if (location.hash !== want) location.hash = want;

  const my = ++S.seq;
  S.pending = (async () => {
    mount($stage, el('div', { class: 'loading', text: `正在读 ${name} 的楼层与产物…` }));
    // 标注与楼层并行取：它失败**不拦住页面**（一层楼都还没显示就先报错更坏），
    // 但也**不许吞**——失败的话那句原话要出现在数字条旁边。
    API.annotations(name).then((d) => {
      if (my !== S.seq) return;
      S.anns = Array.isArray(d?.items) ? d.items : [];
      // ★ 问题类型清单**只从服务端取**，不在前端抄一份。
      //   两份清单迟早不一样，而"漏了一条"在屏幕上表现为那个类型存不进去
      //   （服务端 400）或者存进去显示成空白 —— 都不像清单漂了（铁律 043）。
      if (Array.isArray(d?.types) && d.types.length) S.types = d.types;
      ann?.setItems(visibleAnns());
      paintFacts();
      paintAnnBar();
    }).catch((e) => {
      if (my !== S.seq) return;
      S.annMsg = `标注读不出来：${e?.message ?? e}`;
      paintFacts();
    });
    markCurrent();
    let floors;
    try {
      floors = await get(`/api/buildings/${name}/floors`);
    } catch (e) {
      if (my !== S.seq) return;
      return mount($stage, panicBox(e, `读不到 ${name} 的楼层数据`));
    }
    if (my !== S.seq) return;
    S.floors = Array.isArray(floors) ? floors : (floors?.floors ?? []);

    // 默认图种：有 CAD 就用 CAD；没有就退到识别叠加；都没有就是空的。
    const hasCad = S.floors.some((f) => f.cad?.exists);
    const hasPlan = S.floors.some((f) => f.plan?.exists);
    S.mode = hasCad ? 'cad' : (hasPlan ? 'plan' : 'cad');
    // 默认楼层：**最低那一层**，不是写死的 floor0 —— c001 是 [0..5]，
    // 但库里有带地下层的楼（负层号），写死 floor0 会在那些楼上取空。
    const want1 = S.floors.find((f) => pick(f, S.mode)?.exists) ?? S.floors[0];
    S.floor = want1 ? want1.floor : null;
    paintStage();
  })();
  return S.pending;
}

const pick = (f, mode) => (mode === 'plan' ? f?.plan : f?.cad);

// ── 整页重绘（换楼时） ────────────────────────────────────────────
function paintStage() {
  const b = S.row;
  const head = el('header', { class: 'b-head h-head' },
    el('h1', { class: 'b-title', text: `${b.name}${b.title ? ` · ${b.title}` : ''}` }),
    el('p', { class: 'b-sub' },
      el('span', { text: `图号 ${b.name}` }), el('span', { class: 'b-sep', text: '·' }),
      el('span', { text: `${N(b.floor_count)} 层` }), el('span', { class: 'b-sep', text: '·' }),
      // ★★ 这里原来写的是「足迹」——**名字指的是另一个量**（2026-10-02 改）。
      //   `outline_area_m2` 的定义在后端 `artifacts.py:191` 的注释里写得很清楚：
      //   「交付楼板面积（**各层** outline 面积之和）」；`_outline_total` 是
      //   `for F in floors: tot += shoelace(floor_F.outline)` —— 逐层相加。
      //   而**足迹**是一层的轮廓面积。c001 是 6 层 ⇒ 屏幕上那个数约等于真足迹的
      //   6 倍，读的人会拿它当这栋楼占多大地方（铁律 124/141：一个名字指两个量）。
      //   同一个仓里 `sitecheck.js` 的「模型足迹」才是真足迹（那份 fp 是单个多边形），
      //   所以只改这一处，别去动那个。
      el('span', { text: b.outline_area_m2 ? `各层楼板 ${N(b.outline_area_m2, 1)} ㎡` : '楼板面积未记录',
        title: 'floors/floorN.json 各层 outline 面积之和（不扣洞）——**不是**单体足迹' }),
      el('span', { class: 'b-sep', text: '·' }),
      el('span', { text: Number.isFinite(b.layer_height) ? `层高 ${N(b.layer_height, 1)} m` : '层高未记录' }),
      el('span', { class: 'b-sep', text: '·' }),
      // ★ 写「房间**台账**」不是「房间」：`b.rooms` 是 `len(rooms.json)`，即那份
      //   交付的房间台账；而底下事实条里那个数是 `floors/floorN.json` 里有 `poly`
      //   的几何房间数之和 —— c001 上一个是 69、一个是 12。**两个数都是真的**，
      //   是两样东西（台账带 purpose/dept/area；几何条目只有 {id, poly}）。
      //   一个词指两个量，就是本仓 artifacts.py:191 那条注释说的「必须各自标名」。
      el('span', {
        text: Number.isFinite(b.rooms) ? `房间台账 ${N(b.rooms)} 间` : '房间台账未记录',
        title: 'rooms.json（交付的房间台账，带用途/部门/面积）的条目数',
      })));
  // ★ 这里原来还有一格写着 `体量 ${b.style}`，2026-10-02 浏览器冒烟实测印出来是
  //   `体量 [object Object]`：`style` **不是**体量分类，是那栋楼的**材质配色字典**
  //   （`{facade:'#a4533d', roof:'#6b5a4a', roofType:'flat', glass:…, door:…}`），
  //   而后端给的是 `cfg.get("style") or {}` —— 空字典 `{}` 是**真值**，
  //   于是那个 `b.style ? … : '体量未分类'` 的三元**每一栋都走真分支**，
  //   92 栋一栋不漏地印出同一个 `[object Object]`。
  //   ⇒ 模板串里**只许出现标量**：数走 N()，字走 String，对象先挑出字段再印。
  //     判「有没有」用 Number.isFinite 这类**针对标量**的判据，不用真值性 ——
  //     `{}`、`[]` 都是真值，真值性判不出「这里到底有没有东西」。

  const rp = rightPane();
  rp.id = 'rpane';              // repaintRight() 按这个 id 换掉它
  mount($stage,
    head,
    el('div', { class: 'h-cmp' }, leftPane(), rp),
    cautionBand(),
    factsStrip());
}

// ── 左：图纸 ──────────────────────────────────────────────────────
function leftPane() {
  const cadLabel = S.floors.find((f) => f.cad?.label)?.cad.label ?? 'CAD 原图';
  const planLabel = S.floors.find((f) => f.plan?.source)?.plan.label ?? '识别叠加';
  const okCad = S.floors.some((f) => f.cad?.exists);
  const okPlan = S.floors.some((f) => f.plan?.exists);

  const tabs = el('div', { class: 'h-bar' },
    el('span', { class: 'h-bar-k', text: '图种' }),
    modeTab('cad', cadLabel, okCad),
    modeTab('plan', planLabel, okPlan));

  const flrs = el('div', { class: 'h-bar' },
    el('span', { class: 'h-bar-k', text: '楼层' }),
    ...S.floors.map(floorTab));

  const sheet = el('div', { class: 'h-sheet', id: 'sheet' });
  const cap = el('p', { class: 'h-cap', id: 'sheet-cap' });

  // ★ 换一栋楼就重建一圈图层，**旧的必须 destroy()** —— 它在 window 上挂了
  //   keydown 与 resize 两个监听器；只管新建不管拆，换 92 栋就是 92 组野监听器
  //   同时在跑，而屏幕上什么都看不出来（本仓铁律 022 那一族）。
  if (ann) ann.destroy();
  ann = createAnnotator(sheet, { onCommit: annCommit, onSelect: annSelect });

  const form = el('div', { class: 'ann-form', id: 'ann-form' });
  paintSheet(sheet, cap);
  paintAnnForm(form);
  return el('section', { class: 'h-pane' }, tabs, flrs, sheet, cap, annBar(), form);
}

// ── 左屏：圈问题 ──────────────────────────────────────────────────
//
// ★ `kind` 只由**当前图种**决定，不额外问人：
//   `annotations.json` 的 kind 恰好就是左屏那两个模式（src / recog），
//   多问一次会多出一个「人和图种对不上」的自由度 —— 那种不一致在屏幕上
//   是一个框画在 A 图上、回显到 B 图上，而它长得完全正常。
const kindOf = (mode) => (mode === 'plan' ? 'recog' : 'src');

/** 本层、且**图种相同**的标注。
 *
 *  ★ 图种这一维不许省：CAD 原图（`dxf_plan_fast`，1600×1192）与识别叠加
 *    （`dxf_plan_recog`，920×872）是**两张图幅不同的图**，同一个 0..1 比例
 *    在两张图上指的根本不是同一个地方。不按 kind 滤，圈在原图上的框会
 *    安静地画到识别图上，位置全错，而它看着像一个正常的框。
 */
function visibleAnns() {
  const k = kindOf(S.mode);
  return S.anns.filter((r) => r.kind === k && String(r.f) === String(S.floor))
    .map((r, i) => ({
      id: `${r.ts ?? ''}#${i}`,
      box: r.box,
      label: typeLabel(r.type),
      note: r.note,
      rec: r,
    }));
}

const typeLabel = (t) => (S.types ?? []).find((x) => x.key === t)?.label ?? t;

function annBar() {
  const hasImg = S.floors.some((f) => pick(f, S.mode)?.exists);
  const btn = el('button', {
    class: `h-tab h-ann-arm${S.annArmed ? ' is-on' : ''}`, type: 'button',
    'aria-pressed': S.annArmed ? 'true' : 'false',
    disabled: !hasImg,
    title: hasImg ? '打开后在图上按住拖一个框' : '这一层这种图没有，圈不了',
    onclick: () => {
      S.annArmed = !S.annArmed;
      ann?.setArmed(S.annArmed);
      paintAnnBar();
    },
  }, S.annArmed ? '画框中 —— 在图上拖一个框' : '圈问题');
  return el('div', { class: 'h-bar ann-bar', id: 'ann-bar' },
    btn,
    el('span', { class: 'ann-n', text: `本层 ${visibleAnns().length} 处` }),
    el('span', { class: 'ann-n', text: `本栋 ${S.anns.length} 处` }),
    el('span', { class: 'ann-hint', text: S.annArmed
      ? '拖完会问你是什么问题。Esc 取消。'
      : '用鼠标/触屏拖框（这个动作没有键盘等价物）。' }));
}

/** 只换这一条，不动左边的图 —— 重画整栏会让 <img> 重新请求一遍。 */
function paintAnnBar() {
  const old = document.getElementById('ann-bar');
  if (old) old.replaceWith(annBar());
}

function annCommit(box, px) {
  S.draft = { box, px };
  S.annMsg = null;
  paintAnnForm(document.getElementById('ann-form'));
}

function annSelect(id) {
  const it = visibleAnns().find((x) => x.id === id);
  if (it) S.annMsg = `${it.label}${it.note ? ` · ${it.note}` : ''}`;
  paintAnnForm(document.getElementById('ann-form'));
}

function paintAnnForm(host) {
  if (!host) return;
  const d = S.draft;
  if (!d) {
    if (!S.annMsg) return mount(host);
    return mount(host, el('p', { class: 'ann-msg', text: S.annMsg }));
  }
  const sel = el('select', { class: 'ann-sel', 'aria-label': '问题类型' },
    ...(S.types ?? []).map((t) => el('option', { value: t.key, text: t.label })));
  const note = el('input', { class: 'ann-note', type: 'text',
    placeholder: '一句话说明（可空）', 'aria-label': '备注' });
  mount(host, el('div', { class: 'ann-card' },
    el('p', { class: 'ann-q' }, el('b', { text: '这一处是什么问题？' }),
      el('span', { class: 'dim', text: `框 ${d.box.x0.toFixed(3)},${d.box.y0.toFixed(3)} → `
        + `${d.box.x1.toFixed(3)},${d.box.y1.toFixed(3)}（图幅比例 0..1）` })),
    el('div', { class: 'ann-row' }, sel, note,
      el('button', { class: 'btn btn-1', type: 'button', text: '存下',
        onclick: () => annSave(host, sel.value, note.value) }),
      el('button', { class: 'btn btn-ghost', type: 'button', text: '取消',
        onclick: () => { S.draft = null; paintAnnForm(host); } })),
    el('p', { class: 'dim', text:
      `存到 _qa/annotations.json：${S.name} · F${S.floor} · `
      + `${kindOf(S.mode)} · 比例框` })));
}

async function annSave(host, type, note) {
  const d = S.draft;
  if (!d) return;
  try {
    const rec = await API.annAdd({
      building: S.name, f: String(S.floor), kind: kindOf(S.mode),
      type, note, box: d.box,
    });
    S.anns = [...S.anns, rec];
    S.draft = null; S.annMsg = '已存下。';
    S.annArmed = false;
    ann?.setArmed(false);
    ann?.setItems(visibleAnns());
  } catch (e) {
    // ★ 原样打印服务端那句话。`GYM3D_COMPUTE=0` 的只读服务器会回
    //   403 `compute_disabled` —— 那是**对的**，页面上必须说清是"这台服务器
    //   按设计只读"，不许退化成"保存失败，请重试"（重试一万次也不会成）。
    S.annMsg = `${e?.code === 'compute_disabled' ? '这台服务器按设计是只读的：' : ''}`
      + `${e?.message ?? e}`;
  }
  paintAnnForm(host);
  paintAnnBar();
  paintFacts();
}

function modeTab(mode, label, ok) {
  return el('button', {
    class: 'h-tab h-mode', type: 'button', disabled: !ok,
    dataset: { mode },
    'aria-pressed': S.mode === mode ? 'true' : 'false',
    title: ok ? `${label}（本栋有）` : `${label}：这一栋没有这种图`,
    onclick: () => { S.mode = mode; repaintLeft(); },
  }, label);
}

function floorTab(f) {
  const ent = pick(f, S.mode);
  const ok = !!ent?.exists;
  return el('button', {
    class: 'h-tab h-flr', type: 'button', disabled: !ok,
    dataset: { floor: String(f.floor) },
    'aria-pressed': f.floor === S.floor ? 'true' : 'false',
    title: ok ? `第 ${f.floor} 层 · ${ent.label}` : `第 ${f.floor} 层没有这张图`,
    onclick: () => { S.floor = f.floor; repaintLeft(); },
  }, `F${f.floor}`);
}

function repaintLeft() {
  const host = document.getElementById('sheet');
  const cap = document.getElementById('sheet-cap');
  if (!host || !cap) return;
  // 按钮的加亮态要跟着走 —— 它们不在 host 里，局部重绘够不着。
  // ★ 认的是 dataset 里存的**身份**，不是按钮上的字：按钮文字是给人看的
  //   标签，改一次文案就会让下面这串比较静默地全判成 false（本仓记过：
  //   判据钉在「名字」上而不是「量」上）。
  const pane = host.closest('.h-pane');
  // ★ 这一句必须在 paintSheet **之前**：paintSheet 会把图换掉，而旧图上的
  //   那个框属于旧楼层 —— 先把画框模式关掉、把存量框清空，再换图。
  //   换过来的新图的框由下面 ann.setItems() 重新铺（按新楼层、新图种滤过）。
  //   并且退出画框模式：留着它，下一个拖拽会正好落在一张刚换过的图上，
  //   而人以为画的还是刚才那一层。
  S.draft = null;
  S.annArmed = false;
  ann?.setArmed(false);
  paintSheet(host, cap);
  ann?.setItems(visibleAnns());
  paintAnnBar();
  paintAnnForm(document.getElementById('ann-form'));
  for (const btn of pane.querySelectorAll('.h-mode')) {
    btn.setAttribute('aria-pressed', S.mode === btn.dataset.mode ? 'true' : 'false');
  }
  for (const btn of pane.querySelectorAll('.h-flr')) {
    btn.setAttribute('aria-pressed', btn.dataset.floor === String(S.floor) ? 'true' : 'false');
  }
}

function paintSheet(host, cap) {
  const f = S.floors.find((x) => x.floor === S.floor);
  if (!f) {
    ann?.track(null);            // 没有图 ⇒ 覆盖层退场，别铺在白底上接指针
    return mount(host, el('p', { class: 'h-sheet-miss', text: '这栋楼没有逐层数据。' })),
      mount(cap, el('span', { text: '没有楼层记录 —— 「查不到」不是「是空的」。' }));
  }
  const ent = pick(f, S.mode);

  // 三种状态必须分开说，不许都印成「没有图」：
  //   ① 后端说这一层这种图不存在  （ent.exists 假）
  //   ② 地址取不回来（img onerror）—— 上面说存在，下面取不到，是真矛盾
  //   ③ 一切正常
  if (!ent || !ent.exists) {
    ann?.track(null);
    mount(host, el('p', { class: 'h-sheet-miss' },
      el('b', { text: `第 ${S.floor} 层没有${ent?.label ?? '这张图'}。` }),
      el('br'), el('span', { text: '后端逐层清单里这一格是 exists=false —— 不是请求失败。' })));
    return mount(cap, el('span', { text: `第 ${S.floor} 层 · ${ent?.label ?? '—'} · 清单标为不存在` }));
  }

  const img = el('img', { alt: `${S.row.name} 第 ${S.floor} 层 ${ent.label}` });
  const px = el('span', { text: '读取中…' });
  // ★ 先挂 onerror 再设 src：反过来的话，命中浏览器缓存里的失败结果时
  //   这一枪打空，图就停在「什么都不显示」——与「这层没图」同形。
  img.addEventListener('error', () => {
    mount(host, el('p', { class: 'h-sheet-miss' },
      el('b', { text: '图取不到。' }), el('br'),
      el('span', { text: '接口说这一张存在，但地址取不回来：' }),
      el('code', { text: img.src })));
    mount(cap, el('span', { class: 'warn', text: '接口说存在、实际取不到 —— 这两句话矛盾，值得查。' }));
  });
  img.addEventListener('load', () => {
    px.textContent = `${img.naturalWidth}×${img.naturalHeight} px`;
  });
  // ★ 「在不在」由后端的 `ent.exists` 说了算，「往哪发」走 API.url ——
  //   这是全站唯一认识 GYM3D_API_BASE 前缀的地方。拿后端回的 `ent.url`
  //   当 src，在带前缀的部署下会静默 404（后端不知道前缀）。
  img.src = S.mode === 'plan' ? API.url.plan(S.row.name, S.floor)
    : API.url.cad(S.row.name, S.floor);
  mount(host, img);
  // ★ 覆盖层挂在**这张图**的矩形上（分母只能是图自己，不能是 .h-sheet ——
  //   图是居中放的，用底板当分母一换宽高比框就漂）。见 annotate.js 文件头。
  ann?.track(img);

  mount(cap,
    el('span', { text: `第 ${S.floor} 层` }), el('span', { class: 'b-sep', text: '·' }),
    el('span', { text: ent.label }), el('span', { class: 'b-sep', text: '·' }),
    ent.source ? el('code', { text: `${ent.source}/floor${S.floor}.png` }) : null,
    ent.source ? el('span', { class: 'b-sep', text: '·' }) : null,
    el('span', { text: MB(ent.bytes) }), el('span', { class: 'b-sep', text: '·' }),
    px);
}

// ── 右：三维 ──────────────────────────────────────────────────────
let stageHost = null;   // 常驻的 .stage 容器

/** 右屏的模式页签：[模型 | 实景校核 | 外形稽核]。与左边 `modeTab` 同一套样式与写法。 */
function rightTabs() {
  const t = (mode, label, title) => el('button', {
    class: 'h-tab h-rmode', type: 'button',
    dataset: { rmode: mode },
    'aria-pressed': S.rmode === mode ? 'true' : 'false',
    title,
    onclick: () => { S.rmode = mode; repaintRight(); },
  }, label);
  return el('div', { class: 'h-bar h-bar-r' },
    el('span', { class: 'h-bar-k', text: '右屏' }),
    t('model', '三维模型', '整栋 GLB'),
    t('site', '实景校核', '无人机正射影像 ⊕ 模型足迹（要有锚点）'),
    t('audit', '外形稽核', '全库一次扫完：模型自己跟自己自洽不自洽（不需要锚点、不需要无人机数据）'));
}

function rightPane() {
  const b = S.row;
  const tabs = rightTabs();

  // ── 实景校核：**与三维模型互斥** ────────────────────────────────
  // ★ 进这一格必须把 WebGL 看图器拆干净：rAF 不停的话上下文一直占着显存，
  //   而且 `stageHost` 是个**脱离文档**的节点 —— viewer 的 ResizeObserver
  //   挂在它身上，尺寸再也不会更新（屏幕上只是"窗口拉大后没反应"）。
  //   验收 N7 就钉在这：切到 site 模式后全文档 canvas 数必须是 0。
  if (S.rmode === 'site') {
    destroyViewer();
    stageHost = null;
    loadManifest();               // 底图那一行（CRS/分辨率/金字塔）要它
    return sitePane({
      name: b.name, half: S.half, head: tabs,
      onHalf: (h) => { S.half = h; repaintRight(); },
    });
  }

  // ── 外形稽核：这一格**不看某一栋**，看全库 ──────────────────────
  // ★ 同样必须拆干净看图器（同 site 模式那一段的理由）：rAF 不停会一直占着显存，
  //   而 `stageHost` 是脱离文档的节点 —— viewer 的 ResizeObserver 挂在它身上，
  //   尺寸再也不会更新。验收那条「切走之后全文档 canvas 数必须是 0」也管着这一格。
  if (S.rmode === 'audit') {
    destroyViewer();
    stageHost = null;
    loadAudit();                  // 起手就发请求；它慢（首次几秒），别等切回去才开始
    return auditPane({ head: tabs });
  }

  const cap = el('p', { class: 'h-cap', id: 'gl-cap' });
  const bar = el('div', { class: 'h-bar' },
    el('span', { class: 'h-bar-k', text: '三维' }),
    el('span', { text: b.has_model ? '整栋 GLB 交付件，可转可缩' : '这一栋还没有三维模型' }));

  if (!b.has_model) {
    // ★ 没有模型时**不许**留一个空 canvas：空画布上什么都不报错，
    //   屏幕上是「一块灰底」——它与「正在载入」同形，也与「这栋楼没模型」同形。
    destroyViewer();
    stageHost = null;
    paintGlCap(cap, '没有三维模型');
    return el('section', { class: 'h-pane' }, tabs, bar,
      el('p', { class: 'stage-miss' },
        el('b', { text: `${b.name} 没有三维模型。` }), el('br'),
        el('span', { text: '楼栋清单里 has_model=false —— 左右两栏里只有左边那一半。' })),
      cap);
  }

  if (!stageHost) stageHost = buildStageHost();
  const host = stageHost;
  const pane = el('section', { class: 'h-pane' }, tabs, bar, host, cap);
  loadModel(host, cap);
  return pane;
}

/** 只换右屏。★ 不重画整页 —— 重画会把左边的图重新请求一遍，
 *  而人点的是右边那两个页签。 */
function repaintRight() {
  const old = document.getElementById('rpane');
  if (!old) return;
  const nu = rightPane();
  nu.id = 'rpane';
  old.replaceWith(nu);
}

function buildStageHost() {
  const hud = el('div', { class: 'hud' });
  const notes = el('div', { class: 'stage-notes' });
  add(notes,
    el('p', { class: 'stage-note', text: '整栋显示，不随左侧楼层切换' }),
    el('p', { class: 'stage-note', text: '建模通用配色，非本楼实测外观' }));
  const tools = el('div', { class: 'stage-tools' },
    el('button', {
      class: 'btn btn-ghost', type: 'button', text: '复位视角',
      onclick: () => S.viewer?.refit(),
    }));
  return el('div', { class: 'stage' }, el('canvas'), hud, notes, tools);
}

async function loadModel(host, cap) {
  const hud = host.querySelector('.hud');
  mount(hud, el('span', { text: '正在载入…' }));
  paintGlCap(cap, '正在载入');
  const my = S.seq;

  let viewer;
  try {
    viewer = ensureViewer(host);
  } catch (e) {
    mount(hud, el('span', { text: 'WebGL 起不来' }));
    return paintGlCap(cap, `浏览器起不了 WebGL：${e.message}`);
  }

  const url = API.url.model(S.row.name);
  try {
    const r = await viewer.load(url, (done, total) => {
      if (my !== S.seq) return;
      mount(hud, el('span', { text: total
        ? `正在载入 ${MB(done)} / ${MB(total)}`
        : `正在载入 ${MB(done)}` }));
    });
    if (my !== S.seq) return;
    S.triangles = r.triangles;
    mount(hud,
      el('span', {}, '三角面 ', el('b', { text: N(r.triangles) })),
      el('span', { text: `尺寸 ${N(r.size.x, 1)} × ${N(r.size.z, 1)} × ${N(r.size.y, 1)} m` }));
    paintGlCap(cap, '已载入');
  } catch (e) {
    if (my !== S.seq) return;
    S.triangles = 0;
    mount(hud, el('span', { text: '载入失败' }));
    paintGlCap(cap, `载入失败：${e.message}`);
  }
}

function paintGlCap(cap, state) {
  const b = S.row;
  mount(cap,
    el('span', { text: state }), el('span', { class: 'b-sep', text: '·' }),
    el('code', { text: `${b.name}/${b.name}-building.glb` }),
    el('span', { class: 'b-sep', text: '·' }),
    el('span', { text: '整栋，不切层' }));
}

function ensureViewer(host) {
  if (S.viewer) return S.viewer;
  // ★ canvas 必须**已经挂在 DOM 里**再建查看器：viewer.js 在构造那一刻就
  //   `ro.observe(renderer.domElement.parentElement)`，而且只观察那一个节点。
  //   所以宿主 .stage 一旦被换掉（换楼时重建），观察器就挂在脱离文档的节点上，
  //   尺寸再也不更新 —— 而屏幕上只是「窗口拉大后模型没跟着变」，不报错。
  //   这就是 stageHost 要**常驻**、不每栋重建的原因。
  S.viewer = createViewer(host.querySelector('canvas'));
  S.viewer.start();   // load() 只 resize，不启动渲染循环
  return S.viewer;
}
function destroyViewer() {
  try { S.viewer?.dispose(); } catch { /* 已经坏了就算了，别盖住真正的错 */ }
  S.viewer = null;
}

// ── 口径与事实 ────────────────────────────────────────────────────
function cautionBand() {
  return el('p', { class: 'h-caution' },
    el('b', { text: '两边不是同一个口径：' }),
    '左边是', el('b', { text: '第 N 层的平面图' }), '，右边是', el('b', { text: '整栋' }),
    '的三维模型 —— 不是同一张图的两个视图。逐点比形状会比出并不存在的差异。');
}

function factsStrip() {
  const c = (k) => SUM(S.floors, (f) => f.counts?.[k]);
  const fact = (v, k, unit) => el('span', { class: 'h-fact' },
    el('b', { text: v }), el('i', { text: unit ?? '' }), el('span', { text: k }));
  // ★ 这一格原来写的是「N 个房间」，与头部那个「房间 N 间」**同词不同量**：
  //   这里是 `floors/floorN.json` 的 `rooms` 数组长度之和 —— 那些条目的形状是
  //   `{id, poly}`（**只有几何**，没有房号/名称/用途），是建模用的房间多边形；
  //   头部那个是 `rooms.json` 的台账行数。c001 实测 12 : 69。
  //   ⇒ 两个都印，但**各自标名**；并且这一个给 tooltip 写清它数的是哪一份。
  const rooms = SUM(S.floors, (f) => f.rooms);
  const roomFact = fact(N(rooms), '间已建几何的房间');
  roomFact.title = 'floors/floorN.json 里带 poly 的房间条目之和（几何口径，无房号名称）'
    + '；与头部「房间台账」不是同一份清单';
  // ★「圈过 N 处」是本栋**人圈的**那一条，它点开就是汇总页 —— 也就是
  //   「是不是通用问题」那一问的答案。它必须与机器找到的条目**分开摆**，
  //   而且各自标名（两套坐标系不同，不许相加）。
  const annBtn = el('button', {
    class: 'h-fact h-fact-btn', type: 'button',
    title: '本栋已有的人工标注条数；点开看全库两个轴的汇总',
    onclick: () => openSummary(),
  }, el('b', { text: N(S.anns.length) }), el('i', {}), el('span', { text: '处人圈的问题 ↗' }));
  return el('div', { class: 'h-facts', id: 'facts' },
    fact(N(S.floors.length), '层有逐层记录'),
    fact(N(c('walls')), '段墙'),
    fact(N(c('windows')), '扇窗'),
    fact(N(c('doors')), '樘门'),
    fact(N(c('columns')), '根柱'),
    roomFact,
    annBtn,
    S.annMsg ? el('span', { class: 'h-fact dim', text: S.annMsg }) : null);
}

function paintFacts() {
  const old = document.getElementById('facts');
  if (old) old.replaceWith(factsStrip());
}

// ── 出错 ──────────────────────────────────────────────────────────
function panic(e) {
  mount($stage, panicBox(e, '读不到楼栋清单'));
  $boot.remove();
}

/** 401 / 403 / 503 / 连不上 —— **四句话不同**，因为下一步的动作不同。 */
function panicBox(e, what) {
  const box = el('div', { class: 'panic' });
  const st = e instanceof ApiError ? e.status : null;
  if (st === 401 || e?.code === 'unauthenticated') {
    return mount(box,
      el('h2', { text: '请先登录' }),
      el('p', { text: `${what}：楼栋清单、图纸和模型都要求登录后查看。` }),
      el('div', { class: 'panic-hint' },
        el('p', { text: '登录入口在建模后台。登录后回到本页即可。' }),
        el('p', {}, el('a', { class: 'btn btn-1', href: '/admin/', text: '去后台登录 →' }))));
  }
  if (st === 403 || e?.code === 'forbidden') {
    return mount(box,
      el('h2', { text: '你的账号看不到这些楼栋' }),
      el('p', { text: `${what}：后端认得你，但你的授权范围里没有这栋楼。` }),
      el('div', { class: 'panic-hint', text: '这是范围问题，重新登录解决不了 —— 要找管理员加授权。' }));
  }
  if (st === 503) {
    return mount(box,
      el('h2', { text: '账号库暂时连不上' }),
      el('p', { text: `${what}：后端连不上账号库，认不出任何身份。` }),
      el('div', { class: 'panic-hint', text: '这不是密码的问题，等库恢复后重试即可。' }));
  }
  if (e?.code === 'network') {
    return mount(box,
      el('h2', { text: '连不上后端' }),
      el('p', { text: `${what}：请求根本没到服务器。` }),
      el('div', { class: 'panic-hint' },
        el('p', { text: '8140 上的 API 没在跑，或者地址不对。' }),
        el('p', { text: e.message })));
  }
  return mount(box,
    el('h2', { text: '页面出错了' }),
    el('p', { text: `${what}。` }),
    el('div', { class: 'panic-hint', text: e?.message ?? String(e) }));
}

// ── 生命周期 ──────────────────────────────────────────────────────
window.addEventListener('hashchange', () => {
  const n = decodeURIComponent((location.hash.match(/^#\/(.+)$/) || [, ''])[1] || '');
  if (n && S.rows.some((b) => b.name === n) && n !== S.name) select(n);
});
// 切走/关页时收干净：rAF 不停的话 WebGL 上下文会一直占着显存。
window.addEventListener('pagehide', () => destroyViewer());

// ── 给验收脚本的探针 ──────────────────────────────────────────────
// 「数在 DOM 里」与「数在屏幕上」不是一回事（本仓铁律 39），但下面这些
// 至少是**脚本能读到**的，不必靠肉眼；断言写在 _scratch 的验收脚本里。
window.__home = {
  settled: () => S.pending,
  snapshot: () => ({
    rows: S.rows.length, shown: S.shown.length, total: S.total,
    summary: [...document.querySelectorAll('#summary .tally-v')].map((e) => e.textContent),
    name: S.name, mode: S.mode, floor: S.floor,
    hasModel: S.row?.has_model ?? null,
    canvas: !!document.querySelector('.stage canvas'),
    miss: document.querySelector('.stage-miss, .h-sheet-miss')?.textContent ?? null,
    triangles: S.triangles,
    sheetSrc: document.querySelector('#sheet img')?.getAttribute('src') ?? null,
    sheetNatural: document.querySelector('#sheet img')?.naturalWidth ?? null,
    floors: S.floors.length,
    disabledFloors: [...document.querySelectorAll('.h-flr')].filter((b) => b.disabled).map((b) => b.textContent),
    disabledModes: [...document.querySelectorAll('.h-mode')].filter((b) => b.disabled).map((b) => b.textContent),
    hash: location.hash,

    // ── 圈选（annotate.js）──────────────────────────────────────
    rmode: S.rmode, half: S.half,
    annArmed: S.annArmed,
    annTotal: S.anns.length,
    annBoxes: document.querySelectorAll('.ann-box').length,
    // ★ 覆盖层的**分母**：验收要拿它把屏幕坐标换算成比例，
    //   再与存下去的 box 比 —— 这样测的是"比例口径对不对"，
    //   而不是"两个数是不是恰好不同"（后者可能因为别的原因不同）。
    annLayer: rectOf('.ann-layer'),
    sheetImg: rectOf('#sheet img'),
    imgNatural: (() => { const i = document.querySelector('#sheet img');
      return i ? [i.naturalWidth, i.naturalHeight] : null; })(),

    // ── 实景校核（sitecheck.js）─────────────────────────────────
    // ★ N7 钉在 canvasAll 上：切到 site 模式后它必须是 0。
    canvasAll: document.querySelectorAll('canvas').length,
    siteImg: !!document.querySelector('.site-sheet img'),
    siteMiss: document.querySelector('.site-miss')?.textContent ?? null,
    siteCap: document.getElementById('site-cap')?.textContent ?? null,

    // ── 外形稽核（audit.js）─────────────────────────────────────
    // ★ 探针只钉**屏幕上真的有那些字**：`.textContent` 读的是 DOM，
    //   而本仓铁律 39 记着「数在 DOM 里 ≠ 数在屏幕上」——
    //   所以这里另外给 `auText`（整块的纯文本），让判据能对字面下断言；
    //   要判"看得见"仍须走 190（自己没隐 + 祖先没裁 + 没人盖住）那三条。
    auLoaded: !!document.querySelector('#au-host .au-head'),
    auMiss: document.querySelector('#au-host .site-miss')?.textContent ?? null,
    auBarNote: document.getElementById('au-bar-note')?.textContent ?? null,
    auCap: document.getElementById('au-cap')?.textContent ?? null,
    auCards: document.querySelectorAll('#au-host .au-card').length,
    auTags: [...document.querySelectorAll('#au-host .au-tag')].map((e) => e.textContent),
    auTagClasses: [...document.querySelectorAll('#au-host .au-tag')].map((e) => e.className),
    auTableRows: document.querySelectorAll('#au-host .au-table tbody tr').length,
    auTableShown: (() => { const w = document.querySelector('#au-host .au-table-wrap');
      return !!w && getComputedStyle(w).display !== 'none'; })(),
    auHostText: document.getElementById('au-host')?.innerText ?? null,
    auErrText: document.querySelector('#au-host .site-miss')?.innerText ?? null,
  }),
  select: (n) => select(n),
  setMode: (m) => { S.mode = m; repaintLeft(); },
  setFloor: (f) => { S.floor = f; repaintLeft(); },
  setRmode: (m) => { S.rmode = m; repaintRight(); },
  setHalf: (h) => { S.half = h; repaintRight(); },
  arm: (on) => { S.annArmed = !!on; ann?.setArmed(S.annArmed); paintAnnBar(); },
  // 给验收用：**不经过指针**直接喂一个框进来（真实的 pointer 事件在无头浏览器里
  // 要一格一格地派发；这里喂的是"拖完之后那个框"，计算比例的代码路径完全一样）。
  draw: (box) => annCommit(box, { w: 0, h: 0 }),
  openSummary: () => openSummary(),
  annItems: () => visibleAnns(),
  viewerAlive: () => !!S.viewer,
};

function rectOf(sel) {
  const n = document.querySelector(sel);
  if (!n) return null;
  const r = n.getBoundingClientRect();
  return { x: r.left, y: r.top, w: r.width, h: r.height };
}
