// 「图谱」视图 —— `kb/` 那张知识图谱的前端。三栏，不是一张力导向大图。
//
// 路由（hash，零依赖，可分享）：
//     #/kg            这一屏的骨架：图里现在有什么
//     #/kg/<说法>      某个说法扩散激活出来的整条链（可带楼号，如 `c057 楼层错位`）
//
// ★★ 四条不许含糊的规矩：
//   1. **三态分开画**：`hit` / `unverified` / `miss` 各是各的色和话。
//      `miss` 是「图里没有这个说法」，**绝不是「没问题」**（铁律 16 一族）。
//   2. **按字段画，不按状态画**：下面渲染什么，看这份载荷**有哪些键**，
//      不看 `state` 是哪一档。理由：引擎往后加一个字段，按 state 写死的分支
//      会把它**静默漏掉** —— 而少画的东西不会喊（memory: silent-failure-needs-a-voice）。
//      所以末尾还有一个「这份载荷还有这些字段没画」的兜底块，宁可难看也不许吞。
//   3. **前端一个判断都不做**：链上的每一条结论、每个指纹都原样来自
//      `GET /api/kg/ask` 的 `data`（它就是 `kb/ask.py --json` 的那一份，
//      逐字段相同由 `python -m backend.checks.kg_view_accept --parity` 守着）。
//   4. **跑判据这条路是"有路 + 有闸门"，不是"没有路"**（★ 2026-09-25 这条事实变了）。
//      原先这里写着「本页不执行任何命令，连"运行"按钮都不放」，靠的是
//      「`kb/ask.py --run` **没有 HTTP 通路**」这个更强的保证。**那个保证已经放弃** ——
//      用户拍板把「跑判据」按钮直接放在这一屏上，走 `POST /api/kg/run`
//      （真起一个作业，最坏 900 秒；等结果靠轮询，不挂在请求上）。
//      ⇒ 新的闸门是**「通路 ＋ 本机限定」**，就挂在既有的那一处判定上
//        （`deps.exec_denied_reason`，与真正执行时**同一个函数**）：
//        · 非回环来源 ⇒ 403 `local_only`（除非设了 `GYM3D_ADMIN_TOKEN` 且带对
//          `X-Admin-Token`）；`GYM3D_COMPUTE=0` ⇒ 403 `compute_disabled`；
//        · 只读的那些照旧在局域网上可用 —— 这一屏本来就是"给局域网看的"。
//      ⇒ 所以按钮的状态**先问 `API.capabilities()`**，不行就置灰并把**后端自己那句话**
//        原样显示出来 —— 「点了才发现不能用」和「一开始就写明」不是一回事。
//      ⇒ 仍然**没有** HTTP 通路的是另外两条，别顺手也给它们开口子：
//        `kb/ask.py --pending`（登记，写 `kb/pending.json`）、`kb/build_kb.py`（重打包）。
//        那两条只给复制按钮。
import { el, add, mount } from '../dom.js';
import { API, ApiError } from '../api.js';

export const label = '图谱';

const state = { inv: null, invMeta: null, invErr: null, data: null, meta: null, askErr: null,
  of: null,      // 点链接的人想打开的节点 id（手打的查询没有这个，见 parseSub）
  view: 'chain', // 'chain' | 'graph'
  act: null, actMeta: null, actErr: null,  // 扩散激活那张图（`GET /api/kg/activation`）
  caps: null, capsErr: null,        // `GET /api/capabilities` —— 按钮开关的**唯一**依据
  run: null,                        // 当前那个「跑判据」作业的最近一次读数
  q: '', root: null, sub: '' };     // 重画要用的东西（视图一换就得重画整屏）

let disposed = false;
let pollTimer = null;
let resizeWired = false;

export function dispose() {
  disposed = true;
  stopPoll();
  if (resizeWired) { window.removeEventListener('resize', onResize); resizeWired = false; }
  // canvas 本身随 `mount()` 的 clear() 一起离开 DOM；这里只是把引用放开，
  // 免得下一屏拿到一个已经不在文档里的画布（画上去什么也看不见，且不报错）。
  GVDOM = { wrap: null, cv: null, tip: null, note: null };
  GV.nodes = []; GV.edges = []; GV.pos = {}; GV.adj = {};
}

/** 三态各自的说法。★ 措辞是判据的一部分：`miss` 那句必须说清"不是没问题"。 */
const STATES = {
  hit: {
    cls: 'ok', head: '命中',
    why: '图里有这个说法 —— 下面是它的根因 / 处置 / 可跑判据 / 并列陷阱。',
  },
  unverified: {
    cls: 'warn', head: '命中，但没有仓内锚点',
    why: '这一条**只有人记着**（仓内找不到可复核的锚点）⇒ 可参考，不许当已核。',
  },
  miss: {
    cls: 'miss', head: '图里没有这个说法',
    why: '★这不是「没问题」，是「没查过 / 还没收」。下面给最接近的几条与登记入口。',
  },
};

/** 中栏按这个次序画；不在这张表里的键走兜底块。 */
const ORDER = ['title', 'kind', 'symptom', 'cause', 'fix', 'run', 'related',
  'mechanism', 'guards', 'masquerades_as', 'cases', 'unverifiable',
  // ★ `content` 是**知识条目那一支的正文**（整篇 md）。加在这里是量出来的：
  //   逐条走完 29 个节点后，9 篇条目每篇都报「还有 3 个字段本页没画」，
  //   那三个正是 `content` / `domain` / `entry` —— 条目那一支当时只画出了标题，
  //   正文落进了 JSON 兜底块。上面那句「宁可难看，不许吞」当时只做到了"说没画"，
  //   而这三栏恰恰是这一支的**全部内容**。
  // ★ 2026-09-24 补：`spread` / `activated` / `satellites` 是扩散激活那一层的三个键。
  //   加进 ORDER ＝ 真的画（见下面 `spreadBlock` 那一段的说明），**不是**加进 DRAWN 了事。
  'spread', 'activated', 'satellites', 'content'];

// ── 小件 ────────────────────────────────────────────────────────────

function pill(text, cls, title) {
  return el('span', { class: `kg-pill${cls ? ' ' + cls : ''}`, text, title: title || null });
}

/**
 * 一个节点 id（`pb:<家族>` / `trap:<陷阱>` / 条目 id）→ **一个查得动它的词**。
 *
 * ★ 为什么不直接拿节点 id 当查询词：`ask.py` 的分词器把 `:` 也算分隔符，
 *   于是 `trap:<slug>` 会被拆成两个词 —— 而**裸词 `trap` 本身就是一条退化别名**：
 *   `kb/ask.py` 的别名索引除手工别名外还从 slug 自动切词，每条 slug 都带 `trap-`，
 *   ⇒ 实测**裸词 `trap` 一个词点亮全部 14 条陷阱 ＋ 4 个家族**。
 *   后果不是"查不到"，是**查到了但糊**：`trap:<slug>` 点亮 **18** 个节点（头一条确实是它，
 *   因为权重 1.0），而走别名表只点亮 **1** 个。两个数由 `kg_view_accept --parity` 第 ③ 节
 *   每次实测报出（★ 我先前把这件事写成"前缀会落到别的节点上"，是**错的**，
 *   而且我当时的判据"前缀点不点得到自己"量出来 14/14 全中 —— 那是**饱和判据**：
 *   待检对象整个落在判据的分辨力之外，满分什么也没证明）。
 *   ⇒ 一律走**别名表**：那是"能点亮这个节点、且点得干净"的那份表，而且
 *     `kg_view_accept --parity` 的第 ③ 节会逐条验它真的点亮了**这个**节点。
 *
 * ★ 清单没取到 ⇒ 回 null，调用方画成**不可点的纯文本**（不猜、不硬拼）。
 */
function wordFor(node) {
  if (!node || typeof node !== 'string') return null;
  const inv = state.inv;
  if (!inv) return null;
  if (node.startsWith('pb:')) {
    const f = (inv.families || []).find((x) => x.id === node.slice(3));
    return (f && f.aka && f.aka.length) ? f.aka[0] : null;
  }
  if (node.startsWith('trap:')) {
    const t = (inv.traps || []).find((x) => x.slug === node.slice(5));
    return (t && t.aka && t.aka.length) ? t.aka[0] : null;
  }
  // 条目 id 本身就是查询词（实测 `图线-线型-线宽` → hit kind=entry，且由验收器③守着）
  return (inv.entries || []).some((x) => x.id === node) ? node : null;
}

/**
 * 一条链接的 href：查词 ＋ **想打开的那个节点**（`?of=<节点 id>`）。
 *
 * ★ 为什么要把"我想打开谁"写进 URL：因为**引擎不一定给我那一个**。
 *   实测（`--parity` ③ 那把尺子量出来的）：14 条陷阱里有 **8 条**，
 *   它的**每一个**别名（含 slug、含标题全文）主命中都落在**某个家族**上 ——
 *   即那 8 条陷阱**打不开自己**（`饱和` → 家族 楼层错位、`代理几何` → 家族 房间骑墙外溢…）。
 *   光看 `activated` 是看不出来的：那些词**确实点亮了**那条陷阱（所以旧判据 18/18 全绿），
 *   只是主命中不是它。一个"点了打开别处"的链接，正是本页最恨的那类安静假话。
 *   ⇒ 带上 `of=`，页面就能在**打开之后**把这件事喊出来（见 `intentBlock`），
 *     而不是让用户对着一个不认识的家族页自己纳闷。
 */
function hrefOf(word, node) {
  const q = `#/kg/${encodeURIComponent(word)}`;
  return node ? `${q}?of=${encodeURIComponent(node)}` : q;
}

/** 可点就画链接，不可点就画**纯文本并说明原因** —— 不给"点了没反应"的假链接。 */
function jumpTo(node, label) {
  const w = wordFor(node);
  if (!w) {
    return el('span', { class: 'kg-rail-a off', text: label ?? node,
      title: '认不出一个查得动它的词（清单没取到，或这一条没有别名）⇒ 不做成链接' });
  }
  return el('a', { class: 'kg-go', href: hrefOf(w, node),
    text: label ?? node, title: `用 ${w} 查（想打开 ${node}）` });
}

