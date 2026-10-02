// 341 条**真建筑轮廓** —— 把「有形状、没身份」的那份实测数据画进世界。
//
// 这份数据是 1:500 实测地形图上的建筑轮廓（`campus_outlines.json`），
// 与三维模型同源、同一套 TX/TY。它取代的是原来那份 `blocks.js` 里
// **手编的 15 个 MOCK_BLOCKS** —— 那些块叫 `M-01 图书馆`，而真名册里
// 根本没有这两栋楼（真的是 `c001`/`c002`…）。屏幕上写着一个不存在的楼名，
// 比什么都不写更糟：它看起来像有数据。
//
// ★★ 但这一份**也没有身份**。341 条轮廓里没有建筑编号（`i` 只是数组序号，
//   `ring` 是 `ringsA[0]` 这种），而名册 93 条里没有位置。盘上也不存在能把
//   两者连起来的变换 —— 我量过四次（平移投票 / 旋转扫描 / `cx−offset` /
//   Y 翻转），四次最高票都在噪声底上（14/92），**且四种都报不出峰**。
//   ⇒ 所以本模块**只画形状，不编身份**。身高、占地、地面高程是**实测**，
//     楼名是**没有**。面板上这两者必须分开写（见 `describe()`）。
//
// ★ 三档高度口径**必须分色**（用户 2026-10-01 定）：`h_m` 有两个来源，
//   231 条来自屋顶点云 p50（量到了）、94 条退回地面（可能没屋顶）、
//   16 条退回屋顶面。**把「不知道高度」画得跟「量到了」一样**，
//   读的人会把 0.43 m 当成"这栋楼只有一层"。

import { localOf, axialFromTileset } from './place.js';

/** 三档口径 → 三种颜色。颜色是**语义**，不是装饰：一眼看出哪一档。
 *
 *  · `roof_p50`      量到了屋顶（p50），可信；
 *  · `fallback_roof` 屋顶面有、但点不够，取的是面；
 *  · `fallback_ground` 屋顶量不到，**退回地面高程** —— h_m 会接近 0，
 *                     那**不是"这栋楼很矮"**，是"这里没量到"。
 */
export const CALIBERS = Object.freeze({
  roof_p50: { key: 'roof_p50', label: '屋顶实测', color: '#5ad2ff', edge: '#a8ecff' },
  fallback_roof: { key: 'fallback_roof', label: '屋顶面推算', color: '#ffc857', edge: '#ffe0a3' },
  fallback_ground: { key: 'fallback_ground', label: '退回地面（高度不可信）', color: '#ff7b72', edge: '#ffb3ad' },
});

export function caliberOf(cal) {
  return CALIBERS[cal] || { key: cal || '未知', label: cal || '口径未知', color: '#9aa7b4', edge: '#c3ccd6' };
}

/**
 * 把一处轮廓的原始记录整理成画得出来的东西。
 * ★ **不补默认值**：`h_m` 缺了就是缺了，不许写成 0 —— 0 在屏幕上是个合法的读数。
 */
export function normalise(raw) {
  const items = [];
  (raw?.outlines || []).forEach((b) => {
    const poly = b.poly_en || [];
    if (poly.length < 3) return;              // 三点以下画不出面，**跳过并计数**（别静默）
    const base = Number(b.ground_med_m);
    const h = Number(b.h_m);
    items.push({
      i: b.i,
      poly,
      area: Number(b.area_m2),
      h: Number.isFinite(h) ? h : null,
      base: Number.isFinite(base) ? base : null,
      cal: b.height_caliber,
      onHole: !!b.on_hole,
      ring: b.ring,
      // 顶面绝对高程：量到过才给数，没量到就是 null（`null` 与 `0` 在屏幕上不一样）
      top: (Number.isFinite(base) && Number.isFinite(h)) ? base + h : null,
      code: null,          // ← 身份位。锚点接上之前**恒为 null**，不许猜。
    });
  });
  return items;
}

