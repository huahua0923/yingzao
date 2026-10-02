// 世界层 —— 门户页那块铺满视口的 2024 实景三维。**这一层取代了原来的 three.js 舞台。**
//
// 为什么换掉 `js/scene.js`（那份 421 行的 three.js）：它不是坏，是**太薄**。
// 它把真地形 GLB 当一块"贴在纸面上的展板"画 —— 画布底色 `PLATE = 0xEFEAE1`
// 同时当雾色，于是地形四边是硬边、周围一圈米色，**没有天空、没有地平线**。
// 而大厂那种"数字孪生"的第一眼不是分辨率，是**这个世界有边界之外**。
// ⇒ 换成一整片实景瓦片 + 一个不显形的 Cesium 椭球：世界从边界一直铺到地平线。
//
// ★ 这一份**只负责"世界"**（相机 / 瓦片 / 拾取 / 度量），不含任何 HUD、不含业务。
//   业务那一半（点一栋楼出它的档案）在第 2 关接 `outlines.js` 与 `place.js`。

// ★★ Cesium 必须用**经典 `<script>`** 装，**绝不能** `import()` —— 这是量出来的，不是偏好。
//
//   实测（2026-10-02，同一台机、同一份 Cesium 1.89、同一份 tileset、同一个机位）：
//   · `await import('.../Cesium.js')` ⇒ 建完 viewer 的第一时间 **WebGL 上下文就被丢弃**，
//     画面恒黑（非背景占比 100%，其实全是 0,0,0 的黑），而且**一次也不出图**：
//     `rendered = 0`、`tiles` 树走了 0 个节点。
//   · 同一份代码，只把加载方式换成 `<script src>` ⇒ 非背景 **38.92%**、就绪块 **369**、
//     藏掉底再量 **0%**（阴性对照 Δ 38.92）。逐字相同，只差加载方式。
//
//   ★ 最阴的一点是**症状指向别处**：控制台里刷屏的是
//     「`[Cesium WebGL] Fragment shader failed to compile. Compile log: null`」，
//     而紧挨着的上一行才是真凶 —— `CONTEXT_LOST_WEBGL: loseContext: context lost`。
//     上下文没了 ⇒ `getShaderInfoLog()` 返回 null ⇒ Cesium 报"编译失败"。
//     **照 Cesium 报的那句话去查着色器，会一路查到明天**（铁律 105/165：
//     "两个数不一致"的第一嫌疑人是量具；这里是"报错指向的地方"不是"出错的地方"）。
//
//   ★ 机制**没有**查清（记下来免得被当成已知）：只能确认 UMD 包在模块作用域里求值
//     会比经典脚本多一步，而那一步之后上下文就没了。要再动这里，先照上面那两步
//     各跑一次，别推理。
//
//   ★ 路径从**本模块自己的 URL**推（`import.meta.url`），不写死 `/portal/` ——
//     写死了，页面换前缀部署就悄悄坏。而 `CESIUM_BASE_URL`（Workers/Assets 的根）
//     本来经典脚本能自己从 `document.currentScript.src` 推出来；这里仍显式设一遍，
//     因为它只在"没被设过"时才生效，设了不改变行为、却能防住被别处打包重组的那天。
const CESIUM_DIR_URL = new URL('../../vendor/cesium/', import.meta.url).href;
if (!globalThis.CESIUM_BASE_URL) globalThis.CESIUM_BASE_URL = CESIUM_DIR_URL;

let _cesiumLoading = null;
/** 装 Cesium（经典脚本）。已在页面上就立刻返回，不会重复装。 */
function loadCesium() {
  if (globalThis.Cesium) return Promise.resolve(globalThis.Cesium);
  if (_cesiumLoading) return _cesiumLoading;
  _cesiumLoading = new Promise((resolve, reject) => {
    const tag = document.createElement('script');
    tag.src = CESIUM_DIR_URL + 'Cesium.js';
    tag.onload = () => (globalThis.Cesium
      ? resolve(globalThis.Cesium)
      // 脚本"加载成功"但它没挂上全局 —— 那多半是路径对了、内容不是那一份。
      // 这时**必须报错**：静默下去的表现是"世界永远不出现"，与"底数据没有"同形。
      : reject(new Error(`Cesium.js 加载成功但 globalThis.Cesium 仍是空的（${tag.src}）`)));
    tag.onerror = () => reject(new Error(`Cesium.js 加载失败：${tag.src}`));
    document.head.appendChild(tag);
  });
  return _cesiumLoading;
}

// ★★ `widgets.css` 必须挂上，否则**画布恒是 300×150**（HTML 里 canvas 的默认尺寸）。
//   这一条我亲手踩过：Viewer 建出来了、tileset 也解析了、控制台一个字都不报，
//   而屏幕上是一片黑 —— 因为 `.cesium-viewer` / `.cesium-widget canvas` 的
//   `width:100%;height:100%` 全在那份 CSS 里，没有它，容器就没有尺寸，
//   WebGL 的绘图缓冲就停在校准用的 300×150。
//   ★ 随即触发的第二个症状更误导：上下文被丢弃（`CONTEXT_LOST_WEBGL`），
//     而 Cesium 把它报成「Fragment shader failed to compile」——
//     **症状指向着色器，病根在样式表**。
//   ⇒ 所以这一句写在模块里、而不是指望宿主页面记得加一行 `<link>`：
//     依赖要么被模块自己保证，要么迟早会漏（铁律 017 的同族）。
const widgetsLink = document.querySelector('link[data-cesium-widgets]')
  || (() => {
    const link = document.createElement('link');
    link.rel = 'stylesheet';
    link.href = CESIUM_DIR_URL + 'Widgets/widgets.css';
    link.setAttribute('data-cesium-widgets', '');
    document.head.appendChild(link);
    return link;
  })();

