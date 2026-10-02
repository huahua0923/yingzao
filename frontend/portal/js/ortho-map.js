// 正射底图画布：把那张影像铺开，把建筑轮廓叠上去，接管点选与缩放。
//
// ★ 这个文件里**一条判据都没有** —— 帧对不对、图是不是那张、轮廓少了几个，
//   全在 `ortho-base.js` 里核完了。这里只管画。
//   分工的理由：判据混进绘制代码之后，两者会一起错（尺子与被测对象同源），
//   而屏幕上只会表现为"这张图看着有点不对"。
//
// 坐标：本文件一律用**图像像素**。ENU → 像素的换算在 `ortho-base.js` 里做过一次，
//   之后每帧只做一次线性变换（s, cx, cy）。理由见 `enu_to_px` 的注释：
//   那个换算式的凭据是网格 accessor，改一次就该重算一次，不该每帧重算。

import { el, fill } from './dom.js';

const ZOOM_MIN = 0.06;     // 视口再小也不许把图缩成一颗米粒
const LABEL_MIN_AREA_PX = 260;   // 标签只在条大到读得清时出现，否则 341 个 id 糊成一团

// 线色 = **高度口径**，与 `campus_buildings_viewdata.json` 自己那张口径表一一对应。
// ★ 为什么这不能只当配色：341 条里 `fallback_ground` 那 **94** 条，源数据层的原话是
//   「p90 落进**地**那一坨 ⇒ 这个 h **不是楼高**，是地高，读它等于读空地」——
//   实测这 94 条的 h 中位正好是 **0.0 m**、面积中位 79 m²。
//   把它们画成与真楼同色，屏幕上就是在说"这些也是楼"。
//   所以：橙 = 量的是屋顶（真楼），橄榄 = 屋顶格偏少但 p90 仍在屋顶上，灰 = 那是地。
// ★ 它是 `export` 的，是为了让**别处画图例时用的是同一份墨**。
//   数据大屏的图例小样要画"这条线在影像上长什么样" —— 那个颜色只有从这里取
//   才与地图上真正画出来的一致。在别处再抄一份 rgb 就是两个来源（铁律 018），
//   而颜色对不上是**看不出来**的：两个橙摆在不同底色上，谁都像个正常的橙。
// ★★ **这张表是深底版**（2026-10-02）。
//
//   旧值是**为浅底选的**：`rgba(193,68,14,.62)` 那种深赭压在中灰的航拍影像上够看，
//   转深色之后它压在同一张影像上仍然够看 —— 但**图例小样是画在面板上的**，
//   而面板已经是 `--surface #151A21`。实测：旧朱 `#C1440E` 压 `--surface` 只有
//   **3.4:1**（`portal.css` 顶上那段自己写着这个数），而它正是全页最小的字号。
//   ⇒ 换成 `:root` 里那三支**已经量过对比度**的语义色（accent 6.8 / warn 8.1 / muted 5.7）。
//
//   ★ 小样（`datascreen.js:drawSwatch`）与图里的线**读的是同一张表** ——
//     所以改这里它们一起改，不存在「图例说一个颜色、图上画另一个颜色」。
export const CALIBER_STYLE = {
  // 实测屋顶高（231 条）—— 最"真"的一档，用朱
  roof_p50:        { stroke: 'rgba(255,122,69,.80)',  fill: 'rgba(255,122,69,.10)' },
  // 兜底·屋顶（16 条）
  fallback_roof:   { stroke: 'rgba(232,163,61,.80)',  fill: 'rgba(232,163,61,.10)' },
  // 兜底·地面（94 条）—— ★ 这一档的 `h` 是**地高不是楼高**，画成和真楼一个色
  //   等于在屏幕上说"这些也是楼"，所以它必须明显退到后面去
  fallback_ground: { stroke: 'rgba(134,149,167,.75)', fill: 'rgba(134,149,167,.08)' },
  _:               { stroke: 'rgba(134,149,167,.55)', fill: 'rgba(134,149,167,.06)' },
};

