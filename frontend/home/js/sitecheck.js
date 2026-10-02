// 首页右屏第三模式：「实景校核」—— 把建好的模型贴到无人机正射影像上，看外形偏不偏。
//
// ── 这个文件里唯一一处「顺序就是正确性」────────────────────────
//
// 图是**两条**接口：一条回 JSON（「这栋能不能校核」），一条回 PNG（字节）。
// 页面必须**先取 JSON，再决定要不要设 `<img src>`**。
//
// ★ 反过来写（先挂 img、404 了在 onerror 里补救）会把「无锚点」画成一张破图 ——
//   而破图与「这块地上什么都没有」在屏幕上太像了。
//   `frontend/admin/js/views/compare.js` 的文件头记着同族的坑：
//   「404 与 409 在 onerror 下分不开」。这里是同一个形状第二次出现。
//
// ── 三态分开，不许合成一个「失败」──────────────────────────────
//
//   ok         有锚点、算出来了          下一步：看图
//   no_anchor  这栋没有落位锚点          下一步：**去补锚点**（页上给出文件路径）
//   failed     我们的管道坏了            下一步：**修服务端**（原样打印服务端那句话）
//
//   「没有锚点」与「取图失败」的下一步动作**相反**，所以不许都印成「暂时看不了」。

import { API, ApiError } from '/site/js/api.js';
import { el, mount, add, rich } from '/site/js/dom.js';

const N = (v, d = 0) => (v == null ? '—'
  : Number(v).toLocaleString('zh-CN', { minimumFractionDigits: d, maximumFractionDigits: d }));

// 半幅档位（米）。★ 与路由的 `Query(80.0, ge=10.0, le=400.0)` 对得上：
//   超出 10..400 后端会 422，而页面上会显示成「我的请求参数错了」——所以这里先卡住。
const HALVES = [40, 80, 160, 320];

let _man = null;          // 清单只取一次：它不带锚点数据，换楼不必重取
let _manErr = null;

export async function loadManifest() {
  if (_man || _manErr) return _man;
  try { _man = await API.siteManifest(); } catch (e) { _manErr = e; }
  return _man;
}

/**
 * 右屏那一格。`head` 是模式页签（由 home.js 造，好让它与左侧同一套 .h-tab）；
 * `onHalf` 换档时回调 → home.js 重绘整个右栏。
 */
export function sitePane({ name, half, onHalf, head }) {
  const cap = el('p', { class: 'h-cap', id: 'site-cap' });
  const host = el('div', { class: 'h-sheet site-sheet', id: 'site-host' });
  const bar = el('div', { class: 'h-bar' },
    el('span', { class: 'h-bar-k', text: '窗口' }),
    ...HALVES.map((h) => el('button', {
      class: 'h-tab h-half', type: 'button',
      dataset: { half: String(h) },
      'aria-pressed': h === half ? 'true' : 'false',
      title: `以锚点为中心，取 ±${h} m 的正射窗口`,
      onclick: () => onHalf(h),
    }, `±${h} m`)));
  const pane = el('section', { class: 'h-pane' }, head, bar, host, cap);
  loadSite(host, cap, name, half);
  return pane;
}

async function loadSite(host, cap, name, half) {
  mount(host, el('p', { class: 'loading', text: `正在取 ${name} 的正射窗口…` }));

  // ★ 清单**先取**（它决定底图那一行能不能印出来），但**不因为它失败就不出图**：
  //   它是页脚性质的一行说明，而正射裁切是主角。两个请求并行发。
  const manP = loadManifest();
  let d;
  try {
    d = await API.siteCheck(name, half);
  } catch (e) {
    await manP;
    return paintState(host, cap, name, half, e);
  }
  await manP;
  paintOk(host, cap, name, d, half);
}