/**
 * 「你点的是 A，引擎打开的是 B」—— 只在**不一致**时出现，一致时一个字都不说。
 *
 * ★ 措辞是判据的一部分：这句话必须让读者立刻明白**该信哪一个**。
 *   打开的是 B（引擎的主命中），但 B 不是他要找的那一条 ⇒ 说清"这一条打不开自己"，
 *   而不是含糊地说"结果可能不准"。含糊的那版会让人以为是自己查错了词。
 */
function intentBlock(d) {
  const of = state.of;
  if (!of || !d) return null;
  const got = d.hit_kind === 'family' ? (d.family ? `pb:${d.family}` : null)
    : d.hit_kind === 'trap' ? (d.trap ? `trap:${d.trap}` : null)
      : d.hit_kind === 'entry' ? (d.entry || null) : null;
  if (got === of) return null;
  return el('div', { class: 'kg-warnline kg-intent' },
    el('b', { text: '★ 你点的是 ' }), code(of),
    el('b', { text: '，引擎打开的是 ' }), code(got || '（没有主命中）'),
    el('span', { text: ' —— 左边那一条**打不开自己**：它的每个别名（连 slug 与标题全文）'
      + '主命中都被别的节点占了。这不是查错了词，是**排序**的事；'
      + '下面画的是打开了的那个节点的内容，要那条陷阱自己的字段得另想办法。' }));
}

function code(text, cls) {
  return el('code', { class: cls || null, text });
}

/** 复制按钮 —— 失败就说失败，不假装复制了（剪贴板在非安全上下文会被拒）。 */
function copyBtn(text) {
  const b = el('button', { class: 'kg-copy', type: 'button', text: '复制' });
  b.addEventListener('click', async () => {
    try {
      await navigator.clipboard.writeText(text);
      b.textContent = '已复制';
    } catch (e) {
      b.textContent = '复制失败';
      b.title = String(e && e.message ? e.message : e);
    }
    setTimeout(() => { b.textContent = '复制'; }, 1600);
  });
  return b;
}

function card(title, cls, ...children) {
  return el('section', { class: `kg-card${cls ? ' ' + cls : ''}` },
    title ? el('h3', { class: 'kg-card-h', text: title }) : null, children);
}

/** `[{what, evidence}]` 一族的条目。**认不出的形状也照样画出来**，不许跳过。 */
function itemList(items) {
  return el('ul', { class: 'kg-items' }, (items || []).map((it) => {
    if (it === null || typeof it !== 'object') return el('li', { text: String(it) });
    const { what, evidence, ...rest } = it;
    const head = what ?? it.node ?? it.title ?? null;
    const ev = evidence ?? it.at ?? null;
    const restEntries = Object.entries(rest).filter(([k]) => !['node'].includes(k));
    return el('li', {},
      head !== null ? el('div', { class: 'kg-what', text: String(head) }) : null,
      ev !== null ? el('div', { class: 'kg-ev' }, code(String(ev))) : null,
      // ★ 一条目里其余的键**一个都不丢**：只画 what/evidence 时，`readonly`/`writes`
      //   这类会改变"这条命令能不能跑"的字段就被吞掉了。
      restEntries.length
        ? el('div', { class: 'kg-rest' }, restEntries.map(([k, v]) =>
          el('span', { class: 'kg-kv' }, el('b', { text: k }), ' ',
            typeof v === 'string' ? code(v) : code(JSON.stringify(v, null, 0)))))
        : null);
  }));
}

/** 「跑一条命令」的块。★ 会写盘的要先说出来 —— 一条命令写不写盘，是它自己的字段。 */
function runBlock(runs) {
  return card('可跑判据（命令原样给出来，跑不跑随你）', 'kg-run', el('div', { class: 'kg-note' },
    '每一条都能照原样在命令行跑；复制按钮给的就是那条命令。'
    + '上面那个「跑判据」按钮走的是同一条命令，只是经由 HTTP —— 它由**后端**按来源判：'
    + '本机放行、局域网一律 403（见那一行的说明）。'
    + '两条路都要落盘（`_qa/<楼>_qa.txt` 与 `data/_meta/kg_runs.json`），所以都不是只读的。'), (runs || []).map((r) => {
    const writes = r.writes || r.write || null;
    return el('div', { class: `kg-cmd${writes ? ' writes' : ''}` },
      el('div', { class: 'kg-cmd-line' }, code(r.cmd || '(没有 cmd 字段)'), copyBtn(r.cmd || '')),
      writes ? el('div', { class: 'kg-warnline' },
        el('b', { text: '★ 会写：' }), code(String(writes)),
        '（跑之前先确认这处产物可以覆盖 —— 覆盖交付件是不可回滚的）') : null,
      r.expect ? el('div', { class: 'kg-kv' }, el('b', { text: '预期 ' }), r.expect) : null,
      r.read ? el('div', { class: 'kg-kv' }, el('b', { text: '怎么读 ' }), r.read) : null,
      r.readonly !== undefined
        ? el('div', { class: 'kg-kv' }, el('b', { text: '只读 ' }), String(r.readonly)) : null,
      r.evidence ? el('div', { class: 'kg-ev' }, code(r.evidence)) : null,
      Object.entries(r).filter(([k]) => !['cmd', 'expect', 'read', 'evidence', 'readonly',
        'writes', 'write'].includes(k)).map(([k, v]) =>
        el('div', { class: 'kg-kv' }, el('b', { text: k + ' ' }), code(String(v)))));
  }));
}

/** 陷阱块：**有锚点 / 只有人记着**必须一眼分得开（形状＋字，不只靠颜色）。 */
function trapBlock(traps) {
  return card('并列陷阱 —— 几何根因之外的量具/方法论坑', null,
    el('div', { class: 'kg-note' },
      '这些不是「另一种病因」，是**判据自己会怎么骗你**。查症状之前先看一眼这一栏。'),
    el('ul', { class: 'kg-traps' }, (traps || []).map((t) => el('li', {
      class: t.anchored ? 'anchored' : 'human-only',
    },
      el('div', { class: 'kg-trap-head' },
        pill(t.anchored ? '有仓内锚点' : '只有人记着', t.anchored ? 'ok' : 'warn'),
        el('span', { class: 'kg-trap-title', text: t.title || t.slug }),
        t.slug ? jumpTo(`trap:${t.slug}`, '查它 ↗') : null),
      t.masquerades_as
        ? el('div', { class: 'kg-masq' }, el('b', { text: '它装成：' }), t.masquerades_as) : null))));
}

// ── 中栏：扩散激活那一层（`spread` / `activated` / `satellites`）──────
//
// ★ 这三栏是 2026-09-24 补的，补它的直接原因是 **K5 的 `--shapes` 判据当场红了 46 处**：
//   引擎的答案多了 `spread` 与 `satellites` 两个键，而本页没有画它们的代码 ⇒
//   它们落进「还有 N 个字段本页没画」。★ 更早的一处更值得记：`activated`
//   原本就写在 `DRAWN` 里、却**一个渲染分支都没有** —— `DRAWN` 是手写的名单，
//   把一个键写进去就够让兜底块闭嘴，所以"声明画得出来"和"真的画了"在屏幕上
//   是两件事（本仓铁律：形式≠语义）。这也是把这三栏做成**真代码**而不是加进 `DRAWN` 的理由。
//
// ★ 画法全部**按值的形状**（与上面那条教训同一条）：对象 → 键值行、数组 → 列表，
//   认不出的形状照样原样打出来，绝不 silent skip。

/** 扩散那一栏：这一屏的「点亮」是怎么来的，以及**它有没有被截断/回落**。 */
function spreadBlock(s) {
  if (!s || typeof s !== 'object') {
    return card('扩散（图上的传播）', 'kg-warn', el('div', { class: 'kg-note' },
      `这一屏带了 spread 字段，但它的形状本页认不出（${typeof s}）：`,
      code(JSON.stringify(s, null, 0)), ' —— 原样贴出来，不猜。'));
  }
  const legacy = s.mode !== 'graph';
  const cut = s.cut && typeof s.cut === 'object' ? s.cut : null;
  // ★ 三态必须分开写（本仓铁律 16）：① 回落（图不在）② 截断（亮着的没列全）
  //   ③ 没截断。**「没截断」与「没量过截断」不是一句话** —— 旧产物没有 cut 字段时
  //   只能说「说不了」，不许折成「没有截断」。
  const cutText = cut === null
    ? '这一份产物里没有 cut 字段（旧产物）⇒ 截没截断说不了：跑 python -u kb/build_kb.py 重建。'
    : (cut.n ? `亮着的节点被截断：另有 ${cut.n} 个更弱的没列出来`
        + `（列到的最弱 ${cut.min_shown}、被截掉的最强 ${cut.min_cut}）。`
      : '没有截断：亮着的节点这里全都列出来了。');
  return card('扩散（图上的传播，不是查表）', legacy || (cut && cut.n) ? 'kg-warn' : null,
    el('div', { class: 'kg-kv' },
      el('b', { text: '模式 ' }),
      legacy ? '回落成一跳（产物里没有 graph 一节）' : '扩散（沿图走）',
      el('b', { text: ' ｜ 实走 ' }), String(s.hops ?? '—'),
      el('b', { text: ' 跳 / 上限 ' }), String(s.max_hops ?? '—'), ' 跳'),
    legacy ? el('div', { class: 'kg-warnline' },
      '★ 这一屏是「回落」的：只有直接指向这个词的那些节点，转一手能到的那一片不在上面。'
      + '两者的区别是「答案不全」，不是「答案一样」。') : null,
    el('div', { class: cut === null || cut.n ? 'kg-warnline' : 'kg-note', text: cutText }));
}

