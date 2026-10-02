// 应用外壳 —— 顶栏 / 路由 / 页脚。视图本身在 js/views/ 里，一个视图一个模块。
//
// 路由用 hash（#/检查/楼号），两条好处：零依赖（不用 history API 的服务端改写），
// 而且**可分享** —— 一条「某栋某层的验收单」能直接贴给人。
//
// ★ 加一个新视图只有两步：写 `js/views/<名字>.js`（导出 label 与 render(root, sub)），
//   在下面 VIEWS 里登记一行，再到 index.html 里给它的样式表加一个 <link>。
//   刻意不做「自动发现」：清单看得见，比约定看得见可靠。
import { el, add, mount, clear } from './dom.js';
import { API, onUnauthenticated } from './api.js';
import { can, getPrincipal, loadRoleNames, loadSession, logout, renderLogin,
         renderMustChange, roleLabel } from './session.js';

// ★ 这里有两条线，别再混起来：
//   · **后台**（本目录 frontend/admin/）= 管理面：改参数、跑阶段、查台账、核检查。
//   · **前台**（frontend/site/）        = 呈现面：只读地给人看这栋楼长什么样。
//   判断一个新功能去哪边只有一句：**它会不会改变数据？** 会 → 后台；只是看 → 前台。

/**
 * 把顶栏的**实测高度**写进 CSS 变量 `--topbar-h`。
 *
 * ★ 为什么要有这个东西：顶栏高度被三处样式表各自**手抄**过一遍 ——
 *   `app.css` 的表头粘性偏移（57px）、`js/views/campus.css` 的画布算式（81px）、
 *   `js/views/console.css` 的两栏高度（128px 里含的那段）。
 *   第 14 个导航项加进去之后顶栏从 81 长到 111，三处**同时**过期，而三处都不报错：
 *   表头被顶栏盖住看不见、画布的页脚被顶出折线多一条滚动条、控制台两栏各矮 30px。
 *   ⇒ 只留一个数，而且是**量出来的**那个。
 *
 * ★ 为什么监听元素自己、不只监听 window.resize：让它变高的原因不止视口宽度 ——
 *   导航项增减、身份栏多出一个"本机免登录"徽标、中文字体贴上来之后的换行，
 *   都会改它。只看 window 会漏掉后面几种，而漏掉的表现就是上面那三条。
 *
 * ★ 为什么要 `requestAnimationFrame` 补一帧：boot() 跑的时候 DOM 有了但**布局未定**，
 *   那一刻量到的是 0，而 0 会让表头粘到顶栏底下 —— 正好是我们要修的那个缺陷。
 *   `h > 0` 那道判断是第二道保险：量到 0 就当没量到，不覆盖上一次的真值。
 */
function trackTopbarHeight() {
  const bar = document.querySelector('.topbar');
  if (!bar) return;
  const put = () => {
    const h = Math.round(bar.getBoundingClientRect().height);
    if (h > 0) document.documentElement.style.setProperty('--topbar-h', h + 'px');
  };
  put();
  requestAnimationFrame(put);
  if (window.ResizeObserver) new ResizeObserver(put).observe(bar);
  window.addEventListener('resize', put);
}

// 导航分组。**顺序由这张表定，不由下面 VIEWS 的书写顺序定** ——
// 以后往 VIEWS 中间插一项，不必回头挪分组的位置。
// 空的分组（一个视图都没归进去）不渲染，所以这张表可以先把位置占着。
// ★ 2026-10-02 重排为五组（用户原话：「后台就是**档案和流程以及构件库**等信息，
//   和建模没有关系的页面就不要了」）。旧的四组是 `概览/数据/诊断/建模`，
//   分法本身没错，但"数据"把**成品档案**和**共用判据**混在一起、
//   "建模"把一个阶段的执行面和整条流程混在一起。新的分法是**按问题分**：
//     · 概览 —— 这批楼现在什么状态
//     · 档案 —— 这栋楼**建成了什么**（只读、逐栋、成品）
//     · 流程 —— 会写盘、跑阶段的那些（动手做东西）
//     · 构件库 —— 全库共用的**识别判据**（不是某栋楼的档案，所以单独成组）
//     · 诊断 —— 做出来的东西**对不对**
//   "档案"与"流程"这一对是新的主分界：**只读的成品 ⇄ 会写盘的动作用**。
const GROUPS = ['概览', '档案', '流程', '构件库', '诊断'];
// 忘了写 group 的视图落到这一组。★ 这个兜底不是装饰：导航**少一项**和
// 「它本来就没有」在屏幕上长得一模一样，谁也不会发现。落到末尾至少还看得见。
const MISC_GROUP = '其他';

