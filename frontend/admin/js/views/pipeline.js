// 「流程总表」视图 —— 用户那句「把做三维模型的流程都梳理一下」的落点。
//
// 路由：`#/pipeline`，`#/pipeline/<阶段id>` 会把那一条标出来并滚过去（可分享）。
//
// ★★ 这一屏**只读**，一个执行按钮都不放。跑阶段是「控制台」那一屏的活
//   （它管着 `require_compute` 那条执行面）。在这里再放一个「跑」就是**第二处执行面**
//   —— 本仓记过这个形状（memory: executor-must-run-the-gate-itself）：同一个动作
//   有两个入口时，闸往往只挂在其中一个上，另一个是 fail-open。
//
// ★★ 唯一真源是仓里的 `config/pipeline.json`（`_说明` 那句原话：「改这个文件就是
//   改流程；不用动 console_meta.py 的代码」）。这一屏**一个判据都不算** ——
//   阶段表、可跑名单、危险标记、上游键全是随 `GET /api/console/meta` 下发的。
//   在前端照抄一遍判据 = 第二份实现 ⇒ 同一件事两屏会说两句不同的话
//   （memory: one-judgement-many-implementations）。
//   ⚠ 顺带一条实测：`backend/web/console_meta.py` 的 `PIPELINE_FALLBACK` 是
//   **回落**不是真源，两者曾各自漂移（铁律 006 的面）。所以本页只印接口给的，
//   不去读那个 .py。
//
// ★ 三条「不许把没量到说成没有」的规矩，写在这里一次：
//   1. `upstream: null`（是**登记过的取值**，见 `UPSTREAM_KEYS`，意思是"不以上游产物
//      为过期判据"）与「这个字段压根没登记」**不是一句话** ⇒ 用 `has(s,'upstream')`
//      分开判，不许写成 `s.upstream || '无'` —— 那个写法把两者并成一个字。
//      本仓前科：`if x and x != Y` 让空值跳过整段核对（铁律 144 / 171）。
//   2. `produces: []`（这个阶段没有独立产物）与字段缺失（没登记）同理分开。
//   3. `_source` 两态必须分开显示（`live` / `frozen`），且措辞与「控制台」那屏的
//      `paintMetaLine()` **逐字一致** —— 同一个后端状态两屏说两种话，读的人
//      只能自己猜哪个是真的。`frozen` 是**回退**不是常态，只写"阶段表已载入"
//      等于把一次静默回退藏起来。
//
// ★ 危险阶段**由数据挑**（`danger === 'high'`），不在这里写死 id。
//   写死的话，流程表以后加一条危险阶段时这一屏会**照样绿**（铁律 174：手打的计数
//   在清单长到 N+1 那一刻才第一次出声，而那一刻它长得像"被测对象坏了"）。
//
// ★ 两处"我另算一遍同一个量"的自查（铁律 182：每条判据旁边要有一条独立算同一个量的
//   路）。两处**不一致就印出来**，不静默取其中一个：
//     · `meta.stages`（路由现造的计数） vs `data.pipeline.length`
//     · `data.runnable`（给定的名单）  vs 从 `pipeline` 现滤出来的 runnable
import { el, add, mount, rich } from '../dom.js';
import { API } from '../api.js';

export const label = '流程总表';

// 段名用短前缀 `pl-`（pipeline），与 app.css 的通用类不撞。
const DANGER_HIGH = 'high';

/** 「这个键在这条记录里有没有」。
 *  ★ 不能用 `s.upstream || …` 判 —— 那会把 `null`（登记过的取值）和"没这个键"
 *    并成同一个字。`in` 才分得开（铁律 171：`'k' in obj` 与 `!== undefined` 不是一回事）。 */
function has(obj, key) {
  return Object.prototype.hasOwnProperty.call(obj, key);
}

/** 阶段表里的 `scope` 三档 → 中文。取值集合实测是 `['all','single','source']`。 */
const SCOPE_CN = { single: '单栋', all: '全仓', source: '图纸源目录' };