/** 激活路径：每个节点带**跳数** —— 直指 / 一转 / 两转，这是"凭什么觉得它相关"的凭据。 */
function activationBlock(a) {
  if (!Array.isArray(a)) {
    return card('激活路径', 'kg-warn', el('div', { class: 'kg-note' },
      `activated 不是数组（${typeof a}）—— 原样贴出来：`, code(JSON.stringify(a, null, 0))));
  }
  return card(`激活路径（扩散激活，不是查表）${a.length ? ` — ${a.length} 个节点` : ''}`, null,
    el('div', { class: 'kg-note' },
      '一个词点亮一片：权重 1.0 = 这个词直接指到它；下面标着几跳的，就是转了几手才碰上。'
      + '跳数越大越可能是噪声，别看权重排序就当结论。'),
    el('ul', { class: 'kg-traps' }, a.map((n) => el('li', {},
      el('div', { class: 'kg-trap-head' },
        pill(n.hops === 0 ? '直指' : `${n.hops} 跳`, n.hops === 0 ? 'ok' : null),
        jumpTo(n.node, n.node),
        el('span', { class: 'kg-kv' }, el('b', { text: ' 权重 ' }), String(n.weight ?? '—'))),
      n.why ? el('div', { class: 'kg-ev', text: String(n.why) }) : null,
      n.via ? el('div', { class: 'kg-kv' }, el('b', { text: '由 ' }), code(String(n.via))) : null))));
}

/** 附属节点：**「还点亮」不等于「答案」** —— 这一栏单列，就是不许它们混进主命中。 */
function satellitesBlock(sats) {
  if (!Array.isArray(sats)) {
    return card('还点亮（附属节点）', 'kg-warn', el('div', { class: 'kg-note' },
      `satellites 不是数组（${typeof sats}）—— 原样贴出来：`, code(JSON.stringify(sats, null, 0))));
  }
  return card(`还点亮（附属节点，不是答案） — ${sats.length} 个`, null,
    el('div', { class: 'kg-note' },
      '这些是**被带亮的实物/用例/命令节点**（`ev:` / `run:`）：它们告诉你"这个词在哪落过地"，'
      + '但它们不是这个说法本身。'),
    el('ul', { class: 'kg-traps' }, sats.map((n) => el('li', {},
      el('div', { class: 'kg-trap-head' },
        pill(String(n.kind ?? '?')),
        el('span', { class: 'kg-trap-title', text: String(n.node ?? '') }),
        el('span', { class: 'kg-kv' }, el('b', { text: ' 权重 ' }), String(n.weight ?? '—'))),
      n.why ? el('div', { class: 'kg-ev', text: String(n.why) }) : null))));
}

// ── 中栏：三态横幅 ＋ 链 ────────────────────────────────────────────

function stateBanner(d) {
  const s = STATES[d.state] || { cls: 'unknown', head: `不认识的状态：${d.state}`,
    why: '★页面不认识它 —— 说明引擎加了一档而这里没跟上。不把它硬塞进三态里的任何一档。' };
  return el('div', { class: `kg-banner ${s.cls}` },
    el('div', { class: 'kg-banner-head' },
      pill(s.head, s.cls),
      d.query ? el('span', { class: 'kg-q' }, '说法 ', code(d.query)) : null,
      d.building ? el('span', { class: 'kg-q' }, '楼号 ', code(d.building)) : null,
      d.hit_kind ? el('span', { class: 'dim', text: `（命中类型 ${d.hit_kind}）` }) : null,
      // `family` / `trap` 是节点 id（`floor-misalign` / `trap-…`）。**画出来** ——
      // 它们是 `--list` 里那一列的同一个东西，人拿它去对照命令行；
      // 留在兜底块里等于这一栏悄悄少一项（★实测：只画 family 时，trap 那一支
      // 的 `trap` 字段就落进了「还有 1 个字段本页没画」）。
      d.family ? el('span', { class: 'dim' }, '家族 ', code(d.family)) : null,
      d.trap ? el('span', { class: 'dim' }, '陷阱 ', code(d.trap)) : null,
      // `entry` 与 `domain` 同理：条目那一支的节点 id 与它所属的域。
      // `domain` 是「一台引擎 + N 个域」（drafting / solid / twin）在页面上的那一栏 ——
      // 不画出来就分不清「这条结论是哪个域的」，而 twin 域正在建。
      d.entry ? el('span', { class: 'dim' }, '条目 ', code(d.entry)) : null,
      d.domain ? el('span', { class: 'dim' }, '域 ', code(d.domain)) : null),
    el('p', { class: 'kg-banner-why', text: s.why }));
}

/** miss 那一栏：**必须**有最近似的几条与登记入口，否则"查不到"没法变成"排队"。 */
function missBlock(d) {
  return card('最接近的几条 ＋ 登记入口', 'kg-miss',
    (d.nearest || []).length
      ? el('ul', { class: 'kg-items' }, d.nearest.map((n) => el('li', {},
        el('div', { class: 'kg-what' },
          jumpTo(n.node, n.node || '(没有 node 字段)'),
          n.score !== undefined ? el('span', { class: 'dim', text: ` 分数 ${n.score}` }) : null),
        n.matched ? el('div', { class: 'kg-masq' }, el('b', { text: '靠近在：' }), n.matched) : null)))
      : el('div', { class: 'kg-warnline', text: '★ 连「最接近的几条」都没有 —— 这不是「没有相近的知识」，是这一栏没画出来。' }),
    d.already_pending
      ? el('div', { class: 'kg-kv' }, el('b', { text: '此前已登记 ' }),
        `${d.already_pending.times} 次（最近 ${d.already_pending.at}，${d.already_pending.who}）`)
      : null,
    d.register
      ? el('div', { class: 'kg-cmd' },
        el('div', { class: 'kg-cmd-line' }, code(d.register), copyBtn(d.register)),
        el('div', { class: 'kg-note' },
          '登记**不等于**已经认识它 —— 在它落进 `playbook.json` 之前，同一个说法照样回 miss。'
          + '重复登记是有用的（重复次数本身就是「这个症状有多常见」的证据），所以不许去重抹掉。'))
      : null);
}

/** 兜底：这份载荷里有、而本页没画的字段。宁可难看，不许吞。 */
const DRAWN = new Set(['query', 'building', 'state', 'hit_kind', 'ruler', 'activated',
  'families', 'family', 'trap', 'traps', 'entries', 'nearest', 'register',
  'already_pending', 'next_action', 'derived_instances', 'instances',
  'unverified', 'entry', 'domain', ...ORDER]);

function leftoverBlock(d) {
  const rest = Object.keys(d).filter((k) => !DRAWN.has(k));
  const unv = d.unverified;
  return fragList(
    unv && unv.length
      ? card('本家族声明「无锚点」的条目（诚实性那一栏，不是缺陷栏）', 'kg-warn',
        itemList(unv))
      : null,
    el('details', { class: 'kg-leftover' },
      el('summary', { text: rest.length
        ? `这份载荷还有 ${rest.length} 个字段本页没画（点开看原样）`
        : '这份载荷的字段本页都画了' }),
      el('pre', { class: 'kg-json', text: JSON.stringify(
        rest.length ? Object.fromEntries(rest.map((k) => [k, d[k]])) : {}, null, 2) })),
    d.next_action
      ? el('div', { class: 'kg-next' }, el('b', { text: '下一步：' }), d.next_action)
      : el('div', { class: 'kg-next dim', text: '（这份载荷没有 next_action 字段）' }));
}

function fragList(...children) {
  return el('div', {}, children);
}

/** 中栏：链。 */
function chainBlock() {
  const d = state.data;
  if (!d) return el('div', { class: 'kg-empty' },
    el('h2', { text: '给一个说法' }),
    el('p', { class: 'dim' },
      '左边点一条，或在上面的框里写一个说法（「楼层错位」「没量成」「洞中洞」），'
      + '再或者带上楼号（「c057 楼层错位」）。'));
  // ★ 顺序即优先级：三态横幅 → **"你点的那条打开了没有"** → 其余的内容。
  //   中间这一条只在**不一致**时出现（`intentBlock` 返回 null 就什么都不画），
  //   所以正常情况下这一行是看不见的 —— 它出现即代表"左边那一条打不开自己"。
  const blocks = [stateBanner(d), intentBlock(d)];
  const label = { title: null, kind: null, symptom: '症状（这说的是什么现象）', cause: '根因',
    fix: '处置', related: '相关的坑与边界', mechanism: '它怎么发生的（机制）',
    guards: '防线（下次怎么不被它骗）', masquerades_as: '它装成什么样子',
    cases: '仓内锚点（可复核的实物）', unverifiable: null,
    content: '知识条目正文（原样 markdown —— 本页不做渲染，所见即 kb/src/*.md 的那一篇）' };
  // ★ **按值的形状画，不按键的名字画**（这一条是被实测逼出来的）：
  //   原先按键分派，`mechanism` 走了"列表"那一支，而陷阱载荷里它是**一段散文**，
  //   于是直接抛 `(items || []).map is not a function`，整页只剩「视图加载失败」。
  //   而那正是 `ask.py` 的**主分支之一**（查任何一条陷阱都会这样）。
  //   键分派还有第二层坏：引擎哪天给某个键换形状（散文 ↔ 列表），页面会**当场全挂**，
  //   而改动本身完全合法。⇒ 分派只认三种形状：串 → 段落；数组 → 列表；对象 → 列表。
  //   这样任何 JSON 值都画得出来，渲染是**全函数**，不会因为形状而崩。
  const PROSE_CLS = { masquerades_as: 'kg-masq' };      // 只有它要那个斜体风格
  for (const key of ORDER) {
    const v = d[key];
    if (v === null || v === undefined || v === '' || (Array.isArray(v) && !v.length)) continue;
    if (key === 'title') {
      blocks.push(el('h2', { class: 'kg-title', text: String(v) },
        d.kind ? el('span', { class: 'sub', text: ` ${d.kind}` }) : null));
    } else if (key === 'kind') {
      continue;
    } else if (key === 'run') {
      blocks.push(runBlock(v));
    } else if (key === 'spread' || key === 'activated' || key === 'satellites') {
      // ★ 扩散激活那一层：**这三支必须排在通用分支前面**。
      //   排在后面的话 `activated`/`satellites` 会被 `Array.isArray(v)` 那一支吃掉、
      //   `spread` 会被对象支吃掉 —— 画出来的东西**看着有内容**，只是跳数/截断/回落
      //   这些"这次这份答案可不可信"的信息全没了，而屏幕上一点异常都看不出来。
      blocks.push(key === 'spread' ? spreadBlock(v)
        : key === 'activated' ? activationBlock(v) : satellitesBlock(v));
    } else if (key === 'content') {
      // 整篇 md：**原样**放 `<pre>`，不做 markdown 渲染 ——
      // 渲染器一旦漏掉一段，屏幕上就少一段而没人知道（本项目最恨的那类安静假话）。
      blocks.push(card(label[key], null, el('pre', { class: 'kg-md', text: v })));
    } else if (Array.isArray(v)) {
      // 字符串数组（`guards`）与对象数组（`symptom`/`cause`/`cases`）都走这一支 ——
      // itemList 认非对象，本来就能画串。
      blocks.push(card(label[key], null, itemList(v)));
    } else if (typeof v === 'string') {
      blocks.push(key === 'unverifiable'
        ? el('p', { class: 'kg-warnline', text: v })
        : card(label[key], null,
          el('p', { class: PROSE_CLS[key] || 'kg-prose', text: v })));
    } else if (typeof v === 'object') {
      blocks.push(card(label[key], null, itemList([v])));
    } else {
      // 数字/布尔：不许不画，也不许假装它是个列表。
      blocks.push(card(label[key], null, el('p', { class: 'kg-prose', text: String(v) })));
    }
  }
  blocks.push(trapBlock(d.traps));
  if (d.state === 'miss') blocks.push(missBlock(d));
  blocks.push(leftoverBlock(d));
  // 尺子：没有它，这个结论分不清是哪把尺子量的（铁律 24）。
  // ★ 三个版本号**分开印、各自带名**：`criterion_version` 只是**打包器**的版本，
  //   真正决定这条结论的是手册与陷阱表；只印一个泛名，读的人会拿它当"语义版本"用
  //   （`trap-same-field-name-different-artifact`：同名不同制品，字段在、量级合理、没人再问）。
  //   "谁是谁"那句话来自产物（`criterion_version_means`），页面不再自己写一份。
  const r = d.ruler || {};
  const v = (k) => (r[k] === undefined || r[k] === null ? '—' : r[k]);
  blocks.push(el('div', { class: 'kg-ruler' },
    el('b', { text: '尺子 ' }),
    code(`kb ${r.kb_self_sha12 ?? '—'} · gate ${r.gate_sha12 ?? '—'}`),
    el('span', { class: 'kg-ver', text: `· 打包器 v${v('criterion_version')}`
      + ` · 手册 v${v('playbook_criterion_version')}`
      + ` · 陷阱 v${v('traps_criterion_version')}` }),
    ' ', el('span', { class: 'dim', text: '（报告任何「这条不对」时请连它一起报）' })));
  return el('div', {}, blocks);
}

