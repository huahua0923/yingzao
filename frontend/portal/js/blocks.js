// 模拟体块 —— 本轮**刻意不放真实建筑**。
//
// ★ 用户 2026-10-01 明令：「先不用忙着把建筑放在上面去，先模拟几个块儿都可以」。
//   所以这一层画的是**假体块**，它的用途是：
//     ① 把底图、拾取、详情面板、锚点这套**通路**跑通；
//     ② 让"点开一栋看每层功能"在没有真实对应关系时也能演示。
//   真实建筑层在盘上是有的（`/api/campus/buildings.json`，341 块，实测轮廓 ×
//   实测屋顶高）—— 但它**没有身份**（341 块 ↔ 93 栋名册连不起来，那个变换
//   在盘上不存在）。所以真实层解决的是"形状"，解决不了"这是哪栋"。
//   身份来自**人工锚点**（用户原话「我可以把位置基本 1 对 1 地给你点上」）。
//
// ★ 每个块都带 `mock: true`，并且**屏幕上必须看得见这个标记**（场景里用斜纹/
//   异色，面板里挂「模拟」章）。理由不是谦虚：一张图里混着实测与样例，
//   而两者只靠颜色区分时，读的人迟早会把样例数当实测数报上去。
//
// ────────────────────────────────────────────────────────────────────
// 坐标系：与地形 GLB **同一个 ENU**。但这里**不写死** e0/n1 ——
//   体块位置用 `u,v ∈ [0,1]`（占地形外接矩形的比例）表达，运行时按
//   `viewdata.grid` 现算成米。写死的话，地形产物换一版（范围一改），
//   体块就整体挪窝，而屏幕上只是"楼摆错地方了"，看不出是坐标系的事。

