// 数字孪生数据大屏 —— 用户 2026-10-01：「你还有一个数据大屏，数字孪生数据大屏，
// 你继续做吧」，以及紧接着的一句口径：**「点击大屏，所有的房屋都在上面显示」**。
//
// ★★ 这一屏与其他模块的分工，用一句话说清：
//     · 纵览驾驶舱 —— 单张图 + 侧栏事实，**用来查**：一条条看、点开看坐标。
//     · 数据大屏（本页）—— **全校区一张图上挂满仪器**，**用来看**：
//       一屏之内把"手上有多少、有多少是敢当楼用的、这份数据的边界在哪"同时说完。
//   所以它不是驾驶舱的放大版：驾驶舱的侧栏是"这一条"的事实，本页是**全局**。
//
// ★★ 为什么中间那根柱子是**竖的**（三栏：仪器 / 图 / 仪器）：
//   底图是 1392 × 1644 m 的**竖幅**（比例 0.85:1）。横过来铺满一条横带的话，
//   `fit` 之后图只占那一带宽度的一小半，两边全是空底 —— 大屏上正中一块空场。
//   竖着放，图能把中央那根柱子填到九成；两块仪器也正好有地方站。
//
// ★ 本页所有条数都是**这一趟从 `base.blocks` 现算的**，一个都不许手打。
//   手打的那个数只在数据长到 N+1 那一刻才第一次出声，而那一刻它看起来像
//   "被测对象坏了"（铁律 174：`assert len(names) == 6` 就是那么栽的）。
//   ⇒ 所以本页**不引用** cockpit.js 里那张 `CALIBER` 长文案 —— 那三句里写着
//     "（231 条）"（当时手打的），引过来就会与这里现算的数并排出现两个来源。
//     本页用自己的短标签（不带条数），条数一律现算。
//
// ★★ 三条口径仍必须印在屏幕上（缺一条，这一屏就会把人引到错的地方去）：
//     ① 这份轮廓**只覆盖渠东那一片**（1:500 图上描的）—— 图上没有线 ≠ 那里没有房子；
//     ② 341 条里只有 **247 条**带真楼高，另 94 条的"高"是**地高不是楼高**；
//     ③ 那 94 条里有一部分**整条被另一条轮廓包住** —— 它是内院/空腔，
//        连"独立的这一栋"都不是。③ 在本页现算（见 cavities()），①② 由 facts 给出。
//
// ★★ 2026-10-01 用户口径：「现在每个页面有很多解释，这些没有啥用吧，只要功能」
//   ⇒ 本轮删掉的是**散文与出处**，不是口径：整张「凭据」卡（sha256 / 版本 /
//     容差阈值）、页脚「图源」那一格、以及各处解释性 `note()` 全删；
//     ①②③ 这三条**读数与它的边界声明**留着（它们防的是误读，不是装饰）。
//     口径标签同步压短（见 CAL_SHORT）—— 判据里不许再依赖长标签文案。

import { API } from './api.js';
import { el, fill, note, rich, int, num } from './dom.js';
import { loadOrthoBase } from './ortho-base.js';
import { createOrthoMap, CALIBER_STYLE } from './ortho-map.js';
import { kvList } from './cockpit.js';

// 三档口径的**短标签**（不带条数 —— 见文件头）。长文案在 cockpit.js 的 CALIBER。
// ★ 用户 2026-10-01：「现在每个页面有很多解释，这些没有啥用吧，只要功能」
//   ⇒ 口径标签压到最短（原先那三句是解释，不是读数）。判据里不许再依赖长标签文案。
const CAL_SHORT = {
  roof_p50:        '屋顶高',
  fallback_roof:   '有效楼高',
  fallback_ground: '地高（不是楼高）',
};
const CAL_ORDER = ['roof_p50', 'fallback_roof', 'fallback_ground'];

// 上一份的计时器与画布。★ 与 cockpit.js 同一个理由：`ResizeObserver` 只被这个
// 对象持有，丢掉返回值它就可能被回收，而画布会**停止跟随窗口大小**且不报错。
let dsTimer = 0;
let liveMap = null;

// ────────────────────────────────────────────── 几何：谁被谁包住

/** 多边形的包围盒（图像像素系，`xy` 是 `Float64Array`）。 */
function bboxOf(b) {
  const p = b.xy;
  let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
  for (let i = 0; i < p.length; i += 2) {
    if (p[i] < x0) x0 = p[i];
    if (p[i] > x1) x1 = p[i];
    if (p[i + 1] < y0) y0 = p[i + 1];
    if (p[i + 1] > y1) y1 = p[i + 1];
  }
  return [x0, y0, x1, y1];
}