// ── 右栏：命中的楼栋·层 ─────────────────────────────────────────────

const INST_STATE = {
  ok: ['ok', '这份逐层清单可用'],
  missing: ['missing', '★源产物不在 ⇒ 下面没有东西，但**不等于没有命中**'],
};

function instancesBlock() {
  const di = state.data && state.data.derived_instances;
  if (!di) {
    return card('命中的楼栋·层', 'kg-empty',
      el('p', { class: 'dim' },
        '这份载荷没有 `derived_instances` —— 要么还没查，要么这个说法没有机器派生的实例。'
        + '（「没有这一栏」与「一栋都没命中」不是一回事。）'));
  }
  const st = INST_STATE[di.state] || ['unknown', `不认识的状态：${di.state}`];
  const byFlag = di.by_flag || {};
  const byCode = di.by_code || {};
  const both = new Set(di.both || []);
  const rows = [...new Set([...Object.keys(byFlag), ...Object.keys(byCode)])].sort();
  return card('命中的楼栋·层（机器派生）', `kg-inst ${st[0]}`,
    el('div', { class: 'kg-note' }, `实例侧状态：${st[1]}`),
    el('div', { class: 'kg-kv' },
      el('b', { text: '合计 ' }), `${di.n_buildings ?? '—'} 栋 · ${di.n_floor_pairs ?? '—'} 个层对`),
    rows.length
      ? el('table', { class: 'kg-inst-table' },
        el('thead', {}, el('tr', {},
          el('th', { scope: 'col', text: '楼' }),
          el('th', { scope: 'col', text: '几何侧报的层（by_flag）' }),
          el('th', { scope: 'col', text: '识别/台账侧（by_code）' }))),
        el('tbody', {}, rows.map((b) => el('tr', { class: both.has(b) ? 'kg-both' : null },
          el('td', {},
            el('a', { class: 'kg-go', href: `#/checks/${encodeURIComponent(b)}`, text: b }),
            both.has(b) ? el('div', {}, pill('两把尺子都命中', 'ok')) : null),
          el('td', { text: floorsText(byFlag[b]) }),
          el('td', { text: floorsText(byCode[b]) })))))
      : el('div', { class: 'kg-warnline', text: '★ 一栋都没有 —— 这与「这一栏没画出来」在屏幕上不该长得一样，所以这里明确说：**是空的**。' }),
    // 一侧为零时**明说这一侧是空的**：整列「—」会被读成"没量到"，而它是"这一侧没登记"。
    !Object.keys(byCode).length
      ? el('div', { class: 'kg-note' },
        'by_code 这一侧**一条都没有** —— 那是「识别/台账侧没有登记本家族」，'
        + '不是「没量过」；两条轴的分工见下面那句。')
      : null,
    di.axis_note ? el('div', { class: 'kg-note', text: di.axis_note }) : null,
    el('div', { class: 'kg-note' },
      '楼号点进去是**检查**那一屏的逐层验收单（那条路今天就能带楼号）。'
      + '「8150 缺陷标注台」目前**没有深链**（它的选楼/选层是页内函数，不吃 hash），'
      + '所以这里不给一个点了却不带楼号的假链接。'),
    (() => {
      const src = Object.keys((di.ruler_of_instances || {}).src_sha || {}).length;
      const h = (di.ruler_of_instances || {}).derive_self_sha12;
      return el('div', { class: 'kg-ruler' }, el('b', { text: '实例尺子 ' }),
        code(`derive ${h ?? '—'} · 源 ${src} 份`),
        el('span', { class: 'dim', text: '（源一改，这份清单就该重出）' }));
    })());
}

function floorsText(map) {
  if (!map) return '—';
  return Object.entries(map).map(([f, n]) => `F${f}×${n}`).join('  ');
}

// ── 左栏：图里有什么 ────────────────────────────────────────────────

/**
 * 一行在**引擎那边的节点 id** —— 必须与 `wordFor` 认的三种前缀逐字一致。
 * 写成一处、两边用同一个函数：前缀拼错的话，`?of=` 就永远对不上，
 * 于是"永远显示不一致"或"永远显示一致"，两种都是安静的假话。
 */
function nodeOf(kind, r) {
  if (kind === 'fam') return `pb:${r.id}`;
  if (kind === 'trap') return `trap:${r.slug}`;
  return r.id;                       // 条目：id 本身
}

/**
 * 这一行拿哪个词去查。
 *
 * ★ 条目这一支**不用 `aka`**：`aka` 的含义是「能点亮这一条的**别名**」，
 *   而手册篇章没有别名 —— 它有 id，而 **id 本身就是个查得动的词**
 *   （实测 `图线-线型-线宽` → `hit_kind=entry`，验收器 ③ 每次都验）。
 *   之前这里给条目喂了 `aka: []`，于是九篇知识全画成"不可点"的灰字，
 *   而命令行明明查得动 —— 页面在**同一件事上说反话**（铁律 25 的形状）。
 */
function wordOfRow(kind, r) {
  if (kind === 'entry') return r.id || null;
  const aka = r.aka || [];
  return aka.length ? aka[0] : null;
}

function railList(kind, rows, badge) {
  return el('ul', { class: `kg-rail-list ${kind}` }, rows.map((r) => {
    const node = nodeOf(kind, r);
    const w = wordOfRow(kind, r);
    const aka = r.aka || [];
    return el('li', { class: w ? null : 'no-aka' },
      el('div', { class: 'kg-rail-head' },
        w
          ? el('a', { class: 'kg-rail-a', href: hrefOf(w, node),
            text: r.title || r.slug || r.id,
            title: `用「${w}」查，想打开 ${node}` })
          : el('span', { class: 'kg-rail-a off', text: r.title || r.slug || r.id,
            title: '这一条没有别名 ⇒ 点不亮，只能靠上面那个框自己写说法' }),
        badge(r)),
      aka.length
        // 每个别名都**带上同一行的 `of=`**：换了词，想打开的仍是这一条。
        ? el('div', { class: 'kg-aka' }, aka.slice(0, 5).map((a) =>
          el('a', { class: 'kg-aka-a', href: hrefOf(a, node), text: a })),
        aka.length > 5 ? el('span', { class: 'dim', text: `＋${aka.length - 5}` }) : null)
        // ★ 没有别名时**不逐行写「（没有别名）」**：九行同义重复会把"哪一条点得亮"
        //   这个真正的信号淹掉。整段说一次就够（见 railBlock 的知识条目那一节）。
        : null);
  }));
}