// 背景色 = 世界之外的那片底色。**读 `portal.css` 的 `--void`**，不是在这里再写一个数。
//
// ★ 这里原来写的是 `const VOID_COLOR = '#080b10'`，上面那句注释声称它与
//   「`portal.css` 的 `--void` 是同一个值」—— 而 `--void` **在 CSS 里根本不存在**
//   （那边只有一个 `--paper: #0E1116`）。两个数差 6 个数，屏幕上的形状是
//   世界与页面之间一条看不太出来、但一直在的横线。
//   铁律 018：两个地方写同一个数，「一致」证明不了它是对的 —— 现在只剩一个来源。
const VOID_FALLBACK = '#080b10';   // 只在 CSS 还没解析出来时兜底（首帧、单测）
function readVoidColor() {
  const v = getComputedStyle(document.documentElement)
    .getPropertyValue('--void').trim();
  return v || VOID_FALLBACK;
}
const VOID_COLOR = readVoidColor();

// ★★ 地面**要铺到瓦片之外**，否则世界是一块**悬在虚空里的菱形板子**。
//
//   实景瓦片的覆盖范围是一次航飞的测区，有边。`globe.show = false` 之后，
//   边外就是背景色 ⇒ 屏幕上是一条**硬边**，那块地看起来像个物件、不像个世界。
//   （这正是本仓第 1 条缺点：旧版是"斜浮在米色纸上的板子"，成因不同、形状一样。）
//
//   ⇒ 在瓦片底面高度铺一张**大得多的暗色地面**，把世界从测区一直延伸出去；
//     再由雾把它在远处化成背景色 ⇒ 边界不存在了，只有**远近**。
//
//   ★ 高度取 415 m（比 §二 反解出的网格原点 422.00 低 7 m）：
//     放得比瓦片底面**低**，它就只出现在测区之外；放高了会把楼的下半截盖住，
//     而"楼被切了一刀"看起来像建模错了。
//   ★ 这是**一块地板，不是数据**。它上面没有任何读数、也不参与拾取
//     （`pickable`/`allowPicking` 关掉，`outlines.js` 的 `scene.pick` 才不会被它截胡）。
//   ★★ 一块**纯色**的板子没用 —— 实测过：#0d1219 对 #080b10 只差 5 个数，
//     判像素的量具看得见、眼睛看不见（`_p3_probe.py` 量到"板子画了、占 99.7%"，
//     而截图上仍然是一圈黑 + 一条硬边）。**"画出来了"与"看得见"是两件事。**
//   ⇒ 板子必须自己**从亮到暗收边**：中心比背景亮一档（校区像坐在一块被照亮的地上），
//     到边缘**恰好等于背景色** ⇒ 那条边不再是边，是一次渐变。
//   ★ 边缘色**必须写 `VOID_COLOR` 本身**，不许写一个"差不多"的深色：
//     差一点就会在 33 km 处留下一圈比背景亮/暗的环，而那圈环看起来像"远山的轮廓"。
const GROUND_PLANE = Object.freeze({
  height: 415.0,
  spanDeg: 0.12,          // ±0.12° ≈ ±13 km：远到视野外，又不至于梯度全落在屏幕外
  center: '#1c2836',      // 校区脚下那块"被照亮的地"
  edge: VOID_COLOR,       // 收到这里就必须**正好**是背景色
  texSize: 512,
});

/** 生成"从亮到暗"的那张底图。用画布是**故意的** —— 不往仓里塞一个二进制贴图，
 *  它只是一段两行的渐变，写成文件以后没人知道它该是什么样子。 */
function groundGlowTexture() {
  const S = GROUND_PLANE.texSize;
  const c = document.createElement('canvas');
  c.width = S; c.height = S;
  const g = c.getContext('2d');
  const grd = g.createRadialGradient(S / 2, S / 2, 0, S / 2, S / 2, S / 2);
  grd.addColorStop(0.00, GROUND_PLANE.center);
  grd.addColorStop(0.30, GROUND_PLANE.center);   // 中间一大片是平的，否则校区周围一圈会像聚光灯
  grd.addColorStop(1.00, GROUND_PLANE.edge);
  g.fillStyle = grd;
  g.fillRect(0, 0, S, S);
  return c;
}

// 瓦片失败的清单**只增不减**，且**要在屏幕上说出来**：
// 一块瓦片读不到，画面上的表现是"那里少了一块"，与"那里本来就没有东西"同形。
// 而 3D Tiles 的设计恰恰允许缺块（refine=REPLACE 时子块不来、父块就顶上）。
// ⇒ 不出声的话，一份坏掉的产物与一份正常的产物在截图上长得一样（铁律 046/048）。
const MAX_FAILURES = 50;

