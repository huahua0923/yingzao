// 纵览驾驶舱的底图数据：正射影像 + 它的帧 + 建筑轮廓。
//
// ★ 为什么单独一个文件：这一份里全是**判据**（下面每一条 `problems.push` 都是一个
//   会被印到屏幕上的事实），而画布那一半（`ortho-map.js`）里一条判据都没有。
//   混在一起的话，读的人分不清"这个数是量出来的"还是"画上去的"。

import { API } from './api.js';

/**
 * 载入底图所需的全部东西，并**当场核对**。
 *
 * ★ 两份数据的帧（e0/n1/step/nx/ny）**必须一致**，而它们来自不同文件：
 *     · `campus_ortho.json` —— 底图侧车，记录"这张图是谁、摆在哪儿"
 *     · `campus_terrain_viewdata.json` —— 地形交付件的数据层，帧的**权威来源**
 *   侧车的帧是**生成时抄过去的**。抄一次就有两个来源（铁律 018）——
 *   所以这里**每次打开都重新比一遍**：万一哪天 GLB 换了而侧车没重出，
 *   两个来源就会岔开，而屏幕上"楼整体偏一点"是看不出来的。
 *
 * 返回 `{img, url, map, blocks, grid, problems, facts}`。
 * `problems` 非空时**不阻断作画** —— 底图照画，但每一条都会印在屏幕上。
 */
