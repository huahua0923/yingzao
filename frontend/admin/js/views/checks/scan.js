// 全库扫描：先问清单"哪几栋有产物"，只对那几栋取一次，然后**按检查编号数一遍**。
// （清单取自 GET /api/checks/manifest；取不到就退化成逐栋去问，见 listBuildings。）
//
// ★ 前端在这里做的**只是数**：每条判据在几栋上是什么状态。
//   一个判据都不算 —— 每一格的状态都是引擎写在产物里的原文
//   （用户明令：不许在前端自己算判据）。所以这里读的是
//   `GET /api/checks/{楼}` 回的 report.findings[].status。
//
// ★★ 三种结局必须分开记，绝不许合并成一个「没问题」：
//     有产物   —— 取到了产物，能数
//     无产物   —— 后端回 404 check_artifact_missing（这栋还没跑过检查）
//     没扫成   —— 网络断了 / 后端 500 / 别的错误（**这一栋根本不知道**）
//   合并的后果正是本项目反复栽的那条：没见过的东西显示成绿的
//   （memory: gauge-coverage-invisible-in-summary）。
//
// ★★ 以及单位宁可写啰嗦也不能错：同一个编号下，**一栋可能贡献好几条**
//   （A2/A3/B3 是逐层出结论，11 层的楼就有 11 条）。所以每格分开记
//     栋数（去重后的楼）  条数（findings 的条数）  层数（floor 非空的条数）
//   引擎自己就栽过"拿条数当层数"（backend/checks/__init__.py 里那段注释），
//   屏幕上光写「×48」会被读成 48 栋 —— 量具报了个对不上单位的数，比不报还坏。
//
// ★ 用「检查编号」当键，而不是「标题」：标题会改，编号是注册表里的主键。
import { API, ApiError } from '../../api.js';

/**
 * 楼栋清单，每行带 `hasCheck`：
 *   true / false —— 后端清单说这栋有 / 没有检查产物
 *   null         —— **不知道**（清单没取到），调用方照旧逐栋去问
 *
 * ★ 为什么要多问一次清单：95 栋里只有 7 栋有产物，逐栋去撞会往 console 里
 *   灌 88 条 404 红字。红字不是"错"，但满屏红字会训练人忽略真错误。
 * ★ 清单取不到时**不许当成"都没有"** —— 那会把 7 栋有产物的楼画成"未跑"，
 *   也就是把"没量到"说成"量过了、没有"。所以这里是 null，不是 false
 *   （memory: gauge-coverage-invisible-in-summary）。
 */
export async function listBuildings() {
  const [rows, have] = await Promise.all([
    API.buildings(),
    // 清单失败**不抛**：它是加速用的，不是数据本身。取不到就退化成逐栋问。
    API.checksManifest().then((env) => {
      const list = env?.data?.buildings;
      return Array.isArray(list) ? new Set(list) : null;
    }).catch(() => null),
  ]);
  return (Array.isArray(rows) ? rows : []).map((r) => ({
    name: r.name,
    title: r.title || r.name,
    floorCount: r.floor_count ?? (Array.isArray(r.floors) ? r.floors.length : null),
    hasCheck: have ? have.has(r.name) : null,
  }));
}

/** 取一栋楼，把「无产物」与「真出错」分成两个不同的返回值。 */
async function fetchOne(name) {
  try {
    const env = await API.checks(name);
    return { ok: true, name, data: env.data, meta: env.meta };
  } catch (e) {
    if (e instanceof ApiError && e.code === 'check_artifact_missing') {
      return { ok: false, kind: 'no_artifact', name, error: e };
    }
    if (e instanceof ApiError && (e.code === 'network' || e.status === 0)) {
      throw e;   // 接口整体不可用：停下整轮，别把 95 栋都标成「没扫成」
    }
    return { ok: false, kind: 'error', name, error: e };
  }
}

const emptyCell = () => ({ who: new Set(), findings: 0, floors: 0 });

/**
 * 扫全库。
 * @param {Array<{name:string}>} buildings
 * @param {{concurrency?:number, onProgress?:Function, signal?:AbortSignal}} [opts]
 */