function scopeText(s) {
  const v = s.scope;
  if (!has(s, 'scope')) return '（没登记 scope）';
  if (SCOPE_CN[v]) return SCOPE_CN[v];
  // 四档之外**原样印出来**，不落回"单栋" —— 落回就等于把一条新取值说成了旧取值。
  return `（未知 scope：${JSON.stringify(v)}）`;
}

/** 一枚小徽章。`tone` 决定配色，`title` 走 `plain()`（`el` 的 title 分支统一降级标记）。 */
function badge(text, tone, title) {
  return el('span', { class: `pl-badge ${tone || ''}`.trim(), text, title: title || null });
}

/**
 * 一条阶段上的徽章。**顺序有意义**：危险排最前 —— 一条阶段最多两三个徽章，
 * 扫一眼时先撞上的应该是"这一条会毁东西"。
 */
function badgesOf(s) {
  const out = [];
  if (s.danger === DANGER_HIGH) {
    out.push(badge('危险', 'is-danger', 'danger=high：这一步会改写已有产物'));
  } else if (has(s, 'danger')) {
    // 非 high 且有这个键 —— 原样说明是几档，不吞掉。
    out.push(badge(`danger=${JSON.stringify(s.danger)}`, 'is-warn'));
  }
  if (s.writes === true) out.push(badge('写盘', 'is-warn', '这一步会改盘上的数据'));
  else if (s.writes === false) out.push(badge('只读', 'is-ok', '这一步只读、不写数据'));
  else out.push(badge('写不写：没登记', 'is-warn'));

  if (s.runnable === true) out.push(badge('可一键跑', 'is-ok'));
  else if (s.runnable === false) out.push(badge('不可一键跑', 'is-no', '只能在命令行跑 —— 原因见下面那段'));
  else out.push(badge('能不能跑：没登记', 'is-warn'));

  if (s.inplace === true) {
    out.push(badge('就地改写', 'is-warn',
      '改的就是 floors/floorN.json（recognize 早就写过那个文件）⇒ 拿它的存在当'
      + '「这一步做过了」是假信号'));
  }
  if (s.slow === true) out.push(badge('慢', 'is-dim'));
  out.push(badge(scopeText(s), 'is-dim'));
  return out;
}

/** 一个「键 → 值」的小格。`val` 已是节点或字符串。 */
function pair(k, val) {
  return el('div', { class: 'pl-pair' },
    el('span', { class: 'pl-k', text: k }),
    el('span', { class: 'pl-v' }, val));
}

/** `script` + `args`。`--apply` 单独标色：它是"真写"的开关（去掉就是干跑）。 */
function scriptLine(s) {
  const parts = [];
  if (has(s, 'script')) {
    parts.push(el('code', { class: 'pl-scriptname', text: String(s.script) }));
  } else {
    parts.push(el('span', { class: 'pl-miss', text: '（没登记 script）' }));
  }
  const args = has(s, 'args') ? s.args : null;
  if (Array.isArray(args)) {
    for (const a of args) {
      const isApply = a === '--apply';
      parts.push(el('code', {
        class: 'pl-arg' + (isApply ? ' is-apply' : ''),
        text: String(a),
        title: isApply ? '带着它 = 真写盘；去掉它就是只报不写的干跑' : null,
      }));
    }
  } else if (has(s, 'args')) {
    parts.push(el('span', { class: 'pl-miss', text: `（args 不是数组：${JSON.stringify(args)}）` }));
  } else {
    // ★ 与"空数组"分开：没这个键 = 这个阶段不收名字参数（多为全仓阶段）。
    parts.push(el('span', { class: 'pl-note', text: '（不收参数 —— 它是全仓阶段）' }));
  }
  return el('div', { class: 'pl-cmd' }, parts);
}

/** `produces`。三种结局三句话：给了 / 空 / 没登记。 */
function producesOf(s) {
  if (!has(s, 'produces')) return el('span', { class: 'pl-miss', text: '（没登记 produces）' });
  const v = s.produces;
  if (Array.isArray(v) && v.length === 0) {
    return el('span', { class: 'pl-note', text: '（无独立产物 —— 就地改写或只出报告）' });
  }
  if (Array.isArray(v)) {
    return el('span', {}, v.map((p, i) => [
      i ? el('span', { class: 'pl-sep', text: '、' }) : null,
      el('code', { class: 'pl-path', text: String(p) }),
    ]));
  }
  return el('span', { class: 'pl-miss', text: `（produces 不是数组：${JSON.stringify(v)}）` });
}

