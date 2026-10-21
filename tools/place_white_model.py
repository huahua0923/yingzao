#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""把**白模**与**实景主件**放到同一个公共局部帧里，供网页分层叠加（步 5 ②）。

    python -I tools/place_white_model.py [--out <目录>] [--margin-m 60] [--anchor ground|roof]
                                        [--blocks a,b] [--key 1层]

【做什么】三件，各自落一个文件：
  ① 白模  `rebuild/05_build/c006_white.glb`
     → `RP.model_placement()` 拿 2D 刚体位姿 → `RP.model_glb_to_en()` 映到 (E, N)
     → 竖向 `h = h0 + y`（y ＝ glb 的 y ＝ 相对 ±0.000 的米） → 公共局部帧
     ⇒ `<out>/white_local.glb`
  ② 实景  `_layers/reality_c006/<块>/<块>.glb`（**由程序现列文件系统**，不手打块名）
     → `RP.glb_to_4544_grid()` → 公共局部帧 → **按白模平面范围 + 边距裁剪** →
     再按**模型 1 层轮廓多边形**（172 点，非凸，**不是包围盒**）切成两层：
       · `<out>/reality_local.glb`       —— 远景：轮廓**外**（楼四周，带纹理）
       · `<out>/reality_fill_local.glb`  —— 近景糊面：轮廓**内**（可由白模顶替）
     ★ 只换**楼身上那一层**、不藏整个实景 —— 否则连楼周围的地面也没了，看着像模型悬空。
  ③ 出处档 `<out>/layers_c006.json`：三个输入件的 sha256、θ/tr_en/残差、两个竖向锚、
     各层包围盒、覆盖自检读数、两层面数（**必须互补**）。

【公共局部帧】（three.js 右手 Y-up）
    ORIGIN = (OE, ON, OH)
    to_local(E, N, h) = ( E − OE , h − OH , −(N − ON) )
  ★ 为什么 z 取负：水平两轴要与竖直轴成右手 —— E × U = −N ⇒ 第二水平轴必须取 **−N**。
  ★ 实景层在这个帧里是**纯平移**（`E = 416281 + x`、`N = 3393904 − z`、`h = 422 + y`），
    **不含旋转**；旋转只在白模那一侧（θ = 110°）。

【竖向锚 h0 两个候选 —— 本工具**不挑**】
  见 `RP.vertical_anchors()`。本工具按 `--anchor` 选一个出件，并把**两个**都写进出处档、
  把 `delta_m` 一并落盘；网页用 `delta_m` 做**运行时整体平移**（纯 Y 平移、逐位精确），
  把两个候选**都摆给人看**。
  ★ 谁裁：用户。理由见 `gates/J-10.10-08` 判词与盲区 —— 两个候选读数的差**恒等于**
    ③ 的偏差，「层高其实是 4.0 m」与「模型 ±0.000 不在实测地面上」给出**同一个读数**
    （铁律 018），本工具**结构上分不开**，不许自己改口径。

【量具盲区】（如实说，别把本件当判据）
  ① 本件**只做坐标变换与裁剪**，**不判「两层叠得对不对」** —— 那是 `gates/J-10.10-09` 的事。
  ② 裁剪以**面心**是否落在盒内为准 ⇒ 跨界面的**整块保留或整块丢弃**，不是精确求交。
     所以边距（`--margin-m`）必须**足够大**；本件**自检**：白模平面范围必须完全落在
     裁剪盒内，否则**报错退出**（不许悄悄出一个缺了角的层）。
  ③ 2D 落位残差 ≤1e-6 m 只证明「**复算 = 盘上存的那份**」，**不证明落位本身对** ——
     落位对错由 `J-10.8-01` 的 IoU 0.7487 / 边界中位 2.06 m 说话。
  ④ 实景侧的 h **完全来自瓦片自己的锚**（约定 B），与白模的 h0 是**两个独立来源**；
     即便白模 h0 选对，**两面墙之间的竖向残差**也不由本件保证 —— 本件只保证「同帧」，
     不保证「同高」。这条必须由闸量，不许拿本件的残差冒充。
  ⑤ 白模**没有 UV、没有贴图**：本件是**几何层**，不解决白模上色。