export async function scanFleet(buildings, opts = {}) {
  const concurrency = opts.concurrency ?? 6;
  const total = buildings.length;
  const perCheck = new Map();   // 编号 → {id, by:{状态:cell}, reasons:[{text, who:Set, by:{}}}]
  const scanned = new Map();    // 楼 → {name, kind, verdict, counts, nFindings, state, meta, floors}
  let done = 0;

  const touch = (cid) => {
    if (!perCheck.has(cid)) perCheck.set(cid, { id: cid, by: {}, reasons: [] });
    return perCheck.get(cid);
  };

  const index = (name, res) => {
    const report = res.data?.report || {};
    const findings = Array.isArray(report.findings) ? report.findings : [];
    scanned.set(name, {
      name,
      kind: 'has_artifact',
      verdict: report.verdict,
      counts: report.counts || {},
      nFindings: findings.length,
      state: res.data?.state,
      meta: res.meta,
      floors: [...new Set(findings.map((f) => f.floor).filter((f) => f !== null))]
        .sort((a, b) => a - b),
    });
    for (const f of findings) {
      const e = touch(f.check);
      const cell = (e.by[f.status] = e.by[f.status] || emptyCell());
      cell.who.add(name);
      cell.findings += 1;
      if (f.floor !== null && f.floor !== undefined) cell.floors += 1;
      // 「原因」按引擎给的 detail 原文归并 —— 墙上一个格子要能看出**是什么形状**，
      // 光有「×45 栋」看不出红在哪。这里只做字符串相等归并，不做任何推断。
      const key = f.detail || f.blocked_by || f.title || '';
      let r = e.reasons.find((x) => x.text === key);
      if (!r) { r = { text: key, who: new Set(), by: {} }; e.reasons.push(r); }
      r.who.add(name);
      r.by[f.status] = (r.by[f.status] || 0) + 1;
    }
  };

  const queue = buildings.slice();
  // ★ 清单已经说"没有产物"的，**不再发请求**：结论一样，但少 88 条 404 红字。
  //   注意只跳 hasCheck === false 的那些；=== null（清单没取到）照旧去问。
  const known = [];
  const toAsk = [];
  for (const b of queue) (b.hasCheck === false ? known : toAsk).push(b);
  for (const b of known) {
    // 与 fetchOne 的 no_artifact 记**同一种 kind**，只是来源不同 —— 下游数格子
    // 只认 kind，不该因为"少发了一次请求"就把这栋楼从分母里弄丢。
    scanned.set(b.name, { name: b.name, kind: 'no_artifact', fromManifest: true });
  }
  const ask = toAsk.slice();
  const totalAsk = ask.length;

  let stopped = null;
  const worker = async () => {
    while (ask.length && !stopped) {
      if (opts.signal?.aborted) return;
      const b = ask.shift();
      try {
        const res = await fetchOne(b.name);
        if (res.ok) index(b.name, res);
        else scanned.set(b.name, { name: b.name, kind: res.kind, error: res.error });
      } catch (e) {
        stopped = e;      // 接口不可用：让调用方去报错，不在这层假装扫过
        return;
      }
      done += 1;
      // 进度按**真的发出去的请求数**报，不按楼栋总数 —— 否则 7 次请求的活儿
      // 会显示成"7/95"永远不到头，看着像卡住了。
      opts.onProgress?.({ done, total: totalAsk, name: b.name });
    }
  };

  await Promise.all(Array.from({ length: Math.max(1, Math.min(concurrency, totalAsk || 1)) }, worker));
  if (stopped) throw stopped;
  if (opts.signal?.aborted) return null;

  const kinds = { has_artifact: 0, no_artifact: 0, error: 0 };
  for (const row of scanned.values()) kinds[row.kind] += 1;

  return {
    perCheck,
    scanned,
    order: [...perCheck.keys()],
    totals: {
      buildings: total,
      ...kinds,
      // 其中几栋是"清单说没有"、几栋是"问了才知道没有" —— 两个都是"没有产物"，
      // 但来源不同，报出来才分得清是"真问过"还是"清单跳过的"。
      no_artifact_by_manifest: known.length,
      probed: totalAsk,
      findings: [...scanned.values()].reduce((a, r) => a + (r.nFindings || 0), 0),
    },
    scannedAt: new Date(),
  };
}
