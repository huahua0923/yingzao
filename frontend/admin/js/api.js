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

async function api(path, { method = 'GET', body, signal } = {}) {
  let res;
  try {
    res = await fetch(BASE + path, {
      method,
      signal,
      headers: body ? { 'content-type': 'application/json' } : undefined,
      body: body ? JSON.stringify(body) : undefined,
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

export const API = {
  health:        ()      => get('/api/health'),
  capabilities:  ()      => get('/api/capabilities'),
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
  agents:        ()      => getEnv('/api/agents'),
  agentRun:      (id, n) => post(`/api/agents/${id}/run/${n}`),

  // 检查（引擎在 backend/checks/，这里只读它的产物 + 触发一次运行）
  // ★ 走 getEnv 而不是 get：这两条路由的 meta 是有内容的
  //   （产物的文件名/大小/层、注册表的来源），页面上要显示"这个结论是哪来的"。
  checksRegistry: ()     => getEnv('/api/checks/registry'),
  // 哪几栋有检查产物。给扫描用：先问清单，别对全库逐栋撞 404。
  checksManifest: ()     => getEnv('/api/checks/manifest'),
  // 全库级结论（引擎对整个库跑一次的那份）。★ 分母是全库，与单栋那条不同。
  checksFleet:    ()     => getEnv('/api/checks/fleet'),
  checks:         (n)    => getEnv(`/api/checks/${n}`),
  // 图谱（引擎在 kb/，HTTP 只有这两条只读 GET）
  // ★ 走 getEnv：这两条的 meta 是有内容的（子进程退出码/耗时/夹过的 top/复现用的 argv），
  //   而 data 是 `kb/ask.py --json` **原样透传**的那一份 —— 逐字段相同由
  //   `python -m backend.checks.kg_view_accept --parity` 守着。
  // ★ 写操作（`--run` 跑判据、`--pending` 登记）刻意**没有** HTTP 口子，
  //   所以这里也只有两条读。别顺手补一个 POST。
  kg:             ()     => getEnv('/api/kg'),
  kgAsk:          (q, building = '', top = 3) =>
    getEnv(`/api/kg/ask?q=${encodeURIComponent(q)}`
      + `&building=${encodeURIComponent(building)}&top=${encodeURIComponent(top)}`),
  // heavy 是**查询参数**（FastAPI 的 bool query），不是请求体 —— 别塞进 body。
  checksRun:      (n, heavy = false) =>
    post(`/api/checks/${n}/run${heavy ? '?heavy=true' : ''}`),
  url: {
    cad:   (n, f) => `${BASE}/api/buildings/${n}/cad/floor${f}.png`,
    plan:  (n, f) => `${BASE}/api/buildings/${n}/plan/floor${f}.png`,
    model: (n)    => `${BASE}/api/buildings/${n}/model.glb`,
    dxf:   (n)    => `${BASE}/api/buildings/${n}/source.dxf`,
  },
};