function railBlock() {
  const inv = state.inv;
  if (state.invErr) {
    const e = state.invErr instanceof ApiError ? state.invErr : new ApiError('unknown', String(state.invErr));
    const down = e.code === 'network' || e.status === 0;
    return el('div', { class: 'kg-panic' },
      el('h2', { class: 'kg-card-h', text: down ? '接口不可用' : `取图谱清单失败：${e.code}` }),
      el('p', { class: 'dim', text: e.message }),
      e.code === 'kg_graph_missing'
        ? el('p', { class: 'dim' },
          '图谱还没打包。先跑 ', code('python -u kb/build_kb.py'), '。')
        : null,
      // 清单取不到**不画空列表**：空列表会被读成「图里什么都没有」。
      el('p', { class: 'kg-warnline' }, '★ 这里不画空列表 —— 空列表会被读成「图里什么都没有」，'
        + '而实际是「这一屏没取到数」。'));
  }
  if (!inv) return el('div', { class: 'kg-empty dim', text: '正在读图谱清单…' });
  const c = inv.counts || {};
  return el('div', {},
    el('div', { class: 'kg-rail-sum' },
      el('b', { text: '图里现在有 ' }),
      `${c.families} 个症状家族 · ${c.traps} 条陷阱（有锚点 ${c.traps_anchored} / 只有人记着 ${c.traps_human_only}）`
      + ` · ${c.entries} 篇知识 · ${c.aliases} 个别名`),
    el('h3', { class: 'kg-rail-h', text: '症状家族' }),
    el('div', { class: 'kg-note' },
      '点一条 = 拿它的第一个别名查一次（别名就是「能点亮这一条」的那些叫法；'
      + '底下的药丸都是可直接点的词）。'),
    railList('fam', inv.families || [], (r) => el('span', { class: 'kg-badges' },
      pill(`别名 ${r.aliases ?? '—'}`, null, `能点亮这一条的叫法：${(r.aka || []).join('、')}`),
      pill(`可跑判据 ${r.runs ?? '—'}`, r.runs ? 'ok' : 'warn'),
      r.declared_no_anchor
        ? pill(`声明无锚点 ${r.declared_no_anchor}`, 'warn')
        : null)),
    el('h3', { class: 'kg-rail-h', text: '陷阱（量具/方法论）' }),
    el('div', { class: 'kg-note' },
      '「有锚点」= 仓内有可复核的实物（判据 / 文件:行）；'
      + '「只有人记着」= 只剩经验，**不许当已核**。两种都在这儿，但形状不同。'),
    railList('trap', inv.traps || [], (r) =>
      pill(r.anchored ? '有锚点' : '只有人记着', r.anchored ? 'ok' : 'warn',
        r.anchored ? '仓内有可复核的实物' : '★只有人记着 —— 不许当已核')),
    el('h3', { class: 'kg-rail-h', text: '知识条目' }),
    el('div', { class: 'kg-note' },
      '手册篇章，不是症状 —— **没有别名**（别名表是「症状的叫法」，收不到手册），'
      + '但 **id 本身就是个查得动的词**，所以点得开；正文在 ', code('kb/src/'), '。'),
    railList('entry', inv.entries || [], () => null),
    el('div', { class: 'kg-ruler' },
      el('b', { text: '清单来源 ' }),
      code(`${(inv.source || {}).file || '—'} ${(inv.source || {}).bytes ?? '—'}B`),
      el('div', { class: 'dim' },
        `${(inv.source || {}).mtime_iso || '—'} · ${(inv.source || {}).generated_by || ''}`),
      // 门禁结论**不在这里重算**，指个路就完（同一个结论两份实现 = 两份会漂的写法）。
      el('div', { class: 'dim' },
        '图谱自己的门禁（C4）在 ', el('a', { class: 'kg-go', href: '#/checks', text: '检查那一屏' }),
        ' 里，本页不重算它。')));
}

// ── 关系图（中栏的第二个视图） ──────────────────────────────────────
//
// ★ **数据在后端、布局在页面** —— 这是这次收编时定的分界，不是随手写的：
//   节点与边来自 `GET /api/kg/activation`（`services/kg.py:graph()`），页面只负责**摆放**。
//   理由：这张图上有一层语义 —— 「哪几个机器节点还没映射到任何症状」**就是图上那几个
//   虚线空心的点**，把它算进页面，就是同一份判断的第二个实现（两份必然漂，而漂的那天
//   两张图各自都像是对的）。⇒ 这里**一次都不读** `data/_meta/kg_instances.json`。
//
// ★ 节点 id 的三种前缀（`fam:` / `trap:` / `ent:`）必须与上面 `wordFor()` 认的逐字一致。
//   拼错的话，图上点一个节点会跳到别的东西上，而**那种错不报错**（后端那侧同一个理由）。
//
// ★ 配色**与 8155 那版不同，这是有意的、也必须说出来**：那份页面是米色纸面
//   （`--paper:#f2efe7`），这一屏是深色工程底（`app.css` 的 `--ink:#0e1116`）。
//   同一组色值搬过来，深灰（图元）与暗金（缺陷码）在深底上几乎看不见 ——
//   而「看不见」与「图上没有这一类」在屏幕上是同一件事。所以按深底重挑了一组，
//   并且把**每一类的含义**写在表里：这张图上颜色是**分类**，不是深浅。
//
//   | 类     | 为什么是这个色 |
//   |--------|----------------|
//   | 症状   | 橙红：图上的入口与锚，最大一号 |
//   | 根因   | 琥珀：与「待拍板」同族 —— 它是这条链的由来 |
//   | 处置   | 绿：与「对账通过」同族 —— 有解法 |
//   | 命令   | 青：与「可信」同族 —— 可复核 |
//   | 陷阱   | 紫：**方法论**坑，与几何根因不是一类（同族不同色） |
//   | 规范   | 青绿：制图约定，手册的第三支 |
//   | 图元   | 灰：被规范描述的那个制图对象 |
//   | 缺陷码 | 暗金：机器**数出来**的（来自实例产物） |
//   | 实测旗 | 铜：机器**逐层量出来**的（与缺陷码同一层，两把尺子） |
const GV = { nodes: [], edges: [], adj: {}, pos: {}, hover: null, sel: null, scale: 1, cx: 0, cy: 0 };
let GVDOM = { wrap: null, cv: null, tip: null, note: null };

const KIND = {
  symptom: { c: '#ff8a5c', r: 24, label: '症状（家族）', always: true },
  cause:   { c: '#e8a33d', r: 7,  label: '根因', always: false },
  fix:     { c: '#46a758', r: 7,  label: '处置', always: false },
  run:     { c: '#35c6d4', r: 7,  label: '可跑命令', always: false },
  trap:    { c: '#a98cf0', r: 14, label: '陷阱（方法论）', always: true },
  entry:   { c: '#5fd0b0', r: 12, label: '规范 / 约定', always: true },
  geom:    { c: '#8b98a3', r: 5,  label: '图元（制图对象）', always: false },
  code:    { c: '#c9a227', r: 10, label: '缺陷码（机器数出来的）', always: false },
  flag:    { c: '#d98a4b', r: 9,  label: '实测旗（逐层量出来的）', always: false },
};
const EDGE_C = { trap: '#a98cf0', cause: '#e8a33d', fix: '#46a758', run: '#35c6d4',
  code: '#c9a227', flag: '#d98a4b', geom: '#5fd0b0', none: '#8b98a3' };
// ★ 后端加了一类而这里没跟上时，**不许**让它静默变成 `undefined.c`（那是 TypeError，
//   整屏白掉），也不许悄悄画成别的颜色 —— 画成红点**并数出来**，屏幕上要能看见它。
const UNKNOWN_KIND = { c: '#e5484d', r: 8, label: '★这一屏不认识的类', always: true };
const kindOf = (k) => KIND[k] || UNKNOWN_KIND;

/**
 * 画布上的短名。★ 与后端 `services/kg._short_title` **同一套规则**
 * （去掉全角括号里的补语、截 14 字），所以对已经短过的 `symptom` 标签再用一次是幂等的；
 * 对根因/处置/规范那些**没短过的**，这一步才是真的在起作用。
 */
function shortTitle(t) { return String(t || '').replace(/（.*?）/g, '').slice(0, 14); }

/**
 * 一个节点**该画什么字**。
 *
 * ★ 这里必须分两类，不能一律用 `label`：`cause` / `fix` / `run` 这三类的 `label`
 *   是**类名**（「根因」「处置」「命令」，后端 `graph()` 里写死的 `cname`），
 *   它们的内容在 `full` 里。一律画 `label` 的话，几十个根因节点会**全部**印着
 *   「根因」两个字 —— 那不是"看不清"，是**把内容换成了类别**，而图上没有任何地方
 *   提示这件事发生过。（其余类别的 `label` 本来就是内容：家族短名 / 陷阱标题 /
 *   条目标题 / 图元 drafting / 缺陷码键。）
 */
function drawLabel(n) {
  const contentInFull = n.kind === 'cause' || n.kind === 'fix' || n.kind === 'run';
  return shortTitle(contentInFull ? (n.full || n.label) : n.label);
}

/** 一条边里谁是父。认不出父的（未映射的码与旗）落到最外圈 —— **缺口必须画出来**。 */
function isParentKind(k) { return k === 'symptom' || k === 'entry'; }

/** 只算摆放。**不读任何文件**（见本节开头那条分界）。 */
function layoutGraph() {
  const act = state.act || {};
  GV.nodes = (act.nodes || []).map((n) => Object.assign({}, n));
  GV.edges = (act.edges || []).map((e) => Object.assign({}, e));
  GV.adj = {};
  for (const n of GV.nodes) GV.adj[n.id] = [];
  for (const e of GV.edges) {
    (GV.adj[e.a] = GV.adj[e.a] || []).push(e.b);
    (GV.adj[e.b] = GV.adj[e.b] || []).push(e.a);
  }
  const byId = {};
  for (const n of GV.nodes) byId[n.id] = n;
  const kids = {}; const isKid = {};
  for (const e of GV.edges) {
    const A = byId[e.a]; const B = byId[e.b];
    if (!A || !B) continue;
    const parent = isParentKind(A.kind) ? A : (isParentKind(B.kind) ? B : null);
    if (!parent) continue;
    const kid = parent === A ? B : A;
    isKid[kid.id] = 1;
    (kids[parent.id] = kids[parent.id] || []).push(kid);
  }
  // 症状排内圈、规范排外圈，各自的子节点贴着父母扇形铺开。
  const fams = GV.nodes.filter((n) => n.kind === 'symptom');
  const ents = GV.nodes.filter((n) => n.kind === 'entry');
  const SPC = 2 * Math.PI / Math.max(fams.length, 1);
  fams.forEach((n, i) => { n.a = -Math.PI / 2 + i * SPC; n.r = 92; });
  ents.forEach((n, i) => {
    n.a = -Math.PI / 2 + 2 * Math.PI * (i + 0.5) / Math.max(ents.length, 1); n.r = 372;
  });
  const RING = { cause: 152, fix: 196, run: 238, code: 186, flag: 170, trap: 300, entry: 372, geom: 418 };
  const R3 = { cause: 1, fix: 1, run: 1, code: 1, flag: 1 };   // 同类里再错开三层，免得叠死
  const place = (parent, spread) => {
    const arr = (kids[parent.id] || []).slice().sort((x, y) =>
      (RING[y.kind] || 0) - (RING[x.kind] || 0) || String(x.id).localeCompare(String(y.id)));
    arr.forEach((n, i) => {
      const frac = arr.length === 1 ? 0.5 : i / (arr.length - 1);
      n.a = parent.a + spread * (frac - 0.5);
      n.r = (RING[n.kind] || 200) + (R3[n.kind] ? (i % 3) * 14 : 0);
    });
  };
  for (const f of fams) place(f, 1.7);      // 这一圈只有症状，扇面角度是它的
  for (const en of ents) place(en, 0.5);    // 图元贴着它所属的那篇规范
  const free = GV.nodes.filter((n) => !isKid[n.id] && !isParentKind(n.kind));
  free.forEach((n, i) => {
    n.r = 478; n.a = -Math.PI / 2 + 2 * Math.PI * (i + 0.5) / Math.max(free.length, 1);
  });
  const maxR = Math.max(520, ...GV.nodes.map((n) => (n.r || 0) + 46));
  const W = (GVDOM.wrap && GVDOM.wrap.clientWidth) || 760;
  const H = (GVDOM.wrap && GVDOM.wrap.clientHeight) || 560;
  GV.scale = Math.min(W, H) * 0.47 / maxR;
  GV.cx = W / 2; GV.cy = H / 2;
  for (const n of GV.nodes) {
    GV.pos[n.id] = { x: GV.cx + n.r * GV.scale * Math.cos(n.a),
      y: GV.cy + n.r * GV.scale * Math.sin(n.a) };
  }
  return {
    nodes: GV.nodes.length, edges: GV.edges.length,
    // 外圈（未映射）由**服务端给的那份清单**数出来，不在这里重新判一遍 —— 判两遍就是
    // 两个分母（服务端 `counts.orphans` 与这里各算一个，屏幕上会同时出现两个数）。
    orphans: ((state.act || {}).counts || {}).orphans,
    unknown: GV.nodes.filter((n) => !KIND[n.kind]).length,
  };
}