"""

import argparse
import glob
import hashlib
import json
import math
import os
import sys

import numpy as np
import trimesh
from trimesh.visual import TextureVisuals

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import reality_placement as RP      # noqa: E402

REPO = RP.REPO
LAYERS_DIR = os.path.join(REPO, "过程/_layers", "reality_c006")
DEFAULT_OUT = os.path.join(REPO, "过程/_layers", "layers_c006")
_RC_OK, _RC_FAIL = 0, 1


def _sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


class _KeepImage:
    """★ 包住 PIL 图，只为让 trimesh 的 glb 写出器**别动这张贴图**。

    不包有两条暗伤，**都不出声**（本仓 2026-10-16 实测 57.1 MB → 563.0 MB）：
      ① `TextureVisuals.copy()` → `PBRMaterial.copy()` 会调 `PIL.Image.copy()`，
         而 PIL 的 copy **不带上 `.format`**；trimesh 的 `_append_image` 只认
         `img.format == "JPEG"`，判不出来就走 PNG 分支 ⇒ 每张贴图涨 7~8 倍；
      ② 就算格式对了，trimesh 调 `img.save(f, format=...)` **不传 quality**
         ⇒ Pillow 按 q75 重压，白掉一代画质。
    ⇒ 这里给 `quality="keep"` ＋ `subsampling="keep"` ＋ `qtables="keep"`：
      **原图的量化表原样复用**。
    ★ 本件**不改一个像素**，只做「原样搬运」；也不做任何画质判断 —— 那是闸的事。
    ★ 另一条现成的路是「干脆不 copy 材质、共享同一个 PIL 图」，但那样 `uv` 没法按
      顶点重编号（本件要按轮廓切层），所以从**图像对象**这一层下手。
    """

    __slots__ = ("_im", "_fmt")

    def __init__(self, im):
        self._im = im
        # ★ `PIL.Image.open()` 出来的图 .format 是 'JPEG'/'PNG'；取不到就按 PNG 走
        #   （宁可大，不可丢 —— 但那种情况由闸的字节量具点名，不许静默）
        self._fmt = getattr(im, "format", None) or "PNG"

    @property
    def format(self):
        return self._fmt

    def save(self, fp, format=None):                      # noqa: A002 —— trimesh 按位置/关键字都传
        if self._fmt == "JPEG":
            try:
                self._im.save(fp, format="JPEG", quality="keep",
                              subsampling="keep", qtables="keep")
                return
            except (OSError, ValueError, AttributeError):
                # 渐进式 JPEG 等拿不到量化表的，退回高质量重压；**不许静默掉到 q75**
                self._im.save(fp, format="JPEG", quality=95, subsampling="keep")
                return
        self._im.save(fp, format=self._fmt)

    def copy(self):
        """trimesh 的 `PBRMaterial.copy()` 会调它。本件包的是**不可变**的贴图 ⇒ 返回自己。"""
        return self

    def __array__(self, dtype=None, copy=None):           # noqa: A002
        """`PBRMaterial.__hash__` 要对 `_data` 里每项取 `np.asanyarray(v).tobytes()`
        ⇒ 本件必须能变成数组，否则材质哈希直接炸。"""
        return np.asarray(self._im, dtype=dtype)


def _submesh(g: trimesh.Trimesh, loc: np.ndarray, mask=None) -> trimesh.Trimesh:
    """按面掩膜裁一块，**顶点与 UV 一起重编号**；`mask=None` ＝ 不裁面。

    ★ 为什么不用现成的 `g.copy()` ＋ `update_faces()` ＋ `remove_unreferenced_vertices()`：
      那条路**每一步都会 copy 一次材质**（`TextureVisuals.copy()` → `PBRMaterial.copy()`
      → `PIL.Image.copy()`），于是 `.format` 丢掉、贴图被按 PNG 重存。见 `_KeepImage`。
    ⇒ 本函数**只搬顶点与 UV，不碰材质对象**。
    """
    f = np.asarray(g.faces, dtype=np.int64)
    if mask is not None:
        f = f[np.asarray(mask, dtype=bool)]
    used = np.unique(f)
    remap = np.full(len(g.vertices), -1, dtype=np.int64)
    remap[used] = np.arange(len(used), dtype=np.int64)
    out = trimesh.Trimesh(vertices=np.asarray(loc, dtype=float)[used],
                          faces=remap[f], process=False)
    vis = getattr(g, "visual", None)
    uv = getattr(vis, "uv", None)
    if uv is not None:
        mat = getattr(vis, "material", None)
        out.visual = TextureVisuals(uv=np.asarray(uv, dtype=np.float64)[used],
                                    material=_wrap_material(mat))
    return out


def _wrap_material(mat):
    """把材质里的那张贴图换成 `_KeepImage`。★ 其余键**一个不动**。"""
    if mat is None:
        return None
    tex = getattr(mat, "baseColorTexture", None)
    if tex is None or isinstance(tex, _KeepImage):
        return mat
    new = mat.copy()                       # 这里 copy 一次没关系：图像还没被换进去
    new.baseColorTexture = _KeepImage(tex)
    return new


def _geom_node_map(sc: trimesh.Scene, tag: str) -> dict:
    """geometry 名 → 它的那个 node 名。★ 一个 geometry 只能挂在**一个** node 上：
    挂多处＝被实例化了多份，那必须**逐实例**产出，本件不处理 ⇒ 直接报错，不许只搬一份。"""
    m = {}
    for n in sc.graph.nodes:
        g = sc.graph[n][1]
        m.setdefault(g, []).append(n)
    multi = {g: ns for g, ns in m.items() if len(ns) != 1}
    if multi:
        raise ValueError("%s 有 geometry 被多个 node 引用（%d 个，例：%s）⇒ 本件不处理实例化，"
                         "拒绝出数" % (tag, len(multi), list(multi.items())[:2]))
    return {g: ns[0] for g, ns in m.items()}


def _to_world(sc: trimesh.Scene, node: str, g: trimesh.Trimesh) -> np.ndarray:
    """把该 node 的 transform **烘进顶点** ⇒ **场景帧（glb Y-up）**顶点。

    ★ 为什么必须烘：实测 `c006_white.glb` 的 88 个节点**全都带非单位 transform**
      —— 那是 **Z-up(CAD) → Y-up(glTF) 的翻转** `(x, y, z) → (x, z, −y)`
      （几何局部 x[58.8,146.4] y[42.5,98.9] z[−3.5,0]，乘完正好落进场景盒
      x[17.25,146.55] y[−3.5,41.5] z[−99,−15]）。**不烘就等于把白模摆错一个翻转**
      —— 症状是「白模看着像栋楼、位置却完全不对」，而**没有任何东西会报错**
      （铁律 183：一处改了、兄弟没改）。
    ★ 实景主件那边实测全是单位阵，但**照同一段代码走**：两条路只留一份实现，
      哪天源件带上真 transform，两边一起对，不会只对一边（铁律 174）。
    """
    T, _ = sc.graph.get(frame_to=node)
    return trimesh.transformations.transform_points(np.asarray(g.vertices, dtype=float),
                                                    np.asarray(T, dtype=float))


def _assert_world_matches_scene(sc: trimesh.Scene, wmin, wmax, tag: str) -> None:
    """★ **两手对账**：本件烘出来的场景帧包围盒，必须与 trimesh 自己给的 `sc.bounds` 同解。
    这是**两个来源**（本件的逐点烘焙 vs 库自己走的图），不是自说自话。对不上就报错。"""
    a = np.asarray(sc.bounds, dtype=float)
    b = np.array([wmin, wmax], dtype=float)
    err = float(np.abs(a - b).max())
    if not (err <= 1e-6):
        raise ValueError("%s 烘出来的场景帧包围盒与 trimesh 的 sc.bounds 差 %.3e m（>1e-6）\n"
                         "  本件算出 %s\n  库  给出 %s\n⇒ 本件对节点 transform 的读法有误，拒绝出数"
                         % (tag, err, b.tolist(), a.tolist()))


# ────────────────────────────── 白模 ──────────────────────────────
def build_white(mp, h0, OE, ON, OH, extra_yaw_deg=0.0):
    """白模 → 公共局部帧。`extra_yaw_deg` 绕**落位质心**再转一次（见 `--yaw-extra`）。

    ★ 为什么这一转**不写回** `regbest_1层.json`：那是 **DOM 配准**的读数，`J-10.8-01`
      与 `RP.model_placement()` 都按它复算。实测该平面**近乎中心对称**
      （8 层塔楼质心离落位质心只有 4 m），IoU 对 180° **不敏感**：
      θ=110 → 0.7466、θ=290 → 0.7214，塔楼掩膜 IoU 0.3347 / 0.3250
      ⇒ **尺子分不开**，不是「尺子说 110 对」。用户按外观裁 180°（2026-10-18）。
      ⇒ 于是把这一转记成**另一个量**（`extra_yaw_deg`），与配准的 θ **不同名、分开落盘**，
        谁在哪个口径上看的数一眼就能分清（铁律 174/197）。
    """
    dyaw = math.radians(float(extra_yaw_deg))
    R2 = np.array([[math.cos(dyaw), -math.sin(dyaw)], [math.sin(dyaw), math.cos(dyaw)]])
    tr2 = np.asarray(mp["tr_en"], dtype=float)
    sc = trimesh.load(RP.WHITE_GLB, force="scene")
    tag = "白模 " + os.path.basename(RP.WHITE_GLB)
    g2n = _geom_node_map(sc, tag)
    out = trimesh.Scene()
    n_v = n_f = 0
    en_lo = np.array([np.inf, np.inf]); en_hi = np.array([-np.inf, -np.inf])
    wmin = np.array([np.inf] * 3); wmax = np.array([-np.inf] * 3)
    has_uv = False
    for name, g in sc.geometry.items():
        w = _to_world(sc, g2n[name], g)              # ★ 先烘节点 transform ⇒ 场景帧（glb Y-up）
        E, N, y = RP.model_glb_to_en(w, mp)          # ← 平面两步**只在这里拼一次**
        if extra_yaw_deg:                            # ★ 绕落位质心再转（用户裁的 180°）
            en = (np.c_[E, N] - tr2) @ R2.T + tr2
            E, N = en[:, 0], en[:, 1]
        loc = np.c_[E - OE, (h0 + y) - OH, -(N - ON)]
        ng = _submesh(g, loc, None)                  # 不裁面，只搬顶点（★ 不碰材质）
        out.add_geometry(ng, node_name=name, geom_name=name)
        n_v += int(len(w)); n_f += int(len(g.faces))
        has_uv = has_uv or (getattr(g.visual, "uv", None) is not None)
        en_lo = np.minimum(en_lo, [E.min(), N.min()])
        en_hi = np.maximum(en_hi, [E.max(), N.max()])
        wmin = np.minimum(wmin, w.min(0)); wmax = np.maximum(wmax, w.max(0))
    _assert_world_matches_scene(sc, wmin, wmax, tag)
    return out, {"n_geometry": len(sc.geometry), "n_vertices": n_v, "n_faces": n_f,
                 "en_lo": en_lo.tolist(), "en_hi": en_hi.tolist(), "has_uv": bool(has_uv),
                 "glb_scene_bounds": np.array([wmin, wmax]).tolist()}


# ────────────────────────────── 实景 ──────────────────────────────
def list_blocks(layers_dir: str):
    """★ 块名**由程序现列文件系统**得出，不手打（真源＝文件系统，仓规）。"""
    return sorted(os.path.basename(p) for p in glob.glob(os.path.join(layers_dir, "*"))
                  if os.path.isdir(p)
                  and os.path.exists(os.path.join(p, os.path.basename(p) + ".glb")))


def _in_polygon(pts, poly) -> np.ndarray:
    """**向量化奇偶跨越判定**：点集是否落在（可非凸的）平面多边形内。

    ★ 为什么要多边形而不是包围盒：模型 1 层轮廓是**转了个 110° 的矩形**，
      它的轴对齐包围盒面积约是实际轮廓的 2 倍 —— 拿包围盒当「楼占的地方」，
      会把楼周围一大片**真实的实景**一起抠掉，页面上就是楼边凭空缺一片。
    ★ 边界上的点算「内」（`>=`/`<` 的取向不影响本用途：它是**分层显示**，
      不是面积核算，落在墙线上的一圈面归哪边都看得过去）。
    """
    p = np.asarray(pts, dtype=float)
    q = np.asarray(poly, dtype=float)
    inside = np.zeros(len(p), dtype=bool)
    x, y = p[:, 0], p[:, 1]
    n = len(q)
    for i in range(n):
        x1, y1 = q[i]
        x2, y2 = q[(i + 1) % n]
        if y1 == y2:
            continue
        # 射线朝 +x：只有当 y 落在 [min,max) 内才算跨过
        cond = ((y1 > y) != (y2 > y))
        xint = x1 + (y - y1) * (x2 - x1) / (y2 - y1)
        inside ^= cond & (x < xint)
    return inside


def _glb_bbox_to_en(b, anc):
    """glb 轴对齐盒 → EN 盒。glb `(x, z)` → `E = E₀+x`、`N = N₀−z` ⇒ z 的上下限**互换**。"""
    E0, E1 = anc["E4544"] + b[0, 0], anc["E4544"] + b[1, 0]
    N0, N1 = anc["N4544"] - b[1, 2], anc["N4544"] - b[0, 2]
    return np.array([E0, N0]), np.array([E1, N1])


def build_reality(blocks, layers_dir, anc, box_lo_en, box_hi_en, outline_en, OE, ON, OH):
    """实景主件 → **两层**，同一段代码、只差一个面掩膜：

        far  （远景层）：裁剪盒内 ∩ 模型轮廓**外** —— 楼四周的街景与地面，**带纹理**
        fill （近景糊面）：裁剪盒内 ∩ 模型轮廓**内** —— 就是「近景糊面」，可由白模顶替

    ★ 分两层而不是「近景时把实景整个藏掉」：那样连楼周围的地面也没了，
      看起来像模型悬空。**换的只是楼身上那一层**，这正是方案 §7.4.1 分层的本意。
    ★ 两层面数必须**互补**（far + fill == 裁剪后总面数）—— 这条由闸核，不许在这里印完了事。
    """
    far = trimesh.Scene()
    fill = trimesh.Scene()
    stat = []
    corners = np.array([[box_lo_en[0], box_lo_en[1]], [box_lo_en[0], box_hi_en[1]],
                        [box_hi_en[0], box_lo_en[1]], [box_hi_en[0], box_hi_en[1]]])
    covered = np.zeros(4, dtype=bool)
    for b in blocks:
        p = os.path.join(layers_dir, b, b + ".glb")
        sc = trimesh.load(p, force="scene")
        tag = "实景主件 " + b
        g2n = _geom_node_map(sc, tag)
        kept_f = tot_f = far_f = fill_f = 0
        wmin = np.array([np.inf] * 3); wmax = np.array([-np.inf] * 3)
        blk_lo = np.array([np.inf, np.inf]); blk_hi = np.array([-np.inf, -np.inf])
        for name, g in sc.geometry.items():
            w = _to_world(sc, g2n[name], g)          # ★ 与白模**同一段代码**（那条实测是单位阵，
            E, N, h = RP.glb_to_4544_grid(w, anc)    #    但两份实现迟早会漂，只留一份）
            tot_f += int(len(g.faces))
            wmin = np.minimum(wmin, w.min(0)); wmax = np.maximum(wmax, w.max(0))
            lo, hi = _glb_bbox_to_en(np.c_[w.min(0), w.max(0)].T, anc)
            blk_lo = np.minimum(blk_lo, lo); blk_hi = np.maximum(blk_hi, hi)
            fc = w[np.asarray(g.faces, dtype=int)].mean(axis=1)   # 面心（已是场景帧）
            fE, fN, _fh = RP.glb_to_4544_grid(fc, anc)
            inbox = ((fE >= box_lo_en[0]) & (fE <= box_hi_en[0]) &
                     (fN >= box_lo_en[1]) & (fN <= box_hi_en[1]))
            if not inbox.any():
                continue
            insc = _in_polygon(np.c_[fE, fN], outline_en)
            loc = np.c_[E - OE, h - OH, -(N - ON)]   # ★ 先摆坐标（顶点数与面索引一致）
            for sc_out, mask, acc in ((far, inbox & ~insc, "far"), (fill, inbox & insc, "fill")):
                if not mask.any():
                    continue
                ng = _submesh(g, loc, mask)           # 面掩膜裁 ＋ 顶点/UV 一起重编号
                sc_out.add_geometry(ng, node_name=("%s__%s" % (acc, name)), geom_name=("%s__%s" % (acc, name)))
                if acc == "far":
                    far_f += int(len(ng.faces))
                else:
                    fill_f += int(len(ng.faces))
        kept_f = far_f + fill_f
        _assert_world_matches_scene(sc, wmin, wmax, tag)
        covered |= ((corners[:, 0] >= blk_lo[0]) & (corners[:, 0] <= blk_hi[0]) &
                    (corners[:, 1] >= blk_lo[1]) & (corners[:, 1] <= blk_hi[1]))
        stat.append({"block": b, "faces_total": tot_f, "faces_kept": kept_f,
                     "faces_far": far_f, "faces_fill": fill_f,
                     "en_lo": blk_lo.tolist(), "en_hi": blk_hi.tolist(),
                     "glb_scene_bounds": np.array([wmin, wmax]).tolist(),
                     "src_sha256": _sha256(p), "src_bytes": os.path.getsize(p)})
    return far, fill, stat, int(covered.sum())


# ────────────────────────────── main ──────────────────────────────
def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=DEFAULT_OUT)
    ap.add_argument("--layers", default=LAYERS_DIR)
    ap.add_argument("--margin-m", type=float, default=60.0)
    ap.add_argument("--anchor", choices=["ground", "roof"], default="ground")
    ap.add_argument("--key", default="1层")
    ap.add_argument("--blocks", default="")
    ap.add_argument("--yaw-extra", type=float, default=0.0,
                    help="绕落位质心再转的角度（deg）。★ 只改白模这一层，不动 regbest")
    a = ap.parse_args(argv)
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    mp = RP.model_placement(a.key)
    va = RP.vertical_anchors()
    h0 = va["h0_ground_m"] if a.anchor == "ground" else va["h0_roof_m"]

    # ★ 帧原点：平面取**模型落位质心**（不是手打数，是 model_placement 现算的），
    #   竖向取**地面候选**——固定用地面那个，好让两个候选在页面上只差一个纯 Y 平移。
    OE, ON, OH = float(mp["tr_en"][0]), float(mp["tr_en"][1]), float(va["h0_ground_m"])
    other = va["h0_roof_m"] if a.anchor == "ground" else va["h0_ground_m"]
    print("[帧] ORIGIN = (%.6f, %.6f, %.6f)" % (OE, ON, OH))
    print("[竖向] h0 选用 = %s ⇒ %.6f m ｜ 另一候选 %.6f m ｜ delta = %.6f m"
          % (a.anchor, h0, other, va["delta_m"]))

    white, wstat = build_white(mp, h0, OE, ON, OH, a.yaw_extra)
    box_lo = np.asarray(wstat["en_lo"], dtype=float) - a.margin_m
    box_hi = np.asarray(wstat["en_hi"], dtype=float) + a.margin_m
    print("[白模] %d geometry ｜ %d 顶点 ｜ %d 面 ｜ UV=%s ｜ 平面 E[%.1f,%.1f] N[%.1f,%.1f]"
          % (wstat["n_geometry"], wstat["n_vertices"], wstat["n_faces"], wstat["has_uv"],
             wstat["en_lo"][0], wstat["en_hi"][0], wstat["en_lo"][1], wstat["en_hi"][1]))
    print("[裁剪盒] 白模范围 + %.1f m 边距 ⇒ E[%.1f,%.1f] N[%.1f,%.1f]"
          % (a.margin_m, box_lo[0], box_hi[0], box_lo[1], box_hi[1]))

    blocks = [s for s in a.blocks.split(",") if s] or list_blocks(a.layers)
    print("[实景] 块（程序现列）= %s" % blocks)
    anc = RP.anchor(RP.load_tileset())
    far, fill, rstat, n_cover = build_reality(blocks, a.layers, anc, box_lo, box_hi,
                                              mp["outline_en"], OE, ON, OH)
    for s in rstat:
        print("       %-16s 面 %7d → 裁剪盒内 %7d（远景 %7d + 近景糊面 %7d）"
              % (s["block"], s["faces_total"], s["faces_kept"], s["faces_far"], s["faces_fill"]))
    print("[覆盖自检] 裁剪盒四角被实景覆盖 %d/4" % n_cover)
    if n_cover < 4:
        print("    ⇒ ★ 如实：白模范围（含边距）没有被实景全覆盖，网页上会看到"
              "「白模旁边没有实景」——这是**真的没拍到/没转**，不是坏件。")

    kept = sum(s["faces_kept"] for s in rstat)
    if wstat["n_faces"] <= 0:
        print("白模层为空 ⇒ 拒绝出数", file=sys.stderr)
        return _RC_FAIL
    if kept <= 0:
        print("实景层被裁成空 ⇒ 拒绝出数（边距太小？块不全？）", file=sys.stderr)
        return _RC_FAIL
    if len(fill.geometry) == 0:
        print("近景糊面层为空 ⇒ 拒绝出数（轮廓多边形与裁剪盒对不上？）", file=sys.stderr)
        return _RC_FAIL

    os.makedirs(a.out, exist_ok=True)
    wp = os.path.join(a.out, "white_local.glb")
    rp = os.path.join(a.out, "reality_local.glb")
    fp = os.path.join(a.out, "reality_fill_local.glb")
    white.export(wp)
    far.export(rp)
    fill.export(fp)

    prov = {
        "schema": "cdut3d-reality-layerstack/1",
        "local_frame": {"origin_en_h": [OE, ON, OH],
                        "map": "xl=E-OE, yl=h-OH, zl=-(N-ON)（three.js 右手 Y-up）"},
        "model_placement": {"key": mp["key"], "theta_deg": mp["theta_deg"], "yflip": mp["yflip"],
                            "plan_ctr_m": mp["plan_ctr_m"].tolist(), "tr_en": mp["tr_en"].tolist(),
                            "best_iou": mp["best_iou"],
                            "boundary_median_m": mp["boundary_median_m"],
                            "boundary_p90_m": mp["boundary_p90_m"],
                            "selfcheck_max_err_m": mp["selfcheck_max_err_m"],
                            "src": mp["src"],
                            "extra_yaw": {"deg": float(a.yaw_extra),
                                          "pivot_en": [float(OE), float(ON)],
                                          "note": "★ 与 theta_deg 不是同一个量：theta_deg 是 DOM 配准读数；"
                                                  "extra_yaw 是用户按外观裁的附加转角（2026-10-18 裁 180°）。"
                                                  "平面近乎中心对称 ⇒ IoU 对 180° 不敏感（θ=110→0.7466 / θ=290→0.7214），"
                                                  "尺子分不开，不是尺子说 110 对"}},
        "vertical_anchor": {"chosen": a.anchor, "h0_m": h0,
                            "h0_ground_m": va["h0_ground_m"], "h0_roof_m": va["h0_roof_m"],
                            "delta_m": va["delta_m"], "ground_spread_m": va["ground_spread_m"],
                            "item3": va["item3"], "src": va["src"],
                            "note": "★ delta_m 是两个候选的差，恒等于 ③ 的偏差；由用户裁，本工具不挑"},
        "white": dict(wstat, path=os.path.relpath(wp, REPO).replace("\\", "/"),
                      src=os.path.relpath(RP.WHITE_GLB, REPO).replace("\\", "/"),
                      src_sha256=_sha256(RP.WHITE_GLB),
                      src_bytes=os.path.getsize(RP.WHITE_GLB),
                      out_bytes=os.path.getsize(wp),
                      bbox_local=np.asarray(white.bounds, dtype=float).tolist()),
        "reality": {"margin_m": a.margin_m, "clip_lo_en": box_lo.tolist(),
                    "clip_hi_en": box_hi.tolist(), "corners_covered": n_cover,
                    "faces_kept": kept,
                    "faces_far": sum(s["faces_far"] for s in rstat),
                    "faces_fill": sum(s["faces_fill"] for s in rstat),
                    "outline_n": int(len(mp["outline_en"])),
                    "blocks": rstat,
                    "far_path": os.path.relpath(rp, REPO).replace("\\", "/"),
                    "far_bytes": os.path.getsize(rp),
                    "far_bbox_local": np.asarray(far.bounds, dtype=float).tolist(),
                    "fill_path": os.path.relpath(fp, REPO).replace("\\", "/"),
                    "fill_bytes": os.path.getsize(fp),
                    "fill_bbox_local": np.asarray(fill.bounds, dtype=float).tolist()},
        "tileset_anchor": {"E4544": anc["E4544"], "N4544": anc["N4544"], "h": anc["h"],
                           "lat": anc["lat"], "lon": anc["lon"]},
        "controls": {"delta_equals_item3": bool(
            abs(va["delta_m"] - (va["item3"]["read"] - va["item3"]["decl"])) < 1e-9)},
    }
    jp = os.path.join(a.out, "layers_c006.json")
    with open(jp, "wb") as f:                      # ★ 字节层写盘（铁律 79/123）
        f.write(json.dumps(prov, ensure_ascii=False, indent=1, allow_nan=False).encode("utf-8"))
    print("[出件] white_local.glb %.2f MB ｜ reality_local.glb %.2f MB ｜ "
          "reality_fill_local.glb %.2f MB ｜ layers_c006.json"
          % (os.path.getsize(wp) / 1e6, os.path.getsize(rp) / 1e6, os.path.getsize(fp) / 1e6))
    print("place_white_model: OK")
    return _RC_OK


if __name__ == "__main__":
    sys.exit(main())