// ★ `cap` 是这一项要的**能力**（见 backend/api/authz.py 的三档 view<edit<manage）。
//   不写 = 登录了就能看。写了 = 顶栏上只给有这个能力的人**画这个入口**。
//
//   ★★ 它**只是导航糖，不是权限**。真正的闸在服务端，每条路由自己声明
//      （`require_cap(...)`），改一行 JS 绕不过去。这里的用处只有一个：
//      一个只能看的人面前摆着「控制台／作业台／账号」，点进去全是 403 ——
//      那是把「你没这个权限」说成了「这个功能坏了」。
//
//   ★ 与后端**必须对得上**：写了 `cap:'manage'` 而那条路由在后端没挂闸，
//     就是**安全表演**（藏了入口、接口还开着）；反过来是白藏着。
//     对得上的那一份名单，是 `python -m backend.api.main` 启动时印的那张清册。
const VIEWS = [
  { id: 'overview',   label: '总览', group: '概览', load: () => import('./views/overview.js') },
  // ── 档案：这栋楼「建成了什么」的只读记录 ──────────────────────
  // ★ 这四屏的共同点：**只读、逐栋、成品**。它们与下面「流程」那组（会写盘、跑阶段）
  //   恰好相对 —— 那条分界就是用户那句话里「档案和流程」的分法。
  { id: 'drawings',   label: '图纸', group: '档案', load: () => import('./views/drawings.js') },
  { id: 'ledger',     label: '台账', group: '档案', load: () => import('./views/ledger.js') },
  { id: 'area',       label: '面积', group: '档案', load: () => import('./views/area.js') },
  // 构件库**不进档案**：它不是某栋楼的档案，是全库共用的识别判据
  // （`backend/.../component_library.py` 的 COMPONENTS/GAUGES）⇒ 单独成组。
  // ★ 它排在 `drawings` 之后是历史位置；导航次序由上面的 GROUPS 定，
  //   与这里的书写顺序无关（那是本文件开头就写明的一条约定）。
  { id: 'components', label: '构件', group: '构件库', load: () => import('./views/components.js') },
  { id: 'checks',     label: '检查', group: '诊断', load: () => import('./views/checks.js') },
  // 影像比对：本机照片（有 EXIF 坐标）↔ 高德卫星（各自独立的两份证据）。
  // ★ 归「诊断」而不是「档案」：档案那几屏是**查已经做出来的东西**（图纸/台账/构件/面积），
  //   这一屏跟「检查」是一类 —— 回答「做出来的东西跟真实场地对得上吗」。
  //   （原文写的是「跟『检查』『图谱』是一类」；2026-10-02 图谱从导航摘掉，见下面那一段。）
  //   它也是唯一一屏**证据来自本机以外**的（卫星影像是第三方影像）。
  { id: 'compare',    label: '影像比对', group: '诊断', load: () => import('./views/compare.js') },
  // 建模控制台：原 `backend/web/control.py`(8130) 那一屏（改参数 · 跑阶段 · 看模型），
  // 2026-09-25 收编进管理台。★ 做成**原生视图**而不是 iframe：管理台的文档 URL
  // 永远是 `/`（hash 路由），所以原控制台里那几处相对引用一行都不用改就指向了
  // `/data/...` —— 反而是 iframe 会自己制造「基址」这个难题（见该视图文件头）。
  //  ── 流程：会写盘、跑阶段的那些 ────────────────────────────
  // ★ 旧组名是「建模」。改叫「流程」是因为这一组与上面「档案」构成主分界：
  //   **只读的成品 ⇄ 会写盘的动作用**；"建模"这个词把两边都罩住了，分不开。
  // ★ 新增的「流程总表」排在最前：那一屏是**这张表的说明书**
  //   （读 `config/pipeline.json` 的 15 个阶段，只读），
  //   而控制台是**动手执行其中一条**的地方。先看全貌，再动手。
  { id: 'pipeline',   label: '流程总表', group: '流程', cap: 'manage',
    load: () => import('./views/pipeline.js') },
  // ★ 归「流程」与作业台同组：两屏都是「动手做东西」，
  // 与旁边那几屏「查已经做出来的东西」不是一类。
  { id: 'console',    label: '控制台', group: '流程', cap: 'manage',
    load: () => import('./views/console.js') },
  // 流程开关：读/改 `config/branches.json` —— 那份登记表**就是**「哪些是公共流程、
  // 哪些是单独流程」的判据源（`kind` 三档：公共 / 单独 / 死键）。
  // ★ 归「流程」紧挨着控制台：那两屏是同一件事的两半 ——
  //   控制台改**一栋楼的取值**（profile/spec），这一屏改**流程本身的归属与说明**
  //   （这条开关是全库一条规则、还是要逐栋定；它属于哪一步、为什么要有它）。
  // ★ 它是本仓**唯一一屏把"流程"本身当数据来编辑**的：表在仓里（`config/branches.json`），
  //   不在代码里 —— 用户原话「写在后台、我后面能修改、能成图，不是写死再代码里面」。
  //   所以这一屏**只读文件、只写那四列**，不参与任何计算。
  { id: 'branches',   label: '流程开关', group: '流程', cap: 'manage',
    load: () => import('./views/branches.js') },
  // 作业台：原 `_scratch/_portal.py`(8144) 的活（上传 · 一键生产 · 看结论），
  // 2026-09-25 收编进管理台 —— 界面重写成原生视图，原来那个页面退役。
  // ★ 归「流程」而不是「档案」：它干的是**派出生产/门禁的活**，不是查台账。
  //   它同时也是这一屏唯一有**写/执行**能力的一屏（两条 POST 挂在 `require_compute` 上）。
  { id: 'workshop',   label: '作业台', group: '流程', cap: 'manage',
    load: () => import('./views/workshop.js') },
  // 整栋三维：托管 `frontend/building.html`（同源 iframe，根级 `/building.html`）。
  // ★ 它是**后台**的：这一屏是「看这栋楼建出来长什么样」的检视工具，
  //   但入口在管理面 —— 前台 `frontend/site/` 是给访客的另一套，两边不混。
  // ★ 2026-10-02 归**档案**（原「建模」）：它的产物是一栋建好的楼，读的时候
  //   不改一个字节 —— 与上面图纸/台账/面积同属"只读、逐栋、成品"。
  { id: 'building',   label: '整栋三维', group: '档案', load: () => import('./views/building.js') },
  // ── 2026-10-02 从导航摘掉的两屏（用户原话：「和建模没有关系的页面就不要了」）──
  //
  // ★★ 「不要了」= **从这张表里摘掉入口**，不是删文件。两处理由：
  //   ① 删了就是碰数字孪生侧的资产（校区地形/实景那一摊由另一个 claude 管，越界）；
  //   ② 摘入口**可逆**（把下面两行的 `// ` 去掉就回来了），删文件不可逆。
  //   ⇒ `js/views/kg.js|css`、`js/views/campus.js|css` **四个文件一个字节没动**，
  //     直接敲 hash `#/campus`、`#/kg` 仍然进得去（下面 `visibleViews()` 认的是
  //     VIEWS，而路由是从 hash 反查 VIEWS；所以严格说摘掉之后这两条 hash 也
  //     不再解析 —— 文件在、入口不在。文件在盘上这件事由验收脚本 N3 核）。
  //
  // 图谱：引擎在 `kb/`（`ask.py` 是唯一查询入口），本视图只读两条 GET。
  // ★ 它进的是**后台**（管理面）而不是前台：这一屏回答的是「遇到这个症状该查什么」，
  //   是排查工具，不是给访客看这栋楼长什么样的东西。
  // { id: 'kg',      label: '图谱',     group: '诊断', cap: 'manage',
  //   load: () => import('./views/kg.js') },
  //
  // 校区地形：真实地形 DTM ＋ 真实影像正射合成的一份带贴图 GLB，摆在**真实场地**上看。
  // ★ 与「整栋三维」是一对：那一屏看**一栋楼建出来长什么样**（面向上层建筑），
  //   这一屏看**这块地本身是什么样**（高程、坡向、哪儿没有数据）—— 面向整个校区。
  // ★ 它也是本仓**唯一一份没有自造数据的产物**：没有高程的地方留洞，不插值、不补平。
  //   所以这一屏的重点不是"好看"，是"哪一块测不到"要说清楚（洞层 + 洞底实拍）。
  // ★ 从 `_scratch/_campus3d/campus-terrain/view_campus.html` **原生重写**过来，
  //   不是 iframe —— 那个页面是我们自己写的 24 KB（不像 building.html 是 128 KB 的
  //   成熟页），原生更省事，也免掉「基址」那一类的坑（见该视图文件头）。
  // { id: 'campus',  label: '校区地形', group: '建模', load: () => import('./views/campus.js') },
  // 账号与授权：搭 建 方 专 属。后端那一组（`/api/auth/users*`）挂的是
  // `require_cap("manage")`，这里是同一个 `manage` —— 两边对得上。
  // ★ 归「概览」而不是新建一组：它是**系统**那一档，不是"档案"也不是"流程"。
  //   分组表（GROUPS）不新增，免得为一个入口多出一行标题。
  { id: 'account',    label: '账号', group: '概览', cap: 'manage',
    load: () => import('./views/account.js') },
];