/** `upstream`。★ `null` 是**登记过的取值**（`UPSTREAM_KEYS` 里有它），与"没登记"分开。 */
function upstreamOf(s) {
  if (!has(s, 'upstream')) return el('span', { class: 'pl-miss', text: '（没登记 upstream）' });
  const v = s.upstream;
  if (v === null) {
    return el('span', { class: 'pl-note',
      text: '无上游 —— 不拿任何已有产物的 mtime 当过期的判据' });
  }
  return el('span', {}, [
    el('code', { class: 'pl-path', text: String(v) }),
    el('span', { class: 'pl-note', text: '（产物比它旧 = 过期）' }),
  ]);
}

/** 一条阶段。 */
function stageNode(s) {
  const danger = s.danger === DANGER_HIGH;
  const why = has(s, 'why_manual') ? s.why_manual : null;
  const hasWhy = typeof why === 'string' && why.trim() !== '';

  return el('li', {
    class: 'pl-stage' + (danger ? ' is-danger' : '') + (s.inplace ? ' is-inplace' : ''),
    dataset: { id: String(s.id ?? ''), danger: danger ? DANGER_HIGH : '' },
  },
    el('div', { class: 'pl-no', text: has(s, 'no') ? String(s.no) : '?' }),
    el('div', { class: 'pl-main' },
      el('div', { class: 'pl-title' },
        el('span', { class: 'pl-label', text: has(s, 'label') ? String(s.label) : '（没登记 label）' }),
        el('span', { class: 'pl-id', text: String(s.id ?? '') }),
        el('span', { class: 'pl-badges' }, badgesOf(s))),
      scriptLine(s),
      has(s, 'desc') ? el('p', { class: 'pl-desc' }, rich(String(s.desc))) : null,
      el('div', { class: 'pl-facts' },
        pair('产物', producesOf(s)),
        pair('上游', upstreamOf(s))),
      // ★ `why_manual` 原样展示，一个字不改、一段不删 —— 这一段**就是**「为什么必须人工」。
      //   走 `rich()` 而不是 `text`：后台那些串里写着 `**不在 git**` 这种强调，
      //   走 text 会把星号当正文印出来（dom.js 的 plain() 注释里记了这个前科）。
      hasWhy ? el('div', { class: 'pl-why' },
        el('span', { class: 'pl-why-h', text: '为什么必须人工' }),
        el('p', {}, rich(why))) : null));
}

/** 顶部那行「这份阶段表是哪来的」。★ 措辞与 console.js 的 `paintMetaLine()` 一致。 */
function sourceBox(meta, pipelineLen) {
  const src = meta && meta.source;
  const live = src === 'live';
  const box = el('div', { class: 'pl-src ' + (live ? 'is-ok' : 'is-warn') });
  add(box,
    el('span', { class: 'pl-src-h', text: live
      ? '阶段表：本机实时求值（console_meta 现读）'
      : `阶段表：${src === 'frozen' ? '冻结产物（实时求值失败的回退）' : `来源不明（${JSON.stringify(src)}）`}` }),
    el('span', { class: 'pl-src-n', text: `　${meta?.stages ?? '?'} 个阶段，本机可跑 `
      + `${Array.isArray(meta?.runnable) ? meta.runnable.length : '?'} 个` }));
  if (!live) {
    add(box, el('span', { class: 'pl-src-w', text: '　★ 回退不是常态：请查本机 `console_meta` 是否报错' }));
    const fz = meta && meta.frozen;
    if (fz && typeof fz === 'object') {
      add(box, el('div', { class: 'pl-src-prov' },
        el('code', { text: `generatedAt=${String(fz.generatedAt)}` }),
        el('code', { text: `source=${String(fz.source)}` }),
        el('code', { text: `sha256=${String(fz.sourceSha256).slice(0, 12)}…` })));
    }
  }
  return box;
}