// ★★ **写在源码里的那个 16 是个错** —— 它决定"世界多久才出现在屏幕上"。
//
//   16 是 Cesium 的默认值，而那个默认值是**为单栋精细模型**定的。本机实测：
//     · SSE=16  ⇒ fps **2.5**，`numberOfPendingRequests` **恒等于 6**
//                  （正好是 Chromium 对同源的连接上限），
//                 `tilesLoaded` **48 秒都到不了 true**，画面永远是**一片洞**；
//     · SSE=256 ⇒ **22 秒** `pend` 归 0，fps 升到 6.7，**画面是完整的**。
//   ⇒ 病根不是网络（`page.route` 从盘上直读，覆盖曲线**逐点相同**）、也不是缺文件
//     （199 条响应**全是 200**，`state.failed` 空）—— 是**渲染循环一秒只转两圈半，
//     而 16 这个数要求它每一帧都再要一批新瓦片，队列永远追不上**。
//
// ★ 试过、并**已用像素否决**的写法：先 256 铺一遍、停下再细化到 64。
//   理论上是通法（先铺上屏、再上细节），实际结果是**更差**：
//   细化一开始，Cesium 会把已经铺好的粗瓦片**扔掉**（实测 `ready` 122 → 66），
//   而 64 这一档在这台机器上**永远铺不完**（>150 s），
//   于是画面**从"完整"退回成"一片洞 + 浮在空中的轮廓线"**（`FIX-fine-nohud.png`）。
//   ⇒ **一个铺不完的细化，比不细化更差。** 参数只在"它真的能跑完"时才成立。
//   ★ 所以这里只留**一个**值。取值不是挑的，是**冷启动逐个量出来的**
//     （`_scratch/_p3_sse_cold.py`，每次新开浏览器上下文，等到 `pend==0 && tilesLoaded`）：
//
//         SSE   收敛耗时    fps    就绪块
//          64   >150 s ✗    3.8      66
//         128    122.5 s    4.0     450
//         192     32.2 s    6.3     154
//         256     22.4 s    6.7     122
//
//   ⇒ 128 能收敛，但**要两分钟**，而这两分钟里画面是**一片洞**。
//     用户看到的不是"正在变清楚"，是"这个系统坏了"。
//   ⇒ 取 256：**唯一同时满足"最快铺完"与"fps 最高"的一档**。
//   ★ 这个数**跟机器绑**：本机渲染器是 SwiftShader（软件 WebGL，实测）。
//     真实 GPU 上 16 是能收敛的、也只有 16 才够清晰。
//     ⇒ 换机器要重量（一条命令的事），**不许照抄这个 256 走**。
// ★★ 这三个常数**全部换掉了**（2026-10-02：真 GPU 与 SwiftShader 各扫一遍全档）。
//
//   上一版是「先看渲染器是谁 ⇒ 软件 256 / GPU 16；看不住就只往粗退」。
//   那张表**只量过一档**（软件 256），其余是推的。这次把 16/32/64/128/256
//   在**两条渲染路径**上各量了一遍，结论把整套设计掀掉了：
//
//   ── 真 GPU（RTX 3060，1600×950，相机高 599 m）─────────────────────
//       档位  就绪块  三角面   在飞  几何MB   fps(前/后)
//        16     561    1.1M     14   107    24.5 / 23.2   ← 永不收敛
//        32    1795    2.2M      0   258    60.0 / 60.0   ← 铺完了
//        64    1788    2.2M      0   258    60.0 / 60.0
//       128    1194    1.5M      0   214    60.0 / 60.0   ← 画面开始破
//       256     419    0.8M      0   156    60.1 / 60.0   ← 画面塌了
//
//   ── SwiftShader（无 GPU，相机高 877 m）───────────────────────────
//       32 → 2.1 fps ｜ 64 → 2.3 ｜ 128 → 3.5 ｜ 256 → 4.5
//
//   ★ 两条结论，**都不是"再调调参数"能得到的**：
//
//   ① **32 比 16 更好，而且好得全面。** 画面：`sse_016/032/064.png` 三张的
//      中心裁切**逐处一样**（同一排窗户、同一条屋脊）；帧率 **24 → 60**；
//      而且 16 那一档 `在飞=14` —— 它**一直在流、从不收敛**，32 是 `在飞=0`。
//      ⇒ 16 付了 2.5 倍的帧率，换到的画面**一样**。默认档改成 32。
//
//   ② ★★ **往粗退不是"变糊"，是"变坏"，而 64 以外没有能用的层。**
//      `sse_128.png` 中央已出现黑洞（一整块楼的屋面缺了），
//      `sse_256.png` 整片塌成互不衔接的错位板子 —— **软件渲染那条路上同样塌**
//      （`_cmp_sw.png`）。**这不是渲染器的毛病，是数据的毛病**：本仓这份瓦片是
//      从 OSGB 的 PagedLOD 转的，**中间层的粗节点不是细节点的简化版**，
//      `refine=REPLACE` 退到那一层，露出来的就是那些互不衔接的板。
//      ⇒ 这同时说明**原来那个 `SSE_SOFTWARE = 256` 是个真缺陷**：
//        它让**每一台没有显卡的机器**看到的就是一片被撕碎的校园。
//      ⇒ 阶梯砍成 `[32, 64]`，**64 是下限，再往下画面就没了**。
//
//   ★ 判据也跟着换：**直接量 fps**。前两版分别拿"死线"和"进度"当代理 ——
//     死线（25 s 没收完就退）在这份 48695 块的数据上**恒触发**，一个恒触发的
//     判据等于没有判据，只是单方面把代价付了出去；进度（连续 20 s 没新块才退）
//     **从不触发**，而它想指认的那件事**是真的**（16 确实只有 6~9 fps）。
//     两个都是代理，而这个量**本身就能直接量**：「看不住」的直译就是
//     每秒画不出几帧。⇒ 量帧。（铁律 183：修好一个错法只算改了一半 ——
//     上一版把警铃拆了，却没量警铃报的那个数。）
const SSE_SOFTWARE = 64;        // 与 256 同量级（2.3 vs 4.5 fps，都不可用），但画面是好的
const SSE_HARDWARE = 32;        // 与 16 画面相同、60 fps、且会收敛（见上表①）
const SSE_LADDER = [32, 64];    // ★ 只两级：64 是下限，再粗数据本身就没有能看的层