// ── 三种状态 ──────────────────────────────────────────────────────
function paintState(host, cap, name, half, e) {
  const code = e instanceof ApiError ? e.code : null;
  const detail = e?.detail ?? {};
  const anchorsFile = detail.anchors_file ?? _man?.anchors_file ?? 'data/_meta/site_anchors.json';

  // ★ 这里**没有** `<img>` 元素 —— 不是「设了 src 但没加载出来」。
  //   判据 N1 就钉在这一句上：切到实景校核后 DOM 里连一个 img 都不该有。
  if (code === 'no_anchor' || detail.state === 'no_anchor') {
    mount(host,
      el('div', { class: 'site-miss' },
        el('b', { text: `无锚点：${name} 还没有落位锚点，外形校核做不了。` }),
        el('p', { text: '这不是「这一栋没问题」，是「这一栋还没量过」。' }),
        el('p', { class: 'dim' },
          '「楼号 → EPSG:4544 坐标」这一步是配准的第一道工序，'
          + '而它属于数字孪生侧的落位工作，不在本页这一侧。'),
        el('p', {}, el('span', { text: '锚点表：' }), el('code', { text: anchorsFile })),
        el('p', { class: 'dim' },
          '补上一行 {building, E, N, src} 之后本页立刻可用；'
          + 'src 必须写清谁给的 —— 手推的变换不许当锚点用。')));
    return mount(cap, el('span', { class: 'warn', text: `无锚点 · ${name}` }));
  }

  if (code === 'network') {
    mount(host, el('div', { class: 'site-miss' },
      el('b', { text: '连不上后端。' }),
      el('p', { text: '8140 上的 API 没在跑，或者地址不对 —— 与「这栋没有锚点」不是一回事。' })));
    return mount(cap, el('span', { class: 'warn', text: e.message }));
  }

  // 剩下的都是**我们的**管道坏了：485/500 一律原样打印服务端那句话。
  mount(host, el('div', { class: 'site-miss' },
    el('b', { text: '取图失败。' }),
    el('p', { text: '这是服务端这一侧的问题（有锚点但算不出来），不是这栋楼没有锚点。' }),
    el('p', { class: 'dim' }, el('span', { text: '服务端原话：' }), el('code', { text: e?.message ?? String(e) })),
    detail.reason ? el('p', { class: 'dim' }, el('span', { text: '原因档：' }), el('code', { text: detail.reason })) : null));
  mount(cap, el('span', { class: 'warn', text: `取图失败 · HTTP ${e?.status ?? '?'}` }));
}

function paintOk(host, cap, name, d, half) {
  const img = el('img', { class: 'site-img', alt: `${name} 锚点周围 ±${half} m 的正射影像与模型足迹` });
  const px = el('span', { text: '取图中…' });
  // 先挂 onerror 再设 src（缓存里的失败结果会让后挂的监听器一枪打空）——
  // 与 home.js paintSheet() 里那句同源，两次都是同一个原因。
  img.addEventListener('error', () => {
    mount(host, el('div', { class: 'site-miss' },
      el('b', { text: '图取不到。' }),
      el('p', { text: 'JSON 说算好了，但 PNG 这个地址取不回来 —— 这两句话矛盾，值得查。' }),
      el('code', { text: img.src })));
    mount(cap, el('span', { class: 'warn', text: '接口说好了、实际取不到' }));
  });
  img.addEventListener('load', () => {
    px.textContent = `${img.naturalWidth}×${img.naturalHeight} px`;
  });
  img.src = API.url.ortho(name, half);
  mount(host, img);

  const a = d.anchor ?? {};
  const fp = d.footprint ?? {};
  const m = d.metrics;

  // ★ `px` 必须当**子节点**挂进来，不许写成 `el('span', {text: px})` ——
  //   后者会把它 stringify 成 "[object HTMLSpanElement]" 印在屏幕上，
  //   而 `px.textContent = …` 那行照样跑、照样改一个**不在文档里**的节点。
  //   症状是「尺寸那格永远空着」，不是报错。（本趟冒烟抓到的第一处。）
  mount(cap,
    el('span', { text: `±${half} m` }), el('span', { class: 'b-sep', text: '·' }),
    el('span', { text: `${N(d.mpp, 3)} m/px` }), el('span', { class: 'b-sep', text: '·' }),
    px, el('span', { class: 'b-sep', text: '·' }),
    el('span', { text: `${N(d._ms, 0)} ms${d._cached ? '（进程内缓存）' : ''}` }),
    d.clipped ? el('span', { class: 'warn', text: '· 窗口被正射边界裁过' }) : null);

  add(host, el('div', { class: 'site-notes' },
    note('锚点出处', `${a.E ?? '—'}, ${a.N ?? '—'}（EPSG:4544 米）`
      + (a.rot_deg ? `，朝向 ${a.rot_deg}°` : '，未设朝向'),
      `谁给的：${a.src ?? '（未记）'}${a.by ? ` · ${a.by}` : ''}${a.ts ? ` · ${a.ts}` : ''}`),
    note('模型足迹', `${N(fp.n_pts)} 点 · ${N(fp.plan_area_m2, 1)} ㎡ · ${N(fp.w_m, 1)} × ${N(fp.d_m, 1)} m`,
      fp.caliber),
    m ? note('对不上多少', `面积比 ${N(m.ratio, 3)}`
      + `（模型 ${N(m.model.area_m2, 1)} ㎡ / 实测框 ${N(m.trace.area_m2, 1)} ㎡）`,
      m.why_no_iou) : null,
    ...reliefNotes(d.relief),
    note('这个数的口径', d.caveat, '★ 这一条必须显示：贴合的「假设」写在数据里，不写在文档里。')));

  paintSourceLine(host);
}

