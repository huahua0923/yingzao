// 「校区地形」视图 —— 真地形 DTM + 真影像正射合成的一份带贴图 GLB，摆在真实场地上看。
//
// ★ 这一屏是从 `_scratch/_campus3d/campus-terrain/view_campus.html` **原生重写**过来的，
//   不是 iframe 托管。那个页面是**我们自己写的 24 KB**（不像 `building.html` 是 128 KB
//   的成熟页），所以原生反而更省事；更要紧的是原生天然落在根上 ——
//   本仓的文档 URL 永远是 `/`（hash 路由），于是 `/api/...` 是根绝对路径，
//   一行基址都不用算。（iframe 才是"基址"这个问题的制造者。）
//
// ★★ 三条从源页**原样继承**的东西，一条都不能省 —— 它们各自对应一次已经栽过的账：
//
//   1. **高程只从数据层拿，绝不用包围盒。**
//      交付件 POSITION 的 `min.y = 0` 是**哨兵**：构建器
//      `build_campus_terrain_glb.py:1243` 的 `nan_to_num(verts, nan=0.0)` 把每个无高程
//      顶点写成了 0。真地面在 **449.5 ~ 500.8 m**。谁拿 `bb` 当地面，谁就把相机与探针
//      放到地面以下 463 m —— 而屏幕上只是一个"角度有点怪"的正常画面。
//      ⇒ `gy` / `gyTop` 一律走 `VD.elev`；数据层没载入就印「拿不到」，**不许退回 bb
//        还假装知道**（「不知道」与「0」必须分开写）。
//
//   2. **洞层一格一个四边形，且落点高程逐格来自数据层。**
//      洞里本来就没有高程，"洞里该画在哪"只能由 `interior_holes.y_marker` 给。
//      长度对不上或某一格不是有限数 ⇒ **不画**，而不是退回哨兵 ——
//      退回哨兵正是本页原来那个 bug（画在 y=0 ⇒ 地面以下 463 m ⇒ depthTest 挡掉 ⇒
//      洞层静默消失，与「洞层是空的」完全同形）。
//
//   3. **交付件字节数要真核一次。**
//      数据层里那句 `glb.bytes` / `sha256_12` 是**记录**，不是**复测**（铁律 24/50）。
//      源页把它印在清单上，却从没对着拿回来的字节比过一眼。这里补上：
//      字节数不符 ⇒ 报错、不照画。因为"这栋楼的模型不是数据层描述的那一份"这种事，
//      画出来是看不出来的（两个 GLB 都是同一片地形）。
//
// ★★ 与管理台契约有关的四处**刻意改动**（不是遗漏）：
//   · **不安装全局 `window.onerror`。** 源页是独享一页，`addEventListener('error')`
//     把任何异常都变成错误卡是合理的；在管理台里它是**跨视图的**：
//     切走之后钩子还在，别的视图的错会被画到这一屏已经拆掉的 DOM 上。
//     这里只用 try/catch 管住自己的失败面。
//   · **没有全局 id。** 源页用 `$('errmsg')` 这类全局 id；在管理台里 id 是全文档共享的，
//     换一屏就可能撞。全部改成闭包里的节点引用。
//   · **画布尺寸从 `.cp-stage` 的实测盒来**，不是 `innerWidth/innerHeight` ——
//     这一屏只占窗口的一部分（右边还有 440px 的读数栏）。用 `ResizeObserver` 盯那个盒子，
//     顺带把「窗口没变但布局变了」（导航折叠、面板滚动条出现）也一起接住。
//   · **`dispose()` 要真拆 WebGL。** 每进一次这一屏就新建一个上下文，浏览器上限约 16 个，
//     超了会**静默丢掉最老的** —— 症状是"点来点去三维就白了"，不报错、不警告。
//
// ★ 调试钩子 `__snapshot` / `__probeCells` / `__probeCell` / `__CAMPUS` **保留**：
//   它们是「洞层有没有画在真洞上」唯一能被**量**出来的途径（`verify_campus_view.py` 靠它们）。
//   但 `dispose()` 里必须**删掉** —— 否则探针会读到一个已经销毁的画布，
//   而"读回来一片空"与"这块地是黑的"在屏幕上是同一个样子（铁律 16）。
import * as THREE from 'three';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { el, add, mount } from '../dom.js';

export const label = '校区地形';

const VIEWDATA_URL = '/api/campus/viewdata';
const GLB_URL = '/api/campus/model.glb';
const HOLE_URL = (crop) => `/api/campus/hole/${encodeURIComponent(crop)}`;
// 建筑层（派生物：渠东 1:500 实测轮廓 × 实测屋顶高 nDSM）—— 与地形**并排的两份文件**，
// 刻意不并进地形 GLB：两份产物的来源、判据版本、更新节奏都不同，合成一份之后
// 「这个文件变了」就再也分不出是地形换了还是楼换了（同 criterion_version 与
// viewdata_version 必须分开印的那条理由）。
// ★ 两条都是**裸字节**（后端 FileResponse），与 VIEWDATA_URL 一样**不套本仓信封** ⇒
//   必须走裸 fetch，不许经 `js/api.js`（那个 api() 是拆信封的，套上去会解析失败）。
const BUILDINGS_GLB_URL = '/api/campus/buildings.glb';
const BUILDINGS_JSON_URL = '/api/campus/buildings.json';

// 底色与源页一致：管理台的暗室底色。three 的 scene.background 会盖在它上面，
// 这一层兜的是「画布还没挂上」的那几帧。
const PLATE = 0x0b0f14;
const HOLE_RGBA = 0xf2a516;
// 明暗两档下洞层的透明度：无光时压暗一点，否则纯色会把纹理吃掉。
const HOLE_OPACITY = { lit: 0.42, flat: 0.30 };