/** 一行汇总数。★ 每个数都写清它是**从哪来的** —— 见下面 countRow 的注释。 */
function countRow(stages, meta) {
  const danger = stages.filter((s) => s.danger === DANGER_HIGH);
  const inplace = stages.filter((s) => s.inplace === true);
  // 自己再滤一遍 runnable（与后端给的 `data.runnable` 是两条独立的算路）。
  const runSelf = stages.filter((s) => s.runnable === true).map((s) => String(s.id));
  const given = Array.isArray(meta?.runnable) ? meta.runnable.map(String) : null;
  const agree = given && given.length === runSelf.length
    && [...given].sort().join('\u0000') === [...runSelf].sort().join('\u0000');

  const cell = (n, label, title, tone) => el('div', {
    class: 'pl-count ' + (tone || ''), title: title || null },
    el('b', { text: String(n) }), el('span', { text: label }));

  // 三种结局三句话，**不共用一行字**（本仓铁律：`不适用` 与 `量了、没有` 必须分开）：
  //   后端没给名单 / 两种算法一致 / 两种算法不一致。
  const agreeText = given === null
    ? '（后端没给 data.runnable，无法交叉核对）'
    : (agree ? '两种算法一致 ✓' : '★ 两种算法不一致 —— 见下');

  return el('div', { class: 'pl-counts' },
    cell(stages.length, '个阶段（本表行数）', 'count(data.pipeline)', ''),
    cell(meta?.stages ?? '?', '个阶段（路由现造 meta.stages）',
      'meta.stages —— 与左边那个数**独立**算出来的同一个量', ''),
    cell(runSelf.length, '个可一键跑',
      '从 pipeline 逐条现滤 runnable=true；后端另外给了一份 data.runnable', ''),
    cell(danger.length, '个标了危险',
      'danger=high：' + (danger.map((s) => s.id).join('、') || '（无）'), 'is-danger'),
    cell(inplace.length, '个就地改写',
      'inplace=true：' + (inplace.map((s) => s.id).join('、') || '（无）'), 'is-warn'),
    el('div', { class: 'pl-count is-note' }, el('span', { text: agreeText })));
}

// ★ `disposed` 的作用：`render` 里那次 await 回来时，路由可能已经切走了 ——
//   那时再往 root 里写，写的是一个已经不在文档里的节点（屏幕上"什么都没发生"，
//   而实际发生了一次无用渲染）。所以每个 await 之后都要看一眼这个标志。
const state = { disposed: false };

export function dispose() {
  state.disposed = true;
}

