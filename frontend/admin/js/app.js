// 应用外壳 —— 顶栏 / 路由 / 页脚。视图本身在 js/views/ 里，一个视图一个模块。
//
// 路由用 hash（#/检查/楼号），两条好处：零依赖（不用 history API 的服务端改写），
// 而且**可分享** —— 一条"某栋某层的验收单"能直接贴给人。
//
// ★ 加一个新视图只有两步：写 `js/views/<名字>.js`（导出 label 与 render(root, sub)），
//   在下面 VIEWS 里登记一行，再到 index.html 里给它的样式表加一个 <link>。
//   刻意不做"自动发现"：清单看得见，比约定看得见可靠。
import { el, add, mount } from './dom.js';
import { API } from './api.js';

// ★ 这里有两条线，别再混起来：
//   · **后台**（本目录 frontend/admin/）= 管理面：改参数、跑阶段、查台账、核检查。
//   · **前台**（frontend/site/）        = 呈现面：只读地给人看这栋楼长什么样。
//   判断一个新功能去哪边只有一句：**它会不会改变数据？** 会 → 后台；只是看 → 前台。
const VIEWS = [
  { id: 'overview',   label: '总览',  load: () => import('./views/overview.js') },
  { id: 'drawings',   label: '图纸',  load: () => import('./views/drawings.js') },
  { id: 'ledger',     label: '台账',  load: () => import('./views/ledger.js') },
  { id: 'components', label: '构件',  load: () => import('./views/components.js') },
  { id: 'area',       label: '面积',  load: () => import('./views/area.js') },
  { id: 'checks',     label: '检查',  load: () => import('./views/checks.js') },
  // 图谱：引擎在 `kb/`（`ask.py` 是唯一查询入口），本视图只读两条 GET。
  // ★ 它进的是**后台**（管理面）而不是前台：这一屏回答的是「遇到这个症状该查什么」，
  //   是排查工具，不是给访客看这栋楼长什么样的东西。
  { id: 'kg',         label: '图谱',  load: () => import('./views/kg.js') },
];

// ★ 暂时仍落在「检查」：总览视图还在写，等它落盘再切默认，免得后台一开就是"视图加载失败"。
// 默认落在总览：后台的门面是"这批楼现在什么状态"，不是某一道检查的失败清单。
// 检查视图仍在（hash `#/checks`），只是不再当入口 —— 一进门先看红字，
// 会把"库里 95 栋的整体情况"读成"到处都是毛病"。
const DEFAULT_VIEW = 'overview';

const state = { module: null, id: null, seq: 0 };

