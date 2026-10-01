// 后端唯一的入口 —— 门户里所有 fetch 都从这里走。
//
// ★ 为什么不直接 `import` 旧后台那份 `frontend/admin/js/api.js`：
//   那一份是**旧后台的地址表**（290 行，登记着 console/workshop/kg/checks … 那些
//   建模流水线的口子），门户一条都不用。照抄它等于把一整套不相干的路由表
//   搬进来 —— 而那张表一旦被人"顺手补一条"，就会变成一个没人守的接口清单。
//   **两个前端两个地址表**：各自只登记自己真正调的那几条。
//
// 为什么集中一处：后端回统一信封 `{success,data,error,meta}`，下面 api() 是
// **唯一**拆信封的地方。散着写十几个 fetch 就必然有人忘了看 success，
// 于是错误被当数据渲染出去。

const BASE = (window.GYM3D_API_BASE ?? '').replace(/\/$/, '');

export class ApiError extends Error {
  constructor(code, message, detail, status) {
    super(message);
    this.code = code; this.detail = detail; this.status = status;
  }
}

// ★ 会话掉了要把人送回登录屏 —— 由 app.js 注册回调，api.js 负责喊。
//   放在这里而不是让每处调用自己判 401：调用点会越加越多，**漏一个就是一处
//   静默失败** —— 那块界面会把"会话过期"渲染成"这栋楼的数据读不到"，
//   补救办法完全相反（重新登录 vs 去查后端）。
//
// ★ 只在 **401** 上喊，不在 403 上喊：403 是"登录了、但没这个权限"，
//   把人踢回登录屏只会让他反复登进同一个进不去的地方。
let _onUnauth = null;
/** 注册"会话失效"回调。后注册的覆盖先注册的（只有一个外壳，够用）。 */
export function onUnauthenticated(fn) { _onUnauth = fn; }

