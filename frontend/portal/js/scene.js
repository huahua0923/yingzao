// 三维舞台：真地形底图 ＋ 模拟体块。
//
// ★ 坐标系（照抄 `frontend/admin/js/views/campus.js` 已验证的那一套，**不重推**）：
//   地形 GLB 的 POSITION **已经**是 ENU `(E−e0, 高程, n1−N)`，campus.js 对它
//   **没有施加任何变换**。所以这里也一个都不加 —— 加了就是"整体偏了一点"，
//   而屏幕上没有任何东西会喊。
//   `e0`/`n1`/`step`/`nx`/`ny` 一律从 `/api/campus/viewdata` **现读**，不写死。
//
// ★★ `POSITION` 的 `min.y = 0` 是**哨兵**（构建器把每个 NoData 顶点写在 y=0），
//   真地面在 449.5~500.8 m。谁拿包围盒当地面，谁就把体块与相机放到地下 463 m。
//   本文件里**一次都不读 `bb.min.y`** 当高程 —— 地面一律走自建的高程场。
//
// ★ 地面怎么找：**不用射线**。地形是 181k 顶点的高度场，逐块打射线要
//   375 条 × 36 万三角形，秒级卡顿。这里直接把 POSITION 顶点**分箱**成一张
//   与地形同格的粗高程表（O(n) 一次，~20 ms），之后每块查 9 个点取中位。
//   这不是"近似"——分箱的格子就是地形自己的 `step`（4.8 m）。
//
// ★ 阳性对照（装在代码里，不是装在报告里）：查到的每个高程必须落在
//   `viewdata.elev` 的 [min, max] 内。越界 ⇒ 高程场读错了（最可能是读到了
//   哨兵 0），当场报出来，而不是拿 0 当地面把体块埋进地心。

import * as THREE from 'three';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { layout, radiusOf } from './blocks.js';
import { API } from './api.js';

const PLATE = 0xEFEAE1;          // 与 --paper-2 同色：画布底与页面底连成一片
const SUN = 0xFFF6E8;

// 体块配色：**不是**写实材质，是图集里的三种标注色。
const C_MOCK      = 0x8C857A;    // 模拟（未锚定）—— 灰，不抢眼
const C_ANCHORED  = 0xB4571F;    // 已锚定 —— 朱，与 --accent 同族
const C_SELECT    = 0x2B2620;    // 选中 —— 近墨
const C_UNPLACED  = 0xC0392B;    // 没能落到地面上 —— 红，必须显眼