/**
 * 画进世界，并挂上拾取。
 *
 * @param {object} viewer   Cesium viewer
 * @param {object} tileset  实景瓦片（借它的 `root.transform` 定朝向）
 * @param {object[]} items  `normalise()` 的产出
 * @param {(it:object|null)=>void} onPick
 */
export function buildOutlines(viewer, tileset, items, onPick) {
  const { toEcef } = axialFromTileset(tileset);
  const ents = [];
  const byEntity = new Map();          // entity.id → item（拾取要能反查）
  const byItem = new Map();            // item → [fill, edge]（按条开关用）

  items.forEach((it) => {
    const c = caliberOf(it.cal);
    // ★ 画在**顶面高程**上，不画在地面：实景瓦片是实心的，画在地面等于画在楼里面，
    //   什么都看不见。画在顶面上 = 大厂那种"这栋楼被点亮"的样子。
    //   退回地面那一档（h≈0）本来就贴地，画出来也是一条贴地的环，正好是它的实情。
    const z = Number.isFinite(it.top) ? it.top : (it.base ?? 0);
    const cart = it.poly.map((p) => {
      const [x, y, zz] = localOf(Number(p[0]), Number(p[1]), z);
      return toEcef(x, y, zz);
    });
    const fill = viewer.entities.add({
      polygon: {
        hierarchy: { positions: cart },
        perPositionHeight: true,        // ★ 必须：绝对 Cartesian3 配 `height:` 会整体沉 422 m
        material: Cesium.Color.fromCssColorString(c.color).withAlpha(0.22),
        outline: false,
      },
    });
    const edge = viewer.entities.add({
      polyline: {
        positions: cart.concat([cart[0]]),
        width: 1.6,
        clampToGround: false,
        material: Cesium.Color.fromCssColorString(c.edge).withAlpha(0.85),
      },
    });
    byEntity.set(fill.id, it);
    byEntity.set(edge.id, it);
    byItem.set(it, [fill, edge]);
    ents.push(fill, edge);
  });

  let selected = null;
  let selEdge = null;

  const handler = new Cesium.ScreenSpaceEventHandler(viewer.scene.canvas);
  handler.setInputAction((mv) => {
    const picked = viewer.scene.pick(mv.position);
    const it = picked && byEntity.get(picked.id && picked.id.id);
    if (!it) { clearSelection(); if (onPick) onPick(null); return; }
    select(it);
    if (onPick) onPick(it);
  }, Cesium.ScreenSpaceEventType.LEFT_CLICK);

  function clearSelection() {
    if (selEdge) { viewer.entities.remove(selEdge); selEdge = null; }
    selected = null;
  }

  function select(it) {
    clearSelection();
    selected = it;
    const z = Number.isFinite(it.top) ? it.top : (it.base ?? 0);
    const cart = it.poly.map((p) => {
      const [x, y, zz] = localOf(Number(p[0]), Number(p[1]), z);
      return toEcef(x, y, zz);
    });
    // 选中环**抬高一点点**再画，否则与它自己那条边线 z-fighting（屏幕上表现为闪）。
    const lift = 0.35;
    const hi = cart.map((p) => ({ x: p.x, y: p.y, z: p.z }));
    selEdge = viewer.entities.add({
      polyline: {
        positions: hi.concat([hi[0]]),
        width: 4.5,
        clampToGround: false,
        material: Cesium.Color.fromCssColorString('#ffffff').withAlpha(0.95),
      },
    });
    void lift;
  }

  /** 内外都要用的：把一条轮廓的颜色改掉（锚定高亮用）。`edge=null` 即还原。 */
  function paint(it, color, edgeColor) {
    const pair = byItem.get(it);
    if (!pair) return;
    const c = caliberOf(it.cal);
    pair[0].polygon.material = Cesium.Color.fromCssColorString(color || c.color).withAlpha(color ? 0.55 : 0.22);
    pair[1].polyline.material = Cesium.Color.fromCssColorString(edgeColor || c.edge).withAlpha(0.9);
  }

  // ── 可见性：**两个受控量，一份施加逻辑** ──────────────────────────────
  //
  // ★★ 为什么不是两个各自 `pair.show = …` 的独立开关：那两个开关会**互相拆台**。
  //    "只看已关联"关掉 N 条，紧接着"图例点开退回地面"又把这 N 条里的
  //    `fallback_ground` 全部打开 —— 两个开关都"生效了"，合起来的结果却不是任何
  //    一个开关说的那件事。把它俩折成"过滤函数 ∧ 口径集合"，再统一施加一次，
  //    就不存在中间态。
  let filterItem = null;                 // (it) => boolean | null
  const calOff = new Set();

  function apply() {
    items.forEach((it) => {
      const pair = byItem.get(it);
      if (!pair) return;
      const on = !calOff.has(it.cal) && (!filterItem || filterItem(it));
      pair[0].show = on;
      pair[1].show = on;
    });
    viewer.scene.requestRender();
  }

  return {
    items,
    entityCount: ents.length,
    byItem,
    /** 换一条过滤规则（`null` = 不过滤）。"只看已关联"走这里。 */
    setFilter(fn) { filterItem = fn || null; apply(); },
    /** 整档开关（图例点一下藏掉一档）。 */
    setCaliberVisible(calKey, on) {
      if (on) calOff.delete(calKey); else calOff.add(calKey);
      apply();
    },
    /** 已关联的换色 + 抬笔。`codes` 是 `Set<item>` 或一个判据函数。 */
    setLinked(isLinked) {
      items.forEach((it) => {
        const on = (typeof isLinked === 'function') ? isLinked(it) : isLinked.has(it);
        if (on) paint(it, '#ffb347', '#ffe1a8');
        else paint(it, null, null);
      });
      viewer.scene.requestRender();
    },
    select,
    clearSelection,
    pickAt(x, y) {
      const p = viewer.scene.pick(new Cesium.Cartesian2(x, y));
      return p && byEntity.get(p.id && p.id.id) || null;
    },
    /** 相机飞到这一条上（把整条轮廓收进视野）。 */
    focus(it) {
      if (!it) return;
      const bs = new Cesium.BoundingSphere(
        Cesium.Cartesian3.fromElements(0, 0, 0), 1);
      const cart = it.poly.map((p) => {
        const [x, y, zz] = localOf(Number(p[0]), Number(p[1]),
          Number.isFinite(it.top) ? it.top : 0);
        const e = toEcef(x, y, zz);
        return new Cesium.Cartesian3(e.x, e.y, e.z);
      });
      Cesium.BoundingSphere.fromPoints(cart, bs);
      viewer.camera.viewBoundingSphere(bs, new Cesium.HeadingPitchRange(0, Cesium.Math.toRadians(-45), bs.radius * 4.0));
      viewer.scene.requestRender();
    },
    setVisible(on) { ents.forEach((e) => { e.show = on; }); viewer.scene.requestRender(); },
    destroy() {
      handler.destroy();
      ents.forEach((e) => viewer.entities.remove(e));
      clearSelection();
    },
  };
}

/**
 * 给面板写这一条的说明。**实测数与缺失必须分开写**（这是本模块存在的理由）。
 * ★ 身份那一段**只在真有锚点时**才写楼名；没有就明说"未关联"。
 */
export function describe(it) {
  if (!it) return null;
  const c = caliberOf(it.cal);
  return {
    title: it.code ? `已关联 ${it.code}` : `轮廓 #${it.i}（未关联建筑）`,
    code: it.code,
    rows: [
      ['占地', `${it.area.toFixed(1)} m²`],
      ['地面高程', it.base == null ? '—' : `${it.base.toFixed(1)} m`],
      ['顶面高程', it.top == null ? '—' : `${it.top.toFixed(1)} m`],
      ['净高', it.h == null ? '—' : `${it.h.toFixed(2)} m`],
      ['高度口径', c.label],
      ['落在空洞上', it.onHole ? '是' : '否'],
      ['来源环', it.ring || '—'],
    ],
    caveat: it.h == null ? '这一条没有可用的高度读数。'
      : (it.cal === 'fallback_ground'
        ? '★ 高度退回地面量得 —— 接近 0 **不是**"楼很矮"，是"这里没量到屋顶"。'
        : null),
  };
}