/** 射线法：点在多边形内？**图像像素**坐标里做，与画出来的东西同一套坐标。 */
function inPoly(p, x, y) {
  let inside = false;
  const m = p.length / 2;
  for (let i = 0, j = m - 1; i < m; j = i++) {
    const xi = p[i * 2], yi = p[i * 2 + 1], xj = p[j * 2], yj = p[j * 2 + 1];
    if ((yi > y) !== (yj > y) && x < ((xj - xi) * (y - yi)) / (yj - yi) + xi) inside = !inside;
  }
  return inside;
}

/**
 * 找出**整条被另一条包住**的轮廓（内院 / 空腔）。
 *
 * ★ 判据是"这一条的**每一个顶点**都在那一条里面"。对简单多边形这等价于
 *   "整条被包住" —— 用顶点而不是用形心，是因为凹多边形的形心可能落在**自己外面**，
 *   那时形心判据会把一条明明没被包住的环判成被包住：它不是漏修，它是**静默地
 *   把一个数字改小**，而那个数长得像个正常读数（铁律 149：取错列在聚合里是隐形的）。
 *
 * ★ 宿主必须是**严格更大**的（面积相同则按索引定序）—— 否则两条重合的轮廓会
 *   互相当宿主，屏幕上就会冒出"20 条空腔变 21 条"这种没人能解释的漂移。
 */
function cavities(blocks) {
  const bb = blocks.map(bboxOf);
  const out = [];
  for (let i = 0; i < blocks.length; i++) {
    const a = blocks[i], A = Number.isFinite(a.area_m2) ? a.area_m2 : 0;
    for (let j = 0; j < blocks.length; j++) {
      if (i === j) continue;
      const B = Number.isFinite(blocks[j].area_m2) ? blocks[j].area_m2 : 0;
      if (!(B > A || (B === A && j < i))) continue;      // 宿主必须更大
      const [x0, y0, x1, y1] = bb[j];
      if (bb[i][0] < x0 || bb[i][1] < y0 || bb[i][2] > x1 || bb[i][3] > y1) continue;
      const p = a.xy;
      let all = true;
      for (let k = 0; k < p.length && all; k += 2) all = inPoly(blocks[j].xy, p[k], p[k + 1]);
      if (all) { out.push({ inner: a, outer: blocks[j] }); break; }
    }
  }
  return out;
}

// ────────────────────────────────────────────── 图例小样

/**
 * 一个 34×16 的小样：**这一档的线画在真实影像上**长什么样。
 *
 * ★ 为什么不是一块纯色方块（那才是图例的常态）：
 *   地图上那条线不是不透明的橙，它是 `rgba(193,68,14,.62)` **压在正射影像上**。
 *   屏幕上那个颜色取决于它底下的像素。给一块纯橙，读的人会拿它去图上找一个
 *   "更深的橙" —— 找不到时他会怀疑是自己看错了，不会怀疑图例。
 *
 * ★ 取样点取在**属于这一档的某一条轮廓自己的形心上**，不取图心：
 *   图心可能是 NoData 那一条黑边，小样就变成一块黑。取在一条真轮廓身上，
 *   这块小样同时也是一句"我在图上长这样"的实拍。
 */
function swatch(base, cal, sample) {
  const W = 34, H = 16;
  const dpr = Math.min(window.devicePixelRatio || 1, 2);
  const c = el('canvas', {
    class: 'ds-swatch', width: Math.round(W * dpr), height: Math.round(H * dpr),
  });
  c.style.width = `${W}px`;
  c.style.height = `${H}px`;
  const g = c.getContext('2d');
  g.setTransform(dpr, 0, 0, dpr, 0, 0);
  const s = sample ?? [base.imgW / 2, base.imgH / 2];
  // ★ 源矩形必须**整体落在图内**：越界时规范会按比例调整目标矩形，
  //   于是小样里的影像与边框**各缩各的**，屏幕上只表现为"这块看着有点歪"。
  const sx = Math.max(0, Math.min(base.imgW - W, Math.round(s[0] - W / 2)));
  const sy = Math.max(0, Math.min(base.imgH - H, Math.round(s[1] - H / 2)));
  g.drawImage(base.img, sx, sy, W, H, 0, 0, W, H);
  const st = CALIBER_STYLE[cal] ?? CALIBER_STYLE._;
  g.fillStyle = st.fill;
  g.fillRect(2.5, 2.5, W - 5, H - 5);
  g.strokeStyle = st.stroke;
  g.lineWidth = 1.5;
  g.strokeRect(2.5, 2.5, W - 5, H - 5);
  return c;
}

