// 「构件」视图 —— 把 backend/recognizer/component_library.py 摊开给人看。
//
// 这一屏存在的理由：本项目的识别规则固化在构件库里，识别错了就去更新库。
// 所以要能一眼回答两个问题：
//   · 库里现在有什么（11 个构件的签名 / 参数 / 踩过的坑 + 3 件外部量具）
//   · 库自己自检过不过（component_library 的纯函数判据，边界落在该落的那一侧吗）
//
// ★★ 本屏的三条硬规矩（与 checks 视图同一个模子）：
//   1. 「挂了」不许显示成「通过」。自检接口本身 500 / 连不上时，屏幕上是
//      「自检没跑起来」，绝不是绿色。这是本仓最贵的一类错
//      （memory: gauge-coverage-invisible-in-summary）。
//   2. 「没有」和「通过」要分得开。某个构件没登记参数、没登记坑，
//      那是「未登记」，不画成绿色对勾，也不留空白让人当「没事」。
//   3. 自检的覆盖面要写出来。13 条探针只压 3 个判据函数，而库里是 11 个构件 ——
//      绿灯只说明「这几条边界没写反」，不说明「11 个构件都对」。
//      数字是数出来的（去重 fn 名），不是判出来的。
//
// 前端一个判据都不算：下面每个字都来自 /api/components 与 /api/components/selfcheck。
import { el, add, mount } from '../dom.js';
import { API, ApiError, getEnv } from '../api.js';

export const label = '构件';

// 切视图会调 dispose()：把在飞的 fetch 收掉，否则回来的路上会往一个
// 已经不在 DOM 里的节点写（memory: silent-failure-needs-a-voice）。
let disposed = false;
let inflight = null;

export function dispose() {
  disposed = true;
  inflight?.abort();
  inflight = null;
}

// ── 公用小件 ───────────────────────────────────────────────────

/**
 * 接口不可用 / 出错的统一面板。
 * 措辞上把「连不上」与「后端自己挂了」分开 —— 前者是环境问题，后者是缺陷，
 * 修法完全不同，不能都叫「加载失败」。
 */
function panic(err, opts = {}) {
  const e = err instanceof ApiError ? err : new ApiError('unknown', String(err));
  const down = e.code === 'network' || e.status === 0;
  const title = down ? '接口不可用'
    : e.code === 'internal_error' ? '后端这个接口自己挂了'
      : `取数失败：${e.code}`;
  const box = el('div', { class: `cmp-panic${down ? ' down' : ''}` },
    el('h2', { class: 'cmp-panic-h', text: title }),
    el('p', { class: 'cmp-panic-msg', text: e.message || String(err) }));
  add(box, el('div', { class: 'cmp-panic-body' },
    el('p', {}, down
      ? '这一屏现在什么都没有 —— 所以这里不画空表、也不画绿灯。'
      : '后端回了错误信封，下面是它给的原话。注意「接口挂了」不是「检查通过」，'
        + '这两件事在这一屏上必须分得开。'),
    el('p', { class: 'dim' },
      '取的是 ', el('code', { text: opts.endpoint || '/api/components' }),
      '；后端地址：', el('code', { text: window.GYM3D_API_BASE || '同源（当前页所在主机）' })),
    e.detail ? el('details', { class: 'cmp-details' },
      el('summary', { text: '后端给的细节（原样）' }),
      el('pre', { class: 'cmp-ev', text: JSON.stringify(e.detail, null, 2) })) : null,
    opts.onRetry ? el('div', { class: 'cmp-toolbar' },
      el('button', { class: 'cmp-btn primary', type: 'button', text: '重试',
        onclick: opts.onRetry })) : null));
  return box;
}

function busy(text) {
  return el('div', { class: 'cmp-busy' }, el('span', { class: 'spin' }), text);
}

/** 「没有」的写法：带虚线边框的一句灰字。绝不与绿色/对勾混用。 */
function absent(what) {
  return el('p', { class: 'cmp-absent', text: what });
}

// ── 自检面板 ───────────────────────────────────────────────────

// 后端 meta.verdict 的三个值 + 两种「没给结论」。
const VERDICT_UI = {
  pass: { cls: 'pass', word: '通过', note: '全部探针都落在期望的那一侧' },
  partial: { cls: 'partial', word: '部分未量成',
    note: '有探针没量成（缺依赖等）—— 没量成会压掉绿灯，所以它不是「通过」' },
  fail: { cls: 'fail', word: '不通过', note: '有探针和期望值相反 ⇒ 先怀疑构件库判据' },
};