export async function loadOrthoBase() {
  const problems = [];

  // ★ 三个请求并行发。串行要等三轮 RTT，而它们之间没有依赖。
  const [side, view, outlines, plan] = await Promise.all([
    API.orthoSidecar(), API.viewData(), API.outlines(), API.realBuildings(),
  ]);

  // ── ① 帧：两个来源对一遍 ────────────────────────────────────────────
  const g = view?.grid ?? {};
  const f = side?.frame ?? {};
  const KEYS = ['e0', 'n1', 'step', 'nx', 'ny'];
  const missing = KEYS.filter((k) => !Number.isFinite(f[k]) || !Number.isFinite(g[k]));
  if (missing.length) {
    problems.push(`帧里有 ${missing.length} 个键两边没有同时给出数：${missing.join('、')}`);
  } else {
    for (const k of KEYS) {
      if (f[k] !== g[k]) {
        problems.push(`★ 帧的 ${k} 两个来源不一致：底图侧车 ${f[k]} ／ 地形数据层 ${g[k]}`
          + '（多半是底图换了版本而侧车没重出 —— 这时二维底图与三维已经不是同一帧）');
      }
    }
  }

  // ── ② m/px：不许我另算一个 ─────────────────────────────────────────
  //   侧车里那个数是**量出来的**（图宽 ÷ 跨度）。这里只核它与帧自洽，
  //   不自己用 `span/width` 再算一遍 —— 再算一遍就又是两个来源。
  const mpp = side?.enu_to_px?.m_per_px;
  const width = side?.file?.width, height = side?.file?.height;
  if (!Number.isFinite(mpp) || !width || !height) {
    problems.push('底图侧车里读不到 m_per_px / 尺寸 —— 不知道这张图对应多少米，不能当地图用。');
  } else if (Number.isFinite(g.nx) && Number.isFinite(g.step)) {
    const want = (g.nx * g.step) / width;
    if (Math.abs(want - mpp) > 1e-6) {
      problems.push(`★ m/px 与帧对不上：侧车 ${mpp}，按「跨度 ${g.nx * g.step} m ÷ 图宽 ${width} px」`
        + ` 应是 ${want.toFixed(6)}`);
    }
  }
  // ★★ 这里原来写的是 `if (orient && orient !== 'northwest')` —— 一个 fail-open：
  //   键**读不到**时（undefined）整个判断被跳过，屏幕上一条问题都不报。
  //   而"侧车没声明朝向"与"侧车声明了、且是 northwest"是两件事：
  //   前者意味着**这一页赖以定向的那条凭据不在**，后者才是拿到了凭据。
  //   图上下反了的校园图"看着也挺正常"（这正是这一条要防的），所以读不到必须出声。
  const orient = side?.enu_to_px?.origin_corner;
  if (orient === undefined || orient === null || orient === '') {
    problems.push('★ 侧车里读不到原点角（`enu_to_px.origin_corner`）——'
      + '本页按"行号 0 朝北"画，而**支撑这个画法的凭据不在**。'
      + '图上下反了是看不出来的，所以这一条不能静默。');
  } else if (orient !== 'northwest') {
    // ★ 这一条一旦为假，整页地图上下是反的 —— 而上下反了的校园图"看着也挺正常"。
    problems.push(`★ 侧车声明的原点角是 ${orient}，不是 northwest ——`
      + '本页按"行号 0 朝北"画，不认这个声明，先别信这张图。');
  }

  // ── ③ 建筑轮廓 ──────────────────────────────────────────────────────
  // ★★ 数据源是 `/campus/outlines.json`（341 条**真楼轮廓**），**不是**原来的
  //   `campus_lod1_blocks.json`（213 个 DSM−DTM 派生物块）。换掉的理由是**实测的**：
  //   那一层中位底面积 131 m²、中位高 4.2 m，最小的一批压在马路 / 绿化带 / 转盘 /
  //   工地围挡上 —— 它**不是楼的轮廓**（只有约 13 个 663~2450 m² 的大块真描在楼上）。
  //   而屏幕上当时印着"压在上面的轮廓是从 DSM − DTM 挤出来的体块""轮廓压在楼上"。
  //   **判词与它自己的数据不符**，这比"画得不好看"严重 —— 它会让人按错的地图下判断。
  //   铁律 141：字段的名字不是定义；铁律 174：两个同名的量必须死掉一个。
  const raw = Array.isArray(outlines?.outlines) ? outlines.outlines : [];
  const blocks = [];
  let badPoly = 0;
  for (const b of raw) {
    const p = b?.poly_en;
    if (!Array.isArray(p) || p.length < 3) { badPoly += 1; continue; }
    // 预先把 ENU 换成**图像像素坐标**：一次算好，之后每帧只做线性变换。
    const xy = new Float64Array(p.length * 2);
    let ok = true;
    let sx = 0, sy = 0;                 // 鞋带公式的分子（质心用）
    let cross = 0;                      // 2×有向面积
    for (let i = 0; i < p.length; i++) {
      const e = p[i]?.[0], n = p[i]?.[1];
      if (!Number.isFinite(e) || !Number.isFinite(n)) { ok = false; break; }
      xy[i * 2] = (e - f.e0) / mpp;
      xy[i * 2 + 1] = (f.n1 - n) / mpp;
    }
    if (!ok) { badPoly += 1; continue; }
    // 质心在**像素系**里算就够 —— ENU→像素是错切为零的线性变换，质心跟着走。
    // ★ 用真正的多边形质心（鞋带公式），不是顶点平均：L 形楼的顶点平均会落在楼外，
    //   而那一处正是拾取后"镜头要对准的地方"。
    for (let i = 0; i < p.length; i++) {
      const x0 = xy[i * 2], y0 = xy[i * 2 + 1];
      const j = (i + 1) % p.length;
      const x1 = xy[j * 2], y1 = xy[j * 2 + 1];
      const c = x0 * y1 - x1 * y0;
      cross += c; sx += (x0 + x1) * c; sy += (y0 + y1) * c;
    }
    const A = cross / 2;
    // 退化环（面积 0）会让除法给 NaN —— 那是"这个多边形画不出来"，不是"质心在原点"。
    // 下游（ortho-map 的 `if (!b?.centroid) return`）认的是 null，所以这里显式给 null，
    // 不让一个 NaN 冒充坐标（铁律 019：NaN 让判据恒不触发，而屏幕上什么都看不出来）。
    const cx = A === 0 ? NaN : sx / (6 * A);
    const cy = A === 0 ? NaN : sy / (6 * A);
    // ★ id 取短形（`ringsA[103]` → `A103`）：它是**环的编号**，也就是这一条在
    //   源 npz 里的身份。不许在这里编一个"楼栋号" —— 目前没有任何在盘上成立的
    //   对应关系能把环号映射到楼栋名（那正是锚点表要做的事）。
    const m = /^rings([AB])\[(\d+)\]$/.exec(String(b.ring ?? ''));
    blocks.push({
      id: m ? `${m[1]}${m[2]}` : String(b.ring ?? b.i),
      ring: b.ring, xy,
      area_m2: b.area_m2, h_m: b.h_m,
      height_caliber: b.height_caliber,
      ground_med_m: b.ground_med_m,
      on_hole: !!b.on_hole,
      n_vertices: p.length,
      centroid: Number.isFinite(cx) && Number.isFinite(cy) ? [cx, cy] : null,
    });
  }
  if (badPoly) {
    problems.push(`轮廓里有 ${badPoly} 条多边形的坐标读不出来（已跳过不画）`
      + ' —— 画出来的条数会少于清单里的条数，这两个数**不一样**这件事要说出来。');
  }
  if (!blocks.length) problems.push('轮廓清单是空的（或坐标全读不出来）—— 底图上不会有楼。');

  // ── ④ 图像 ──────────────────────────────────────────────────────────
  const url = API.url.campusOrtho();
  const img = new Image();
  const loaded = new Promise((res, rej) => {
    img.onload = () => res(true);
    // ★ 图片加载失败**不是**"这张图是空的" —— 分开说，否则底图会安静地变成一片白。
    img.onerror = () => rej(new Error(`正射底图加载失败：${url}`));
  });
  img.src = url;
  await loaded;
  if (img.naturalWidth !== width || img.naturalHeight !== height) {
    problems.push(`★ 图上屏的尺寸 ${img.naturalWidth}×${img.naturalHeight} 与侧车记的 `
      + `${width}×${height} 不符 —— 侧车里那些像素换算式对着的是**另一张图**。`);
  }

  // ★★ 画布要用到的两个尺寸，**在顶层给一次**。
  //   原先它们只在 `facts` 里（`facts.imgW`），而 `ortho-map.js` 读的是 `base.imgW`
  //   ⇒ 读到 `undefined` ⇒ `fitS = Math.min(vw/undefined, vh/undefined)` = **NaN**
  //   ⇒ `setTransform(NaN, …)` 被 Canvas 规范**静默忽略**（非有限参数的 setTransform
  //   不生效，变换停在单位阵）⇒ `drawImage(img,0,0)` 按 1:1 画，画布上只剩那张正射
  //   **左上角 554×587 的黑边**（NoData 带）—— 一整块纯黑，而**没有任何一步报错**。
  //   教训有两条，都写在这儿：
  //     ① 字段名不是字段（铁律 141）—— 读一个不存在的键不会报错，只会安静地给 undefined；
  //     ② NaN 进 Canvas API 是**静默**的，屏幕上的表现是"画了别的东西"，不是"出错了"。
  const imgW = img.naturalWidth, imgH = img.naturalHeight;
  if (!Number.isFinite(imgW) || !Number.isFinite(imgH) || imgW <= 0 || imgH <= 0) {
    // 走到这里说明图压根没解码出来（正常路径上 onload 已经等过了）——
    // 与其让下游拿到 NaN，不如当场说清楚。
    throw new Error(`正射底图解码后尺寸不可用：${imgW}×${imgH}（${url}）`);
  }

  // ── ③b 轮廓层与它自己声明的条数、与**当前** viewdata 的版本对一遍 ────────
  // ★ 这两条都是"两个来源"的核对（铁律 018：抄一次就有两个来源）：
  //   · 侧车里记着它生成时 viewdata 的 `criterion_version`；页面另从
  //     `/api/campus/viewdata` 现取一份。两者不一致 ⇒ 侧车是**对着一份旧名册**出的，
  //     那一刻屏幕上的轮廓与"建筑与空间"里列的楼可能已经不是同一批。
  //   · 侧车 `counts.outlines` 是**文件自己数的条数**，与我在上面循环里真正
  //     画出面的条数独立。少了就说明有环被静默跳过（那正是"213 个块"时代的老毛病：
  //     跳过的块不会出声，只会在屏幕上少一条线）。
  const declared = outlines?.counts?.outlines;
  if (Number.isFinite(declared) && declared !== blocks.length) {
    problems.push(`★ 轮廓条数对不上：文件声明 ${declared} 条，本页只画出 ${blocks.length} 条面`
      + '（差的那些读不出坐标，已跳过）—— 屏幕上少一条线是看不出来的。');
  }
  //   ★★ 第一版这里比的是 `view.criterion_version`（**地形**数据层的版本）——
  //   两个数各自来自**不同的文件**（地形 viewdata 是 10，建筑 viewdata 是 4），
  //   于是这条核对**每趟都会红**。假红的代价不只是吵：它会训练人忽略这一栏，
  //   于是真正的那条不一致也一起被忽略。要比就得比**轮廓侧车抄的那一份**：
  //   `source.viewdata` 写的是 `campus_buildings_viewdata.json`，对应的路由是
  //   `/api/campus/buildings.json`（`API.realBuildings()`）。
  const vdName = outlines?.source?.viewdata;
  const vdTag = outlines?.source?.viewdata_criterion_version;
  const vdV = outlines?.source?.viewdata_viewdata_version;
  if (vdName && vdTag && plan?.criterion_version && vdTag !== plan.criterion_version) {
    problems.push(`★ 轮廓侧车是按「${vdName}」的判据 v${vdTag} 生成的，`
      + `而本页现取的那一份是 v${plan.criterion_version}`
      + ' —— 侧车对着一份**旧名册**出的，它画的楼与"建筑与空间"里列的楼可能已经不是同一批。');
  }
  if (vdV && plan?.viewdata_version && vdV !== plan.viewdata_version) {
    problems.push(`★ 同上，数据层版本也对不上：侧车记 v${vdV}，现取 v${plan.viewdata_version}。`);
  }
  // ★ 第三个来源核对：建筑层的 ENU 原点必须与底图那一份**逐位相同**。
  //   两份都自称"从地形 viewdata 读回来的"，而"读回来"这件事抄了一次就有两个来源。
  //   原点差一点 ⇒ 轮廓整体平移一点 ⇒ 屏幕上只是"楼偏了一点点"，看不出来。
  for (const k of ['e0', 'n1']) {
    const a = plan?.grid?.[k], b = f[k];
    if (Number.isFinite(a) && Number.isFinite(b) && a !== b) {
      problems.push(`★ ENU 原点 ${k} 两个来源不一致：建筑数据层 ${a} ／ 底图侧车 ${b}`
        + ' —— 轮廓会整体平移，而屏幕上只是"楼偏了一点"。');
    }
  }
  if (plan?.counts?.buildings !== undefined && Number.isFinite(declared)
      && plan.counts.buildings !== declared) {
    problems.push(`★ 建筑数据层说它有 ${plan.counts.buildings} 栋，轮廓侧车有 ${declared} 条`
      + ' —— 这两份本该是同一批楼的两份视图（一份有数、一份有坐标）。');
  }

  // 屋顶高的实测范围 —— 印出去让人看见"这些高度是哪来的"。
  // ★★ 只在**带楼高**的那两档里取（`roof_p50` / `fallback_roof`）。把
  //   `fallback_ground` 那 94 条一起算进来的话，它们实测 h 中位是 **0.0 m**，
  //   于是屏幕上的"屋顶高"会印成 `0.0~69.9 m` —— 那一头是**地高**冒充楼高，
  //   而它看起来只是一个正常的区间下沿（铁律 124：一个名字指两个量）。
  const ROOF_CALIBERS = new Set(['roof_p50', 'fallback_roof']);
  const isRoof = (b) => ROOF_CALIBERS.has(b.height_caliber);
  const hs = blocks.filter(isRoof).map((b) => b.h_m).filter(Number.isFinite);
  const facts = {
    imageM: width && mpp ? [width * mpp, height * mpp] : null,
    nBlocks: blocks.length,
    nRoof: blocks.filter(isRoof).length,
    nGround: blocks.filter((b) => b.height_caliber === 'fallback_ground').length,
    nHole: blocks.filter((b) => b.on_hole).length,
    areaSum: blocks.reduce((s, b) => s + (Number.isFinite(b.area_m2) ? b.area_m2 : 0), 0),
    // 只算带楼高的那两档 —— 「建面合计」里混进 13610 m² 的**地**，那个数就不是建面了。
    areaSumRoof: blocks.filter(isRoof)
      .reduce((s, b) => s + (Number.isFinite(b.area_m2) ? b.area_m2 : 0), 0),
    hMin: hs.length ? Math.min(...hs) : null,
    hMax: hs.length ? Math.max(...hs) : null,
    mpp,
    grid: Number.isFinite(g.e0) ? g : f,
    source: side?.source ?? null,
    file: side?.file ?? null,
    // ── 轮廓层自己的凭据（原来的 lod1* 三件已随数据源一起换掉）────────────
    olVersion: outlines?.criterion_version ?? null,
    olSource: outlines?.source ?? null,
    olGates: outlines?.gates ?? null,
    olCounts: outlines?.counts ?? null,
    olCalibers: outlines?.height_calibers ?? null,
    olNote: outlines?.note ?? null,
    olBbox: outlines?.bbox_en ?? null,
    olAreaSum: Number.isFinite(outlines?.area_sum_m2) ? outlines.area_sum_m2 : null,
  };
  // ★ `imgW/imgH` 只放在**顶层**这一处（画布直接要用的契约量）。
  //   两处都有的话，将来改了图只改一处，另一处会安静地留着旧数（铁律 018）。
  return { img, url, mpp, grid: facts.grid, blocks, problems, facts, imgW, imgH };
}