// 模块内的状态：切视图时 dispose() 全靠它把东西收干净。
const S = {
  renderer: null, scene: null, camera: null, controls: null,
  mesh: null, srcMat: null, flatMat: null, overlay: null, terrain: null, bldgs: null,
  ro: null, raf: 0, hooks: [],
};
let disposed = false;

/** SVG 节点必须走 createElementNS —— `dom.el()` 用的 createElement 建出来的是
 *  HTMLUnknownElement：**不渲染、也不报错**（屏幕上就是"罗盘不见了"）。 */
const SVG_NS = 'http://www.w3.org/2000/svg';
function svg(tag, attrs = {}, ...children) {
  const n = document.createElementNS(SVG_NS, tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v === null || v === undefined || v === false) continue;
    n.setAttribute(k, String(v));
  }
  add(n, children);
  return n;
}

/** 一行读数。值可以是多个节点/字符串（`el` 的 add 会跳过 null/false）。 */
const kv = (k, ...val) => el('div', { class: 'cp-kv' },
  el('span', { class: 'cp-k', text: k }),
  el('span', { class: 'cp-v' }, val));

/** 明说「拿不到」。**不许印 0** —— 印成 0 是假话，而且会把该出现的告警一起吞掉。 */
const miss = (why) => ['拿不到', el('b', { class: 'cp-miss', text: '（数据层缺失）' }), why];

export function dispose() {
  disposed = true;
  cancelAnimationFrame(S.raf);
  S.raf = 0;
  for (const f of S.hooks.splice(0)) {
    try { f(); } catch { /* 收尾失败不该挡住切视图 */ }
  }
  S.ro?.disconnect();
  S.ro = null;

  // 调试钩子必须跟着这一屏一起消失（见文件头）。
  for (const k of ['__snapshot', '__probeCells', '__probeCell', '__CAMPUS']) {
    try { delete window[k]; } catch { window[k] = undefined; }
  }

  // 几何/材质/贴图逐个还回去。8 MB 的 GLB 里有正射贴图，光丢引用等 GC 会让
  // 显存峰值落在"下次进来"的时候（那时又要新建一个上下文）。
  const kill = (root) => {
    if (!root) return;
    root.traverse?.((o) => {
      o.geometry?.dispose?.();
      const ms = Array.isArray(o.material) ? o.material : (o.material ? [o.material] : []);
      for (const m of ms) {
        for (const k of ['map', 'normalMap', 'aoMap', 'roughnessMap', 'metalnessMap']) {
          m[k]?.dispose?.();
        }
        m.dispose?.();
      }
    });
  };
  kill(S.terrain);
  kill(S.overlay);
  // ★ 楼栋层和地形一样是一整套 geometry + material（341 栋的挤出体块），而且它是
  //   **按需载入**的 —— 只有点过按钮、且真取成功之后才存在。漏掉这一句不会有任何
  //   报错，只会让显存留在那里；攒几次就撞上 16 个上下文的上限（见文件头）。
  kill(S.bldgs);
  S.flatMat?.dispose?.();      // flatMat 与 srcMat 共用 map，上面已释放；材质对象本身还欠一次
  S.controls?.dispose?.();
  if (S.renderer) {
    S.renderer.dispose();
    // forceContextLoss 是**必须**的：`dispose()` 只还 three 自己的资源，
    // 浏览器的 WebGL 上下文还活着，16 个上限照样会被吃掉。
    S.renderer.forceContextLoss?.();
    S.renderer.domElement?.remove?.();
  }
  S.renderer = S.scene = S.camera = S.controls = null;
  S.mesh = S.srcMat = S.flatMat = S.overlay = S.terrain = S.bldgs = null;
}

/**
 * @param {HTMLElement} root 挂载点（app.js 给的是 #main）
 */