/** 世界之外那一圈。**不在这里写死一个数** —— 从 CSS 读 `--void`（唯一定义处）。 */
const VOID_FALLBACK = [8, 11, 16];   // #080b10
const VOID_HEX = (() => {
  const v = getComputedStyle(document.documentElement)
    .getPropertyValue('--void').trim();
  return v || '#080b10';
})();
const VOID_RGB = (() => {
  const m = /^#?([0-9a-f]{6})$/i.exec(VOID_HEX);
  if (!m) return VOID_FALLBACK;
  const n = parseInt(m[1], 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
})();

// ★★ 正射图**自带三块纯黑的角**，而那不是"暗"，是**没有测绘**。
//
//   实测（`campus_ortho.jpg` 2562×2538，取四角与中心）：
//     TL (0,0,0)   TR (0,0,0)   BL (0,0,0)   BR (183,149,122)   中心 (41,49,36)
//   ⇒ 测区是一次航飞的**斜置矩形**，而栅格按外接正矩形出图，三个角没东西。
//   旧版把这图铺在一块**米色板**上（`#E8E3D9`，为浅底画的），于是那三块黑
//   在米色上是一道刺眼的黑三角；页面转深色之后，米色板本身又成了"纸贴在屏幕上"。
//   ⇒ 两件事一起改：**板子换成 `--void`**，并把这三块纯黑**归到 `--void`** ——
//     屏幕上剩下的是"有测绘的那一片"，边界由影像自己的边给出（那才是真信息）。
//   ★ 阈值取得很紧（三通道都 < 12）：航拍里再暗的树影/水面也在 20 以上，
//     而 `--void` 是 (8,11,16) —— 归过去之后最深的地方反而**变亮**，不会吃掉内容。
const BLACK_MAX = 12;

/** 把"没有测绘"的那几块归成 `--void`。**只做一次**，之后 `drawImage` 直接用这张。 */
function voidedImage(img) {
  const c = document.createElement('canvas');
  c.width = img.naturalWidth; c.height = img.naturalHeight;
  const g = c.getContext('2d');
  g.drawImage(img, 0, 0);
  let d;
  try {
    d = g.getImageData(0, 0, c.width, c.height);
  } catch (e) {
    // 同源失败（不该发生，图是自家路由发的）。**退回原图**并让调用方印出来 ——
    // 悄悄退回会让"黑角还在"看起来像"我压根没打算改它"。
    return { img, replaced: -1 };
  }
  const a = d.data;
  let n = 0;
  for (let i = 0; i < a.length; i += 4) {
    if (a[i] < BLACK_MAX && a[i + 1] < BLACK_MAX && a[i + 2] < BLACK_MAX) {
      a[i] = VOID_RGB[0]; a[i + 1] = VOID_RGB[1]; a[i + 2] = VOID_RGB[2];
      n++;
    }
  }
  g.putImageData(d, 0, 0);
  return { img: c, replaced: n };
}

/** 球面上算不出来的东西不在这里算：这是平面校区的 1:1 像素映射。 */
export function createOrthoMap(host, base, { onPick } = {}) {
  const canvas = el('canvas', { class: 'ortho-canvas' });
  const readout = el('div', { class: 'ortho-readout' });
  const scalebar = el('div', { class: 'ortho-scalebar' });
  const north = el('div', { class: 'ortho-north', text: 'N' });
  const tools = el('div', { class: 'ortho-tools' });
  const stage = el('div', { class: 'ortho-stage' }, canvas, north, scalebar, readout, tools);
  fill(host, stage);

  const ctx = canvas.getContext('2d');
  // ★★ 这两个数**必须先验再用**。它们一旦是 `undefined`，`fitS` 就是 `NaN`，
  //   而 `setTransform(NaN, …)` 按规范**不生效**（变换停在单位阵，不抛错）
  //   ⇒ 画的是一张 1:1 的图，屏幕上只剩正射左上角那条黑边，**一句错都不报**。
  //   所以在这里大声死掉：调用方（cockpit.js）会把它当"底图没起来"印在屏幕上。
  const W = base.imgW, H = base.imgH;
  if (!Number.isFinite(W) || !Number.isFinite(H) || W <= 0 || H <= 0) {
    throw new Error(`画布拿不到图像尺寸：base.imgW=${W}／base.imgH=${H}`
      + '（要的是 ortho-base.js 顶层那两个数，不是 facts 里的）');
  }
  const view = { cx: W / 2, cy: H / 2, s: 1 };
  // "没有测绘"那几块归成 --void。**在这里做一次**，不进 render() ——
  // 那是 650 万像素的逐点扫描，放进每帧会把它变成一台幻灯片。
  const src = voidedImage(base.img);
  /** 量出来的替换点数（-1 = getImageData 被拒，退回原图）。调用方要印它。 */
  const voided = src.replaced;
  let fitS = 1, vw = 1, vh = 1, dpr = 1;
  let hover = null, selected = null, moved = false, down = null, raf = 0;

  const toScreen = (x, y) => [(x - view.cx) * view.s + vw / 2, (y - view.cy) * view.s + vh / 2];
  const toImage = (sx, sy) => [(sx - vw / 2) / view.s + view.cx, (sy - vh / 2) / view.s + view.cy];

  function resize() {
    const r = stage.getBoundingClientRect();
    if (!r.width || !r.height) return;
    vw = Math.round(r.width); vh = Math.round(r.height);
    dpr = Math.min(window.devicePixelRatio || 1, 2);
    canvas.width = Math.round(vw * dpr);
    canvas.height = Math.round(vh * dpr);
    canvas.style.width = vw + 'px';
    canvas.style.height = vh + 'px';
    // ★ 首帧之前 fitS 是 1，resize 里的 `view.s / fitS` 比值会把"刚算出来的 fit"
    //   当成一次用户缩放 —— 所以只在 fitS 已经定过之后才按比例跟。
    fitS = Math.min(vw / W, vh / H);
    if (!fitted) { view.s = fitS; fitted = true; }
    render();
  }
  let fitted = false;

  function fit() { view.cx = W / 2; view.cy = H / 2; view.s = fitS; render(); }
  function zoomBy(k, ax = vw / 2, ay = vh / 2) {
    const [ix, iy] = toImage(ax, ay);
    view.s = Math.max(ZOOM_MIN, Math.min(80, view.s * k));
    // 让光标底下那个点**不动**：换完 scale 再把中心挪回去。
    const [nx, ny] = toImage(ax, ay);
    view.cx += ix - nx; view.cy += iy - ny;
    render();
  }

  /** 射线法。在**图像像素**坐标里做 —— 与画出来的东西同一套坐标，不换第二次。 */
  function hit(x, y) {
    for (let k = base.blocks.length - 1; k >= 0; k--) {
      const p = base.blocks[k].xy, m = p.length / 2;
      let inside = false;
      for (let i = 0, j = m - 1; i < m; j = i++) {
        const xi = p[i * 2], yi = p[i * 2 + 1], xj = p[j * 2], yj = p[j * 2 + 1];
        if ((yi > y) !== (yj > y) && x < ((xj - xi) * (y - yi)) / (yj - yi) + xi) inside = !inside;
      }
      if (inside) return base.blocks[k];
    }
    return null;
  }

  function render() {
    raf = 0;
    if (!vw || !vh) return;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, vw, vh);
    // 图外面的底色 = 世界之外那一圈（`--void`）。**不是米色板** ——
    // 米色是浅底时代给"图有边界"用的底，转深色后它成了屏幕上唯一一块纸。
    ctx.fillStyle = VOID_HEX;
    ctx.fillRect(0, 0, vw, vh);
    ctx.setTransform(view.s * dpr, 0, 0, view.s * dpr,
                     (vw / 2 - view.cx * view.s) * dpr, (vh / 2 - view.cy * view.s) * dpr);
    ctx.imageSmoothingQuality = 'high';
    ctx.drawImage(src.img, 0, 0);
    // ★ 出图范围边界：这是"到此为止"的凭据。深底上必须是**亮发丝线**，
    //   原来那条 `rgba(20,17,14,.45)` 是深底画深线 ⇒ 屏幕上什么都没有。
    ctx.lineWidth = 1.5 / view.s; ctx.strokeStyle = 'rgba(215,224,234,.22)';
    ctx.strokeRect(0, 0, W, H);

    const showLabels = view.s >= 0.55;
    ctx.lineJoin = 'round';
    for (const b of base.blocks) {
      const p = b.xy;
      ctx.beginPath();
      ctx.moveTo(p[0], p[1]);
      for (let i = 2; i < p.length; i += 2) ctx.lineTo(p[i], p[i + 1]);
      ctx.closePath();
      const isSel = selected === b, isHov = hover === b;
      ctx.lineWidth = (isSel ? 2.6 : isHov ? 2.0 : 1.0) / view.s;
      // ★ 线色按**高度口径**分，不是按装饰分（理由写在 `CALIBER_STYLE` 那张表上）：
      //   341 条里有 94 条的 `h` 是**地高不是楼高**（源数据层自己的定义），
      //   把它们画成和真楼同一个颜色，等于在屏幕上说"这些也是楼"。
      const st = CALIBER_STYLE[b.height_caliber] ?? CALIBER_STYLE._;
      // 选中 / 悬停也要**亮起来**：旧值是 `#C1440E` / `#14110E`（深赭 / 近黑），
      // 压在深底上等于把那条线**藏掉** —— 而这两个态正是"我点了它"的唯一回执。
      ctx.strokeStyle = isSel ? '#FF7A45' : isHov ? '#F2F6FA' : st.stroke;
      ctx.fillStyle = isSel ? 'rgba(255,122,69,.26)' : st.fill;
      ctx.fill();
      ctx.stroke();
      if (showLabels && b.centroid && Number.isFinite(b.area_m2)) {
        const aPx = (b.area_m2 / (base.mpp * base.mpp)) * view.s * view.s;
        if (aPx >= LABEL_MIN_AREA_PX) label(b);
      }
    }
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    paintScalebar();
  }

  function label(b) {
    const [sx, sy] = toScreen(b.centroid[0], b.centroid[1]);
    const t = Number.isFinite(b.h_m) ? `${b.id} · ${b.h_m.toFixed(1)} m` : b.id;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.font = '10px "Cascadia Mono", Consolas, monospace';
    const w = ctx.measureText(t).width;
    // 标签片：**深玻璃 + 亮字**（旧版是米底墨字 —— 那是一片一片的小白纸，
    // 而它们压的正是航拍影像，读起来像图上贴了便利贴）。
    ctx.fillStyle = 'rgba(8,11,16,.78)';
    ctx.fillRect(sx - w / 2 - 3, sy - 7, w + 6, 13);
    ctx.fillStyle = '#D7E0EA';
    ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
    ctx.fillText(t, sx, sy);
    ctx.setTransform(view.s * dpr, 0, 0, view.s * dpr,
                     (vw / 2 - view.cx * view.s) * dpr, (vh / 2 - view.cy * view.s) * dpr);
  }

  /** 比例尺：挑一个"整数米"的长度，让它在屏幕上落在 70~150 px。 */
  function paintScalebar() {
    if (!Number.isFinite(base.mpp) || view.s <= 0) { scalebar.hidden = true; return; }
    const mPerPx = base.mpp / view.s;
    const STEPS = [10, 20, 50, 100, 200, 500, 1000, 2000];
    let m = STEPS[STEPS.length - 1];
    for (const s of STEPS) { if (s / mPerPx >= 70) { m = s; break; } }
    const px = m / mPerPx;
    scalebar.hidden = false;
    fill(scalebar, el('i', { style: `width:${px.toFixed(1)}px` }), el('b', { text: `${m} m` }));
  }

  function pickAt(ev) {
    const r = canvas.getBoundingClientRect();
    const [ix, iy] = toImage(ev.clientX - r.left, ev.clientY - r.top);
    return { b: hit(ix, iy), ix, iy };
  }

  // ── 交互 ────────────────────────────────────────────────────────────
  canvas.addEventListener('pointerdown', (ev) => {
    canvas.setPointerCapture(ev.pointerId);
    down = { x: ev.clientX, y: ev.clientY, cx: view.cx, cy: view.cy };
    moved = false;
  });
  canvas.addEventListener('pointermove', (ev) => {
    if (down) {
      const dx = ev.clientX - down.x, dy = ev.clientY - down.y;
      // ★ 3 px 是"手抖"与"拖动"的界 —— 不设这条界的话，点选会变成每次拖完都选一次。
      if (Math.abs(dx) + Math.abs(dy) > 3) moved = true;
      if (moved) {
        view.cx = down.cx - dx / view.s; view.cy = down.cy - dy / view.s;
        requestRender();
      }
    }
    const { b, ix, iy } = pickAt(ev);
    // 读出光标底下的 EPSG:4544 坐标 —— 这一屏唯一能拿去对图纸的数。
    fill(readout, el('span', { text: `E ${(base.grid.e0 + ix * base.mpp).toFixed(2)}` }),
      el('span', { text: `N ${(base.grid.n1 - iy * base.mpp).toFixed(2)}` }));
    if (b !== hover) { hover = b; canvas.style.cursor = b ? 'pointer' : 'grab'; requestRender(); }
  });
  canvas.addEventListener('pointerup', (ev) => {
    const wasDrag = moved; down = null;
    if (wasDrag) return;
    const { b } = pickAt(ev);
    selected = b;
    render();
    onPick?.(b ?? null);
  });
  canvas.addEventListener('pointerleave', () => { readout.hidden = true; hover = null; render(); });
  canvas.addEventListener('pointerenter', () => { readout.hidden = false; });
  canvas.addEventListener('wheel', (ev) => {
    ev.preventDefault();
    const r = canvas.getBoundingClientRect();
    zoomBy(Math.exp(-ev.deltaY * 0.0016), ev.clientX - r.left, ev.clientY - r.top);
  }, { passive: false });

  const btn = (label, title, fn) => el('button', { type: 'button', title, onclick: fn, text: label });
  fill(tools,
    btn('＋', '放大', () => zoomBy(1.35)),
    btn('－', '缩小', () => zoomBy(1 / 1.35)),
    btn('全校区', '缩到整幅底图', fit));

  function requestRender() { if (!raf) raf = requestAnimationFrame(render); }
  const ro = new ResizeObserver(() => resize());
  ro.observe(stage);
  resize();

  return {
    el: stage,
    requestRender,
    fit,
    zoomBy,
    /** "没有测绘"那几块归成 `--void` 的**点数**（-1 = 读像素被拒、退回原图）。 */
    voidedPx: voided,
    select(b) { selected = b; render(); },
    /** 把某个块摆到屏幕中央（从别的控件点过来时用）。 */
    focus(b, minScale = 1.1) {
      if (!b?.centroid) return;
      view.cx = b.centroid[0]; view.cy = b.centroid[1];
      view.s = Math.max(view.s, minScale);
      selected = b; render();
    },
    destroy() { ro.disconnect(); cancelAnimationFrame(raf); },
  };
}
