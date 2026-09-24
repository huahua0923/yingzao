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
//   4. **本页不执行任何命令**：`run[]` 里给的是命令与其预期，跑不跑由人/智能体
//      去命令行决定。所以这里只画、只给复制按钮，连"运行"按钮都不放。
import { el, add, mount } from '../dom.js';
import { API, ApiError } from '../api.js';

export const label = '图谱';

const state = { inv: null, invMeta: null, invErr: null, data: null, meta: null, askErr: null,
  of: null };   // 点链接的人想打开的节点 id（手打的查询没有这个，见 parseSub）

let disposed = false;
export function dispose() { disposed = true; }

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
  'content'];

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

/** 「跑一条命令」的块。★ 会写盘的要先说出来 —— 白名单里只收只读命令。 */
function runBlock(runs) {
  return card('可跑判据（本页不执行，只给命令）', 'kg-run', el('div', { class: 'kg-note' },
    '这些命令请到命令行跑。`--run` 那条路是**写**操作（跑判据要落 `data/_meta/kg_runs.json`），'
    + '所以 HTTP 那两条路由刻意不开口子。'), (runs || []).map((r) => {
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
  const r = d.ruler || {};
  blocks.push(el('div', { class: 'kg-ruler' },
    el('b', { text: '尺子 ' }),
    code(`kb ${r.kb_self_sha12 ?? '—'} · gate ${r.gate_sha12 ?? '—'} · criterion v${r.criterion_version ?? '—'}`),
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
  const mid = el('div', { class: 'kg-mid' }, searchBox(sub), askErrorBlock() || chainBlock());
  const right = el('div', { class: 'kg-right' },
    state.data ? instancesBlock() : el('div', { class: 'kg-empty dim', text: '右边这一栏要有一个说法才算得出来。' }));
  mount(root, el('div', { class: 'kg-wrap' },
    el('div', { class: 'kg-rail' }, railBlock()),
    mid, right));
  // 带上耗时/退出码：这张屏上的结论是**一次子进程**产出的，代价要看得见。
  if (state.meta) {
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
  mount(root, el('div', { class: 'kg-empty dim', text: '正在读图谱…' }));
  // 两份**分开取**：清单取不到不该挡住查询，查询挂了也不该让左栏空掉。
  await Promise.all([loadInventory(false), loadAsk(q)]);
  if (disposed) return;
  paint(root, q);
}