const SSE_FPS_FLOOR = 22;        // 低于这个数，拖动/旋转会明显顿
const SSE_FPS_SAMPLES = 3;       // 连续三笔都低于门槛才退档（避开瞬时抖动）
const SSE_FPS_WINDOW_MS = 1200;  // 一笔量多长的帧数
const SSE_FPS_WARMUP_MS = 15000; // 起手这段不算：首屏的上传与解码本来就慢
const SSE_FPS_AFTER_MS = 8000;   // 退完一档后等这么久再判（让粗的落位、细的卸掉）

/** 这一台到底是软件渲染还是真 GPU —— 读**渲染器自己的名字**，不猜。
 *
 *  ★ 为什么不去猜"有没有 GPU"（比如看 `devicePixelRatio` 或 UA）：那些与
 *    "这一帧画得多慢"之间隔着好几层，而渲染器名字是**直接**的。本机实测
 *    它就是 `SwiftShader`（`_scratch/_p3_sse_cold.py` 那张表的来源）。
 */
function detectSse() {
  const q = new URLSearchParams(location.search).get('sse');
  if (q !== null && /^[0-9]+$/.test(q) && Number(q) >= 1) {
    return { sse: Number(q), why: `URL 指名 ?sse=${q}` };
  }
  let r = '';
  try {
    const gl = document.createElement('canvas').getContext('webgl');
    const ext = gl && gl.getExtension('WEBGL_debug_renderer_info');
    r = (ext && gl.getParameter(ext.UNMASKED_RENDERER_WEBGL)) || '';
  } catch { /* 取不到名字 ⇒ 按硬件走（那档更细；真跑不动有看门狗兜） */ }
  const soft = /swiftshader|llvmpipe|software|基本呈现|basic render/i.test(r);
  return {
    sse: soft ? SSE_SOFTWARE : SSE_HARDWARE,
    why: soft ? `软件渲染（${r || '名字取不到'}）` : `GPU（${r || '名字取不到'}）`,
  };
}

