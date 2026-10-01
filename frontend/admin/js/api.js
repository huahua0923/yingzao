// 后端唯一的入口 —— 所有 fetch 都从这里走。
//
// 为什么集中一处：后端回了统一信封 {success,data,error,meta}，
// 下面这个 api() 是**唯一**拆信封的地方。散着写 20 个 fetch，
// 就必然有人忘了看 success，于是错误被当成数据渲染出去。

const BASE = (window.GYM3D_API_BASE ?? '').replace(/\/$/, '');

export class ApiError extends Error {
  constructor(code, message, detail, status) {
    super(message);
    this.code = code; this.detail = detail; this.status = status;
  }
}

// ★ 会话掉了要能把人送回登录页 —— 由 app.js 注册一个回调，api.js 负责喊。
//
// 为什么放在这里而不是让每个视图自己判 401：视图有十几个，**漏一个就是一处
// 静默失败** —— 那个视图会把自己的错误渲染成"这栋楼的数据读不到"，
// 而真相是"你的会话过期了"，补救办法完全相反（刷新页面去登录 vs 查后端）。
//
// ★ 只在 **401** 上喊，不在 403 上喊：403 是"登录了但没这个权限"，
//   把人踢回登录页只会让他反复登进同一个进不去的地方。
let _onUnauth = null;
/** 注册"会话失效"回调。后注册的覆盖先注册的（只有一个外壳，够用）。 */
export function onUnauthenticated(fn) { _onUnauth = fn; }

async function api(path, { method = 'GET', body, rawBody, signal } = {}) {
  // ★ 三种取值必须分开，合起来写就会出错：
  //   · 没有 body            ⇒ 连 content-type 都不带（带了会让 FastAPI 去解析空体）
  //   · rawBody = **文件本体** ⇒ 只给 body，**不写 content-type**：让浏览器按 File 自己定；
  //     上传那条路由也不解析请求体（`await request.body()`），类型对它没有意义
  //   · body = 对象          ⇒ JSON，由 api() 自己 stringify
  //   ⇐ 反例：把 File 塞进 body，`JSON.stringify(File)` 得到 `{}`，请求照样 200，
  //     屏幕上写着「上传成功」，而盘上落的是 2 字节。**只有一个拆信封的地方**这条
  //     不能用来省另一条 —— 得让它自己认出这是文件。
  const isRaw = rawBody !== undefined && rawBody !== null;
  let res;
  try {
    res = await fetch(BASE + path, {
      method,
      signal,
      // ★ credentials 必须显式写：fetch 的默认值是 `'same-origin'`，但那是
      //   **规范默认**，不是"永远会带 cookie"的保证 —— 一旦有人把
      //   `GYM3D_API_BASE` 指到另一个源（前端本机、后端在服务器上，本期正是
      //   这个形态），默认值就退化成 `'same-origin'` 对那个跨源请求**不带 cookie**，
      //   症状是"登录成功了，但每个接口都 401"，而浏览器控制台**一个字都不报**。
      //   写死成 'same-origin' 至少让这条规则在源码里看得见。跨源要真带 cookie，
      //   那得改成 'include' 并同时配 `Access-Control-Allow-Credentials`。
      credentials: 'same-origin',
      headers: body && !isRaw ? { 'content-type': 'application/json' } : undefined,
      body: isRaw ? rawBody : (body ? JSON.stringify(body) : undefined),
    });
  } catch (e) {
    // 网络层失败（后端没起 / 端口不对）与业务错误要分开说，
    // 否则「后端没启动」会被显示成「这栋楼不存在」。
    throw new ApiError('network', `连不上后端（${BASE || '同源'}）：${e.message}`,
                       null, 0);
  }
  let env;
  try {
    env = await res.json();
  } catch {
    throw new ApiError('bad_response', `后端回了非 JSON（HTTP ${res.status}）`,
                       { path }, res.status);
  }
  if (!env || env.success !== true) {
    const err = env?.error ?? {};
    // ★ 会话失效要把人送回登录页。两处**必须**排除，否则会制造一个更坏的体验：
    //   · `/api/auth/login` 本身 —— 口令打错时后端回的就是 401，若在这里喊，
    //     页面正在显示的那张登录表会被自己的回调拆掉重建，输一半的口令没了；
    //   · `/api/auth/session` —— 它按约定回 200 + `logged_in:false`，不是 401，
    //     列在这里只是把"它不该走到这支"写明。
    if (res.status === 401 && _onUnauth && !path.startsWith('/api/auth/')) {
      try { _onUnauth(err); } catch { /* 回调自己坏了不该盖掉原始错误 */ }
    }
    throw new ApiError(err.code ?? 'unknown', err.message ?? `HTTP ${res.status}`,
                       err.detail, res.status);
  }
  return env;
}