/** 把 hash 拆成 {id, sub}。`#/checks/c113` → {id:'checks', sub:'c113'} */
function parseHash() {
  const raw = (location.hash || '').replace(/^#\/?/, '');
  const parts = raw.split('/').filter((p) => p !== '');
  const id = parts[0] || DEFAULT_VIEW;
  const sub = parts.slice(1).map((p) => {
    try { return decodeURIComponent(p); } catch { return p; }
  }).join('/');
  return { id, sub };
}

/** 顶栏导航：当前视图高亮。 */
function paintNav(activeId) {
  const nav = document.getElementById('nav');
  if (!nav) return;
  mount(nav, VIEWS.map((v) => el('a', {
    href: `#/${v.id}`,
    text: v.label,
    'aria-current': v.id === activeId ? 'page' : null,
  })));
}

/** 顶栏右侧：后端能力。取不到就**明说接口不可用**，不留空。 */
function paintRunState(caps, err) {
  const box = document.getElementById('runstate');
  if (!box) return;
  if (err) {
    mount(box, el('b', { class: 'miss', text: '接口不可用' }),
      el('span', { text: err.message?.slice(0, 60) || String(err) }));
    return;
  }
  mount(box,
    el('span', {}, el('b', { text: '后端 ' }), 'ok'),
    el('span', {}, el('b', { text: '写权限 ' }),
      caps.write_enabled ? '开（可跑检查）' : '关（只读进程）'),
    el('span', {}, el('b', { text: '楼栋 ' }), String(caps.buildings ?? '—')),
    el('span', {}, el('b', { text: '检查产物目录 ' }),
      caps.checks_artifact_dir_present ? '在' : '不在'));
  if (!caps.write_enabled && caps.write_disabled_reason) {
    box.title = caps.write_disabled_reason;
  }
}

function paintFooter(caps) {
  const src = document.getElementById('foot-src');
  const api = document.getElementById('foot-api');
  if (src) src.textContent = '前端零构建（原生 ES module）· 判据来源 backend/checks/CHECK_REGISTRY';
  if (api) {
    // ★ 逐段拼，缺的那段**不出现**。写成 `env=${caps.env}` 时后端只要没这个字段，
    //   屏幕上就是字面的 `env=undefined` —— 「不知道」的正确写法是不说，
    //   而不是让模板串替你说一个不存在的值。
    const parts = [`接口 ${window.GYM3D_API_BASE || '同源'}`];
    if (!caps) {
      parts.push('未连上');
    } else {
      parts.push(`compute=${caps.compute ? 1 : 0}`);
      if (caps.env) parts.push(`env=${caps.env}`);
    }
    api.textContent = parts.join(' · ');
  }
}

/** 路由不存在 / 视图挂了：都要说清楚，不能白屏。 */
function paintPanic(main, title, msg, actions = []) {
  mount(main, el('div', { class: 'chk-panic' },
    el('h2', { class: 'chk-panic-h', text: title }),
    el('p', { class: 'chk-panic-msg', text: msg }),
    actions.length ? el('div', { class: 'chk-toolbar' }, actions) : null));
}

async function route() {
  const main = document.getElementById('main');
  if (!main) return;
  const { id, sub } = parseHash();
  paintNav(id);

  const spec = VIEWS.find((v) => v.id === id);
  if (!spec) {
    paintPanic(main, '没有这个视图',
      `#/${id} 不在前端的视图清单里。现有视图：${VIEWS.map((v) => v.label).join('、')}。`,
      // ★ 按钮文字跟着 DEFAULT_VIEW 走，不写死 —— 写死的那版在默认视图改成总览之后
      //   就变成了一句错话（"回检查视图"而它其实回总览）。
      [el('a', {
        class: 'chk-btn', href: `#/${DEFAULT_VIEW}`,
        text: `回${VIEWS.find((v) => v.id === DEFAULT_VIEW)?.label || DEFAULT_VIEW}`,
      })]);
    return;
  }

  // 切视图时先让上一个视图收尾（检查视图会停下正在跑的扫描）。
  if (state.module && state.id !== id && typeof state.module.dispose === 'function') {
    try { state.module.dispose(); } catch { /* 收尾失败不该挡住切换 */ }
  }
  const mySeq = ++state.seq;
  mount(main, el('div', { class: 'loading', text: `正在加载「${spec.label}」…` }));
  try {
    // 同一个视图不重复 import（模块本来也只求值一次）；切视图则按需加载那一份。
    const mod = state.module && state.id === id ? state.module : await spec.load();
    state.module = mod;
    state.id = id;
    if (mySeq !== state.seq) return;      // 已经切到别的视图了，别再画
    document.title = `${spec.label} · 建模后台 gym3d`;
    await mod.render(main, sub);
  } catch (e) {
    if (mySeq !== state.seq) return;
    paintPanic(main, '视图加载失败', String(e && e.message ? e.message : e),
      [el('button', { class: 'chk-btn', type: 'button', text: '重试', onclick: () => route() })]);
  }
}

async function boot() {
  window.addEventListener('hashchange', () => { route(); });
  // 能力先问再画（按钮的开关读它）；问不到也不挡看结论。
  try {
    const caps = await API.capabilities();
    paintRunState(caps, null);
    paintFooter(caps);
  } catch (e) {
    paintRunState(null, e);
    paintFooter(null);
  }
  if (!location.hash) location.hash = `#/${DEFAULT_VIEW}`;
  await route();
}

boot();