/** 这个身份**看得见**的视图。★ 导航用，不是权限 —— 见 VIEWS 上面那段。 */
function visibleViews() {
  return VIEWS.filter((v) => !v.cap || can(v.cap));
}

// ★ 暂时仍落在「检查」：总览视图还在写，等它落盘再切默认，免得后台一开就是「视图加载失败」。
// 默认落在总览：后台的门面是「这批楼现在什么状态」，不是某一道检查的失败清单。
// 检查视图仍在（hash `#/checks`），只是不再当入口 —— 一进门先看红字，
// 会把「库里 95 栋的整体情况」读成「到处都是毛病」。
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

/**
 * 顶栏导航：按分组渲染，当前视图高亮。
 *
 * ★ 为什么要分组：集成之后这一条上有十一个入口，平铺着扫一遍要读完十个词。
 * ★ 分组标题用 `aria-hidden` 掩掉、把名字挪到包一层的 `aria-label` 上 ——
 *   否则读屏会念两遍（「数据 图纸 图纸」）。屏幕上照常显示那个词。
 */
function paintNav(activeId) {
  const nav = document.getElementById('nav');
  if (!nav) return;
  // ★ 没登录就**一个入口都不画**：这时候画出来的是"点了会 401"的链接，
  //   而屏幕上那句"请先登录"会被读成"这个系统只有这几个功能"。
  if (!getPrincipal()) { clear(nav); return; }
  const shown = visibleViews();
  const groupOf = (v) => v.group || MISC_GROUP;
  const names = GROUPS.filter((g) => shown.some((v) => groupOf(v) === g));
  if (shown.some((v) => groupOf(v) === MISC_GROUP)) names.push(MISC_GROUP);
  mount(nav, names.map((name) => el('div', {
    class: 'nav-g', role: 'group', 'aria-label': name,
  },
    el('span', { class: 'nav-g-label', text: name, 'aria-hidden': 'true' }),
    shown.filter((v) => groupOf(v) === name).map((v) => el('a', {
      href: `#/${v.id}`,
      text: v.label,
      'aria-current': v.id === activeId ? 'page' : null,
    })))));
}