export function createScene(canvas, opts = {}) {
  const onPick = opts.onPick ?? (() => {});

  const renderer = new THREE.WebGLRenderer({ canvas, antialias: true });
  renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.setClearColor(PLATE, 1);

  const scene = new THREE.Scene();
  // 雾给远处一点大气感（校区对角线 ~2900 m）。★ 雾的 near 必须**远大于**
  // 相机到最远角的距离，否则整片校区会被洗成一片灰白 —— 那看起来像
  // "底图没加载出来"，而不像"雾设重了"。
  scene.fog = new THREE.Fog(PLATE, 4200, 13000);

  // ★ near 不许取 1~2：`near/far` 比值太大时深度缓冲精度不够，
  //   体块底面与地形之间会闪出条纹（z-fighting），而它看起来像
  //   "地形没铺平"。校区外接 ~2050 m，最远视距 ~8000 m ⇒ [5, 15000] 够用。
  const camera = new THREE.PerspectiveCamera(38, 1, 5, 15000);
  const controls = new OrbitControls(camera, canvas);
  controls.enableDamping = true;
  controls.dampingFactor = 0.075;
  controls.maxPolarAngle = Math.PI / 2 - 0.03;   // 不许转到地平线以下
  controls.minDistance = 40;
  controls.maxDistance = 6000;

  scene.add(new THREE.HemisphereLight(0xFFFFFF, 0x9C9484, 1.5));
  const sun = new THREE.DirectionalLight(SUN, 1.7);
  sun.position.set(-900, 1500, 700);
  scene.add(sun);
  scene.add(new THREE.AmbientLight(0xFFFFFF, 0.28));

  // ── 按需渲染：OrbitControls 一动就画一帧，静止时**不烧 GPU**。
  //    常驻 rAF 在"一屏不动看三分钟"的场景下纯属白烧，而这一页会开着很久。
  let raf = 0, disposed = false;
  function requestRender() {
    if (raf || disposed) return;
    raf = requestAnimationFrame(() => { raf = 0; renderer.render(scene, camera); });
  }
  controls.addEventListener('change', requestRender);

  // ── 尺寸：**必须盯容器盒子**，不是 window。
  //    这一页左右都有栏，窗口没变但主区会变（窄屏下详情栏挪到下面）。
  //    ★ 只设 drawingBuffer 不设 CSS 尺寸 = 画面被拉扁，而看不出是代码的事。
  let W = 1, H = 1;
  function syncSize() {
    const box = canvas.parentElement ?? canvas;
    const w = Math.max(1, box.clientWidth);
    const h = Math.max(1, box.clientHeight);
    if (w === W && h === H) return;
    W = w; H = h;
    renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
    renderer.setSize(w, h, false);
    canvas.style.width = `${w}px`;
    canvas.style.height = `${h}px`;
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
    requestRender();
  }
  const ro = typeof ResizeObserver !== 'undefined'
    ? new ResizeObserver(() => syncSize()) : null;
  ro?.observe(canvas.parentElement ?? canvas);
  window.addEventListener('resize', syncSize);

  const state = {
    ready: false,
    view: null,          // viewdata
    grid: null,
    blocks: [],          // 模拟体块（含 landY / mesh）
    unplaced: [],        // 没落到地面的块 id —— 必须在屏幕上说出来
    anchored: new Set(), // 已锚定的 block_id
    picked: null,
    group: null,
    terrain: null,
    groundMin: NaN, groundMax: NaN,
  };

  // ─────────────────────────────────────────── 高程场（不用射线）
  /**
   * 把地形顶点的 y 按 `(x,z)` 分箱成与地形同格的粗高程表。
   * 返回 `{get(x,z), nCell, nHit, note}`。
   */
  function buildHeightField(mesh, grid) {
    const pos = mesh.geometry.attributes.position;
    const n = pos.count;
    const S = grid.step, NX = grid.nx, NY = grid.ny;
    const xs = new Float64Array(n), zs = new Float64Array(n);
    const sum = new Float64Array(NX * NY);
    const cnt = new Int32Array(NX * NY);

    // 先取 x/z 的范围 —— **不许**用 `grid.e0/n1` 直接当原点：e0/n1 是
    // 网格角的**地理坐标**，而顶点减过原点之后落在 [0, (nx-1)*step] 上，
    // 两者差一个 step 就可能整体错一格（错一格 = 4.8 m 的高程错配）。
    let x0 = Infinity, z0 = Infinity;
    for (let i = 0; i < n; i++) {
      const x = pos.getX(i), z = pos.getZ(i);
      xs[i] = x; zs[i] = z;
      if (x < x0) x0 = x;
      if (z < z0) z0 = z;
    }
    let nHit = 0;
    for (let i = 0; i < n; i++) {
      const y = pos.getY(i);
      // ★ `y === 0` 是哨兵，不是地面。用一个明显高于误差、明显低于真地面的
      //   阈值把它挑出去 —— 真地面最低 449.5 m，取 1 m 已经很宽松。
      if (!Number.isFinite(y) || Math.abs(y) < 1) continue;
      const ix = Math.round((xs[i] - x0) / S);
      const iz = Math.round((zs[i] - z0) / S);
      if (ix < 0 || ix >= NX || iz < 0 || iz >= NY) continue;
      const k = iz * NX + ix;
      sum[k] += y; cnt[k]++; nHit++;
    }

    function at(ix, iz) {
      if (ix < 0 || ix >= NX || iz < 0 || iz >= NY) return NaN;
      const k = iz * NX + ix;
      return cnt[k] ? sum[k] / cnt[k] : NaN;
    }

    /** 查 (x,z) 处的地面高。空箱就往外找一圈半，仍空则 NaN（**不说 0**）。 */
    function get(x, z) {
      const ix = Math.round((x - x0) / S), iz = Math.round((z - z0) / S);
      for (let r = 0; r <= 3; r++) {
        let acc = 0, nAcc = 0;
        for (let dx = -r; dx <= r; dx++) {
          for (let dz = -r; dz <= r; dz++) {
            if (r > 0 && Math.max(Math.abs(dx), Math.abs(dz)) !== r) continue;
            const v = at(ix + dx, iz + dz);
            if (Number.isFinite(v)) { acc += v; nAcc++; }
          }
        }
        if (nAcc) return acc / nAcc;
      }
      return NaN;
    }

    return { get, nCell: NX * NY, nHit, x0, z0, note: `格 ${NX}×${NY}，命中顶点 ${nHit}/${n}` };
  }

  // ─────────────────────────────────────────── 体块几何
  /** 局部多边形（米，绕块心）→ THREE.Shape（XY 面；y = −z，见下）。 */
  function toShape(poly, hole) {
    // ★ 为什么 `y = −z`：`ExtrudeGeometry` 沿 +Z 挤出，之后整块要
    //   `rotateX(−90°)`，而该旋转把 `(x, y, z)` 映射成 `(x, z, −y)`。
    //   所以形状里的 y 对应世界的 −z，挤出深度对应世界的 +y。
    const v2 = (pts) => {
      const out = pts.map(([x, z]) => new THREE.Vector2(x, -z));
      // 绕向归一：外圈逆时针、洞顺时针。**必须做**，否则整个实体是
      // 里外翻的（外表面被背面剔除吃掉，看到的是内壁）。
      let a = 0;
      for (let i = 0; i < out.length; i++) {
        const p = out[i], q = out[(i + 1) % out.length];
        a += p.x * q.y - q.x * p.y;
      }
      return a < 0 ? out.reverse() : out;
    };
    const s = new THREE.Shape(v2(poly));
    if (hole) s.holes.push(new THREE.Path(v2(hole).slice().reverse()));
    return s;
  }

  /**
   * 建一块的网格。
   * @param block blocks.js 的块（`world` 是绕块心的多边形）
   * @param groundY 该块**自己**的地面高（查高程场得到，**不是包围盒**）
   */
  function buildBlockMesh(block, groundY, clipped) {
    // 底向下埋 1.5 m：地形是起伏的，地面只取了一组样本的**中位**，
    // 平底贴在斜坡上必然有一角悬空。做裙边比每角各自求高简单得多，
    // 而这里的目标是"看得出来是一栋楼"，不是精确填挖方。
    const SKIRT = 1.5;
    const shape = toShape(block.world, block.hole);
    const geo = new THREE.ExtrudeGeometry(shape, {
      depth: block.h, bevelEnabled: false, curveSegments: 6,
    });
    geo.rotateX(-Math.PI / 2);
    geo.translate(block.x, groundY - SKIRT, block.z);

    const mat = new THREE.MeshStandardMaterial({
      color: clipped === 'unplaced' ? C_UNPLACED : C_MOCK,
      roughness: 0.86, metalness: 0.0,
      // 斜拉的双面：底裙的侧面在斜坡上会露出来，单面会在那几处穿帮。
      side: THREE.DoubleSide,
    });
    const mesh = new THREE.Mesh(geo, mat);
    mesh.userData.blockId = block.id;
    mesh.userData.role = 'block';
    // 阴影那套本轮不开（没有 ShadowMap，省一轮 GPU 与一份阴影相机），
    // 用"顶面提亮一点"来给体块分层 —— 便宜且不依赖光源配置。
    return mesh;
  }

  /** 选中的块换颜色；其余还原。只动**材质颜色**，不重建几何。 */
  function paint() {
    for (const b of state.blocks) {
      const m = b.mesh?.material;
      if (!m) continue;
      const v = b.unplaced ? C_UNPLACED
        : b.id === state.picked ? C_SELECT
        : state.anchored.has(b.id) ? C_ANCHORED : C_MOCK;
      m.color.setHex(v);
    }
    requestRender();
  }

  // ─────────────────────────────────────────── 拾取
  const ray = new THREE.Raycaster();
  const ndc = new THREE.Vector2();
  let downAt = null;
  canvas.addEventListener('pointerdown', (e) => { downAt = { x: e.clientX, y: e.clientY }; });
  canvas.addEventListener('pointerup', (e) => {
    // ★ 拖动转视角**不是**点击。没有这个 4px 门槛的话，每一次转场都会选中
    //   手指底下那块 —— 而用户根本没打算选它。
    if (!downAt) return;
    const moved = Math.hypot(e.clientX - downAt.x, e.clientY - downAt.y);
    downAt = null;
    if (moved > 4 || !state.ready) return;

    const r = canvas.getBoundingClientRect();
    ndc.x = ((e.clientX - r.left) / r.width) * 2 - 1;
    ndc.y = -((e.clientY - r.top) / r.height) * 2 + 1;
    ray.setFromCamera(ndc, camera);
    const meshes = state.blocks.filter((b) => b.mesh && !b.unplaced).map((b) => b.mesh);
    const hits = ray.intersectObjects(meshes, false);
    // ★ 点空 ⇒ 取消选中（回 null），而不是"保持上一次"。
    //   保持的话，点一下空地再点详情栏，看到的还是上一栋，而没有任何提示。
    const id = hits.length ? hits[0].object.userData.blockId : null;
    if (id !== state.picked) { state.picked = id; paint(); }
    onPick(id);
  });

  // ─────────────────────────────────────────── 视角
  function fit(ext, center, gy, radius) {
    const d = radius * 1.9;
    camera.position.set(center.x - d * 0.62, gy + d * 0.78, center.z + d * 1.05);
    camera.far = Math.max(8000, radius * 12);
    camera.updateProjectionMatrix();
    controls.target.set(center.x, gy, center.z);
    controls.update();
    requestRender();
  }

  function home() {
    if (!state.ready) return;
    const { ext, center, gy, radius } = state;
    camera.position.set(center.x - ext.w * 0.50, gy + ext.w * 0.42, center.z + ext.d * 0.78);
    camera.far = 15000;
    camera.updateProjectionMatrix();
    controls.target.set(center.x, gy + 24, center.z);
    controls.update();
    requestRender();
  }

  /** 顶视：正上方看下去，接近正交 —— 看清平面关系时用。 */
  function top() {
    if (!state.ready) return;
    const { ext, center, gy } = state;
    const h = Math.max(ext.w, ext.d) * 1.15;
    camera.position.set(center.x, gy + h, center.z + 0.001);
    controls.target.set(center.x, gy, center.z);
    controls.update();
    requestRender();
  }

  /** 对准一块。 */
  function focus(blockId) {
    const b = state.blocks.find((x) => x.id === blockId);
    if (!b || !state.ready) return;
    const r = Math.max(radiusOf(b), 30);
    const gy = Number.isFinite(b.landY) ? b.landY : state.gy;
    fit(state.ext, new THREE.Vector3(b.x, 0, b.z), gy + b.h * 0.4, r);
  }

  // ─────────────────────────────────────────── 装配
  async function boot() {
    // ① 数据层先取 —— `glb.bytes` 是核对字节数的**唯一依据**（它是记录，不是复测）。
    const VD = await API.viewData();
    if (disposed) return;
    const grid = VD?.grid;
    if (!grid || !grid.nx || !grid.ny || !grid.step) {
      throw new Error('数据层里没有可用的 grid（nx/ny/step）—— 不猜，报出来');
    }
    state.view = VD; state.grid = grid;

    // ② 地形 GLB：**fetch + parse**，不用 loadAsync。
    //    loadAsync 会自己再发一次请求，那份字节数就看不见了 ——
    //    于是"数据层记的 glb.bytes"永远只是一句没人核过的记录。
    const r = await fetch(API.url.campusModel(), { cache: 'no-store' });
    if (!r.ok) throw new Error(`地形 HTTP ${r.status} ${r.statusText}`);
    const buf = await r.arrayBuffer();
    if (disposed) return;
    const want = Number(VD?.glb?.bytes);
    if (want && buf.byteLength !== want) {
      throw new Error(`拿到的地形是 ${buf.byteLength} 字节，数据层记的是 ${want} 字节`
        + `（sha ${VD.glb.sha256_12}）—— 不对着画。两份对不上说明盘上的交付件`
        + '与数据层不是同一批。');
    }
    const gltf = await new Promise((res, rej) => new GLTFLoader().parse(buf, '', res, rej));
    if (disposed) return;

    let mesh = null;
    gltf.scene.traverse((o) => { if (o.isMesh && !mesh) mesh = o; });
    if (!mesh) throw new Error('地形 GLB 里没有 Mesh —— 这份交付件是空的');
    // 底图不加任何变换：顶点已经是 ENU。
    mesh.userData.role = 'terrain';
    scene.add(gltf.scene);
    state.terrain = mesh;

    // ③ 高程场 ＋ 阳性对照
    const hf = buildHeightField(mesh, grid);
    const emin = Number(VD.elev?.min), emax = Number(VD.elev?.max);
    const lo = Number.isFinite(emin) ? emin - 1 : -Infinity;
    const hi = Number.isFinite(emax) ? emax + 1 : Infinity;
    state.groundMin = Number.isFinite(emin) ? emin : NaN;
    state.groundMax = Number.isFinite(emax) ? emax : NaN;

    // ④ 体块落位
    const { blocks, ext } = layout(grid);
    const group = new THREE.Group();
    group.name = 'mock-blocks';
    scene.add(group);
    state.group = group;

    let nBad = 0;
    for (const b of blocks) {
      // 取**散布在多边形内部**的样本（面向块心缩 6%），取中位。
      // 单点取样对 U 形/环形会取到内院 —— 内院在地形上没有网格，
      // 结果是"这块落不了地"，而它明明是落得下的。
      const cx = b.world.reduce((s, p) => s + p[0], 0) / b.world.length;
      const cz = b.world.reduce((s, p) => s + p[1], 0) / b.world.length;
      const samples = [];
      for (const [px, pz] of b.world) {
        const sx = px + (cx - px) * 0.12, sz = pz + (cz - pz) * 0.12;
        samples.push(hf.get(b.x + sx, b.z + sz));
      }
      samples.push(hf.get(b.x + cx, b.z + cz), hf.get(b.x, b.z));
      const ok = samples.filter(Number.isFinite).sort((a, c) => a - c);
      if (!ok.length) { b.unplaced = true; b.landY = NaN; state.unplaced.push(b.id); continue; }
      b.landY = ok[Math.floor(ok.length / 2)];
      // ★ 阳性对照：越界说明高程场读错了（最可能是读到了哨兵 0）。
      if (b.landY < lo || b.landY > hi) { b.unplaced = true; nBad++; state.unplaced.push(b.id); }
      b.mesh = buildBlockMesh(b, b.landY, b.unplaced ? 'unplaced' : null);
      group.add(b.mesh);
      state.blocks.push(b);
    }
    if (nBad) {
      throw new Error(`有 ${nBad} 块的高程落在数据层给的范围 [${lo}, ${hi}] 之外`
        + ' —— 高程场读错了（最可能是把哨兵 0 当成了地面）。不对着画。');
    }

    // ⑤ 取景
    const cx = ext.w / 2, cz = ext.d / 2;
    state.ext = ext;
    state.center = new THREE.Vector3(cx, 0, cz);
    // 地面参考高取"数据层的中位" —— 它是**记录**，只用来定相机目标点的高度，
    // 不参与任何体块的落位（体块各用各的实测地面高）。
    state.gy = Number.isFinite(Number(VD.elev?.median)) ? Number(VD.elev.median) : 463;
    state.radius = Math.max(ext.w, ext.d);
    state.view = VD;
    state.ready = true;

    syncSize();
    home();
    return state;
  }

  function dispose() {
    disposed = true;
    if (raf) cancelAnimationFrame(raf);
    ro?.disconnect();
    window.removeEventListener('resize', syncSize);
    controls.dispose();
    scene.traverse((o) => {
      if (o.isMesh) { o.geometry?.dispose?.(); o.material?.dispose?.(); }
    });
    renderer.dispose();
  }

  return {
    state, boot, dispose, home, top, focus, syncSize,
    setAnchored(ids) { state.anchored = new Set(ids); paint(); },
    select(id) { state.picked = id; paint(); },
    paint,
    requestRender,
  };
}