export async function render(root) {
  disposed = false;

  // ──────────────────────────────────────────────────────────── DOM
  // ★ 布局契约（campus.css）：`.cp-ctl` / `.cp-compass` / `.cp-crop` / `.cp-err` 是
  //   `.cp-stage` 的**兄弟**，四个都挂在 `.cp-wrap` 上 —— 前三个用 absolute 定位，
  //   它们的 left/right 是相对**整个 wrap** 算的（所以 CSS 刻意减掉了右栏那 440px）。
  //   挂到 `.cp-stage` 里会让罗盘压到读数面板上，而屏幕上只是「位置有点怪」。
  const stage = el('div', { class: 'cp-stage' });
  const kvs = el('div', { class: 'cp-kvs' });
  const blks = el('div', { class: 'cp-blks' });
  const holenote = el('div', { class: 'cp-note' });
  const side = el('div', { class: 'cp-side' },
    el('h2', { class: 'cp-side-h', text: '这份地形是什么' }),
    kvs,
    el('div', { class: 'cp-sect', text: '没有数据的地方（洞）' }),
    blks,
    holenote);

  const btnIso = el('button', { class: 'cp-btn', type: 'button', 'aria-pressed': 'true', text: '立体' });
  const btnTop = el('button', { class: 'cp-btn', type: 'button', 'aria-pressed': 'false', text: '俯视' });
  const btnHole = el('button', { class: 'cp-btn', type: 'button', 'aria-pressed': 'true', text: '洞层' });
  const btnLit = el('button', { class: 'cp-btn', type: 'button', 'aria-pressed': 'true', text: '明暗' });
  // 楼栋层：**起始是「关」**。它与 btnHole / btnLit 不是一回事 —— 那两层在入场时就
  // 画好了，写「开」是实话；这一层**此刻一个顶点都还没有**（178 KB 的派生物点了才去拿）
  // ⇒ 写「开」等于在无障碍树上说一句假话，屏幕上也会被读成「这层没有楼」。
  // 第一次点 = 「我要看这一层」（载入那一段**强制显示并按下按钮**），之后才是来回切。
  // 取不到就当场禁用并把原因写进 `title`（见下面那一段），绝不留按了没反应的按钮。
  // ※ 这两处**必须一起改**：载入那一段若改成读 `aria-pressed` 决定显示不显示，
  //   起始的 `false` 就会让第一次点白点一下、第二下才看得见（"按了没反应"的老形状）。
  const btnBld = el('button', { class: 'cp-btn', type: 'button', 'aria-pressed': 'false', text: '楼栋' });
  const ctl = el('div', { class: 'cp-ctl' }, btnIso, btnTop, btnHole, btnLit, btnBld,
    el('span', { class: 'cp-hint', text: '拖拽旋转 · 滚轮缩放 · 右键平移' }));

  // 罗盘。0° = 针朝上；下面每帧按相机基向量转它。
  const needle = svg('svg', { width: 54, height: 54, viewBox: '0 0 54 54', class: 'cp-needle' },
    svg('circle', { cx: 27, cy: 27, r: 24, fill: 'none', stroke: 'rgba(255,255,255,.14)' }),
    svg('path', { d: 'M27 5 L33 29 L27 25 L21 29 Z', fill: '#f2a516' }),
    svg('path', { d: 'M27 49 L21 31 L27 35 L33 31 Z', fill: 'rgba(255,255,255,.26)' }),
    svg('text', {
      x: 27, y: 15, fill: '#8b9aa8', 'font-size': 9, 'text-anchor': 'middle',
      'font-family': 'ui-monospace,monospace',
    }, '北'));
  const compass = el('div', { class: 'cp-compass', title: '针指向真北' }, needle);

  const cropImg = el('img', { class: 'cp-crop-img', alt: '洞底下盖着什么（正射实拍裁剪，红框为洞）' });
  const cropCap = el('div', { class: 'cp-crop-cap' });
  const crop = el('div', { class: 'cp-crop' }, cropImg, cropCap);

  const errMsg = el('pre', { class: 'cp-err-msg' });
  const errBox = el('div', { class: 'cp-err' },
    el('h3', { class: 'cp-err-h', text: '地形没能加载' }), errMsg);

  const wrap = el('div', { class: 'cp-wrap' }, stage, side, ctl, compass, crop, errBox);
  mount(root, wrap);

  /** 出错：把卡片点亮并把原因写全。**不静默** —— 空白画布会被读成"这里本来就没东西"。 */
  const die = (msg) => {
    errMsg.textContent = String(msg);
    errBox.classList.add('cp-on');
    console.error('[campus]', msg);
  };
  const undie = () => errBox.classList.remove('cp-on');

  blks.appendChild(el('div', { class: 'cp-kv' },
    el('span', { class: 'cp-v', text: '正在取地形……' })));

  // 遮罩：整块面就是"点一下关掉"的目标，Esc 同样关（两条都留着 ——
  // 只给点击的话键盘用户出不去）。
  const closeCrop = () => crop.classList.remove('cp-on');
  const onCropClick = () => closeCrop();
  const onKey = (e) => { if (e.key === 'Escape') closeCrop(); };
  crop.addEventListener('click', onCropClick);
  window.addEventListener('keydown', onKey);
  S.hooks.push(() => crop.removeEventListener('click', onCropClick));
  S.hooks.push(() => window.removeEventListener('keydown', onKey));

  const openCrop = (file, b) => {
    cropImg.src = HOLE_URL(file);
    cropCap.textContent = `${b.cells} 格 · ${b.area_m2} m²`
      + '（红框 = 洞；这是正射实拍，不是渲染）';
    crop.classList.add('cp-on');
  };

  // ────────────────────────────────────────────────────── 数据层
  // ★ 裸 fetch，不走 api.js：`/api/campus/viewdata` 刻意**不套本仓信封**
  //   （套了就要重新序列化一遍，浮点写法会变，发出去的字节就不再是盘上那份交付件了）。
  //   代价就是这里得自己对 `r.ok` 分支 —— 这是那条取舍得付的钱。
  let VD = null;
  let vdErr = null;
  try {
    const r = await fetch(VIEWDATA_URL, { cache: 'no-store' });
    if (!r.ok) throw new Error(`数据层 HTTP ${r.status} ${r.statusText}`);
    VD = await r.json();
  } catch (e) {
    // 数据层坏了**不能**连带把地形也藏起来：地形照画，只是洞层与高程说明白"拿不到"。
    vdErr = String((e && e.message) || e);
    console.warn('[campus] 数据层没读到', e);
  }
  if (disposed) return;

  // ────────────────────────────────────────────────────── 场景
  // preserveDrawingBuffer：**读回像素**必须开。默认 false 时帧渲完缓冲就被清了，
  // 在 render 之外读回来的是**一片空**，而它和"这块地是黑的"在屏幕上一样（铁律 16）。
  const renderer = new THREE.WebGLRenderer({
    antialias: true, alpha: false, preserveDrawingBuffer: true,
  });
  renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.setClearColor(PLATE, 1);
  stage.appendChild(renderer.domElement);

  const scene = new THREE.Scene();
  scene.background = new THREE.Color(PLATE);
  const camera = new THREE.PerspectiveCamera(38, 1, 5, 40000);
  const controls = new OrbitControls(camera, renderer.domElement);
  controls.enableDamping = true;
  controls.dampingFactor = 0.075;
  controls.maxPolarAngle = Math.PI * 0.495;   // 不许钻到地平线以下

  const amb = new THREE.AmbientLight(0xffffff, 2.2);
  const d1 = new THREE.DirectionalLight(0xffffff, 2.6);
  const d2 = new THREE.DirectionalLight(0xffffff, 1.0);
  scene.add(amb, d1, d2);

  Object.assign(S, { renderer, scene, camera, controls, hooks: S.hooks });

  /** 画布尺寸 = `.cp-stage` 的实测盒（不是窗口）。dpr 变了也走这里。 */
  function syncSize() {
    if (disposed || !stage.clientWidth) return;
    const w = stage.clientWidth, h = stage.clientHeight;
    renderer.setPixelRatio(Math.min(devicePixelRatio, 2));   // 拖到另一块屏时 dpr 会变
    renderer.setSize(w, h, false);
    renderer.domElement.style.width = `${w}px`;
    renderer.domElement.style.height = `${h}px`;
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
  }
  syncSize();
  // 盯盒子而不是盯窗口：导航折叠、面板出滚动条都会改盒子，却不一定触发 resize。
  if (typeof ResizeObserver !== 'undefined') {
    const ro = new ResizeObserver(() => syncSize());
    ro.observe(stage);
    S.ro = ro;
  }
  const onWinResize = () => syncSize();
  window.addEventListener('resize', onWinResize);
  S.hooks.push(() => window.removeEventListener('resize', onWinResize));

  // ────────────────────────────────────────────────────── 取 GLB
  // ★ 用 fetch + parse，而不是 loadAsync：**只下一次** 8 MB，同时拿到字节数。
  //   loadAsync 自己会再发一次请求，那份字节数就看不见了 —— 于是"数据层记的
  //   glb.bytes"永远只是一句没人核过的记录。
  let gltf = null;
  try {
    const r = await fetch(GLB_URL, { cache: 'no-store' });
    if (!r.ok) throw new Error(`地形 HTTP ${r.status} ${r.statusText}`);
    const buf = await r.arrayBuffer();
    if (disposed) return;

    // ★ 一致性核对：**不符就报错，不照画**。两个版本的地形 GLB 画出来长得一样，
    //   没有任何一处会喊"我拿到的不是数据层描述的那一份"。
    const want = VD && VD.glb && Number(VD.glb.bytes);
    if (want && buf.byteLength !== want) {
      throw new Error(`拿到的地形是 ${buf.byteLength} 字节，数据层记的是 ${want} 字节`
        + `（sha ${VD.glb.sha256_12}）—— 不对着画。`
        + '两份对不上说明盘上的交付件与数据层不是同一批，重跑 export_view_data.py。');
    }
    gltf = await new Promise((res, rej) => new GLTFLoader().parse(buf, '', res, rej));
  } catch (e) {
    die(e);
  }
  if (disposed) return;

  let mesh = null;
  let bb = null;
  let srcMat = null;
  let overlay = null;
  let ex = 0, ez = 0, ey = 0, gy = 0, gyTop = 0, cx = 0, cz = 0;

  if (gltf) {
    try {
      const terrain = gltf.scene;
      terrain.traverse((o) => { if (o.isMesh && !mesh) mesh = o; });
      if (!mesh) throw new Error('GLB 里没有 Mesh —— 这份交付件是空的');
      scene.add(terrain);
      mesh.geometry.computeBoundingBox();
      bb = mesh.geometry.boundingBox.clone();
      srcMat = Array.isArray(mesh.material) ? mesh.material[0] : mesh.material;

      ex = bb.max.x - bb.min.x;
      ez = bb.max.z - bb.min.z;
      // y 方向**不许用 bb**（见文件头第 1 条）。
      const hasElev = !!(VD && VD.elev);
      gy = hasElev ? VD.elev.min : bb.min.y;
      gyTop = hasElev ? VD.elev.max : bb.max.y;
      ey = gyTop - gy;
      cx = bb.min.x + ex / 2;
      cz = bb.min.z + ez / 2;

      d1.position.set(-ex * 0.55, ey + 1400, ez * 0.6);
      d2.position.set(ex * 0.75, ey + 700, -ez * 0.7);
    } catch (e) {
      die(e);
    }
  }
  if (disposed) return;

  const home = new THREE.Vector3(cx + ex * 0.62, gyTop + ey + 900, cz + ez * 1.25);
  const target = new THREE.Vector3(cx, gy + ey * 0.35, cz);
  camera.position.copy(home);
  controls.target.copy(target);
  controls.update();

  function isoView() {
    camera.up.set(0, 1, 0);
    camera.position.copy(home);
    controls.target.copy(target);
    camera.lookAt(controls.target);
    controls.update();
  }
  // 俯视：**屏幕上方 = 北**（up = -Z），与 preview PNG、与构建器 C7 的行序同一套朝向。
  // 有了这个固定位姿，"洞层画在哪"才是一件可以**量**的事（见 __probeCells）。
  function topView() {
    syncSize();                                // aspect 要按当前盒子
    const half = Math.tan(THREE.MathUtils.degToRad(camera.fov / 2));
    const needZ = (ez / 2) / half, needX = (ex / 2) / (half * camera.aspect);
    // ey 是**真落差**（51.3 m），不是哨兵撑出来的 500.8 —— 相机高度与支点都按真地面摆。
    const d = Math.max(needZ, needX) * 1.03 + ey;
    camera.up.set(0, 0, -1);
    camera.position.set(cx, gyTop + d, cz);
    controls.target.set(cx, gy, cz);
    camera.lookAt(controls.target);
    controls.update();
  }
  const setPose = (which) => {
    btnIso.setAttribute('aria-pressed', String(which === 'iso'));
    btnTop.setAttribute('aria-pressed', String(which === 'top'));
    if (which === 'iso') isoView(); else topView();
  };
  btnIso.addEventListener('click', () => setPose('iso'));
  btnTop.addEventListener('click', () => setPose('top'));
  // 手动转过之后就不再是那两个固定位姿了 —— 别让按钮显示一个假的"当前状态"。
  const onCtlStart = () => {
    btnIso.setAttribute('aria-pressed', 'false');
    btnTop.setAttribute('aria-pressed', 'false');
  };
  controls.addEventListener('start', onCtlStart);
  S.hooks.push(() => controls.removeEventListener('start', onCtlStart));

  // ────────────────────────────────────────────── 调试钩子（可量的那一半）
  // 唯一的用途是让"洞层有没有画在真洞上"可以被量。世界系：x = 列*step（向东增）、
  // z = 行*step（向南增），见构建器 :329-332。
  // 整帧只读一次、缓存在 __snap：逐点各读一次整画布，163 格就是 163 次全屏 drawImage。
  let snap = null;
  window.__snapshot = () => {
    const W = renderer.domElement.width, H = renderer.domElement.height;
    const cv = document.createElement('canvas');
    cv.width = W; cv.height = H;
    const ctx = cv.getContext('2d', { willReadFrequently: true });
    ctx.drawImage(renderer.domElement, 0, 0);
    snap = { W, H, px: ctx.getImageData(0, 0, W, H).data };
    return { W, H };
  };
  // 批量版：一次往返量一批。两种"没有读数"要分开：
  //   返回 null          —— 该格投影到屏幕外（位置问题）
  //   返回 {rgb: null}   —— 还没抓过快照（没量，不是"读到了黑"）（铁律 16）
  //
  // ★ y 是**必填**，而且必须是**该格自己的地面高**。早先这里写死 bb.min.y + 0.6
  //   ⇒ 探针落在**地面以下 463 m**，透视投影下屏幕偏 39~40 px（洞格只有 1.6 px 宽）
  //   ⇒ 读回来的是**隔壁的地形**，而它长得像"这里没有洞"。
  //   ⇒ 不给默认值：默认值正是那个错。缺 y 就抛，别让它悄悄退回旧行为。
  window.__probeCells = (triples) => {
    const step = VD.grid.step;
    const W = snap ? snap.W : renderer.domElement.width;
    const H = snap ? snap.H : renderer.domElement.height;
    const d = snap ? snap.px : null;
    return triples.map((t) => {
      const j = t[0], i = t[1], y = t[2];
      if (!Number.isFinite(y)) {
        throw new Error(`__probeCells: 格 (${j},${i}) 没给 y —— `
          + '该格自己的地面高是必填的（bb.min.y+0.6 是哨兵，会把点放到地面下 463 m）');
      }
      const p = new THREE.Vector3((i + 0.5) * step, y, (j + 0.5) * step);
      p.project(camera);
      const x = Math.round((p.x * 0.5 + 0.5) * W);
      const yy = Math.round((-p.y * 0.5 + 0.5) * H);
      if (p.z > 1 || x < 0 || yy < 0 || x >= W || yy >= H) return null;
      if (!d) return { x, y: yy, rgb: null };
      const k = (yy * W + x) * 4;
      return { x, y: yy, rgb: [d[k], d[k + 1], d[k + 2]] };
    });
  };
  window.__probeCell = (j, i, y) => window.__probeCells([[j, i, y]])[0];

  // ────────────────────────────────────────────────────── 洞层
  // ★ 只在**有真影像、却因缺高程没渲出来**的地方铺琥珀色 ——
  //   洞不是背景噪点，是"这里没有数据"，必须长成看得懂的样子。
  function buildOverlay() {
    if (!VD || !VD.interior_holes) return null;
    const step = VD.grid.step;
    const mark = VD.interior_holes.y_marker;
    // 先验**长度**，再动一个顶点（见文件头第 2 条）。
    if (!Array.isArray(mark) || mark.length !== VD.interior_holes.cells) {
      die(`数据层里没有 ${VD.interior_holes.cells} 个洞格落点高程（读到的 y_marker=`
        + `${Array.isArray(mark) ? mark.length + ' 个' : String(mark)}）`
        + '—— 洞层没法落在真地面上，本次不出洞层。'
        + '页面是新的、数据层是旧的，重跑 export_view_data.py 即可');
      return null;
    }
    const v = [], idx = [];
    // ★ 一格一个四边形（不是一段一个）：每格的高程**各不相同**，合成一段就得挑一个
    //   代表值，那就是自造数据。代价是 163 个四边形而不是 15 个 —— 无所谓。
    //   顺序 = rows_rle 的枚举顺序（行升序 → 段左到右 → 格升序），与 y_marker 的
    //   填充顺序**逐格对齐**；这是契约，对不上就由下面那条格数恒等式喊出来。
    let n = 0;
    for (const [j, runs] of VD.interior_holes.rows_rle) {
      for (const [c0, len] of runs) {
        for (let c = c0; c < c0 + len; c++) {
          const y = mark[n];
          if (!Number.isFinite(y)) {
            die(`第 ${n} 格的落点高程不是有限数（${String(y)}）—— 不出洞层`);
            return null;
          }
          const x0 = c * step, x1 = (c + 1) * step;
          const z0 = j * step, z1 = (j + 1) * step;
          const b = n * 4;
          v.push(x0, y, z0, x1, y, z0, x1, y, z1, x0, y, z1);
          idx.push(b, b + 1, b + 2, b, b + 2, b + 3);
          n += 1;
        }
      }
    }
    // ★ 跨来源恒等式（不是同源自证）：这一屏自己一格格数出来的格数，必须等于数据层
    //   自己声明的格数。两者独立算、对不上就说明画的不是那批洞 ⇒ 当场喊，不静默画。
    if (n !== VD.interior_holes.cells) {
      die(`洞层覆盖 ${n} 格，而数据层声称 ${VD.interior_holes.cells} 格`
        + ' —— 画的不是那批洞，本次不出洞层');
      return null;
    }
    const g = new THREE.BufferGeometry();
    g.setAttribute('position', new THREE.Float32BufferAttribute(v, 3));
    g.setIndex(idx);
    const m = new THREE.MeshBasicMaterial({
      color: HOLE_RGBA, transparent: true, opacity: HOLE_OPACITY.lit,
      side: THREE.DoubleSide, depthWrite: false,
    });
    const o = new THREE.Mesh(g, m);
    // ★ 写在**被读的那一处**：tick() 读的是 overlay.userData.cells（mesh 的），
    //   而 mesh.userData 与 geometry.userData 是两个对象 —— 写到 geometry 上
    //   读出来是 undefined，不报错、只是屏幕上变 null，与「洞层是空的」同形（铁律 16）。
    o.userData.cells = n;
    return o;
  }
  overlay = buildOverlay();
  if (overlay) {
    scene.add(overlay);
    overlay.visible = btnHole.getAttribute('aria-pressed') === 'true';
  }
  btnHole.disabled = !overlay;
  if (!overlay) {
    btnHole.setAttribute('aria-pressed', 'false');
    btnHole.title = VD ? '数据层里没有可用的洞格落点 ⇒ 这一层出不来' : '数据层没读到 ⇒ 位置画不出来';
  }
  const onHole = () => {
    const on = btnHole.getAttribute('aria-pressed') !== 'true';
    btnHole.setAttribute('aria-pressed', String(on));
    if (overlay) overlay.visible = on;
  };
  btnHole.addEventListener('click', onHole);
  S.hooks.push(() => btnHole.removeEventListener('click', onHole));

  // ────────────────────────────────────────────────────── 楼栋层（派生物，按需取）
  // ★ 与地形**共用同一个 ENU 系**（顶点 = (E-e0, 高程, n1-N)）⇒ 直接加进同一个 scene，
  //   **一个变换都不加**，跟地形网格一样。给它套一个 transform 就等于换了个基准，
  //   而屏幕上只是「楼整体偏了一点」，看不出是坐标系的事。
  // ★ 楼**不许**挂到 terrain 底下：那样一来任何碰 terrain 子树的动作都会连楼一起
  //   带走，而开关是两个 ⇒ 屏幕上就是「点了楼栋，什么都没发生」。
  // ★ 取 178 KB 是**点了才花**：这一屏的主产物是地形，楼是派生物，不该在入场时就
  //   多付一次往返（尤其数据层还没读出来的时候）。
  let bldgsLoading = false;   // 连点两次不许发两次请求（也防住 parse 出两份场景）
  let bldgsVD = null;         // 楼栋自己的数据层：只用来核对字节数、报栋数与色阶
  const onBld = async () => {
    if (bldgsLoading) return;
    if (S.bldgs) {                                   // 已载入：只翻可见性
      const on = btnBld.getAttribute('aria-pressed') !== 'true';
      btnBld.setAttribute('aria-pressed', String(on));
      S.bldgs.visible = on;
      return;
    }
    bldgsLoading = true;
    btnBld.disabled = true;                          // 取的这几百毫秒里按不动
    try {
      // 数据层先取：`glb.bytes` 是**核对字节数的唯一依据**（它是记录，不是复测）。
      // 拿不到不算致命 —— 楼照画，只是「对不对得上」这一问当次答不出来，如实印出来。
      // 裸 fetch：这两条路由都不套本仓信封（同 VIEWDATA_URL 那条注释）。
      try {
        const rj = await fetch(BUILDINGS_JSON_URL, { cache: 'no-store' });
        if (rj.ok) bldgsVD = await rj.json();
        else console.warn('[campus] 建筑层数据层 HTTP', rj.status, rj.statusText);
      } catch (e) {
        console.warn('[campus] 建筑层数据层没读到', e);
      }
      if (disposed) return;                          // 切走了就别碰已销毁的 scene

      const r = await fetch(BUILDINGS_GLB_URL, { cache: 'no-store' });
      if (!r.ok) throw new Error(`建筑层 HTTP ${r.status} ${r.statusText}`);
      const buf = await r.arrayBuffer();
      if (disposed) return;

      // ★ 与地形那一处**同一条核对**：不符就不照画。两个版本的楼画出来都像楼，
      //   没有任何一处会喊「我拿到的不是数据层描述的那一份」。
      const want = bldgsVD && bldgsVD.glb && Number(bldgsVD.glb.bytes);
      if (want && buf.byteLength !== want) {
        throw new Error(`拿到的建筑层是 ${buf.byteLength} 字节，数据层记的是 ${want} 字节`
          + `（sha ${bldgsVD.glb.sha256_12}）—— 不对着画。`
          + '两份对不上说明盘上的派生物与数据层不是同一批，重跑建筑层构建器。');
      }
      const g = await new Promise((res, rej) => new GLTFLoader().parse(buf, '', res, rej));
      if (disposed) return;

      scene.add(g.scene);                            // 兄弟对象，**不挂 terrain**
      // ★ 第一次点 = 「我要看这一层」⇒ **强制显示 + 按下按钮**，不读 `aria-pressed`。
      //   读它就得让起始那一个 `'true'` 撑着，而那就是上面说过的假话；
      //   两处一起改，才既不说假话、又不白点一下。
      g.scene.visible = true;
      btnBld.setAttribute('aria-pressed', 'true');
      S.bldgs = g.scene;
      btnBld.disabled = false;

      // 读数只在**真的画出来之后**才补：先印「341 栋」再失败，那一行就成了一句假话。
      const c = bldgsVD && bldgsVD.counts;
      const hm = bldgsVD && bldgsVD.height_m;
      const numOk = hm && ['min', 'max', 'median'].every((k) => Number.isFinite(Number(hm[k])));
      // ★ 两个版本号都要**先判 undefined 再拼**（同上面地形那一行的写法）：模板串里
      //   一个没值的变量会原样印成 `vundefined` —— 屏幕上是一个正常的短词，
      //   看不出那是「这个字段根本没有」（本仓已栽过：template-string-prints-undefined）。
      const vOf = (x) => (x === undefined || x === null ? '?' : x);
      if (c && Number.isFinite(Number(c.buildings)) && numOk) {
        add(kvs, kv('楼栋', `${Number(c.buildings)} 栋 · 高 ${Number(hm.min).toFixed(1)} … `
          + `${Number(hm.max).toFixed(1)} m（中位 ${Number(hm.median).toFixed(1)}）`
          + ` · 判据 v${vOf(bldgsVD.criterion_version)}`
          + ` · 数据层 v${vOf(bldgsVD.viewdata_version)}`
          + ` · 已核 ${buf.byteLength} 字节`));
      } else {
        // ★ 数据层没读到 ⇒ 这一层的**身份没核过**。它与「核过了、对得上」必须长得
        //   不一样（铁律 16）—— 否则「没量」会被读成「没问题」。
        add(kvs, kv('楼栋', '建筑层已画出来，但数据层没读到 ⇒ 这层有多少栋、'
          + '以及画的这一份是不是数据层描述的那一份，当次都没核（不是「核过了」）。'));
      }
    } catch (e) {
      // ★ 建筑层是**派生物**：它坏了不能把地形一起报成失败（同「数据层坏了不藏地形」）。
      //   处置 = 禁用按钮 + 原因写进 title + 读数栏留一行「拿不到」，三处都要有：
      //   只写 title 的话，不悬停就看不见，而空着的读数栏会被读成「这层没有楼」。
      const why = String((e && e.message) || e);
      btnBld.disabled = true;
      btnBld.setAttribute('aria-pressed', 'false');
      btnBld.title = `建筑层取不到：${why}（地形照常，这一层是派生物）`;
      add(kvs, kv('楼栋', miss(why)));
      console.warn('[campus] 建筑层没读到', e);
    } finally {
      bldgsLoading = false;
    }
  };
  btnBld.addEventListener('click', onBld);
  S.hooks.push(() => btnBld.removeEventListener('click', onBld));
  if (!gltf) {
    // 地形没加载 ⇒ 相机与支点都还是 0（见上面那几行），楼摆在哪根本看不出来。
    // 与其让它「点了没反应」，不如现在就禁用并说清为什么。
    btnBld.disabled = true;
    btnBld.setAttribute('aria-pressed', 'false');
    btnBld.title = '地形没加载 ⇒ 建筑层没有可用的定位基准（两层共用同一个 ENU 系）';
  }

  // ────────────────────────────────────────────────────── 明暗 / 无光
  // 无光那趟换成 MeshBasicMaterial：只是**换个画法看纹理**，不改文件里的材质。
  const flatMat = new THREE.MeshBasicMaterial({
    map: srcMat && srcMat.map ? srcMat.map : null,
    color: (srcMat && srcMat.color) ? srcMat.color.clone() : new THREE.Color(0xffffff),
    side: THREE.DoubleSide,
  });
  const onLit = () => {
    const lit = btnLit.getAttribute('aria-pressed') !== 'true';
    btnLit.setAttribute('aria-pressed', String(lit));
    if (mesh) mesh.material = lit ? srcMat : flatMat;
    amb.visible = d1.visible = d2.visible = lit;
    // 无光时洞层要压暗一点，否则纯色会把纹理吃掉。
    if (overlay) overlay.material.opacity = lit ? HOLE_OPACITY.lit : HOLE_OPACITY.flat;
  };
  btnLit.addEventListener('click', onLit);
  S.hooks.push(() => btnLit.removeEventListener('click', onLit));
  if (!mesh) btnLit.disabled = true;

  Object.assign(S, { mesh, srcMat, flatMat, overlay, terrain: gltf ? gltf.scene : null });

  // ────────────────────────────────────────────────────── 读数清单
  const rows = [];
  if (mesh) {
    rows.push(kv('尺寸', `${ex.toFixed(1)} × ${ez.toFixed(1)} m`));
  }
  if (VD && VD.elev) {
    rows.push(kv('高程', `${VD.elev.min.toFixed(1)} … ${VD.elev.max.toFixed(1)} m`
      + `（落差 ${ey.toFixed(1)} m）· 中位 ${VD.elev.median.toFixed(1)}`));
  } else {
    // 交付件的 POSITION min.y 是哨兵，不是地面 —— 拿它印出来的是「0.0 … 500.8 m」，
    // 把成都的海拔印成了 0，而它与真值都长成一个正常的小数（铁律 16）。
    rows.push(kv('高程', miss('交付件的 POSITION min.y 是哨兵，不是地面 —— 不拿它充数')));
  }
  if (mesh) {
    rows.push(kv('三角', (mesh.geometry.index
      ? mesh.geometry.index.count / 3
      : mesh.geometry.attributes.position.count / 3).toLocaleString()));
  }
  if (VD) {
    rows.push(kv('网格', `${VD.grid.nx} × ${VD.grid.ny} 格 @ ${VD.grid.step.toFixed(1)} m`));
    // ★ 两把尺子分开印（铁律 24）：criterion_version 管**交付件怎么造的**，
    //   viewdata_version 管**这份数据层怎么导的**。合成一个数就分不出是哪把变了。
    rows.push(kv('判据版', `交付件 v${VD.criterion_version}`
      + ` · 数据层 v${VD.viewdata_version === undefined ? '?' : VD.viewdata_version}`));
  }
  rows.push(kv('交付件', VD
    ? `${VD.glb.sha256_12} · ${(VD.glb.bytes / 1048576).toFixed(2)} MB`
    : miss('数据层没读到 ⇒ 连"盘上那份是哪个版本"都说不出来')));
  mount(kvs, rows);

  if (VD && VD.interior_holes) {
    const h = VD.interior_holes;
    // ★ 这一行**必须走 kv()**（键 + 值两个格子）。原先是手写的 `cp-kv` 只放了一个
    //   `cp-v` ⇒ 网格只有两列，单个子元素落进**第一列（92px 的键列）**，右边的值列
    //   （303px）空着；屏幕上是一句挤成三行、左对齐的话，**看起来像个标题**，
    //   而 textContent/innerText 类的判据全绿（量盒子才看得出来，铁律 39）。
    const list = [kv('合计', el('b', { text: String(h.cells) }),
      ` 格 / ${h.area_m2} m²，分成 ${h.blocks.length} 处`)];
    for (const b of h.blocks) {
      list.push(el('div', { class: 'cp-blk' },
        el('div', { class: 'cp-big', text: `${b.cells} 格 · ${b.area_m2} m²` }),
        el('div', { class: 'cp-small' },
          `中心 E=${b.centre[0]} N=${b.centre[1]}`, el('br'),
          `行 ${b.rows[0]}…${b.rows[1]} / 列 ${b.cols[0]}…${b.cols[1]}`),
        // ★ href 是必需的：没有 href 的 <a> 不可聚焦、也不吃 `.cp-blk a` 的指针光标。
        //   而 `#` 必须被 preventDefault 拦住 —— 本仓的 hash **就是路由**，
        //   放它过去等于当场切到默认视图（屏幕上就是"点了链接，这一屏没了"）。
        b.crop ? el('a', {
          href: '#',
          text: '看洞底下盖着什么 ▸',
          onclick: (e) => { e.preventDefault(); openCrop(b.crop, b); },
        }) : null));
    }
    mount(blks, list);
    mount(holenote, '这些是多视角摄影测量 DTM 的',
      el('b', { text: '已知失效区' }),
      '（在建工地裸土、公园水面），正射影像拍到了、高程却没有 ⇒ 呈现为洞。',
      el('b', { text: '不插值填补' }),
      '：填一块平面既看着错、又是假数据。');
  } else {
    mount(blks, el('div', { class: 'cp-kv' },
      el('span', { class: 'cp-v' }, miss('洞的位置**画不出来** —— 这不是"没有洞"'))));
  }
  if (vdErr) {
    mount(holenote, el('div', {},
      '数据层没读到，洞层与高程这两项都拿不到：', el('code', { text: vdErr })));
  }
  if (!gltf) btnTop.disabled = btnIso.disabled = true;

  // ────────────────────────────────────────────────────── 罗盘
  // 屏幕上"北"朝哪：把世界 -Z（北）投到相机的右/上轴上。
  const camR = new THREE.Vector3(), camU = new THREE.Vector3(), camF = new THREE.Vector3();
  const NORTH = new THREE.Vector3(0, 0, -1);
  function drawCompass() {
    camera.matrixWorld.extractBasis(camR, camU, camF);
    const x = NORTH.dot(camR), y = NORTH.dot(camU);
    // SVG 里 0° = 针朝上；屏幕 y 向下为正 ⇒ 取负。
    needle.style.transform = `rotate(${(Math.atan2(x, y) * 180 / Math.PI).toFixed(2)}deg)`;
  }

  // ────────────────────────────────────────────────────── 循环
  function tick() {
    if (disposed) return;
    S.raf = requestAnimationFrame(tick);
    controls.update();
    drawCompass();
    renderer.render(scene, camera);
    // 这一行是给浏览器门禁读的：**它在每一帧末尾刷新**，所以读到的是"此刻"。
    window.__CAMPUS = {
      ok: true,
      hasTerrain: !!S.terrain,
      hasOverlay: !!overlay,
      cells: overlay ? overlay.userData.cells : 0,
      mat: mesh ? mesh.material.type : null,
      hasViewdata: !!VD,
      // 楼栋层是**按需**的 ⇒ 「到现在取没取过」与「此刻开没开」是两个不同的量，
      // 分开报。只报一个的话，「没取过」会被读成「关掉了」（铁律 16）。
      hasBuildings: !!S.bldgs,
      bldgVisible: S.bldgs ? S.bldgs.visible : null,
      // 「数据层记的字节数」与「实际拿到的」分开报 —— 核对过才敢说它们相等。
      glbBytes: (VD && VD.glb) ? VD.glb.bytes : null,
      glbGot: S.terrain ? 'checked' : null,
    };
  }
  syncSize();
  tick();
}