async function api(path, { method = 'GET', body, signal } = {}) {
  let res;
  try {
    res = await fetch(BASE + path, {
      method,
      signal,
      // ★ credentials 显式写死：fetch 的**规范默认**就是 'same-origin'，
      //   但写出来这条规则才在源码里看得见。门户与后端同源（同一台机、同一个口），
      //   所以这一句就是全部所需；哪天真搬到另一个源，它会**当场**变成
      //   "登录成功但每个接口都 401" 而不报任何错 —— 那时这一行就是线索。
      credentials: 'same-origin',
      headers: body ? { 'content-type': 'application/json' } : undefined,
      body: body ? JSON.stringify(body) : undefined,
    });
  } catch (e) {
    // 网络层失败（后端没起 / 端口不对）必须与业务错误分开说，
    // 否则「后端没启动」会被显示成「这栋楼不存在」。
    throw new ApiError('network', `连不上后端（${BASE || '同源'}）：${e.message}`, null, 0);
  }

  let env;
  try {
    env = await res.json();
  } catch {
    throw new ApiError('bad_response', `后端回了非 JSON（HTTP ${res.status}）`, { path }, res.status);
  }
  if (!env || env.success !== true) {
    const err = env?.error ?? {};
    // ★ 两处**必须**排除，否则会制造更坏的体验：
    //   · `/api/auth/login` —— 口令打错时后端回的就是 401，若在这里喊，
    //     正在显示的那张登录表会被自己的回调拆掉重建，输一半的口令没了；
    //   · `/api/auth/session` —— 它按约定回 200 + `logged_in:false`，不是 401。
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

/** 取**没有信封**的裸 JSON（产物本体）。失败也要能分辨"没登录"与"文件不在"。 */
async function rawJson(path) {
  let res;
  try {
    res = await fetch(BASE + path, { credentials: 'same-origin' });
  } catch (e) {
    throw new ApiError('network', `连不上后端（${BASE || '同源'}）：${e.message}`, null, 0);
  }
  if (!res.ok) {
    // ★ 401 时同样要喊会话失效 —— 这条通路绕开了 api()，不喊就成一处分身失效的缺口。
    if (res.status === 401 && _onUnauth) { try { _onUnauth({}); } catch { /* 见 api() */ } }
    // 产物路由的 404 是**信封**（`not_found(...)`），能捞出服务端那句话；
    // 捞不到就退回一句带状态码的 —— 两者都要有 detail，不能只剩"读不到"。
    let detail = null;
    try { detail = (await res.json())?.error ?? null; } catch { /* 不是信封 */ }
    throw new ApiError(detail?.code ?? 'raw_failed',
                       detail?.message ?? `产物读不到（HTTP ${res.status}）`,
                       detail?.detail ?? { path }, res.status);
  }
  try { return await res.json(); } catch {
    throw new ApiError('bad_response', `产物不是 JSON（HTTP ${res.status}）`, { path }, res.status);
  }
}

export const post  = (path, body) => api(path, { method: 'POST', body });
export const del   = (path)       => api(path, { method: 'DELETE' });

/** 会话失效回调里要用的"我是不是被踢了"判据。 */
export function isAuthError(e) { return e instanceof ApiError && e.status === 401; }
/** "读到了但后端坏了"与"这条记录不存在"必须分开：前者该重试，后者该换一栋。 */
export function isMissing(e)   { return e instanceof ApiError && e.status === 404; }

export const API = {
  // ── 会话（`routers/auth.py`）───────────────────────────────────────
  // ★ session() 走 get 不走别的：这条路由回 `ok(data)`、**不带 meta**，
  //   而且它**刻意不回 401** —— 没登录是它的正常输出（`logged_in:false`）。
  session: () => get('/api/auth/session'),
  login:   (u, p) => post('/api/auth/login', { username: u, password: p }),
  logout:  () => post('/api/auth/logout'),
  roles:   () => get('/api/auth/roles'),
  // ★ 这一条要 `manage`（搭建方）。后端一个请求把账号与角色一起给 ——
  //   分成两个就会有两份可能不一致的快照，而这一屏恰恰是讲"谁有什么"的。
  users:   () => get('/api/auth/users'),

  // ── 门户数据面（`routers/portal.py`）──────────────────────────────
  // ★★ 这五条的每一张脸都是**两种数据混在一起**，页面上必须分开画：
  //     · 实测（real）—— 来自盘上的名册与房间表
  //     · 模拟（mock）—— 本轮为演示各模块画的样例块与样例台账
  //   混在一张表里、只靠颜色区分，读的人迟早把样例数当实测数报上去。
  overview: ()      => get('/api/portal/overview'),
  anchors:  ()      => get('/api/portal/anchors'),
  roster:   (q)     => get('/api/portal/roster' + (q ? `?q=${encodeURIComponent(q)}` : '')),
  // 建/改锚点。**能力闸是 manage**（搭建方）——不是"登录了就行"。
  setAnchor:    (body)   => post('/api/portal/anchors', body),
  dropAnchor:   (block)  => del(`/api/portal/anchors/${encodeURIComponent(block)}`),

  // ── 校区底图与地形（`routers/campus.py`）──────────────────────────
  // ★★ 这一组**不走 api()** —— 它们后端是 `FileResponse`，回的是**产物本身**
  //    （数据层 JSON 的原始字节），**没有信封**。走 api() 会在 HTTP 200 上抛
  //    `success !== true`，而那句话会被读成"数据层坏了"（其实是我拆错了壳）。
  //    路由这么写是有意的：信封会重新序列化，浮点写法变了，
  //    发出去的就不再是盘上那一份，而与地形对齐的坐标被重新表达一次
  //    就等于换了个基准（`campus.py:129-132`）。
  viewData:  () => rawJson('/api/campus/viewdata'),
  // 纵览驾驶舱的底图：`campus_ortho.json` 是那张正射的**侧车**（来源指纹、帧、
  // m/px、以及"图的左上角朝西北"这条凭据）。它与 `viewData()` 的帧**必须一致** ——
  // 那道核对在 `ortho-base.js` 里，每次打开都重比一遍。
  orthoSidecar: () => rawJson('/api/campus/ortho.json'),
  // 体块层：213 个 LOD1 体块，`poly_en` 是**绝对** EPSG:4544 ⇒ 前端能直接建面。
  // ★★ 实测结论（2026-10-01）：这一层**不是建筑轮廓** —— 中位底面积 131 m²、
  //    中位高 4.2 m，最小的一批压在马路/绿化带/转盘/工地上。纵览驾驶舱一度拿它
  //    当轮廓画，而屏幕上的判词写着"轮廓压在楼上"。**别再拿它当楼。**
  //    留着这一条只是因为它的**高度**那一半是真的，将来可能还有用处。
  lod1:      () => rawJson('/api/campus/lod1.json'),
  // ★★ 建筑轮廓（341 条真楼轮廓）：`poly_en` 是**绝对** EPSG:4544，逐条带实测
  //    底面积 / 屋顶高 / 高度口径 / 地面中位高程 / 是否落在 NoData 洞上。
  //    与 `realBuildings()`（viewdata，341 条只有 `ring` 没有坐标）**按 ring 号一一对应**，
  //    是同一批楼的两份视图：那份有数、这份有坐标。
  //    ★ 覆盖是**局部**的（渠东那一片）—— 图外的大房子在这一份里没有轮廓。
  outlines:  () => rawJson('/api/campus/outlines.json'),
  // ★ 真正的建筑层（341 块，实测轮廓 × 实测屋顶高）。本轮**没有**用它 ——
  //   用户明令"先不用忙着把建筑放上去，先模拟几个块儿"。留这条地址在这儿，
  //   是为了下次要用时不用重新翻 `routers/campus.py` 找口子。
  //   要切过去时注意：它那份 viewdata 的 `grid` 与地形**同源**，别另算 e0/n1。
  realBuildings: () => rawJson('/api/campus/buildings.json'),

  // ── 楼栋与房间（`routers/buildings.py` / `rooms.py`）──────────────
  // ★ 这两条后端**逐行按范围过滤**：一个只管 c006 的账号在这里只会看到 c006。
  //   页面上不要自己再过滤一遍 —— 两份过滤会漂，而漂了不报错。
  buildings: ()   => get('/api/buildings'),
  floors:    (n)  => get('/api/buildings/' + encodeURIComponent(n) + '/floors'),
  rooms:     (n)  => get('/api/buildings/' + encodeURIComponent(n) + '/rooms'),

  // ── 文件本体（**不是信封**，不能走 get()）─────────────────────────
  url: {
    // 地形 + 正射底图烘在一起的 GLB。前端直接喂给 GLTFLoader。
    campusModel: () => `${BASE}/api/campus/model.glb`,
    // 纵览驾驶舱的正射底图。**它就是三维场景材质里那张**（从 GLB 里原样取出来的），
    // 所以二维与三维不会各偏一点。直接喂给 `new Image()` / 画布，不走 fetch。
    campusOrtho: () => `${BASE}/api/campus/ortho.jpg`,
  },
};