/** 小样的落点：这一档里**面积最大**的那条的形心。 */
function samplePoint(blocks, cal) {
  let best = null;
  for (const b of blocks) {
    if (b.height_caliber !== cal || !b.centroid) continue;
    if (!best || (b.area_m2 ?? 0) > (best.area_m2 ?? 0)) best = b;
  }
  return best?.centroid ?? null;
}

function rung(n, label, sub, tone, indent) {
  return el('div', { class: `ds-rung${indent ? ' ind' : ''}${tone ? ` ${tone}` : ''}` },
    el('b', { text: int(n) }),
    el('span', { class: 'ds-rung-t' },
      el('span', { class: 'ds-rung-k', text: label }),
      sub ? el('span', { class: 'ds-rung-s', text: sub }) : null));
}

function card(title, tag, ...body) {
  const c = el('section', { class: 'ds-card' },
    el('h3', {}, el('span', { text: title }), el('em', { text: tag })), ...body);
  return c;
}

// ────────────────────────────────────────────── 页

export async function renderDatascreen(mod) {
  clearInterval(dsTimer); dsTimer = 0;
  liveMap?.destroy();
  liveMap = null;

  const root = el('div', { class: 'dscreen' });
  const clockHost = el('div', { class: 'ds-clock' });
  root.appendChild(el('header', { class: 'ds-top' },
    el('div', { class: 'ds-brand' },
      el('p', { class: 'kicker', text: '数字孪生 · 数据大屏' }),
      el('h2', { text: '校园一张图' })),
    clockHost));

  const band = el('div', { class: 'ds-band' });
  const hero = el('div', { class: 'ds-hero' });
  const colL = el('aside', { class: 'ds-col left' });
  const colR = el('aside', { class: 'ds-col right' });
  const body = el('div', { class: 'ds-body' }, colL, hero, colR);
  const foot = el('div', { class: 'ds-foot' });
  root.appendChild(band);
  root.appendChild(body);
  root.appendChild(foot);
  fill(hero, el('p', { class: 'busy', text: '读取底图与轮廓…' }));

  let base;
  try {
    base = await loadOrthoBase();
  } catch (e) {
    fill(hero, note(`底图没起来：${e?.message ?? e} —— 这一屏的全部依据就是那张图，`
      + '它没起来时**不画**一个空地图冒充"校区是空的"。', 'err'));
    return root;
  }

  // ── 现算：这一趟的全部读数 ───────────────────────────────────────────
  const blocks = base.blocks;
  const byCal = { roof_p50: [], fallback_roof: [], fallback_ground: [] };
  for (const b of blocks) (byCal[b.height_caliber] ??= []).push(b);
  const hollows = cavities(blocks);
  const nHollowGround = hollows.filter((h) => h.inner.height_caliber === 'fallback_ground').length;
  const f = base.facts;

  // ── 时钟 ────────────────────────────────────────────────────────────
  // ★ 自终止：`fill()` 会把这块节点换掉，而**换掉之后的那一份没人清**；
  //   不检 `isConnected` 的话，凡进过一次大屏，这个 setInterval 就活到刷新为止。
  //   它不报错、也吃不了看得见的 CPU —— 正是那种"没人会去查"的漏。
  //
  // ★★ 初值不许写 `--:--:--`：这一屏是"先把整棵树造好、再由外面挂上去"的
  //   （`renderDatascreen` 返回 `root`，由调度器 append），于是从挂载完成到
  //   定时器第一次响之间有**整整一秒**，那一秒屏幕上是一排横杠。
  //   它不报错、控制台干净、判据也全绿 —— 抓到它的是**截图**：验收脚本的截图
  //   紧跟在「切走再切回来」之后取，正好落进那一秒的窗口里。
  //   （铁律 176：渲图用眼睛看这一步不能省，而看到的那一处**必须变成判据** ——
  //     已加进 ⑬：刚切回来的那一瞬间读 `.ds-time`，必须已经是真时间。）
  //   ⇒ 初值**当场算成真时间**，定时器只负责往后推。
  //   ★ 我第一版把这里的病说成「守卫把自己的定时器杀了 ⇒ 钟永远不走」，
  //     那是**错的**：把旧代码放回去跑一遍对照，秒数照跳（14:38:52 → 14:38:53）。
  //     真正错的只是那**一秒**。别把"我一眼看出来的成因"当成量过的成因。
  // ★ 挂载前的 tick **不自杀**（`everLive`）：只有"连上过又掉线"才算真掉线，
  //   否则第一趟那一下会把刚建好的定时器清掉。
  const fmtTime = (d) => d.toLocaleTimeString('zh-CN', { hour12: false });
  const fmtDay = (d) => d.toLocaleDateString('zh-CN',
    { year: 'numeric', month: '2-digit', day: '2-digit', weekday: 'long' })
    .replace(/\//g, '-');
  const timeEl = el('b', { class: 'ds-time', text: fmtTime(new Date()) });
  const dayEl = el('span', { class: 'ds-day', text: fmtDay(new Date()) });
  fill(clockHost, el('span', { class: 'ds-net', text: '校内网' }), timeEl, dayEl);
  let everLive = false;
  const tickClock = () => {
    if (!timeEl.isConnected) {
      if (everLive) { clearInterval(dsTimer); dsTimer = 0; }
      return;                            // 还没挂上去 —— 等下一秒，别把定时器杀了
    }
    everLive = true;
    const d = new Date();
    timeEl.textContent = fmtTime(d);
    dayEl.textContent = fmtDay(d);
  };
  dsTimer = setInterval(tickClock, 1000);

  // ── 口径带（①：覆盖边界 —— 数字留、散文删） ─────────────────────────
  const bb = f.olBbox;
  fill(band,
    el('b', { text: '覆盖只有图中间那一片' }),
    el('span', {}, rich(bb
      ? `E ${bb.e0.toFixed(0)}~${bb.e1.toFixed(0)}、N ${bb.n0.toFixed(0)}~${bb.n1.toFixed(0)}`
        + '（渠东 1:500 图）。**图上没有线 ≠ 那里没有房子**。'
      : '读不到覆盖范围 —— 先别拿它当下判断。')));
  if (!bb) band.classList.add('bad');

  // ── 英雄区：全校区一张图 + 全部轮廓 ─────────────────────────────────
  const readout = el('div', { class: 'ds-hero-bar' });
  const mapHost = el('div', { class: 'ds-map' });
  fill(hero, readout, mapHost);

  const declared = f.olCounts?.outlines;
  fill(readout,
    el('span', { class: 'ds-hero-k', text: '全校区轮廓' }),
    el('b', { text: `${int(blocks.length)}${Number.isFinite(declared) ? ` / ${int(declared)}` : ''}` }),
    el('span', { class: 'ds-hero-u', text: '条已绘出' }),
    el('span', { class: 'ds-hero-sep', text: '·' }),
    el('span', { text: `底图 ${Number.isFinite(base.mpp) ? base.mpp : '—'} m/px` }),
    el('span', { class: 'ds-hero-sep', text: '·' }),
    el('span', { text: f.imageM
      ? `幅面 ${(f.imageM[0] / 1000).toFixed(2)}×${(f.imageM[1] / 1000).toFixed(2)} km` : '幅面 未填' }),
    el('span', { class: 'ds-hero-hint', text: '拖动平移 · 滚轮缩放 · 点一条轮廓' }));

  // 底图那两个层的核对结论 —— 有问题就**印在图上**，不藏（与驾驶舱同一口径）。
  if (base.problems.length) {
    hero.insertBefore(note(`★ 这一趟量到 ${base.problems.length} 处不自洽：`
      + base.problems.join('／'), 'err'), mapHost);
  }

  // ── 右栏 · 选中一条（dt/dd 走驾驶舱那套：空值印"未填"，不印空白） ────
  let sel = null;
  const col4 = card('选中的一条', '实测几何');
  const paintSel = () => {
    const head = col4.querySelector('h3');
    if (!sel) {
      fill(col4, head, note('点图上的轮廓'));
      return;
    }
    const isGround = sel.height_caliber === 'fallback_ground';
    fill(col4, head,
      el('p', { class: 'ds-sel-head' },
        el('b', { text: sel.id ?? sel.ring }),
        el('span', { class: `ds-tag ${isGround ? 'ground' : 'roof'}`,
          text: isGround ? '疑非楼' : '带楼高' })),
      kvList([
        ['底面积', Number.isFinite(sel.area_m2) ? `${num(sel.area_m2, 1)} m²` : null],
        [isGround ? '地面高（不是楼高）' : '屋顶高',
          Number.isFinite(sel.h_m) ? `${num(sel.h_m, 1)} m` : null],
        ['高度口径', CAL_SHORT[sel.height_caliber] ?? sel.height_caliber ?? null],
        ['所在地面', Number.isFinite(sel.ground_med_m) ? `${num(sel.ground_med_m, 1)} m（椭球高）` : null],
        ['落在 NoData 洞上', sel.on_hole ? '是 —— 这一带没有实测地面' : '否'],
        ['轮廓顶点数', sel.n_vertices ?? null],
        ['源里的键', sel.ring ?? null],
      ]));
  };
  paintSel();

  try {
    liveMap = createOrthoMap(mapHost, base, { onPick: (b) => { sel = b; paintSel(); } });
  } catch (e) {
    fill(mapHost, note(`画布没起来：${e?.message ?? e}`, 'err'));
    return root;
  }

  // ── 左栏 ① 信任阶梯：从"图上描出来的全部"往下走到"连形状都不是独立一栋" ──
  const nRoof = byCal.roof_p50.length + byCal.fallback_roof.length;
  colL.appendChild(card('信任阶梯', '实测',
    rung(blocks.length, '图上描出来的轮廓', '全部（下面两档都算在里面）', ''),
    rung(nRoof, '其中带真楼高', '敢当"楼"用的就是这些', 'roof'),
    rung(byCal.fallback_ground.length, '疑非楼', '那个"高"是地高，不是楼高', 'ground'),
    rung(nHollowGround, '其中整条被别的轮廓包住', '内院 / 空腔 —— 连独立一栋都不是', 'ground', true)));

  // ── 左栏 ② 高度口径：条形与图例合体。★ 色原样取地图那张表，理由见 swatch() ──
  const maxN = Math.max(1, ...CAL_ORDER.map((c) => byCal[c].length));
  colL.appendChild(card('高度口径', '图上那三条线色',
    ...CAL_ORDER.map((c) => {
      const n = byCal[c].length;
      return el('div', { class: 'ds-cal' },
        swatch(base, c, samplePoint(blocks, c)),
        el('div', { class: 'ds-cal-body' },
          el('div', { class: 'ds-cal-top' },
            el('b', { text: int(n) }), el('span', { text: CAL_SHORT[c] })),
          el('i', { class: `ds-bar ${c}`, style: `width:${(n / maxN) * 100}%` })));
    })));

  // ── 右栏 ③ 底面积最大的那几条：点一行，把它拉到图中央 ────────────────
  const top = blocks.filter((b) => b.height_caliber !== 'fallback_ground' && b.centroid)
    .slice().sort((a, b) => (b.area_m2 ?? 0) - (a.area_m2 ?? 0)).slice(0, 14);
  const col3 = card('底面积最大的', `带楼高 · 前 ${top.length}`);
  col3.classList.add('ds-scroll');
  col3.appendChild(el('div', { class: 'ds-list' }, ...top.map((b) => el('button', {
    type: 'button', class: 'ds-item',
    onclick: () => { liveMap?.focus(b, 1.1); sel = b; paintSel(); },
  },
    el('b', { text: b.id ?? b.ring }),
    el('span', { text: `${num(b.area_m2, 0)} m²` }),
    el('span', { class: 'ds-item-h', text: `${num(b.h_m, 1)} m` })))));
  colR.appendChild(col3);
  colR.appendChild(col4);

  // ── 页脚：只留读数。★ 出处那一格（图源）按用户口径删掉了 ──────────────
  fill(foot,
    el('span', { class: 'ds-foot-k', text: '盘上交付' }),
    el('span', { class: 'ds-foot-v', id: 'ds-fleet', text: '读取中…' }),
    el('span', { class: 'ds-foot-sep', text: '·' }),
    el('span', { class: 'ds-foot-k', text: '轮廓' }),
    el('span', { class: 'ds-foot-v', text: `${int(blocks.length)} 条（其中 `
      + `${int(nHollowGround)} 条是套在别的轮廓里的空腔）` }));

  // ── 楼栋与房间：与「建筑与空间」同一把尺子（逐行按范围过滤） ──────────
  // 取不到就**明说取不到**，不留一格 '—' 让人以为那是"校区里没有"。
  const fleet = foot.querySelector('#ds-fleet');
  try {
    const rows = await API.buildings();
    const nRoom = rows.reduce((s, r) => s + (Number(r.rooms) || 0), 0);
    fleet.textContent = `${rows.length} 栋 · 房间 ${int(nRoom)} 间（按你的范围过滤后）`;
  } catch (e) {
    fleet.textContent = `没取到（${e?.message ?? e}）`;
    fleet.classList.add('bad');
  }

  return root;
}