/** 自检面板：先画结论，再画统计，再画不通过/未量成的逐条明细。 */
function selfcheckPanel(env) {
  const d = env?.data;
  if (!d || !Array.isArray(d.probes)) {
    // 后端回了 200 但没有探针数组 —— 这比 500 更隐蔽，必须明说。
    return el('div', { class: 'cmp-verdict unknown' },
      el('span', { class: 'cmp-verdict-w', text: '未给结论' }),
      el('p', { class: 'cmp-verdict-n',
        text: '后端回 200，但响应里没有 probes 数组 —— 这不是「通过」，是这一屏读不懂它的返回。' }));
  }

  const verdict = env?.meta?.verdict;
  const ui = VERDICT_UI[verdict];
  const counts = d.counts || {};
  const bad = d.probes.filter((p) => p.status !== 'pass');

  const head = el('div', { class: `cmp-verdict ${ui ? ui.cls : 'unknown'}` },
    el('span', { class: 'cmp-verdict-w', text: ui ? ui.word : '未给结论' }),
    el('span', { class: 'cmp-verdict-t', text: `verdict=${verdict ?? '（后端没给 meta.verdict）'}` }),
    el('p', { class: 'cmp-verdict-n', text: ui ? ui.note
      : '后端没给 meta.verdict，前端不替它认领一个结论。' }),
    el('p', { class: 'cmp-stats mono' },
      `探针 ${d.total ?? d.probes.length} 条 ｜ 通过 ${counts.pass ?? 0}`
      + ` ｜ 不通过 ${counts.fail ?? 0} ｜ 未量成 ${counts.unavailable ?? 0}`),
    // ★ 覆盖面：绿灯的边界比它看着的窄，写在结论旁边而不是埋在脚注里。
    el('p', { class: 'cmp-cov' },
      '覆盖面：这 ', String(d.probes.length), ' 条探针只压 '
      , el('b', { text: String(new Set(d.probes.map((p) => p.fn)).size) }),
      ' 个判据函数（', [...new Set(d.probes.map((p) => p.fn))].join(' / '), '）。'
      + '它测的是「边界两侧谁算谁不算」，',
      el('b', { text: '不是' }),
      '「0.6/3.0 这两个常量对不对」——'
      + '后者只能靠图纸里的真实门宽这类外部量具。'),
    env?.meta?.hint ? el('p', { class: 'cmp-hint', text: env.meta.hint }) : null);

  const list = bad.length
    ? el('div', {}, el('h3', { class: 'cmp-h3', text: `不通过 / 未量成的探针（${bad.length} 条）` }),
      bad.map((p) => el('div', { class: `cmp-probe ${p.status === 'fail' ? 'fail' : 'unavail'}` },
        el('div', { class: 'cmp-probe-h' },
          el('span', { class: 'cmp-probe-fn mono', text: `${p.fn}()` }),
          el('span', { class: `tag ${p.status === 'fail' ? 'bad' : 'dim'}`,
            text: p.status === 'fail' ? 'FAIL' : '未量成' }),
          el('span', { class: 'cmp-probe-exp mono',
            text: `期望 ${String(p.expected)} ／ 实测 ${String(p.got)}` })),
        el('div', { class: 'cmp-probe-note', text: p.note || '（这条没给说明）' }))))
    // 全过时也要说一句「没有别的条目」，而不是留一片空白让人以为没渲染出来。
    : el('p', { class: 'cmp-allok' },
      `没有不通过、也没有未量成的探针 —— ${d.probes.length} 条全落在期望的那一侧。`);

  const all = el('details', { class: 'cmp-details' },
    el('summary', { text: `全部 ${d.probes.length} 条探针（原样）` }),
    el('table', { class: 'cmp-table' },
      el('thead', {}, el('tr', {},
        ['判据函数', '期望', '实测', '状态', '这条在测什么'].map((h) => el('th', { text: h })))),
      el('tbody', {}, d.probes.map((p) => el('tr', { class: `st-${p.status}` },
        el('td', { class: 'mono', text: `${p.fn}()` }),
        el('td', { class: 'mono', text: String(p.expected) }),
        el('td', { class: 'mono', text: String(p.got) }),
        el('td', {}, el('span', { class: `tag ${p.status === 'pass' ? 'good'
          : p.status === 'fail' ? 'bad' : 'dim'}`, text: p.status })),
        el('td', { class: 'cmp-note-cell', text: p.note || '—' }))))));

  return el('div', {}, head, list, all);
}