/** 外形（实景高程）那两格 —— 与后端 `relief()` 的 state 一一对应。
 *
 *  ★ 四种「量不了」**不许**合成一句「暂时看不了」（铁律 166）：
 *    `no_dsm` 盘上没有高程栅格 / `outside` 锚点落在栅格之外 /
 *    `no_blob` 窗内没有可量的地物 / `failed` 我们的管道坏了。
 *    前三个是「我不知道」，最后一个是「我坏了」—— 而**四个都不是**「这一栋外形没问题」。
 *    所以这里印的是**不适用**，不是「没有异常」：两者的下一步动作相反。
 *
 *  ★ 第二格是**独立算同一个量**的第二条路（铁律 182）：`fly_buildings.json` 里
 *    离锚点最近的那一块，它的地面/屋盖是**另一套口径**（分块 5 分位再平滑）算的。
 *    两边差多少**必须印出来** —— 只印我这一个数，就没人能发现我这把尺子坏了。
 */
function reliefNotes(r) {
  if (!r) return [];
  if (r.state !== 'ok') {
    const LABEL = {
      no_dsm: '没有高程栅格', outside: '锚点在高程栅格之外',
      no_blob: '窗内量不出地物', failed: '服务端算失败了',
    };
    return [note('外形（实景）', `不适用 · ${LABEL[r.state] ?? r.state}`,
      `${r.why ?? ''} —— 这不是「这一栋外形对得上」，是「这一栋没量过」。`)];
  }
  const c = r.cross ?? {};
  const vs = r.vs_model ?? {};
  const rows = [
    note('地面 / 屋盖', `${N(r.ground_m, 2)} m · ${N(r.roof_m, 2)} m ⇒ 高差 ${N(r.h_m, 2)} m`,
      `取法：地面 = 窗内 5 分位，屋盖 = 这栋那块连通体的 95 分位`
      + `（中位 ${N(r.roof_med_m, 2)} m，平屋盖占 ${N(r.flat * 100, 0)}%）`
      + `　★ 两个数取自**同一张栅格、同一套高程基准**，相减时基准抵消 ——`
      + `所以不必知道这张栅格存的是椭球高还是正常高`),
    note('实景外接', `${N(r.ext_e_m, 1)} × ${N(r.ext_n_m, 1)} m`
      + `（模型足迹 ${N(r.model?.w_m, 1)} × ${N(r.model?.d_m, 1)} m）`,
      `每侧多出 ΔE ${N(vs.over_e_m, 2)} m · ΔN ${N(vs.over_n_m, 2)} m —— `
      + `实景量的是**檐口**不是墙（DSM 记顶面）⇒ 这个差本身不是模型错，`
      + `真正的缺陷是**模型里缺这一圈檐**`),
  ];
  if (c.state === 'ok') {
    rows.push(note('第二条路 · 同一个量',
      `地面 ${N(c.gnd_z, 2)} m · 屋盖 ${N(c.roof_z, 2)} m ⇒ 高差 ${N(c.h_m, 2)} m`,
      `出处 ${c.source ?? ''} 最近一块（离锚点 ${N(c.at?.d_m, 1)} m）：${c.anchor_inside_note ?? ''}`
      + `　★ 两路地面差 **${N((r.ground_m ?? 0) - (c.gnd_z ?? 0), 2)} m** —— `
      + `口径不同（那边是分块 5 分位再平滑）；对不上时第一个嫌疑人是**我这把尺子**`));
  } else {
    rows.push(note('第二条路 · 同一个量', `不适用 · ${c.why ?? c.state ?? '没有'}`,
      '这一条不是「两路一致」，是「第二路没得比」—— 少了它，上面那几个数就没人复核。'));
  }
  return rows;
}

/** 一格「名字 / 值 / 小字」。值与小字都过 `rich()`：
 *  `caveat` 与 `why_no_iou` 是**服务端写好的串**，里面带 `**强调**` 记号，
 *  照原样印会把星号一起摆到屏幕上（第一版就是这样，见 dom.js 里 rich() 的注释）。 */
function note(k, v, sub) {
  return el('div', { class: 'site-note' },
    el('span', { class: 'site-note-k', text: k }),
    el('span', { class: 'site-note-v' }, rich(v)),
    sub ? el('span', { class: 'site-note-s' }, rich(sub)) : null);
}

/** 正射那一侧的家底（CRS / 分辨率 / 金字塔）—— 它为什么能当零配准的尺子。 */
function paintSourceLine(host) {
  if (!_man?.ortho) return;
  const o = _man.ortho;
  add(host, el('p', { class: 'site-src' },
    el('b', { text: '底图 ' }), el('code', { text: o.path }),
    el('span', { text: ` · EPSG:${o.epsg} · ${o.width}×${o.height} · ${N(o.res[0], 4)} m/px` }),
    el('span', { text: ` · 金字塔 [${(o.overviews || []).join(', ')}]` }),
    el('br'),
    el('span', { class: 'dim', text:
      '这张图本身就在 EPSG:4544 里，而图上的 1:500 轮廓（campus_outlines.json 的 341 条）'
      + '也是 4544 —— 二维这一层不需要配准。缺的只是每栋楼的锚点（谁在哪）。' })));
}