/**
 * 顶栏右侧：这个人是谁 + 退出。
 *
 * ★ 必须显示"现在是谁"。本机 break-glass 下这个人是"本机／搭建方"，
 *   而**局域网**下可能是任何一个账号 —— 两个都长得一样的话，一个人在
 *   浏览器里看到的权限，和他以为的账号可能是两码事（尤其是共用一台机器时）。
 */
function paintWhoami(p) {
  const box = document.getElementById('whoami');
  if (!box) return;
  if (!p) { clear(box); return; }
  const roles = Array.isArray(p.roles) ? p.roles : [];
  const scopes = Array.isArray(p.scopes) ? p.scopes : [];
  const who = p.username || '（未知）';
  mount(box,
    el('span', { class: 'who-name', text: who }),
    // ★ 印**中文名**不印角色码。会话接口回的是码（`builder`），而同一屏上
    //   账号页那张表印的是「搭建方」—— 一个角色两种写法并排在一屏上，
    //   读的人会以为它们是两样东西。翻译表见 session.js 的 loadRoleNames。
    el('span', { class: 'who-roles',
                 text: roles.length ? roles.map(roleLabel).join('·') : '（无角色）',
                 // 角色码仍要能查到 —— 审计日志、接口里用的是码。
                 title: roles.length ? `角色码：${roles.join('、')}` : '' }),
    // ★ 范围要露出来：一个只在 c006 有权限的人，看到"总览"里别的楼是空的，
    //   原因在这儿；不写出来他会以为是数据丢了。
    scopes.length === 1 && scopes[0] === '*' ? null
      : el('span', { class: 'who-scopes',
                     text: scopes.length ? scopes.join('、') : '无范围',
                     title: '这份账号能看到的范围（沿空间树向下继承）' }),
    // break-glass 必须**说出来**：这个身份不是登录来的，是"你正好在本机"。
    // 不说的话，一台共用机器上谁都能以搭建方身份操作，而屏幕上看着像登录过了。
    // ★ 判据是 `via === 'loopback'`（**这一次是不是走旁路进来的**），
    //   不是"开关开着没有" —— 后端原来回的是后者，那等于把配置状态
    //   贴在一条公开路由上，局域网里谁都能读（2026-10-01 已改成只回 via）。
    p.via === 'loopback' ? el('span', { class: 'who-bg',
      text: '本机免登录', title: 'GYM3D_LOOPBACK_BREAKGLASS：来自 127.0.0.1 的请求直接算搭建方。真上公网前必须关掉。' }) : null,
    el('button', { class: 'who-out', type: 'button', text: '退出',
                   onclick: () => logout() }));
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
      //   就变成了一句错话（「回检查视图」而它其实回总览）。
      [el('a', {
        class: 'chk-btn', href: `#/${DEFAULT_VIEW}`,
        text: `回${VIEWS.find((v) => v.id === DEFAULT_VIEW)?.label || DEFAULT_VIEW}`,
      })]);
    return;
  }

  // ★ 没有这个能力就**不加载那个模块**：光把顶栏上的入口藏掉是不够的，
  //   地址栏里手打 `#/console` 直接就到了。这里挡的仍然只是"看得到的"，
  //   真正的 403 由服务端回（那一条才是判据，这一条只是别让人白跑一趟）。
  if (spec.cap && !can(spec.cap)) {
    paintPanic(main, '这份账号看不了这一屏',
      `「${spec.label}」需要 ${spec.cap} 能力，而当前账号（${getPrincipal()?.username || '—'}）`
      + `的能力是 ${(getPrincipal()?.caps || []).join('、') || '无'}。`,
      [el('a', { class: 'chk-btn', href: `#/${DEFAULT_VIEW}`, text: '回总览' })]);
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

/** 会话中途掉了（任何一条接口回 401）⇒ 停下正在画的东西，请人重新登录。 */
function showLogin(reason) {
  const main = document.getElementById('main');
  if (!main) return;
  state.module = null; state.id = null; state.seq += 1;   // ★ 让在飞的视图别再画
  clear(document.getElementById('nav'));
  paintWhoami(null);
  renderLogin(main, { reason, onSuccess: () => location.reload() });
}

async function boot() {
  // ★ 先把量具挂上：`trackTopbarHeight()` 注册的 ResizeObserver 会在顶栏**每一次**
  //   变高变矮时重写 `--topbar-h`，所以这里量到的是不是最终值并不重要。
  //   启动这一刻顶栏还是空壳（导航和身份栏都没画），量出来必然偏小 ——
  //   那没关系，画完导航它就自己更正了。真正要避免的是"一次都不量"，
  //   那样三处消费者会一直用各自的兜底值，而兜底值全是过期的旧数。
  trackTopbarHeight();
  window.addEventListener('hashchange', () => { route(); });
  // ★ 任何一条接口回 401（会话过期 / 库把会话删了 / 换了个进程）都会走到这里。
  //   注册在**问会话之前**：下面那几条请求自己也可能撞上。
  onUnauthenticated(() => showLogin('登录状态已失效，请重新登录。'));

  const main = document.getElementById('main');

  // ① 先问会话 —— 在**画任何东西之前**。
  //    ★ 顺序不能反：先画视图再问身份的话，一个只能在 c006 看的人会先看到
  //      全校区那一屏渲染出来（哪怕随后被换掉），而那一瞬间的数据已经在
  //      他的屏幕上了。会话是这一屏的**前置条件**，不是它的装饰。
  let p = null;
  try {
    p = await loadSession();
  } catch (e) {
    // ★ 「问不到」和「没登录」是两回事。后端挂了却说"请登录"，用户会去
    //   反复试口令（而问题不在口令）；反过来库连不上时 `session` 回的也是
    //   503，这里必须把后端自己那句话原样显示出来。
    paintPanic(main, '连不上后端',
      `${e && e.message ? e.message : String(e)}`,
      [el('button', { class: 'chk-btn', type: 'button', text: '重试',
                      onclick: () => location.reload() })]);
    return;
  }
  if (!p) { showLogin(null); return; }

  // ①b 角色码 → 中文名。★ 必须在 `paintWhoami` **之前**：顶栏印的是角色名，
  //     表还没到的时候 `roleLabel` 会回原始码（`builder`），而那时候画上去
  //     就**不会再重画**了 —— 屏幕上留下一个别人看不懂的词，且它看起来是对的。
  //     `loadRoleNames` 自己吞异常（读不到就回码），所以这里不 try。
  await loadRoleNames();

  if (p.must_change) {
    // 初次登录必须换掉初始口令。见 session.js 里 renderMustChange 的注释。
    clear(document.getElementById('nav'));
    paintWhoami(p);
    renderMustChange(main, () => location.reload());
    return;
  }
  paintWhoami(p);

  // ② 能力（顶栏那句话、页脚）。问不到也不挡看结论。
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