export function createWorld(host, opts = {}) {
  // ★ 瓦片地址由调用方给（门户给 `/api/tiles/tileset.json`；本机探针页给
  //   静态服务器上的相对路径）—— 世界层**不认识后端**，认识后端的只有 api.js。
  const tilesetUrl = opts.tilesetUrl || '/api/tiles/tileset.json';

  const state = {
    ready: false,           // tileset 解析成功（≠ 瓦片画出来了）
    tiles: 0,               // 树上节点总数
    rendered: 0,            // 内容已就绪、真的画得出来的块数
    failed: [],             // 加载失败的块，**明细只留前 MAX_FAILURES 条**（防内存）
    failedTotal: 0,         // 失败总数（不封顶）—— 屏幕上报的是这一个
    error: null,            // 世界起不来时的原因（原样，不包装）
    base: true,             // 底（实景瓦片）在不在
    // ★ 这三项是**这个数怎么来的**。铁律 121：一个参数不许变成装饰 ——
    //   档位若只活在代码里，谁都答不出"为什么这台机上这么糊"。
    sse: null,              // 当前生效的 maximumScreenSpaceError
    fps: null,              // ★ 最近一次实测帧率 —— **它就是退档判据本身**，
                            //   不留在 state 里，屏幕上就只能看见"档位变了"
                            //   而看不见"因为几帧才变的"（铁律 109：判词要印在
                            //   它输入已定之处）
    renderer: '',           // 判档所依据的渲染器名字（原样，不翻译）
    sseLog: [],             // 档位变动史 [{sse, why, t}]，退档要留痕
  };

  let Cesium = null;
  let viewer = null;
  let tileset = null;
  let destroyed = false;

  /** 一帧的画面统计。判据要钉在**屏幕上有没有东西**，不是"请求发没发出去"（铁律 041）。 */
  function pixStats() {
    const c = viewer.canvas;
    const t = document.createElement('canvas');
    t.width = c.width; t.height = c.height;
    const g = t.getContext('2d');
    g.drawImage(c, 0, 0);
    const d = g.getImageData(0, 0, t.width, t.height).data;
    const bg = [
      parseInt(VOID_COLOR.slice(1, 3), 16),
      parseInt(VOID_COLOR.slice(3, 5), 16),
      parseInt(VOID_COLOR.slice(5, 7), 16),
    ];
    let n = 0, nonBg = 0;
    for (let i = 0; i < d.length; i += 4) {
      n += 1;
      if (Math.abs(d[i] - bg[0]) > 6
        || Math.abs(d[i + 1] - bg[1]) > 6
        || Math.abs(d[i + 2] - bg[2]) > 6) nonBg += 1;
    }
    return { w: t.width, h: t.height, n, nonBg, pct: +(100 * nonBg / n).toFixed(2) };
  }

  /** 把相机**瞬间**放到一个确定的位置。
   *
   *  ★ 不许用 `zoomTo` / `flyTo` —— 它们是动画，而截图是**中途帧**。
   *    本仓实测过：同一页、同一份数据，t=5 s 与 t=120 s 出的是两张不同的图，
   *    而两张都"看着像整片校区"。测什么就得是什么（铁律 026）。
   */
  function viewSphere(radiusMul, pitchDeg) {
    if (!tileset) return;
    const bs = tileset.root.boundingSphere;
    viewer.camera.viewBoundingSphere(
      bs,
      new Cesium.HeadingPitchRange(0, Cesium.Math.toRadians(pitchDeg), bs.radius * radiusMul),
    );
  }

  return {
    state,
    get canvas() { return viewer?.canvas; },
    get camera() { return viewer?.camera; },
    get scene() { return viewer?.scene; },
    get viewer() { return viewer; },
    // ★ `outlines.js` 要**借瓦片自己的** `root.transform` 定朝向（见 `place.js` 的长注释）。
    //   暴露它，而不是让 `outlines.js` 自己去 `scene.primitives.get(0)` ——
    //   后者在"以后再加一层 primitive"的那天会静默取到错的那一个。
    get tileset() { return tileset; },

    /** 立起世界。失败时**抛**，由调用方决定怎么显示 —— 世界层不吞错（铁律：错误不要吞掉）。 */
    async boot() {
      Cesium = await loadCesium();

      // ★ 等样式表**确实生效**再建 Viewer。不等的话，`#world` 那一刻还没有尺寸，
      //   Viewer 会把绘图缓冲定在 300×150 上；后面 `resize()` 虽然能纠正尺寸，
      //   但第一帧的相机纵横比是错的（屏幕上表现为"世界被压扁了一下"）。
      //   ★ 不能只看 `onload`：本地这两份文件是同一个 origin，可能**已经**加载完，
      //     那时 `link.onload` 再也不会响 ⇒ 先看 `sheet`，再挂回调，最后兜个超时。
      if (widgetsLink && !widgetsLink.sheet) {
        await new Promise((res) => {
          widgetsLink.addEventListener('load', res, { once: true });
          widgetsLink.addEventListener('error', res, { once: true });
          setTimeout(res, 3000);
        });
      }

      viewer = new Cesium.Viewer(host, {
        // ★ preserveDrawingBuffer 必须开，否则 `toDataURL` / `drawImage` 读回来是空白 ——
        //   量具自己会骗人，而"读回全空"看起来像"画面上什么都没有"（铁律 021）。
        contextOptions: { webgl: { preserveDrawingBuffer: true } },
        // ★ 这两行是 **1.89 的写法**：`baseLayer:false` 是 1.104+ 才有的选项，
        //   这个版本里得用 `imageryProvider:false`。写错了不报错，它会去连 Cesium Ion。
        imageryProvider: false,
        baseLayerPicker: false,
        geocoder: false,
        homeButton: false,
        sceneModePicker: false,
        navigationHelpButton: false,
        animation: false,
        timeline: false,
        fullscreenButton: false,
        infoBox: false,
        selectionIndicator: false,
        // ★★ 署名容器：**不让它用默认的位置**。
        //   默认容器是 `.cesium-viewer-bottom{position:absolute;bottom:0;left:0}`
        //   （见 `vendor/cesium/Widgets/Viewer/Viewer.css`）—— 而屏幕左下角
        //   `left:0;width:72px` 是**左导轨**的地盘。实测后果：1600×950 的出图上
        //   「Cesium ion」被导轨从左边切掉一半，剩「IUM ion」浮在实景影像上
        //   （`_scratch/_p3_shots/C01.png` 左下角）。
        //   它不是"少画了"，是**画在了别人的地盘上** —— 而屏幕上这与"设计如此"
        //   长得一模一样，一条判据都不会出声。
        //   ⇒ 换成导轨页脚里那个 `#credit`：那一块**永远有底**（导轨自己的
        //     `--rail` 底 + 模糊），也是全页唯一一处不会被任何 HUD 形态盖住的位置。
        creditContainer: 'credit',
      });

      // ★ 这四行**是照抄**已经在本机跑通过的 `_scratch/_fly2024_viewer/z0.html`，
      //   不是我自己挑的。理由：这台机器是**软件 WebGL**（SwiftShader），
      //   它对"多一条设置"的容忍度很低 —— 我先前按自己的口味多写了六行
      //   （`skyAtmosphere/sun/moon.show=false`、`enableCollisionDetection=false`、
      //   `requestRenderMode=true`），结果**上下文在建完 viewer 的第一时间就被丢弃**，
      //   而 Cesium 把它报成「Fragment shader failed to compile」——
      //   症状指着着色器，病根在那几行设置里。⇒ 先用**已知能跑的最小集**立起来，
      //   要加什么，一次加一条、每条都出图验。
      const s = viewer.scene;
      s.globe.show = false;                 // 没有影像底图 ⇒ 把椭球也藏掉，否则是一颗光球
      s.skyBox.show = false;                // 星空盒：一个"球外面还有东西"的错觉，这里不要
      s.backgroundColor = Cesium.Color.fromCssColorString(VOID_COLOR);
      // ★ 雾**要开**：它是"世界有远处"的唯一来源。
      //   关掉它，测区边界以外就是背景色 ⇒ 一条硬边（见 `GROUND_PLANE` 上面那段）。
      //   开了它，远处的地面自己淡出到背景色 ⇒ 看到的不是"边界"，是"远方"。
      //   ★ 密度是量出来的，不是挑的：0.00008 ⇒ 约 12.5 km 处淡到看不见。
      //     太大（默认 0.0002 ≈ 5 km）会把整片校区也染灰，校区就没了"清亮"。
      s.fog.enabled = true;
      s.fog.density = 0.00008;

      try {
        await this.loadBase(tilesetUrl);
      } catch (e) {
        state.base = false;
        state.error = String(e?.message ?? e);
        throw e;
      }
      // ★★ **必须在这里把机位摆好**，否则世界是一块**离屏的黑**。
      //
      // 这一条差一步漏掉，症状极难认：tileset 解析成功（`readyPromise` 兑现了、
      // 请求全 200）、`state.ready === true`、控制台一个字都不报、页面上
      // HUD 一层不少 —— 而画面全黑。因为 Cesium 的默认机位是
      // `Camera.DEFAULT_VIEW_RECTANGLE`（**从两万公里外看整颗地球**），
      // 而我们 `globe.show = false`、瓦片又只有一片校区那么大 ⇒ 相机在
      // 几百公里外对着一个空点。
      //
      // ★ 它是"第 2 关那三只对照"抓不到的：探针页 `w2.html` 自己在开机位
      //   （`world.top()`），于是**探针过、页面黑** —— 两边的差别只在
      //   "谁负责摆机位"，而那件事**没有任何一处写着**。
      // ⇒ 判据不是"探针页出图了"，是**页面自己**出图（见 `_p3_probe.py` 的像素列）。
      //
      // ★ `syncSize()` 必须排在机位**之前**：`viewBoundingSphere` 按当时的
      //   视口宽高比算取景，先摆机位再 resize ⇒ 换一个宽高比就被裁掉一条边。
      this.addGroundPlane();
      this.syncSize();
      this.home();
      state.ready = true;
      return this;
    },

    /** 装"世界底"。单独一个方法，是因为后面几关要能**换底**（实景 / 体块 / 无底）。 */
    async loadBase(url) {
      // ★★ 档位从**这台机器**读出来，不照抄上面那个 256（理由见 `detectSse`）。
      const pick = detectSse();
      state.sse = pick.sse;
      state.renderer = pick.why;
      state.sseLog = [{ sse: pick.sse, why: pick.why, t: 0 }];
      tileset = new Cesium.Cesium3DTileset({ url, maximumScreenSpaceError: pick.sse });
      viewer.scene.primitives.add(tileset);
      tileset.tileFailed.addEventListener((e) => {
        // ★ 两个数，**都要**：`failed` 只留前 50 条明细（防内存），`failedTotal`
        //   一直数到底。只留 `failed.length` 的话，屏幕上「50」既可能是"恰好 50"
        //   也可能是"多到数不清" —— 一个封顶的计数印出来是个像结论的假数
        //   （铁律 060：分母为 0 的 k/N 是最像结论的假数）。
        state.failedTotal += 1;
        if (state.failed.length < MAX_FAILURES) state.failed.push(`${e.url} :: ${e.message}`);
        viewer.scene.requestRender();
      });
      await tileset.readyPromise;
      viewer.scene.requestRender();
      // 每帧刷一次统计。★ 它量的是"现在画得出来多少块"，不是"总共多少块" ——
      //   后者在流式加载里恒等于总节点数，看不出任何东西。
      viewer.scene.postRender.addEventListener(() => {
        if (destroyed) return;
        const st = viewer.scene.primitives.get(0);
        state.tiles = st ? st.statistics.numberOfTilesTotal : 0;
        state.rendered = st ? st.statistics.numberOfTilesWithContentReady : 0;
      });
      this.watchRefine();
      return tileset;
    },

    /** 画不动就**只往粗退**，**但最多退到 `SSE_LADDER` 的末档**（理由见上面那段）。
     *
     *  ★ 它守的是**帧率**，不是"铺完了没有"：`tilesLoaded` 只说明**数据到齐了**，
     *    不说明这台机器画得动（铁律 020 同族 —— "起来"与"在服务"是两件事）。
     *    每 `SSE_FPS_WINDOW_MS` 数一次 `requestAnimationFrame` 的回调数，
     *    那就是屏幕**真的**每秒画出几帧。
     *
     *  ★ 为什么不拿 `state.rendered` 之类当门槛：那个数在**流式**加载里一直在变，
     *    拿一个会动的数去判一件静止的事，等于没有判据（铁律 159）。
     *
     *  ★★ 为什么"到最粗档还是卡"必须**出声**而不是静默停手：在本仓这份数据上，
     *    64 以外**根本没有能看的层**（见常量处 ②）—— 所以正确的处置**不是继续往粗退**，
     *    而是**停手并把这件事报出来**，让人知道该换机器或换数据。
     *    静默停手会让"退到底了"与"刚好够用"在屏幕上长得一样。
     */
    watchRefine() {
      const t0 = performance.now();
      let low = 0;                    // 连续几笔低于门槛
      // ★ 印出来的必须是**秒**。原来这里是 `t: Math.round(el)`，而 `el` 是
      //   `performance.now()` 的差 = **毫秒**，渲染器却拼成 `${t}s`
      //   ⇒ 实测印出 `25201s`、`77378s`，实际是 **25.2 s / 77.4 s**，差 1000 倍。
      //   一个读数单位错了 1000 倍而在屏幕上"看着像个数"，就是铁律 050 那个病。
      const sec = (ms) => Math.round(ms / 100) / 10;

      // 数 `SSE_FPS_WINDOW_MS` 里 rAF 回调了几次 —— 屏幕真的画出几帧。
      // ★ 用 rAF 而不是 `requestAnimationFrame` 之外的办法（比如读 Cesium 的
      //   `fps`）：Cesium 自己那个数是它**渲染循环**的频率，在
      //   `requestRenderMode` 下与"屏幕多久换一帧"不是一回事。
      const sampleFps = (done) => {
        let n = 0;
        const s0 = performance.now();
        const tick = () => {
          n += 1;
          const el = performance.now() - s0;
          if (el < SSE_FPS_WINDOW_MS) requestAnimationFrame(tick);
          else done(Math.round(n / (el / 1000)));
        };
        requestAnimationFrame(tick);
      };

      const step = () => {
        if (destroyed || !tileset || tileset.isDestroyed()) return;
        const now = performance.now();
        if (tileset.tilesLoaded) {
          state.sseLog.push({ sse: state.sse, why: '已铺完', t: sec(now - t0) });
          return;
        }
        if (now - t0 < SSE_FPS_WARMUP_MS) { setTimeout(step, 1500); return; }
        sampleFps((fps) => {
          if (destroyed || !tileset || tileset.isDestroyed()) return;
          state.fps = fps;                 // 判据本身就是这个数，所以要留下来
          if (fps >= SSE_FPS_FLOOR) { low = 0; setTimeout(step, 1500); return; }
          low += 1;
          if (low < SSE_FPS_SAMPLES) { setTimeout(step, 1500); return; }
          low = 0;
          // ★ 取"比当前更粗的下一个"，**不用 `indexOf`** —— 从 URL 指名过
          //   `?sse=8` 这种不在阶梯里的档时，`indexOf` 回 −1，
          //   `SSE_LADDER[0]` 就成了**更细**的一档，方向整个反过来。
          const next = SSE_LADDER.find((v) => v > state.sse) ?? null;
          if (next === null) {             // 已经最粗了 —— 到这里必须**出声**
            state.sseLog.push({
              sse: state.sse, t: sec(performance.now() - t0),
              why: `★已到最粗档（${state.sse}）而实测只有 ${fps} fps；`
                 + '再粗画面就塌，停手',
            });
            return;
          }
          tileset.maximumScreenSpaceError = next;
          state.sse = next;
          state.sseLog.push({
            sse: next, t: sec(performance.now() - t0),
            why: `连续 ${SSE_FPS_SAMPLES} 笔不足 ${SSE_FPS_FLOOR} fps`
               + `（末笔实测 ${fps}），退一档`,
          });
          viewer.scene.requestRender();
          // ★ 退完要**等一等再判**：粗瓦片还没落位、细瓦片还没卸掉的那几秒，
          //   帧率一定是低的 —— 立刻复判会一路退到底（原来是 2 s，太快）。
          setTimeout(step, SSE_FPS_AFTER_MS);
        });
      };
      setTimeout(step, 2000);
    },

    /** 铺一张**比测区大得多**的暗色地面，让世界有"外面"（见 `GROUND_PLANE` 上面那段）。
     *
     *  ★ 它必须**只出现在瓦片之外**，所以：
     *    · 高度低于瓦片底面（415 m）；
     *    · `allowPicking: false` —— 否则 `outlines.js` 的 `scene.pick()` 会在
     *      点空时命中这张地板，而"点到地板"与"点到空气"在代码里长得一样，
     *      表现是**点空白处反而清不掉选中**（一个只在特定机位出现的怪毛病）。
     */
    addGroundPlane() {
      if (!tileset) return;
      // 中心点从**瓦片自己的包围球**取 —— 不写死经纬度：写死了换一份测区就悄悄偏。
      const c = Cesium.Cartographic.fromCartesian(tileset.root.boundingSphere.center);
      const lon = Cesium.Math.toDegrees(c.longitude);
      const lat = Cesium.Math.toDegrees(c.latitude);
      const d = GROUND_PLANE.spanDeg;
      viewer.entities.add({
        id: 'ground-plane',
        allowPicking: false,
        rectangle: {
          coordinates: Cesium.Rectangle.fromDegrees(lon - d, lat - d, lon + d, lat + d),
          height: GROUND_PLANE.height,
          material: new Cesium.ImageMaterialProperty({
            image: groundGlowTexture(),
            transparent: false,
          }),
          outline: false,
        },
      });
      viewer.scene.requestRender();
    },

    /** 默认机位。★ 这个数**不是"看起来合适"挑的，是扫出来的**。
     *
     *  ══ 2026-10-02：判据**换过**，旧的那条是错的，一并记在这里 ══
     *
     *  旧判据 = 「**画面最外 4 圈像素里，瓦片盖住的占比**」，越高越好，扫出 `0.28 / −70°`
     *  （99.2%）。它确实消掉了"斜浮在纸上的板子"，**代价是把世界拍成了一张地图**：
     *  −70° 几乎正俯视 ⇒ 立面贴图摊平铺在地上，没有地平线、没有体量，
     *  屏幕上像一张航摄图，不像一个世界。而大厂的数字孪生清一色是 **3/4 斜视 + 有远处**。
     *  ⇒ 病根是判据：**"把测区塞满画幅"本身不是目的**。
     *
     *  新判据（两条，都要；**先写下来、再去看数**）：
     *    · **体量**   pitch ≤ −30°，否则楼是贴图不是体量
     *    · **溢出**   看得见的那条左边、右边**都要**被瓦片盖住（≥60%）
     *                —— 测区横向跑出画幅才不会被看成"一块板子"；
     *                上边**不许**盖满（要露出远处 ⇒ 有地平线）
     *
     *  ★ 量区也修过一次（`_scratch/_p3_remeasure.py`）：第一版量的是**视口最外 6 px**，
     *    而 `.rail` 占 72 px、`#panel` 占 344 px —— 那两条边**在真实页面上看不见**。
     *    隐藏 HUD 只是为了排除干扰，**不等于用户可以看见那块地方**。
     *    ⇒ 可见世界框 = `x[72,1256] y[56,950]`（活页面上读的矩形，不是从 CSS 变量猜的），
     *      1184×894。**新旧两个量区的数并排印出来过**，不是看到结果才换的尺子。
     *
     *  实测（1600×950，每档都等到 `pend==0`；可见世界框口径）：
     *      机位          上     下     左     右    全幅    判据
     *      r0.28 −70   69.6   70.1   84.4   72.3   78.7    过   ← 旧默认（对照）
     *      r0.35 −45   63.9   76.3   69.5   76.1   78.2    过
     *      r0.35 −40   57.2   71.3   65.5   78.0   77.4    过   ← **取这个**
     *      r0.45 −45   52.8   60.2   58.9   74.5   73.9    不过（左 58.9）
     *      r0.45 −35   27.4   60.8   54.6   75.8   70.0    不过
     *      r1.20 −35    0.0   68.1   24.0   70.2   52.2    不过（远看＝一块板子）
     *
     *  ⇒ 取 **0.35 / −40°**：过线里**最斜**的那一档（−40 比 −45 更接近水平），
     *    覆盖 77.4% 与旧默认 78.7% 基本打平，而上边从 69.6 降到 57.2 ⇒ 远处多露出来一截。
     *
     *  ★ **已知不足，别当成已解决**：这一档的"远边"刚好落在 950 px 视口的顶栏之外
     *    —— 窗口再高一点，测区那条硬边就会露出来。根本出路是**让远边化掉**
     *    （地面板 `GROUND_PLANE` + `groundGlowTexture` + `fog` 这套装置**已经建好了、
     *    现在几乎没用上**：`fog.density` 才 0.00008），那样相机才能退到 r0.7~1.2
     *    去要一条真地平线。**在那之前，这一档是"斜视"与"看不见板子边"之间最好的一个点。**
     */
    home() { viewSphere(0.35, -40); viewer.scene.requestRender(); },
    /** 顶视：正俯视整片校区（看轮廓贴合用这个机位）。 */
    top() { viewSphere(1.8, -90); viewer.scene.requestRender(); },

    /** 铺满视口。容器尺寸变了必须叫一次，否则 Cesium 还按旧尺寸投影（画面被拉伸）。 */
    syncSize() { viewer?.resize(); viewer?.scene.requestRender(); },

    pixStats,

    /** 当前画面真的画出了东西吗 —— 这是第 1 关的判据本体。 */
    measure() { viewer.scene.render(); return pixStats(); },

    /** 阴性对照用：把底藏掉。藏完再量一次，两次**必须不同**。 */
    setBaseVisible(on) {
      if (!tileset) return;
      tileset.show = on;
      viewer.scene.requestRender();
    },

    destroy() {
      destroyed = true;
      viewer?.destroy();
      viewer = null; tileset = null;
    },
  };
}