function resizeCanvas() {
  const cv = GVDOM.cv; const wrap = GVDOM.wrap;
  if (!cv || !wrap) return;
  const d = window.devicePixelRatio || 1;
  cv.width = Math.max(320, Math.round((wrap.clientWidth || 320) * d));
  cv.height = Math.max(320, Math.round((wrap.clientHeight || 320) * d));
  cv.getContext('2d').setTransform(d, 0, 0, d, 0, 0);
}

/** 画一张。**只画，不解释** —— 数据是接口给的，摆放是上面那个函数定的。 */
function drawGraph() {
  const cv = GVDOM.cv; const wrap = GVDOM.wrap;
  if (!cv || !wrap) return;
  const ctx = cv.getContext('2d');
  const w = wrap.clientWidth || 320;
  const h = wrap.clientHeight || 320;
  ctx.clearRect(0, 0, w, h);
  const sel = GV.sel; const near = new Set();
  if (sel) { near.add(sel); (GV.adj[sel] || []).forEach((x) => near.add(x)); }
  for (const e of GV.edges) {
    const pa = GV.pos[e.a]; const pb = GV.pos[e.b];
    if (!pa || !pb) continue;
    const on = !sel || (near.has(e.a) && near.has(e.b));
    ctx.strokeStyle = on ? (EDGE_C[e.kind] || EDGE_C.none) : 'rgba(255,255,255,.07)';
    ctx.lineWidth = on ? 1.2 : 0.7;
    ctx.beginPath(); ctx.moveTo(pa.x, pa.y); ctx.lineTo(pb.x, pb.y); ctx.stroke();
  }
  for (const n of GV.nodes) {
    const p = GV.pos[n.id]; const K = kindOf(n.kind);
    if (!p) continue;
    const on = !sel || near.has(n.id);
    // ★ 缺口 = 「机器数出来的、但还没映射到任何症状」。它由**服务端**那一份
    //   `unmapped` 决定（后端 graph() 里同一个判断），这里画成**虚线空心**：
    //   一眼能分出「这一片还没接上」，而不是靠数颜色深浅去猜。
    const orphan = (n.kind === 'code' || n.kind === 'flag') && !n.mapped;
    ctx.globalAlpha = on ? 1 : 0.22;
    ctx.beginPath();
    ctx.arc(p.x, p.y, K.r * (n.id === sel ? 1.25 : 1), 0, 2 * Math.PI);
    if (orphan) {
      ctx.fillStyle = '#151a21'; ctx.fill();
      ctx.setLineDash([3, 3]); ctx.strokeStyle = K.c; ctx.lineWidth = 1.6;
      ctx.stroke(); ctx.setLineDash([]);
    } else {
      ctx.fillStyle = K.c; ctx.fill();
      if (n.id === sel) { ctx.strokeStyle = '#e6edf3'; ctx.lineWidth = 2; ctx.stroke(); }
    }
    if (K.always || K.r >= 10 || n.id === sel || n.id === GV.hover) {
      const txt = drawLabel(n);
      ctx.font = (n.kind === 'symptom' ? '600 12px ' : '11px ') + 'system-ui,"Microsoft YaHei",sans-serif';
      ctx.textAlign = 'center'; ctx.lineWidth = 3; ctx.strokeStyle = '#0e1116';
      ctx.strokeText(txt, p.x, p.y + K.r + 12); ctx.fillStyle = '#e6edf3';
      ctx.fillText(txt, p.x, p.y + K.r + 12);
      if (n.n !== undefined && n.n !== null) {
        // `×行数`：机器层节点的**分母**。只有名字没有行数的机器节点，读的人不知道
        // 它是一条还是一千条 —— 而"1 条"和"1000 条"在这张图上不该长得一样。
        ctx.font = '10px ui-monospace,Consolas,monospace';
        ctx.strokeText('×' + n.n, p.x, p.y + K.r + 23);
        ctx.fillStyle = EDGE_C.none;
        ctx.fillText('×' + n.n, p.x, p.y + K.r + 23);
      }
    }
    ctx.globalAlpha = 1;
  }
}

function hitTest(mx, my) {
  let best = null;
  for (const n of GV.nodes) {
    const p = GV.pos[n.id];
    if (!p) continue;
    const d = Math.hypot(mx - p.x, my - p.y);
    const r = kindOf(n.kind).r + 3;
    if (d <= r && (!best || d < best.d)) best = { id: n.id, d, n };
  }
  return best;
}

/** 图例。★ 由 `KIND` 一张表生成 —— 色值**只有这一个出处**（页面里没有第二份色表）。 */
function legendEl() {
  return el('div', { class: 'kg-glegend' },
    Object.keys(KIND).map((k) => el('span', {},
      el('i', { style: { background: KIND[k].c }, 'aria-hidden': 'true' }), KIND[k].label)),
    el('span', {},
      el('i', { class: 'gap', style: { borderColor: KIND.code.c }, 'aria-hidden': 'true' }),
      '★未映射（缺口）'));
}

/** 「图上点一个节点」→ 那个节点在 hash 里的样子。**认不出就回 null，不硬拼。** */
function graphNodeId(n) {
  if (n.kind === 'symptom') return `pb:${n.slug}`;
  if (n.kind === 'trap') return `trap:${n.slug}`;
  if (n.kind === 'entry') return n.slug || null;    // 条目的 id 本身就是查询词
  return null;                                      // 根因/处置/命令/图元/机器码：没有落地页
}

function graphPane() {
  if (state.actErr) {
    const e = state.actErr instanceof ApiError ? state.actErr
      : new ApiError('unknown', String(state.actErr));
    const down = e.code === 'network' || e.status === 0;
    return el('div', { class: 'kg-panic' },
      el('h2', { class: 'kg-card-h', text: down ? '接口不可用' : `取图失败：${e.code}` }),
      el('p', { class: 'dim', text: e.message }),
      // ★ 图取不到**不画一张空图**：空白画布与「图里一个点都没有」在屏幕上是一样的，
      //   而这两件事的补救办法完全不同（修接口 vs 重打包产物）。
      el('p', { class: 'kg-warnline' },
        '★ 这里不画空白画布 —— 一张空图会被读成「图上什么都没有」，'
        + '而实际是「这一屏没取到图」。'));
  }
  if (!state.act) return el('div', { class: 'kg-empty dim', text: '正在读图…' });
  const cv = el('canvas', { class: 'kg-gcv' });
  const tip = el('div', { class: 'kg-gtip' });
  const wrap = el('div', { class: 'kg-graphwrap' }, cv, tip, legendEl());
  GVDOM.wrap = wrap; GVDOM.cv = cv; GVDOM.tip = tip;
  return wrap;
}

function onResize() {
  if (state.view !== 'graph') return;
  resizeCanvas(); drawGraph();
}

/** 挂上之后才能量尺寸 ⇒ 这一步必须在 `mount()` **之后**调。 */
function mountGraph() {
  const cv = GVDOM.cv; const wrap = GVDOM.wrap; const tip = GVDOM.tip;
  if (!cv || !wrap) return;
  const info = layoutGraph();
  resizeCanvas();
  drawGraph();
  if (GVDOM.note) {
    // ★ 三个数必须分开写：节点/边是一回事，**外圈**（缺口）是另一回事，
    //   而 `missing` 又是第三件事 —— 那一份源整个不在时，机器节点**一个都没有**，
    //   这时"外圈 0 个"会被读成"全都映射好了"（铁律 16 的正身）。
    const miss = (state.act && state.act.missing) || {};
    mount(GVDOM.note,
      `节点 ${info.nodes} ｜ 边 ${info.edges} ｜ 外圈 ${info.orphans} 个机器节点还没映射到任何症状（虚线空心）`,
      Object.keys(miss).length
        ? el('div', { class: 'kg-warnline' }, '★ 机器层的源整个没读到：',
          code(Object.entries(miss).map(([k, v]) => `${k}：${v}`).join('；')),
          ' ⇒ 上面那两个机器类**一个点都没有**。这与「机器层本来就是空的」不是一回事。')
        : null,
      info.unknown
        ? el('div', { class: 'kg-warnline' },
          `★ 有 ${info.unknown} 个节点的类这一屏不认识（画成红点）—— 后端加了类而这里没跟上。`)
        : null);
  }
  const at = (ev) => {
    const r = cv.getBoundingClientRect();
    return { x: ev.clientX - r.left, y: ev.clientY - r.top };
  };
  cv.addEventListener('mousemove', (ev) => {
    const p = at(ev); const hit = hitTest(p.x, p.y);
    const id = hit ? hit.id : null;
    if (id !== GV.hover) { GV.hover = id; drawGraph(); }
    if (hit) {
      const n = hit.n;
      tip.style.display = 'block';
      tip.style.left = `${Math.min(p.x + 12, Math.max(0, (wrap.clientWidth || 320) - 340))}px`;
      tip.style.top = `${p.y + 12}px`;
      tip.textContent = (n.full || n.label || '')
        + (n.n === undefined || n.n === null ? '' : `\n行数 ${n.n}`)
        + (n.noimpl ? '\n★这一格没有实现（声明了「无实现」）' : '')
        + (graphNodeId(n) ? '\n点一下用它的别名查这条链' : '\n（这一类没有落地页，点它只高亮）');
    } else tip.style.display = 'none';
  });
  cv.addEventListener('mouseleave', () => {
    GV.hover = null; tip.style.display = 'none'; drawGraph();
  });
  cv.addEventListener('click', (ev) => {
    const p = at(ev); const hit = hitTest(p.x, p.y);
    if (!hit) { GV.sel = null; drawGraph(); return; }
    const n = hit.n;
    GV.sel = GV.sel === n.id ? null : n.id;
    const nid = graphNodeId(n);
    const w = nid ? wordFor(nid) : null;
    if (w) {
      window.location.hash = hrefOf(w, nid);      // 走同一套链接：查词 + 想打开谁
      return;
    }
    drawGraph();
    // ★ 认不出词时**说出来**，不做成"点了没反应"（本页对这种假链接最不容忍）。
    if (GVDOM.note) {
      add(GVDOM.note, el('div', { class: 'kg-warnline' },
        `「${String(n.label || n.id)}」认不出一个查得动的词 ⇒ 这一屏不跳`
        + '（清单没取到，或这一条没有别名）。'));
    }
  });
  if (!resizeWired) { window.addEventListener('resize', onResize); resizeWired = true; }
}