export async function render(root, sub = '') {
  state.disposed = false;
  mount(root, el('div', { class: 'loading', text: '正在读阶段表…' }));

  let env;
  try {
    env = await API.consoleMeta();
  } catch (e) {
    if (state.disposed) return;
    // ★ 取不到就**明说取不到**，不画一张空表 —— 空表会被读成"流程表是空的"
    //   （铁律 062：分母为 0 的 k/N 是最像结论的假数）。
    mount(root, el('div', { class: 'pl-wrap' },
      el('h1', { text: '流程总表' }),
      el('div', { class: 'pl-err' },
        el('p', { text: `阶段表取不到：${e && e.message ? e.message : String(e)}` }),
        el('p', { class: 'pl-note', text: e && e.status === 403
          ? '这条接口要「搭建方」能力（后端 BUILDER_ONLY）。当前身份看不到它 —— '
            + '这不是「流程表不存在」。'
          : '这一段不在本页重算：它是 meta_source 从 console_meta 求值或读冻结产物。' }),
        el('p', { class: 'pl-note', text: '本页只读，不会因为取不到而改变任何东西。' }))));
    return;
  }
  if (state.disposed) return;

  const data = env.data || {};
  const meta = env.meta || {};
  const stages = Array.isArray(data.pipeline) ? data.pipeline : null;

  if (!stages) {
    mount(root, el('div', { class: 'pl-wrap' },
      el('h1', { text: '流程总表' }),
      el('div', { class: 'pl-err' },
        el('p', { text: `接口回来了，但 data.pipeline 不是数组：${JSON.stringify(data.pipeline)}` }),
        el('p', { class: 'pl-note', text: '这是「这一份载荷没带阶段表」，不是「流程表是空的」。' }))));
    return;
  }

  const danger = stages.filter((s) => s.danger === DANGER_HIGH);
  const runSelf = stages.filter((s) => s.runnable === true).map((s) => String(s.id));
  const given = Array.isArray(meta.runnable) ? meta.runnable.map(String) : null;
  const mismatch = given && (given.length !== runSelf.length
    || [...given].sort().join('\u0000') !== [...runSelf].sort().join('\u0000'));

  const wrap = el('div', { class: 'pl-wrap' });

  add(wrap,
    el('header', { class: 'pl-head' },
      el('h1', {}, '流程总表', el('span', { class: 'pl-h1n', text: `${stages.length} 个阶段` })),
      el('p', { class: 'pl-lede', text:
        '做三维模型的完整链路。唯一真源是仓里的 config/pipeline.json —— 改那个文件就是改流程，'
        + '不用动任何 .py。本页只读：跑阶段在「控制台」那一屏。' })),

    sourceBox(meta, stages.length),
    countRow(stages, meta),

    // ★ 两个数的交叉核对结果**印在屏幕上**，不静默取一个（铁律 182）。
    (meta.stages !== undefined && meta.stages !== stages.length)
      ? el('div', { class: 'pl-warnbar', text:
          `★ meta.stages=${meta.stages} 而 data.pipeline 有 ${stages.length} 条 —— `
          + '路由现造的计数与本表行数不一致。这两个数各自都对得上出处，先查是不是'
          + '有一层把某一条滤掉了（铁律 060/169：不一致时第一个嫌疑人是量具）。' })
      : null,
    mismatch
      ? el('div', { class: 'pl-warnbar', text:
          `★ 可跑名单两种算法不一致：后端给的 data.runnable = [${(given || []).join(', ')}]；`
          + `从 pipeline 现滤 runnable=true 得 [${runSelf.join(', ')}]。` })
      : null,

    // 危险阶段单列一段：它们散在 15 条里，靠滚动找是最容易漏的一种读法。
    danger.length
      ? el('section', { class: 'pl-dangerbox' },
          el('h2', {}, `会毁东西的三步`, el('span', { class: 'pl-h2n',
            text: `（由数据挑出 danger=high，共 ${danger.length} 条）` })),
          el('p', { class: 'pl-note', text:
            '这三条不是「慢」或「麻烦」，是**跑完盘上的东西就变了**。'
            + '名单不在这里写死 —— 流程表加一条 danger=high 这里自己会长出来。' }),
          el('ul', {}, danger.map((s) => el('li', {},
            el('code', { class: 'pl-path', text: String(s.id) }),
            el('span', { text: ` ${s.label || ''}` }),
            has(s, 'script') ? el('span', { class: 'pl-note', text: `　${s.script}` }) : null))))
      : el('div', { class: 'pl-note', text:
          '（本表没有一条标 danger=high —— 这是数据说的，不是本页的结论）' }),

    el('h2', { class: 'pl-stages-h', text: '逐条' }),
    el('ol', { class: 'pl-stages' }, stages.map(stageNode)));

  // `#/pipeline/<阶段id>`：把那条标出来并滚过去。找不到就**什么都不做**（不是报错）。
  const want = String(sub || '').trim();
  if (want) {
    const hit = [...wrap.querySelectorAll('.pl-stage')]
      .find((li) => li.dataset.id === want);
    if (hit) {
      hit.classList.add('is-focus');
      // 补一帧再滚：`mount` 刚插进去时布局还没定，同步 scrollIntoView 会滚到 0 附近
      // （memory: resize-observer-must-rerender 同族 —— 不补帧就停在错的位置）。
      requestAnimationFrame(() => hit.scrollIntoView({ block: 'center' }));
    }
  }

  mount(root, wrap);
}