/** 取 data（大多数调用只关心它）。 */
export async function get(path, opts) { return (await api(path, opts)).data; }
/** 取整个信封（少数地方要看 meta，例如对账快照时间）。 */
export async function getEnv(path, opts) { return api(path, opts); }

export const post = (path, body) => api(path, { method: 'POST', body });
/** 发**文件本体**（不是 JSON）。见 api() 里 `rawBody` 那一段的理由。 */
export const postRaw = (path, rawBody) => api(path, { method: 'POST', rawBody });
/** PUT。★ 2026-09-25 才有的：在那之前全目录只有一个 fetch（本文件的 api()），
 *  一个 put 都没有 —— 所以「用 put 发」这件事在本目录是新的，不是漏了一个导出。 */
export const put = (path, body) => api(path, { method: 'PUT', body });
/** DELETE。★ 与 `put` 一样是**本目录的新通道**（此前一条 DELETE 都没有），
 *  不是"漏了一个导出"。目前全仓只有一处用它：撤掉一条授权
 *  （`DELETE /api/auth/users/{id}/grants`）。 */
export const del = (path) => api(path, { method: 'DELETE' });

export const API = {
  // ★ 这个对象是**承接口**：列在这里的每一条，都必须有 `backend/api/routers/`
  //   里一条真实路由。它看起来只是一行字符串拼接，但一个视图会照着它去写，
  //   而后端没这条路由时，那个 404 会被读成「接口坏了」，不是「这个方法不存在」。
  //   2026-09-25 删掉了 `agents` / `agentRun`：全仓（含未跟踪的 _scratch/）
  //   grep 过，既没有路由也没有调用点 —— 空头支票。要加智能体，先有路由再登记。
  health:        ()      => get('/api/health'),
  capabilities:  ()      => get('/api/capabilities'),

  // ── 账号与会话（`backend/api/routers/auth.py`）─────────────────────
  // ★ 三条公开 / 其余要 manage —— 「要什么」由**后端**决定，这里只是地址表。
  // ★ `session()` 走 `get` 不走 `getEnv`：这条路由回 `ok(data)` 不带 meta。
  //   而且它**刻意不回 401** —— 没登录是它的正常输出（`logged_in:false`），
  //   回 401 会让上面那个 onUnauthenticated 钩子把登录页拆了重建。
  auth: {
    session: ()            => get('/api/auth/session'),
    login:   (u, p)        => post('/api/auth/login', { username: u, password: p }),
    logout:  ()            => post('/api/auth/logout'),
    // 本人改密：只要「已登录」，不要任何能力（后端挂的是 `current_principal`）。
    // 一个刚建好、还没拿到授权的新账号**必须能改自己的初始口令** ——
    // 给它挂 `require_cap("view")` 会把这种人锁在门外。
    changePw: (oldPw, newPw) => post('/api/auth/password',
      { old_password: oldPw, new_password: newPw }),
    roles:   ()            => get('/api/auth/roles'),
    users:   ()            => get('/api/auth/users'),
    // 开号。`password` 不传 ⇒ 后端生成一个并**只在这一次响应里**回给你看。
    createUser: (body)     => post('/api/auth/users', body),
    setActive:  (id, on)   => post(`/api/auth/users/${id}/active`, { active: on }),
    resetPw:    (id, pw)   => post(`/api/auth/users/${id}/password`,
      pw === undefined || pw === null ? {} : { password: pw }),
    // ★ scope_node 走**查询串**不走路径：节点号里带 `|`（`c006|3|301`），
    //   放进路径会被百分号编码成 `%7C`，而 FastAPI 那边解出来是 `c006%7C3%7C301`
    //   —— 不报错，只是一个永远匹配不上的节点（本仓踩过这一族）。
    addGrant:    (id, role, scope) => post(`/api/auth/users/${id}/grants`,
      { role_code: role, scope_node: scope }),
    dropGrant:   (id, role, scope) => del(`/api/auth/users/${id}/grants`
      + `?role_code=${encodeURIComponent(role)}&scope_node=${encodeURIComponent(scope)}`),
  },
  buildings:     ()      => get('/api/buildings'),
  building:      (n)     => get(`/api/buildings/${n}`),
  artifacts:     (n)     => get(`/api/buildings/${n}/artifacts`),
  floors:        (n)     => get(`/api/buildings/${n}/floors`),
  floor:         (n, f)  => get(`/api/buildings/${n}/floors/${f}`),
  rooms:         (n)     => getEnv(`/api/buildings/${n}/rooms`),
  spec:          (n)     => get(`/api/buildings/${n}/spec`),
  components:    ()      => get('/api/components'),
  selfcheck:     ()      => getEnv('/api/components/selfcheck'),
  areaFleet:     ()      => getEnv('/api/analysis/area'),
  areaOne:       (n)     => getEnv(`/api/analysis/area/${n}`),
  areaRefresh:   (n)     => post(`/api/analysis/area/refresh/${n}`),

  // 作业台（原 `_scratch/_portal.py` 的 8144 页面，2026-09-25 收编进管理台）
  // ★ 这两条 POST 是**写/执行**：非回环一律 403（除非设了 GYM3D_ADMIN_TOKEN 并带对头）。
  //   所以页面必须先问 capabilities.write_enabled 再决定按钮能不能点 ——
  //   「点了才发现不能用」和「一开始就写明」不是一回事。
  workshopStatus: ()       => get('/api/workshop/status'),
  workshopRefs:   ()       => get('/api/workshop/refs'),
  workshopJobs:   (limit = 10) => get(`/api/workshop/jobs?limit=${limit}`),
  workshopJob:    (id)     => get(`/api/workshop/jobs/${encodeURIComponent(id)}`),
  // 上传的请求体就是文件本身 ⇒ 走 postRaw，不能走 post（见 postRaw 的注释）。
  // ★ 这两条回的是**整个信封**（`post`/`postRaw` 的既定约定，先例 `views/area.js:480`
  //   就是按 `env` 收的）⇒ 调用处要取 `.data`。少了那一步**不报错**，只是每个字段
  //   恒 undefined，页面照画（实测：每张图都被说成「图纸」、作业号印成 undefined）。
  workshopUpload: (name, file) => postRaw(
    `/api/workshop/upload?name=${encodeURIComponent(name)}`, file),
  workshopRun:    (mode)   => post(`/api/workshop/run?mode=${encodeURIComponent(mode)}`),

  // 检查（引擎在 backend/checks/，这里只读它的产物 + 触发一次运行）
  // ★ 走 getEnv 而不是 get：这两条路由的 meta 是有内容的
  //   （产物的文件名/大小/层、注册表的来源），页面上要显示「这个结论是哪来的」。
  checksRegistry: ()     => getEnv('/api/checks/registry'),
  // 哪几栋有检查产物。给扫描用：先问清单，别对全库逐栋撞 404。
  checksManifest: ()     => getEnv('/api/checks/manifest'),
  // 全库级结论（引擎对整个库跑一次的那份）。★ 分母是全库，与单栋那条不同。
  checksFleet:    ()     => getEnv('/api/checks/fleet'),
  checks:         (n)    => getEnv(`/api/checks/${n}`),
  // 图谱（引擎在 kb/）
  // ★ 前三条走 getEnv：它们的 meta 是有内容的（子进程退出码/耗时/夹过的 top/
  //   复现用的 argv；激活那条是 counts 与两份机器层源的缺失情况），
  //   而 data 是 `kb/ask.py --json` **原样透传**的那一份 —— 逐字段相同由
  //   `python -m backend.checks.kg_view_accept --parity` 守着。
  // ★★ 2026-09-25 事实变了：`--run`（跑判据）**现在有 HTTP 口子了**。
  //   原先这里写着「写操作刻意没有 HTTP 口子，别顺手补一个 POST」——
  //   那个更强的保证（**没有通路**）已经**放弃**，换成**「通路 ＋ 本机限定」**：
  //   `POST /api/kg/run` 挂的是既有的那处判定（`deps.exec_denied_reason`），
  //   非回环来源一律 403 `local_only`（除非设了 GYM3D_ADMIN_TOKEN 且带对
  //   `X-Admin-Token`），GYM3D_COMPUTE=0 时 403 `compute_disabled`。
  //   ⇒ 页面必须**先问 `capabilities().write_enabled` 再决定按钮**，
  //     不行就把后端自己那句话原样显示出来，**不许"点了才发现 403"**。
  //   ⇒ 仍然**没有**通路的是另两条，别再照抄上面那句把它们也开了：
  //     `kb/ask.py --pending`（写 `kb/pending.json`）、`kb/build_kb.py`（重打包）。
  kg:             ()     => getEnv('/api/kg'),
  kgAsk:          (q, building = '', top = 3) =>
    getEnv(`/api/kg/ask?q=${encodeURIComponent(q)}`
      + `&building=${encodeURIComponent(building)}&top=${encodeURIComponent(top)}`),
  // 扩散激活那张图（节点/边/缺口）。**服务端算好**，页面只负责摆放 ——
  // 图上那层语义（机器码→症状的映射、没映射的那些 = 缺口）只有一份实现。
  kgActivation:   ()     => getEnv('/api/kg/activation'),
  // 真跑一次判据。**回的是作业，不是结果** —— 900 秒级的活不能挂在这一次请求上
  // （合并成一个进程之后，等它的是管着所有屏的那个事件循环）。
  // ★ 回的是**整个信封**（`post` 的既定约定）⇒ 调用处要取 `.data`：
  //   拿着整个信封去读 `job.id` 会恒 undefined，而**不报错**。
  kgRun:          (q, building = '', top = 3, timeoutS = '') =>
    post('/api/kg/run'
      + `?q=${encodeURIComponent(q)}`
      + `&building=${encodeURIComponent(building)}&top=${encodeURIComponent(top)}`
      + (timeoutS === '' || timeoutS === null || timeoutS === undefined
        ? '' : `&timeout_s=${encodeURIComponent(timeoutS)}`)),
  // 作业的当前状态 **＋ 它到底跑出了什么**（`data.run.outcome` 七档）。
  // ★ 走 `get` 不走 `getEnv`：这条路由没有 meta（后端 `ok(data)` 不带第二参），
  //   该说的全在 data 里。走哪一条是**看着路由写的**，不是顺手抄隔壁。
  kgRunStatus:    (id)   => get(`/api/kg/run/${encodeURIComponent(id)}`),
  // 影像比对（高德卫星 ↔ 本机照片；数据由 `_scratch/_compare/build_compare.py` 建）
  // ★ 走 `get` 不走 `getEnv`：这条路由是 `ok(out)`，**没有 meta** ——
  //   该说的（判据版本 / 建清单时间 / 瓦片占位块数）全在 data 里，刻意的。
  compareList:    ()     => get('/api/compare/list'),

  // 建模控制台（原 `backend/web/control.py` 的 8130 那一屏，2026-09-25 收编进管理台）
  // ★ 参数表**不在前端**：`consoleMeta` 下发的 profile/spec 两组字段定义就是真源
  //   （在 `backend/web/console_meta.py`）—— 加一个字段只改后端一处。
  // ★ 楼列表读 `floor_count`（**数字**），不是 `floors`：8140 的 `/api/buildings`
  //   里 `floors` 装的是**数组**，而原 `control.js:193` 把它当数字用（`b.floors + ' 层'`）。
  //   一个词两个意思，正是本轮要收的账。
  // ★ 取文件地址一律读 `links.*`（服务端按真实挂载算好的，没通路时是 `null` 并附
  //   一句 why），**别自己拼** —— 拼出来的必然 404 会让人以为文件丢了。
  consoleMeta:      ()      => getEnv('/api/console/meta'),
  consoleBuildings: ()      => getEnv('/api/console/buildings'),
  consoleStatus:    (n)     => get('/api/console/status/' + n),
  consoleProfile:   (n)     => get('/api/console/profile/' + n),
  consoleSpec:      (n)     => getEnv('/api/console/spec/' + n),
  // 作业的当前状态 **＋ 它的日志文本**。★ 走 getEnv：meta 里有 `log_path`
  //   （路径没丢，只是不在 `data.log` 上 —— 那里现在是日志**文本**）。
  consoleJobs:      (id)    => getEnv('/api/console/jobs/' + encodeURIComponent(id)),
  // 下面三条是**写/执行**：非回环来源一律 403 `local_only`（除非设了
  // GYM3D_ADMIN_TOKEN 且带对 `X-Admin-Token`），GYM3D_COMPUTE=0 时 403
  // `compute_disabled`。⇒ 按钮必须先问 `capabilities().write_enabled`，
  // 页面上**不许**再写一遍 `location.hostname` 判断（一个判断只许一份实现）。
  consolePutProfile: (n, obj) => put('/api/console/profile/' + n, obj),
  consolePutSpec:    (n, obj) => put('/api/console/spec/' + n, obj),
  // 跑一个阶段。★ 参数名是 **`step`**（不是 `stage`），`windows` 是**字符串**
  //   （后端自己按 1/true/yes/on 解析，给别的值回 400 —— 所以这里只能发 1 或 0）。
  // ★ 回一个**作业**，不是结果：900 秒级的活不能挂在这一次请求上。
  // ★ 回的是**整个信封** ⇒ 调用处要取 `.data`（少了那一步不报错，只是字段恒 undefined）。
  consoleRun: (n, step, windows) => post('/api/console/run'
    + `?building=${encodeURIComponent(n)}&step=${encodeURIComponent(step)}`
    + `&windows=${windows ? '1' : '0'}`),

  // 流程开关登记表（`config/branches.json` 那一份 —— 用户原话「写在后台、我后面能修改、
  // 能成图，不是写死再代码里面」的落地处，页面是 `views/branches.js`）。
  // ★ 走 getEnv：meta 是有内容的（文件路径 / sha12 / 字节 / 三档计数 / **哪四列是人写的** /
  //   哪十列是生成器现量的），页面上要显示"这一屏的数是哪来的"。
  // ★★ `consolePutBranch` 回**整个信封**（`put` 的既定约定，与上面两条 PUT 一致）
  //   ⇒ 调用处要取 `.data`（`written` / `changed` / `sha_after` / `backup` 都在那里）。
  // ★★★ 第三条参数 `sha12` 是**乐观锁**，不是可选的装饰：带上它，后端在"表在我读它
  //   之后被生成器重跑过"时回 **409 `branches_stale`**，而不是把我的改动盖到新表上。
  //   不带 ⇒ 这一层保护不存在，而屏幕上照样会写「已保存」。
  consoleBranches:  ()      => getEnv('/api/console/branches'),
  consolePutBranch: (key, obj, sha12) => put(
    '/api/console/branches/' + encodeURIComponent(key)
    + (sha12 ? '?expect_sha12=' + encodeURIComponent(sha12) : ''), obj),

  // heavy 是**查询参数**（FastAPI 的 bool query），不是请求体 —— 别塞进 body。
  checksRun:      (n, heavy = false) =>
    post(`/api/checks/${n}/run${heavy ? '?heavy=true' : ''}`),
  url: {
    cad:   (n, f) => `${BASE}/api/buildings/${n}/cad/floor${f}.png`,
    plan:  (n, f) => `${BASE}/api/buildings/${n}/plan/floor${f}.png`,
    model: (n)    => `${BASE}/api/buildings/${n}/model.glb`,
    dxf:   (n)    => `${BASE}/api/buildings/${n}/source.dxf`,
    // 控制台的取图口（现算，比别的接口慢）。★ 这两条**回的是文件本体，不是信封**
    //   ⇒ 不能走 get()；而且 404/503 都用**信封**形状回（`routers/console.py`），
    //   所以视图那边用 fetch 读 blob、失败时再去 json() 里捞服务端那句话 ——
    //   不能直接 <img src>：`<img>` 的 onerror 分不清 404 与 503，
    //   而这两者的补救办法相反（换一层 vs 装 ezdxf）。
    consoleFloorPng: (n, f) => `${BASE}/api/console/floor/${n}/${f}.png`,
    consoleFloorDxf: (n, f) => `${BASE}/api/console/floor/${n}/${f}.dxf`,
    // 作业台的资源出口。后两条是**给人看的文本页**（另开一个新标签），
    // 不走 fetch —— 它们回的是 text/plain，不是 JSON 信封。
    workshopRefimg:  (f)    => `${BASE}/api/workshop/refimg/${encodeURIComponent(f)}`,
    // 影像比对的两条出图口（**回文件本体，不是信封**）。
    // ★ 键只许来自清单（`compareList` 里那些），这里**不是**一个能塞路径的地方：
    //   服务端先拿键查清单、路径才出现。所以别给它拼别的字符串。
    // ★ 失败时**不能只判 onerror**：404（清单里没这个键）和 409（键对，但文件
    //   跟你建清单时不是同一份了）的补救办法相反，而 `<img>` 看不见这个区别
    //   —— 视图那边是"裂了就回头 fetch 一次把服务端那句话捞出来"。
    compareImg:      (k)    => `${BASE}/api/compare/img/${encodeURIComponent(k)}`,
    comparePhoto:    (k)    => `${BASE}/api/compare/photo/${encodeURIComponent(k)}`,
    workshopPreview: (n, f) => `${BASE}/api/workshop/preview/${n}/${encodeURIComponent(f)}`,
    workshopTask:    (f)    => `${BASE}/api/workshop/task/${encodeURIComponent(f)}`,
    workshopSu:      (f)    => `${BASE}/api/workshop/su/${encodeURIComponent(f)}`,
  },
};