// ── 「跑判据」那一行 ────────────────────────────────────────────────
//
// ★ 能不能点，**只问后端**（`GET /api/capabilities` → 它用**执行时同一个函数**
//   `deps.exec_denied_reason` 回答同一件事）。页面上任何"自己判 location.hostname"
//   的写法都是那件事的第二份实现，两份迟早不一致，而屏幕上会同时出现
//   「能用」与「不能用」两种说法。
// ★ 置灰时把后端那一句**原样显示**：两句理由的补救办法不同（去改本机配置 / 换个地址
//   打开），页面不许把它们揉成一句"当前不可用"。
// ★ 取不到 capabilities ⇒ **先禁用**（不知道就别放行）并说明。
const POLL_MS = 1500;         // 常态轮询间隔
const POLL_MS_SLOW = 5000;    // 连续失败之后放慢（不是停止）
const POLL_SLOW_AFTER = 3;

/** 后端 `run.outcome` 七档 → 屏幕上的一句话。**七档分开写，不许合并。** */
const RUN_HEAD = {
  running: ['', '运行中'],
  ok: ['ok', '跑完了，拿到结论'],
  no_criteria: ['miss', '这个说法没有可跑判据'],
  unparsable: ['warn', '跑完了，但这次的输出读不出来'],
  bad_shape: ['warn', '跑完了，但输出的形状不认识'],
  timeout: ['warn', '到了超时上限，已杀掉'],
  lost: ['miss', '作业记录坏了，这一趟没有结论'],
};

function stopPoll() { if (pollTimer) { clearTimeout(pollTimer); pollTimer = null; } }

function schedulePoll(id) {
  stopPoll();
  const n = (state.run && state.run.polls) || 0;
  const ms = n >= POLL_SLOW_AFTER ? POLL_MS_SLOW : POLL_MS;
  pollTimer = setTimeout(() => { pollTimer = null; pollOnce(id); }, ms);
}

async function pollOnce(id) {
  if (disposed) return;
  const cur = () => state.run && state.run.job && state.run.job.id === id;
  if (!cur()) return;                     // 视图换了 / 又起了别的作业 ⇒ 这一轮作废
  try {
    const rep = await API.kgRunStatus(id);
    if (disposed || !cur()) return;
    state.run.report = rep; state.run.err = null; state.run.polls = 0;
  } catch (e) {
    if (disposed || !cur()) return;
    // ★★ 轮询失败**既不停止轮询、也不把状态清成 idle**：一次网络抖动就让「运行中」
    //   永远为真、按钮永久禁用，正是本仓 `frontend/control.js:359` 那个真 bug 的形状
    //   （`if (!j.success) return;` —— 不重排下一次）。这里两头都写：**报出失败次数并继续排**。
    state.run.err = e;
    state.run.polls = (state.run.polls || 0) + 1;
  }
  repaint();
  const r = state.run && state.run.report;
  if (r && r.state !== 'running') return;   // 终态：停
  if (r && r.run && r.run.outcome && r.run.outcome !== 'running') return;
  if (!r && state.run.polls >= POLL_SLOW_AFTER * 4) {
    // 读不到状态又一直失败 ⇒ 明说"不再自动重试"，而不是安静地永远转下去。
    state.run.gaveUp = true;
    return;
  }
  schedulePoll(id);
}

async function startRun() {
  const q = state.q;
  if (!q) return;
  state.run = { job: null, meta: null, report: null, err: null, polls: 0, starting: true };
  repaint();
  try {
    // ★ 回的是**整个信封** ⇒ 必须取 `.data`。少这一步不报错，只是每个字段恒 undefined。
    const env = await API.kgRun(q, (state.data && state.data.building) || '', topOf());
    if (disposed) return;
    state.run.job = env.data; state.run.meta = env.meta; state.run.starting = false;
  } catch (e) {
    if (disposed) return;
    state.run.starting = false; state.run.err = e; repaint();
    return;
  }
  repaint();
  schedulePoll(state.run.job.id);
}

function topOf() {
  const t = state.meta && state.meta.top;
  return (Number.isFinite(t) && t > 0) ? t : 3;
}

/** 一次 `--run` 的读数。**七档分开画**，`running` 与"跑坏了"绝不同形。 */
function runReportBlock(rep) {
  const r = rep.run || {};
  const head = RUN_HEAD[r.outcome];
  if (!head) {
    // 后端加了档而这里没跟上：**说出来并原样贴**，不塞进任何一档（那会是一句假话）。
    return card('跑判据的结果', 'kg-warn',
      el('div', { class: 'kg-warnline' },
        // ★ `code()` 回的是**元素**，塞进模板串会印成 `[object HTMLElement]`
        //   （这正是本仓「模板串印出 undefined」那一族的正身）⇒ 它只能当小孩，不能当字。
        '★ 后端给了一个这一屏不认识的 outcome：', code(String(r.outcome)),
        ' —— 原样贴出来，不猜。'),
      el('pre', { class: 'kg-json', text: JSON.stringify(r, null, 1) }));
  }
  const rows = Array.isArray(r.results) ? r.results : null;
  return card(`跑判据的结果 —— ${head[1]}`, head[0] ? `kg-run ${head[0]}` : 'kg-run',
    el('div', { class: 'kg-kv' },
      el('b', { text: '作业 ' }), code(rep.id || '—'),
      el('b', { text: ' ｜ 进程 ' }), String(rep.state ?? '—'),
      el('b', { text: ' ｜ 退出码 ' }), rep.exit_code === null || rep.exit_code === undefined
        ? '（还没跑完，不是 0）' : String(rep.exit_code),
      el('b', { text: ' ｜ 用时 ' }), `${rep.elapsed_s ?? '—'}s`,
      el('b', { text: ' ｜ 超时 ' }), r.timeout_s === null || r.timeout_s === undefined
        ? '不判超时' : `${r.timeout_s}s（定它的是 ${r.timeout_source}）`),
    // 后端那句话**原样**：每一档的话在服务端 import 时就核对过一一对应，页面不重写一份。
    el('div', { class: 'kg-note', text: r.why || '（后端没给 why —— 这本身不正常）' }),
    r.log_truncated_bytes
      ? el('div', { class: 'kg-warnline' },
        `★ 日志开头被截掉了 ${r.log_truncated_bytes} 字节 —— 下面是**尾巴**，不是全部输出。`)
      : null,
    r.ledger ? el('div', { class: 'kg-kv' }, el('b', { text: '留痕 ' }), code(String(r.ledger))) : null,
    rows && rows.length
      ? el('ul', { class: 'kg-items' }, rows.map((x) => el('li', {},
        el('div', { class: 'kg-cmd-line' }, code(x.cmd || '(没有 cmd)')),
        el('div', { class: 'kg-kv' },
          el('b', { text: '退出码 ' }), String(x.exit ?? '—'),
          el('b', { text: ' ｜ ' }), `${x.seconds ?? '—'}s`,
          el('b', { text: ' ｜ 声明写：' }), x.writes || '（没写！）'),
        x.expect ? el('div', { class: 'kg-kv' }, el('b', { text: '预期 ' }), String(x.expect)) : null,
        x.tail ? el('pre', { class: 'kg-json', text: String(x.tail) }) : null)))
      : null,
    // ★ 原始输出**一直带**（不是只在出错时带）：`ok` 的时候它也是唯一的凭据 ——
    //   退出码与 expect 的比对**留给人**，页面不替谁宣布合格。
    el('details', { class: 'kg-leftover' },
      el('summary', { text: `原始输出（最后 ${r.raw_lines ?? 0} 行里的末尾若干行）` }),
      el('pre', { class: 'kg-json', text: r.raw_tail || '（没有输出）' })));
}

