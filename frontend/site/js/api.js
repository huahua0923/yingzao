// 前台唯一的后端入口。
//
// ★ 曾经这里写着「前台没有 post()，因为前台根本没有那条路可走」——
//   那是**刻意的**：让"往前台加一个会写数据的按钮"必须先改这个文件，藏不住
//   （memory: verification-form-vs-semantics）。
//   2026-10-02 **真加了** post()，因为首页对比台长出了「圈问题」这个动作 ——
//   用户要的就是「指出问题，然后看是不是通用问题」，而"指出"不落盘就永远聚合不了。
//   ⇒ 原来那句设计意图没有作废，它只是换了个地方站：**全站唯一的写口仍然是这一个**，
//     而且它只服务一条路（`_qa/annotations.json`）。假如下次有人要加第二个写动作，
//     他还是得先动这个文件 —— 闸门还在原地。
//   ⇒ 并且服务端那侧另有两道闸（`require_cap("manage")` + `ComputeDep`）：
//     这个 post 是"能写"的**必要条件**，不是充分条件。
//
// 后端回统一信封 {success,data,error,meta}；下面的 api() 是**唯一**拆信封的地方。
// 不照着后台那份直接 import：两个页面是**分开部署的两个根**（生产期 nginx 里
// / 指前台、/admin 指后台），前台跨目录 import 后台的文件会让部署变成一个整体。

const BASE = (window.GYM3D_API_BASE ?? '').replace(/\/$/, '');

export class ApiError extends Error {
  constructor(code, message, detail, status) {
    super(message);
    this.code = code; this.detail = detail; this.status = status;
  }
}

/** 拆信封。**只有这一处**认识 {success,data,error,meta} 这个形状。 */
async function api(path, { signal, method = 'GET', body } = {}) {
  let res;
  const init = { signal, method };
  if (body !== undefined) {
    // ★ Content-Type 必须写全 `application/json`：后端是按**媒体类型**挑解析器的，
    //   `text/plain` 会让 body 原样进到参数里变成字符串而不是对象 ——
    //   而 FastAPI 那时回的是 422，屏幕上像"我的字段名写错了"。
    init.headers = { 'Content-Type': 'application/json' };
    init.body = JSON.stringify(body);
  }
  try {
    res = await fetch(BASE + path, init);
  } catch (e) {
    // 网络层失败与业务错误必须分开说：后端没起时把它显示成
    // 「这栋楼不存在」是本仓栽过的那类错（量不到 ≠ 是零）。
    throw new ApiError('network', `连不上后端：${e.message}`, null, 0);
  }
  let env = null;
  try {
    env = await res.json();
  } catch {
    throw new ApiError('bad_response', `后端回了非 JSON（HTTP ${res.status}）`,
      { path }, res.status);
  }
  if (!env || env.success !== true) {
    const err = env?.error ?? {};
    throw new ApiError(err.code ?? 'unknown', err.message ?? `HTTP ${res.status}`,
      err.detail, res.status);
  }
  return env;
}

/** 只要 data（大多数调用只关心它）。 */
export async function get(path, opts) { return (await api(path, opts)).data; }

/** 要看 meta 的地方走这条（例如"这份数据是什么时候生成的"）。 */
export async function getEnv(path, opts) { return api(path, opts); }

/**
 * 写。**全站唯一的写口**（见文件头）。
 *
 * ★ 刻意**只收一个** `body` 对象、且**固定 POST** —— 不做成 `post(path, body)`
 *   之外的通用 `request(method)`：那样"哪个动作会写"就又变成读代码才知道的事了。
 */
export async function post(path, body, opts) {
  return (await api(path, { ...opts, method: 'POST', body })).data;
}

export const API = {
  health:    () => get('/api/health'),
  buildings: () => get('/api/buildings'),
  building:  (n) => get(`/api/buildings/${n}`),
  floors:    (n) => get(`/api/buildings/${n}/floors`),
  floor:     (n, f) => get(`/api/buildings/${n}/floors/${f}`),

  // ── 外业校核（2026-10-02）────────────────────────────────────
  /** 「这栋能不能校核」的三态**在那个 JSON 里**，不在图上 —— 先取它，再决定要不要设 src。 */
  siteCheck:  (n, half, px) => get(`/api/site/${n}/check?half=${half}${px ? `&px=${px}` : ''}`),
  siteManifest: () => get('/api/site/manifest'),
  /** 全库「模型竖向自洽」稽核 —— **一次回全库**（92 栋），服务端按目录 mtime 缓存。
   *  ★ 它是只读的：不写盘、不挂执行面闸 ⇒ 只读服务器上也看得了。 */
  shapeAudit: () => get('/api/site/shape-audit'),

  annotations: (n, f) => get(`/api/annotations?building=${encodeURIComponent(n)}`
    + (f == null || f === '' ? '' : `&f=${encodeURIComponent(f)}`)),
  annSummary:  () => get('/api/annotations/summary'),
  annAdd:      (rec) => post('/api/annotations', rec),

  // 二进制：直接当 src/href 用，不进 fetch。
  url: {
    cad:   (n, f) => `${BASE}/api/buildings/${n}/cad/floor${f}.png`,
    plan:  (n, f) => `${BASE}/api/buildings/${n}/plan/floor${f}.png`,
    model: (n)    => `${BASE}/api/buildings/${n}/model.glb`,
    ortho: (n, half) => `${BASE}/api/site/${n}/ortho.png?half=${half}`,
  },
};

export { BASE };