/**
 * 自检这一块的取数：失败与成功都要有面板，绝不塌成空白。
 *
 * ★ 重试必须重新对准 target 自己，不能让重试回调去 mount 一个临时的中间节点 ——
 *   中间节点的孩子早被搬进 target 了，再往里写就是写进一个脱离文档的节点：
 *   点了「重试」什么都不动，也不报错（memory: silent-failure-needs-a-voice）。
 */
async function renderSelfcheck(target) {
  mount(target, busy('正在跑自检…'));
  try {
    const env = await API.selfcheck();
    if (disposed) return;
    mount(target, selfcheckPanel(env),
      el('p', { class: 'dim cmp-src' },
        '来源 GET /api/components/selfcheck ｜ 不重跑识别，只把探针喂给 component_library '
        + '的纯函数判据（判据本体在 backend/recognizer/component_library.py）。'));
  } catch (e) {
    if (disposed) return;
    mount(target, panic(e, {
      endpoint: '/api/components/selfcheck',
      onRetry: () => renderSelfcheck(target),
    }),
    // ★ 这一句是这条规矩的落点：接口挂了 ≠ 通过。
    el('p', { class: 'cmp-warnline',
      text: '★ 上面是「自检没跑起来」，不是「自检通过」。这两件事不许混。' }));
  }
}

function section(title, sub, ...body) {
  return el('section', { class: 'cmp-sec' },
    el('h2', {}, title, sub ? el('span', { class: 'cmp-sub', text: sub }) : null),
    ...body);
}

// ── 构件清单 ───────────────────────────────────────────────────

/** 一个构件的卡片：签名 + 参数表 + 踩过的坑。 */
function componentCard(c) {
  const params = Object.entries(c.params || {});
  const pits = Array.isArray(c.pitfalls) ? c.pitfalls : [];
  return el('article', { class: `card${pits.length ? ' pit' : ''}` },
    el('h3', {}, c.name),
    c.signature
      ? el('div', { class: 'sig', text: c.signature })
      : absent('这个构件没登记签名（它按什么图元、什么条件被认出来）。'),
    el('dl', {},
      el('dt', { text: `识别参数（${params.length}）` }),
      el('dd', {}, params.length
        ? el('table', { class: 'cmp-kv' }, el('tbody', {}, params.map(([k, v]) =>
          el('tr', {}, el('th', { text: k }), el('td', { text: String(v) })))))
        : absent('未登记参数 —— 这个构件不吃命名常量，或者库还没写。')),
      el('dt', { text: `踩过的坑（${pits.length}）` }),
      el('dd', {}, pits.length
        ? el('ul', {}, pits.map((s) => el('li', { text: s })))
        : absent('未登记坑。注意这是「没写」，不是「没坑」。'))));
}

function componentList(env) {
  const comps = env?.data?.components;
  if (!Array.isArray(comps)) {
    return absent('后端响应里没有 components 数组 —— 读不到清单，不画空列表。');
  }
  if (!comps.length) {
    // 「库里一条都没有」和「检查通过」必须分开 —— 这是空空如也，不是绿灯。
    return el('div', { class: 'cmp-none' },
      el('b', { text: '库里一条构件都没有。' }),
      '这是「没有」，不是「检查通过」—— 没有构件就没有任何识别规则可谈。');
  }
  // 分组轴：库本身没有 type / 来源 字段（后端只回 signature / params / pitfalls），
  // 所以这里是前端按「有没有命名参数」分的，不是库标的分类。写明白，
  // 免得以后有人把它当成库的正式分组。
  const withParams = comps.filter((c) => Object.keys(c.params || {}).length);
  const noParams = comps.filter((c) => !Object.keys(c.params || {}).length);
  return el('div', {},
    el('p', { class: 'cmp-axis' },
      '分组轴：', el('b', { text: '有没有命名参数' }),
      '（库本身没有 type/source 字段，这层分组是前端按 '
      + `params 是否为空分的，不是库里标的）。共 ${comps.length} 个构件。`),
    el('h3', { class: 'cmp-h3', text: `有参数表（${withParams.length}）` }),
    withParams.length
      ? el('div', { class: 'cards' }, withParams.map(componentCard))
      : absent('一个都没有。'),
    el('h3', { class: 'cmp-h3', text: `无参数表（${noParams.length}）` }),
    noParams.length
      ? el('div', { class: 'cards' }, noParams.map(componentCard))
      : absent('一个都没有。'));
}