function runBar() {
  const caps = state.caps;
  const capsErr = state.capsErr;
  const q = state.q;
  const R = state.run;
  const live = !!(R && R.job && !(R.report && R.report.state !== 'running'));
  const enabled = !!(caps && caps.write_enabled) && !!q && !live;
  const why = capsErr
    ? `取不到 capabilities：${capsErr.message || capsErr} —— 按钮先禁用（不知道就别放行）。`
    : !caps ? '正在问后端能不能执行…'
      : !caps.write_enabled ? `★ 后端说不能执行：${caps.write_disabled_reason || caps.write_disabled_code}`
        : !q ? '先给一个说法，再跑它登记的判据。'
          : null;
  const btn = el('button', {
    class: 'kg-btn', type: 'button', text: live ? '正在跑…' : '跑判据（--run）',
    disabled: !enabled, title: why || '真起一个作业跑这个说法登记的判据；最坏 900 秒。',
    onclick: () => { if (enabled || (R && R.gaveUp)) startRun(); },
  });
  return el('div', { class: 'kg-runbar' },
    btn,
    R && R.gaveUp
      ? el('button', { class: 'kg-btn ghost', type: 'button', text: '重新问一次',
        onclick: () => { state.run = null; repaint(); } })
      : null,
    el('span', { class: 'kg-note' },
      why
        // ★ 可执行时也要**把代价与出处写在按钮旁边**：这一条不是只读的，
        //   而且它只在本机可用 —— 局域网打开这一页的人应当一眼看到这件事。
        || `可执行（本机）。它会真起一个作业跑登记的那条命令，最坏 900 秒，`
           + `并落盘：_qa/<楼>_qa.txt 与 data/_meta/kg_runs.json。`
           + `${caps.admin_token_configured ? '（本机配了 token，非本机带对头也能执行）' : ''}`),
    R && R.err
      ? el('span', { class: 'kg-warnline' },
        `★ 轮询失败 ${R.polls} 次：${R.err.message || R.err}`
        + `${R.gaveUp ? ' —— 已停止自动重试，按上面那个按钮重来。' : ' —— 仍在重试。'}`)
      : null,
    R && R.job
      ? el('span', { class: 'kg-kv' },
        ' ｜ 作业 ', code(R.job.id),
        R.job.pid === null || R.job.pid === undefined ? '（还没起进程）' : `（pid ${R.job.pid}）`)
      : null,
    R && R.starting ? el('span', { class: 'kg-note', text: '正在起作业…' }) : null,
    R && R.report ? runReportBlock(R.report) : null);
}

// ── 视图入口 ────────────────────────────────────────────────────────

function searchBox(current) {
  const input = el('input', { class: 'kg-input', type: 'search', value: current || '',
    placeholder: '一个说法，可带楼号：c057 楼层错位', 'aria-label': '查询说法' });
  const go = () => {
    const v = input.value.trim();
    window.location.hash = v ? `#/kg/${encodeURIComponent(v)}` : '#/kg';
  };
  input.addEventListener('keydown', (ev) => { if (ev.key === 'Enter') go(); });
  return el('form', { class: 'kg-search', onsubmit: (ev) => { ev.preventDefault(); go(); } },
    input,
    el('button', { class: 'kg-btn', type: 'submit', text: '查' }),
    el('button', { class: 'kg-btn ghost', type: 'button', text: '清空',
      onclick: () => { window.location.hash = '#/kg'; } }));
}

async function loadInventory(force) {
  if (state.inv && !force) return;
  try {
    const env = await API.kg();
    state.inv = env.data; state.invMeta = env.meta; state.invErr = null;
  } catch (e) {
    state.inv = null; state.invErr = e;
  }
}

async function loadAsk(q) {
  state.data = null; state.meta = null; state.askErr = null;
  if (!q) return;
  try {
    const env = await API.kgAsk(q);
    state.data = env.data; state.meta = env.meta;
  } catch (e) {
    state.askErr = e;
  }
}

async function loadActivation(force) {
  if (state.act && !force) return;
  try {
    const env = await API.kgActivation();
    state.act = env.data; state.actMeta = env.meta; state.actErr = null;
  } catch (e) {
    // ★ 取不到就把图**清掉并留下错误**，不留一份半旧的数据 ——
    //   旧图配上新错误，屏幕上会同时出现"图在此"与"取图失败"两句话。
    state.act = null; state.actErr = e;
  }
}

/** 能不能执行：**只问后端**。失败 ⇒ caps 保持 null，按钮按"不知道"处置（不放行）。 */
async function loadCaps() {
  try {
    state.caps = await API.capabilities(); state.capsErr = null;
  } catch (e) {
    state.caps = null; state.capsErr = e;
  }
}

const GRAPH_LABEL = { chain: '链条', graph: '关系图' };

function viewBar() {
  const note = el('span', { class: 'kg-vnote' });
  GVDOM.note = note;
  return el('div', { class: 'kg-toolbar' },
    Object.keys(GRAPH_LABEL).map((v) => el('button', {
      class: `kg-btn ghost kg-vbtn${state.view === v ? ' on' : ''}`,
      type: 'button', text: GRAPH_LABEL[v],
      title: v === 'chain' ? '这条说法的来龙去脉（引擎给的顺序）' : '谁连着谁（节点与边）',
      onclick: () => setView(v),
    })),
    note);
}

/** 换视图。★ 切到图上时要**现取**激活数据（它是另一条路由），取完再重画。 */
async function setView(v) {
  if (v === state.view) return;
  state.view = v;
  if (v === 'graph' && !state.act && !state.actErr) {
    repaint();                       // 先把「正在读图…」画出来，别让点击像没反应
    await loadActivation(false);
    if (disposed) return;
  }
  repaint();
}

function repaint() { if (state.root) paint(state.root, state.sub); }

function askErrorBlock() {
  const e = state.askErr;
  if (!e) return null;
  const a = e instanceof ApiError ? e : new ApiError('unknown', String(e));
  const down = a.code === 'network' || a.status === 0;
  return el('div', { class: 'kg-panic' },
    el('h2', { class: 'kg-card-h', text: down ? '接口不可用' : `查询失败：${a.code}` }),
    el('p', { class: 'dim', text: a.message }),
    // ★ 查询失败**不许**画成 miss 那一栏：前者是"没查成"，后者是"图里没有"。
    el('p', { class: 'kg-warnline' },
      '★ 这一屏现在是「没查成」，**不是「图里没有」**。两者在屏幕上不该长得一样。'),
    a.detail ? el('details', { class: 'kg-leftover' },
      el('summary', { text: '后端给的细节（原样）' }),
      el('pre', { class: 'kg-json', text: JSON.stringify(a.detail, null, 2) })) : null);
}

function paint(root, sub) {
  // ★ 每次重画都把 canvas 那一族的引用清干净：`mount()` 会先 `clear()` 掉旧 DOM，
  //   留着旧引用的话下一屏会把像素画到一个**已经不在文档里**的画布上 ——
  //   什么也看不见，且不报错（本仓对"安静的失效"最不容忍）。
  GVDOM = { wrap: null, cv: null, tip: null, note: null };
  const graph = state.view === 'graph';
  const mid = el('div', { class: 'kg-mid' }, searchBox(sub), viewBar(),
    // 图上不画三态横幅/链条（那是"这个说法"的解读），画的是**整张图**；
    // 而查询失败那条**两种视图下都要出**（图取到了不等于这个词查到了）。
    graph ? (askErrorBlock() || graphPane()) : (askErrorBlock() || chainBlock()));
  const right = el('div', { class: 'kg-right' },
    state.data ? instancesBlock() : el('div', { class: 'kg-empty dim', text: '右边这一栏要有一个说法才算得出来。' }),
    runBar());
  mount(root, el('div', { class: 'kg-wrap' },
    el('div', { class: 'kg-rail' }, railBlock()),
    mid, right));
  // ★ **量尺寸必须在 mount 之后**（`clientWidth` 在文档外恒 0 ⇒ 整张图缩成一个点）。
  if (graph) mountGraph();
  // 带上耗时/退出码：这张屏上的结论是**一次子进程**产出的，代价要看得见。
  if (state.meta && !graph) {
    add(mid, el('div', { class: 'kg-transport dim' },
      `本次查询：退出码 ${state.meta.exit} · ${state.meta.elapsed_ms} ms`
      + ` · top ${state.meta.top}`
      + (state.meta.top_clamped_from !== null && state.meta.top_clamped_from !== undefined
        ? `（原写 ${state.meta.top_clamped_from}，已夹到上限 ${state.meta.top}）` : ''),
      state.meta.stderr_head ? el('div', {}, '子进程 stderr：', code(state.meta.stderr_head)) : null,
      el('div', {}, '复现：', code((state.meta.argv || []).join(' ')),
        '（这是**列表拼给人看的**，不是 shell 串）')));
  }
}

/**
 * `#/kg/<词>?of=<节点 id>` → `{q, of}`。
 *
 * ★ `of` 是**点的人想打开谁**，`q` 是**拿去查的词**。两者常态相同（词就是那条的别名），
 *   但引擎的排序可能让主命中落到别处 —— 那时页面要说得出来（见 `intentBlock`）。
 *   只有**点链接**才带 `of`：在框里手打一个词是没有"想打开谁"的，
 *   这种情况必须**不说**（宁可不提，也不许拿一个猜出来的目标去指控引擎排错）。
 */
function parseSub(sub) {
  const raw = (sub || '').trim();
  const at = raw.indexOf('?of=');
  if (at < 0) return { q: raw, of: null };
  return { q: raw.slice(0, at).trim(), of: raw.slice(at + 4).trim() || null };
}

/**
 * @param {HTMLElement} root app.js 给的 #main
 * @param {string} sub hash 里 `#/kg/` 后面那段（可能空、可能含空格与楼号，可能带 `?of=`）
 */
export async function render(root, sub) {
  disposed = false;
  const { q, of } = parseSub(sub);
  state.of = of;              // ★ 必须在 paint 之前设好：intentBlock 在 paint 里读它
  state.q = q;                // 「跑判据」那个按钮跑的就是它（`runBar` 读 state.q）
  // ★ 换一屏就把上一屏的作业读数丢掉：留着的话，轮询里那句 `cur()` 会认为
  //   "还是同一个作业"而继续排下去，于是**在另一个词的地盘上**弹出一条旧结论。
  state.run = null;
  // ★ `state.sub` 存的是**词**（`q`），不是 hash 里那段原文 —— 原文里可能带 `?of=`，
  //   把它塞进搜索框，框里会显示「c057 楼层错位?of=pb:xxx」这种东西。
  state.root = root; state.sub = q;     // 换视图/轮询回来时靠它俩重画整屏
  mount(root, el('div', { class: 'kg-empty dim', text: '正在读图谱…' }));
  // 四份**分开取**：清单取不到不该挡住查询，查询挂了也不该让左栏空掉，
  // 而"能不能执行"是**另一个问题**（后端答的），它慢/挂都不该拖住这一屏。
  await Promise.all([loadInventory(false), loadAsk(q), loadCaps()]);
  if (disposed) return;
  paint(root, q);
}
