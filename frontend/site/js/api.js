// 前台唯一的后端入口 —— 只读。
//
// ★ 为什么这里**没有** post()：前台是呈现面，不该改变任何数据。
//   后台（frontend/admin/js/api.js）有 post，因为它要跑阶段、刷对账。
//   两边的差别不是"约定前台别调用写接口"，而是**前台根本没有那条路可走** ——
//   把声明换成实物（memory: verification-form-vs-semantics）：
//   要往前台加一个会写数据的按钮，就得先在这个文件里加 post，藏不住。
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
async function api(path, { signal } = {}) {
  let res;
  try {
    res = await fetch(BASE + path, { signal });
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

export const API = {
  health:    () => get('/api/health'),
  buildings: () => get('/api/buildings'),
  building:  (n) => get(`/api/buildings/${n}`),
  floors:    (n) => get(`/api/buildings/${n}/floors`),
  floor:     (n, f) => get(`/api/buildings/${n}/floors/${f}`),

  // 二进制：直接当 src/href 用，不进 fetch。
  url: {
    cad:   (n, f) => `${BASE}/api/buildings/${n}/cad/floor${f}.png`,
    plan:  (n, f) => `${BASE}/api/buildings/${n}/plan/floor${f}.png`,
    model: (n)    => `${BASE}/api/buildings/${n}/model.glb`,
  },
};

export { BASE };