// ── 外部量具 ───────────────────────────────────────────────────

function gaugeCard(g) {
  const rows = [['在哪', g.where], ['用法', g.usage], ['为什么', g.why], ['坑', g.pitfall]];
  return el('article', { class: 'card' },
    el('h3', {}, g.name),
    el('dl', {}, rows.map(([k, v]) => [
      el('dt', { text: k }),
      el('dd', {}, v ? el('div', { class: 'cmp-pre', text: String(v) }) : absent('未登记。')),
    ])));
}

// ── 主渲染 ─────────────────────────────────────────────────────

export async function render(root, _sub) {
  disposed = false;
  mount(root, busy('正在读构件库…'));

  // 两路并发：自检慢（要 import shapely），清单快 —— 先出清单，自检到了再补。
  const listBox = el('div', { class: 'cmp-box' }, busy('正在读构件库…'));
  const checkBox = el('div', { class: 'cmp-box' });
  inflight = new AbortController();

  const head = el('div', {},
    el('h1', {}, '构件 · 识别规则库',
      el('span', { class: 'cmp-sub', text: ' 识别错就更新库，所以要先看得见库里有什么' })),
    el('p', { class: 'lede' },
      '这一屏摊开的是 ', el('code', { text: 'backend/recognizer/component_library.py' }),
      ' —— 11 个构件的签名/参数/踩过的坑，外加 3 件',
      el('b', { text: '外部量具' }), '（图纸自己写的话）。',
      el('br'),
      '上面一栏是库的', el('b', { text: '自检' }),
      '：它只喂探针给纯函数判据，不重跑识别。'));

  mount(root, head, section('库自检', '判据边界落在它该落的那一侧吗', checkBox),
    section('构件清单', '按有没有命名参数分组', listBox));

  renderSelfcheck(checkBox);   // 不 await：清单先出，自检慢（要 import shapely）

  try {
    // ★ 走 getEnv 而不是 API.components()：`API.components` 是 `get(...)`，
    //   它**已经把信封拆掉了**（返回的是 data）。写成 `env.data.components`
    //   就会恒为 undefined —— 于是这一屏永远显示"后端响应里没有 components 数组"，
    //   看着像后端没给数据，其实是这里多拆了一层。这一条是拿刑具试出来的
    //   （memory: 量具覆盖不到的地方，汇总看上去跟"全对"一样）。
    const env = await getEnv('/api/components');
    if (disposed) return;
    const meta = env?.meta || {};
    mount(listBox,
      el('p', { class: 'dim cmp-src' },
        `来源 ${meta.source || '（后端没给 meta.source）'} · `
        + `后端数出来 ${meta.components ?? '—'} 个构件 / ${meta.gauges ?? '—'} 件量具`),
      componentList(env),
      el('h3', { class: 'cmp-h3', text: `外部量具（${(env?.data?.gauges || []).length}）` }),
      (env?.data?.gauges || []).length
        ? el('div', { class: 'cards' }, (env.data.gauges || []).map(gaugeCard))
        : absent('后端响应里没有 gauges（或为空）—— 读不到量具清单。'),
      el('h3', { class: 'cmp-h3',
        text: `命名常量（${Object.keys(env?.data?.constants || {}).length}）` }),
      Object.keys(env?.data?.constants || {}).length
        ? el('div', { class: 'consts' }, Object.entries(env.data.constants).map(([k, v]) =>
          el('div', { class: 'const' }, el('b', { text: k }), ` = ${v}`)))
        : absent('后端响应里没有 constants —— 读不到常量表。'),
      el('p', { class: 'dim cmp-src' },
        '常量改一处全楼生效：白名单式列举（backend/api/routers/components.py 的 _consts），'
        + '新增模块级变量不会自己冒出来。'));
  } catch (e) {
    if (disposed) return;
    mount(listBox, panic(e, {
      endpoint: '/api/components',
      onRetry: () => render(root, _sub),
    }));
  }
}
