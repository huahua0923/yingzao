// ★★ 「EPSG:4544 的点」→「实景瓦片世界里的点」—— **整个系统里只有这一处定义。**
//
// 第 0 关（2026-10-02）已经把这个式子在**渲染出来的像素上**判决过一次，结论是**朴素平移**：
//
//     local = (E − 416281.0,  N − 3393904.0,  h − 422.0)      ← 喂给 Cesium
//     父变换 = tileset.root.transform（瓦片自己的那个）
//
// 为什么不是「精确反解」（`local = M⁻¹ · pyproj(4544→4978)(E,N,h)`）：
//   两者只差一个 **0.446° 的偏航**，也就是「瓦片的内容坐标系」与「真实地心方位」之间的
//   子午线收敛。实测（同一机位、同一份 341 条轮廓、只换 `v=A` / `v=B`）：
//     · 朴素 A 的补偿渲染**贴着屋脊轮廓**；
//     · 精确 B 整体偏 **17~27.5 m**，肉眼可见地歪出建筑。
//   ⇒ 瓦片的内容帧**不是**真 ENU，它跟 EPSG:4544 的格网轴对齐。所以正确的动作是
//     **别去纠那个偏航** —— 一纠，反而把对齐纠坏了。
//
// ★ 这一条与本仓铁律 118 同一个形状：「它不是我以为的那个东西」不等于「数据坏了」。
//   我原来以为 `root.transform` 的旋转列是一支干净 ENU 基（它反解出来的纬度经度都对），
//   于是推出一条「精确」公式；**但那是模型的朝向，不是内容的朝向**。
//
// ★ 三只对照（缺一不可，见第 0 关）：
//   · 正向：按上式摆，落屋顶上；
//   · 负向：同一条轮廓整体平移 100 m ⇒ **判据必须报错**（证明判据有分辨力）；
//   · 阴性：取一个不存在的原点 ⇒ 明显落到场外。
//   下面 `selfCheck()` 把其中最要紧的一条做成了可执行断言：**A 与 B 必须在 1 km 尺度上
//   真的分得开**（约 7.8 m）。若两者算出来一样，说明我抄错了 —— 那时整条对齐都是假的。

/** 局部帧原点（EPSG:4544，米）。三个整数是**站点网格原点**，不是从数据推出来的点。 */
export const ORIGIN = Object.freeze({ E: 416281.0, N: 3393904.0, h: 422.0 });

/**
 * EPSG:4544 的 (E, N, h) → 瓦片局部帧的 (x, y, z)。
 * ★ 纯平移，没有旋转、没有缩放 —— 这就是第 0 关的判决。
 */
export function localOf(E, N, h) {
  return [E - ORIGIN.E, N - ORIGIN.N, h - ORIGIN.h];
}

/**
 * 从瓦片自己的 `root.transform` 取「局部 → 地心（ECEF）」那一支。
 *
 * ★ 为什么用**它的**矩阵而不是自己算一套 ECEF：瓦片的内容就是按这个矩阵摆的，
 *   借它的矩阵 = 借它的口径。自己另立一套（哪怕数学上更"正确"）就会落回候选 B，
 *   也就是那个偏 17~27.5 m 的答案。
 * ★ 返回的 `up` 是局部 +z 在世界里的方向（单位向量）—— 机位要沿"上"抬升时用它，
 *   不许写 `new Cartesian3(0,0,1)`（那是局部的，不是世界的）。
 */
export function axialFromTileset(tileset) {
  const tf = tileset.root.transform;
  const a = (tf && typeof tf.length === 'number' && tf.length === 16)
    ? Array.from(tf)
    : CesiumMatrixToArray(tf);
  const up = normalize3([a[8], a[9], a[10]]);
  /** local(x,y,z) → world(ECEF) */
  function toEcef(x, y, z) {
    return {
      x: a[0] * x + a[4] * y + a[8] * z + a[12],
      y: a[1] * x + a[5] * y + a[9] * z + a[13],
      z: a[2] * x + a[6] * y + a[10] * z + a[14],
    };
  }
  return { toEcef, up, matrix: a };
}

/** 内部：`Matrix4` → 列主序的 16 个数。只在拿不到数组时兜底。 */
function CesiumMatrixToArray(M) {
  const out = new Array(16);
  for (let c = 0; c < 4; c += 1) {
    for (let r = 0; r < 4; r += 1) out[c * 4 + r] = M[c * 4 + r];
  }
  return out;
}

function normalize3(v) {
  const n = Math.hypot(v[0], v[1], v[2]) || 1;
  return [v[0] / n, v[1] / n, v[2] / n];
}

/**
 * 自证 —— 在自己身上找一次**候选 B**，因为 B 才是这条式子的反例。
 *
 * ★ 阴性对照的前提必须把**要验的那个变量**孤立出来（本仓铁律 028）：这里要验的
 *   变量就是「那个 0.446° 偏航到底有没有被消掉」。B 消掉了、A 没消，
 *   所以两者**必须在 1 km 尺度上分得开**。若它们相等 ⇒ 我抄错了，整条对齐都是假的。
 * ★ 判据本体在**别处**（渲染出来的像素）；这里只挡最粗的一类错，不假装它是全判据。
 *
 * @param {(E:number,N:number,h:number)=>number[]} exactB 候选 B 的实现（可选）
 */
export function selfCheck(exactB) {
  const a = localOf(417281.0, 3394904.0, 500.0);          // 离原点 (1000, 1000, 78)
  const near = Math.abs(a[0] - 1000) < 1e-9 && Math.abs(a[1] - 1000) < 1e-9
    && Math.abs(a[2] - 78) < 1e-9;
  const out = { ok: near, checks: [] };
  out.checks.push({
    name: '原点自洽：localOf(E0+1000, N0+1000, h0+78) === (1000, 1000, 78)',
    ok: near, got: a,
  });
  if (exactB) {
    const b = exactB(417281.0, 3394904.0, 500.0);
    const d = Math.hypot(b[0] - a[0], b[1] - a[1]);
    const ok = d > 5 && d < 12;      // 理论 0.446° × 1414 m ≈ 11 m（半径 1414 m 处）
    out.checks.push({
      name: 'A 与候选 B 在 1 km 尺度上分得开（不然就是抄错了）', ok, got: +d.toFixed(3),
    });
    out.ok = out.ok && ok;
  }
  return out;
}