/** FNV-1a —— 把块 id 变成一个种子。 */
function hash32(s) {
  let h = 2166136261 >>> 0;
  for (let i = 0; i < s.length; i++) {
    h ^= s.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return h >>> 0;
}

/**
 * mulberry32 —— **确定性**伪随机。
 * ★ 为什么不用 `Math.random()`：模拟台账每次刷新都要给出**同一组数**。
 *   随机的话，"3 号楼有 12 部电梯"这句话在你第二次打开时变成 9 部，
 *   而没有任何东西会提醒你它是编的 —— 一个会自己变的数，看起来比
 *   一个固定的数更"真"。
 * ★ 种子是字符串本身 ⇒ 换机器、换浏览器、换时间，同一块 id 得到同一组数。
 */
export function rng(seedStr) {
  let a = hash32(seedStr);
  return () => {
    a = (a + 0x6D2B79F5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

const rect = (w, d) => [[-w / 2, -d / 2], [w / 2, -d / 2], [w / 2, d / 2], [-w / 2, d / 2]];

/** L 形：整块 w×d 挖掉右上角，翼宽 t。 */
function shapeL(w, d, t) {
  return [
    [-w / 2, -d / 2], [w / 2, -d / 2], [w / 2, -d / 2 + t],
    [-w / 2 + t, -d / 2 + t], [-w / 2 + t, d / 2], [-w / 2, d / 2],
  ];
}

/** U 形：整块 w×d，南侧留一条 t 厚的底翼，东西两翼夹一个朝北开的内院。 */
function shapeU(w, d, t) {
  return [
    [-w / 2, -d / 2], [w / 2, -d / 2], [w / 2, d / 2],
    [w / 2 - t, d / 2], [w / 2 - t, -d / 2 + t], [-w / 2 + t, -d / 2 + t],
    [-w / 2 + t, d / 2], [-w / 2, d / 2],
  ];
}

/** 正 n 边形环（体育馆那类）。外圈逆时针、内圈顺时针 —— 洞必须反向才被挖掉。 */
function shapeRing(rOuter, rInner, n) {
  const out = [], inn = [];
  for (let i = 0; i < n; i++) {
    const a = (i / n) * Math.PI * 2;
    out.push([Math.cos(a) * rOuter, Math.sin(a) * rOuter]);
    const b = -a;
    inn.push([Math.cos(b) * rInner, Math.sin(b) * rInner]);
  }
  return { out, hole: inn };
}

/**
 * 体块表。`u,v` 是占地形外接矩形的比例（不是米）。
 *
 * ★ `use` / `floors` 是**编的**（模拟）。`h` 是**给渲染用的高度**，也是编的。
 *   真要有数，得走锚点 → 该栋真实的 `floors` 与 `rooms`（见 panel.js）。
 */
export const MOCK_BLOCKS = [
  { id: 'M-01', u: 0.50, v: 0.30, rot: 0,   h: 26, floors: 6, use: '图书馆 · 阅览与藏书',
    shape: () => shapeU(92, 70, 18), note: 'U 形，内院朝南' },
  { id: 'M-02', u: 0.30, v: 0.385, rot: 0,  h: 22, floors: 5, use: '教学主楼',
    shape: () => shapeL(112, 62, 24) },
  { id: 'M-03', u: 0.70, v: 0.385, rot: 180, h: 22, floors: 5, use: '教学副楼',
    shape: () => shapeL(112, 62, 24) },
  { id: 'M-04', u: 0.215, v: 0.575, rot: 0, h: 20, floors: 5, use: '实验楼 A · 基础实验',
    shape: () => rect(78, 46) },
  { id: 'M-05', u: 0.785, v: 0.575, rot: 0, h: 20, floors: 5, use: '实验楼 B · 专业实验',
    shape: () => rect(78, 46) },
  { id: 'M-06', u: 0.50, v: 0.525, rot: 0,  h: 30, floors: 7, use: '行政与会议中心',
    shape: () => rect(58, 40) },
  { id: 'M-15', u: 0.50, v: 0.66, rot: 22.5, h: 19, floors: 4, use: '大礼堂 · 学术报告厅',
    shape: () => rect(52, 52) },
  { id: 'M-14', u: 0.145, v: 0.215, rot: 0, h: 16, floors: 4, use: '校医院',
    shape: () => rect(62, 40) },
  { id: 'M-13', u: 0.865, v: 0.215, rot: 0, h: 46, floors: 12, use: '科研楼 · 重点实验室',
    shape: () => rect(52, 52) },
  { id: 'M-07', u: 0.235, v: 0.785, rot: 0, h: 18, floors: 3, use: '体育馆',
    shape: () => shapeRing(64, 36, 12) },
  { id: 'M-09', u: 0.615, v: 0.735, rot: 0, h: 26, floors: 7, use: '学生宿舍 1 舍',
    shape: () => rect(86, 22) },
  { id: 'M-10', u: 0.615, v: 0.815, rot: 0, h: 26, floors: 7, use: '学生宿舍 2 舍',
    shape: () => rect(86, 22) },
  { id: 'M-11', u: 0.615, v: 0.895, rot: 0, h: 26, floors: 7, use: '学生宿舍 3 舍',
    shape: () => rect(86, 22) },
  { id: 'M-12', u: 0.845, v: 0.795, rot: 0, h: 14, floors: 3, use: '学生食堂',
    shape: () => rect(66, 54) },
  { id: 'M-16', u: 0.895, v: 0.925, rot: 0, h: 12, floors: 2, use: '后勤与动力中心',
    shape: () => rect(72, 42) },
];

/** 多边形面积（shoelace，恒正）。 */
export function polyArea(pts) {
  let a = 0;
  for (let i = 0, n = pts.length; i < n; i++) {
    const [x1, z1] = pts[i], [x2, z2] = pts[(i + 1) % n];
    a += x1 * z2 - x2 * z1;
  }
  return Math.abs(a) / 2;
}

/**
 * 把 `u,v` 摊成 ENU 米制坐标，并把局部多边形旋到世界系。
 *
 * @param {object} grid viewdata 里的 `grid`：{e0,n1,step,nx,ny}
 * @returns {{blocks: object[], ext: {w:number,d:number}}}
 *   `blocks[i].poly` 是**局部**多边形（米，原点在块心），`x/z` 是块心的 ENU 米。
 *   场景那边建面时用 `x + 局部`，不在这儿合成 —— 合成以后就没法拿它做拾取盒了。
 */
export function layout(grid) {
  // ★ 外接矩形从 **grid 自己**算：`nx * step`，不是从别的什么数推。
  //   这两个数就是地形网格的定义，写成 `427*4.8` 那种手打常数，
  //   地形换一版就对不上了（本仓铁律 174：手打计数只在 N+1 那天出声）。
  const W = grid.nx * grid.step;
  const D = grid.ny * grid.step;

  const blocks = MOCK_BLOCKS.map((b) => {
    const s = b.shape();
    const isRing = s && !Array.isArray(s);
    const poly = isRing ? s.out : s;
    const hole = isRing ? s.hole : null;
    const rad = (b.rot * Math.PI) / 180;
    const cs = Math.cos(rad), sn = Math.sin(rad);
    // ★ 旋的是**坐标**不是角度：局部 (lx,lz) → 世界偏移。
    //   这一步做一次，之后按多边形算的面积/包围盒就都是世界系的量，
    //   免得每处用到时各自再旋一遍（三处各旋一次，迟早有一处漏旋）。
    const rot2 = ([lx, lz]) => [lx * cs - lz * sn, lx * sn + lz * cs];
    const world = poly.map(rot2);
    return {
      ...b, mock: true,
      x: b.u * W, z: b.v * D,
      local: poly, hole: hole ? hole.map(rot2) : null,
      world,                              // 相对块心的世界朝向多边形
      area_m2: polyArea(world),
    };
  });

  return { blocks, ext: { w: W, d: D } };
}

/**
 * 体块外接半径（米）—— 拾取与相机取景要用。
 * ★ 用**真多边形**算，不用 `Math.max(w,d)/2` 那种估法：L 形与环形的
 *   实际外接半径差得远，估小了会在边缘处拾取不到，而那种失效看起来
 *   像是"这点没画东西"。
 */
export function radiusOf(b) {
  let r = 0;
  for (const [x, z] of b.world) r = Math.max(r, Math.hypot(x, z));
  return r;
}
