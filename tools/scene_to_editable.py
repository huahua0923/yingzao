# -*- coding: utf-8 -*-
r"""瓦片 → 可编辑主件（步 1 地基；规范见 规范/实景主件格式-v1.md）。

**为什么要有它**：整条实景链今天是**单向**的（影像 → MVS → 瓦片 → 展示），
没有一处能「改完再装回去」。本工具出**可编辑主件**（逐片一个子网格 ＋ 各自的贴图），
由 `tools/editable_to_tiles.py` 装回去；两者合起来就是「可以修改完善」的技术定义（规范 §1）。

★★ 本工具取的是 **LOD 前沿**，**不是**「取最高的那几片 LOD」——
   实测 `Tile_+003_+005` 最高 LOD=19 **只有 2 片**，而它的 L18 有 **4 片**：
   ```
   L17_0uuuu
     ├ L18_0uuuu0    ← 无更深子 ⇒ 前沿
     ├ L18_0uuuu1    ← 无更深子 ⇒ 前沿
     ├ L18_0uuuu2
     │   ├ L19_0uuuu20   ← 前沿
     │   └ L19_0uuuu21   ← 前沿
     └ L18_0uuuu3    ← 无更深子 ⇒ 前沿
   ```
   ⇒ 只取「L19 那 2 片」＝拿到这块的 **1/4**，**而且一声不吭**（铁律 137 的形状：
   名单漏掉主体则永远绿）。`refine=REPLACE` ⇒ 正解是**前沿**：
   有 content 且其下没有更深 content 的节点集合，它恰好**无缝、无重叠、且最深**。
   全库实测：48,694 带 content 节点 → **34,740 前沿片**（13,954 片是被替换的祖先）。

★ **叶名真源 = 程序现列文件系统**，**不信 `meta.json`**——
  实测它的 `lods[].children_files` **48,571 条全写 `.osgb`**，而盘上实物**全是 `.glb`**。
  （铁律 158：尺子对哪几类元素盲，必须先声明；这里是「声明与实物不同形」的活例。）

★ **前置自检先于出件**：若发现**除根以外**还有节点自带 `transform`，本版**拒绝出件**
  （rc=4）而不是静默按「全库共享一个局部坐标系」去合面 —— 后者会把带变换的片**错位**，
  而错位的症状是「看起来有件、几何叠不上」，比不出件更难查。

用法：
  python tools/scene_to_editable.py --blocks Tile_+003_+005      # 单块（快）
  python tools/scene_to_editable.py --all --limit 4              # 前 4 块
  python tools/scene_to_editable.py --all                        # 全库（慢，建议后台）
输出：`<out>/<block>/<block>.glb` ＋ `<block>.lineage.json` ＋ `<out>/_index.json`
退出码：`0` 全成 / `1` 有块失败（**点名**） / `4` 前置自检不过（**量不到就不出结论**）
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import os
import sys
from collections import defaultdict

sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

SCHEMA = "cdut3d-reality-master/1"

DEFAULT_TILES = r"D:/项目/gym3d/gym3d/_scratch/_fly2024_tiles"
DEFAULT_OUT = r"D:/项目/cdut3d/_edit"

RC_PASS, RC_FAIL, RC_NOGAUGE = 0, 1, 4


# --------------------------------------------------------------------------- 小工具

def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def dump_bytes(path: str, obj) -> None:
    """★ 字节层写盘：utf-8 ＋ LF，不让文本模式把行尾翻成 CRLF（铁律 79）。"""
    data = json.dumps(obj, ensure_ascii=False, indent=1).encode("utf-8")
    data = data.replace(b"\r\n", b"\n")
    with open(path, "wb") as f:
        f.write(data)


def block_of(uri: str):
    """`Data/<block>/<file>.glb` → `<block>`。"""
    parts = uri.replace("\\", "/").split("/")
    return parts[1] if len(parts) >= 3 and parts[0] == "Data" else None


def lod_of(stem: str):
    """文件名尾 `_L18_0uuuu0` → 18；根片（无尾）→ None。"""
    tail = stem.rsplit("_L", 1)
    if len(tail) != 2:
        return None
    try:
        return int(tail[1].split("_", 1)[0])
    except (ValueError, IndexError):
        return None


def enu_bbox(bounds) -> list:
    """glb(Y-up) 包围盒 → ENU(Z-up) 六元组 `[xmin,ymin,zmin,xmax,ymax,zmax]`。

    ★ 翻转式 `(x,-z,y)`（等价于绕 X 轴 +90°）**是实测的**，不是照抄规范：
      样例叶件翻转后 `(776.6, 1192.5, 36.5)` 与 tileset 里 child0 包围球心 `(784.08, 1185.85, 42.66)` 吻合。
    """
    import numpy as np

    b = np.asarray(bounds)
    return [round(float(v), 3) for v in
            [b[0][0], -b[1][2], b[0][1], b[1][0], -b[0][2], b[1][1]]]


def visual_image(geom):
    """从 trimesh 的 visual 里取 PIL 图。

    ★★ 必须**同时认两类**：`TextureVisuals` 若来自 OBJ/PLY 是 `SimpleMaterial`（图在 `.image`），
       而**从 glTF 读进来的是 `PBRMaterial`，图在 `.baseColorTexture`**。
       只认前者会对后者**全盲** —— 本工具第一版就是这样，把 5 张活着的贴图读成 0 张，
       还印出 `texture_sizes: []` 这种**会撒谎的字段**（铁律 158）。
    """
    mat = getattr(getattr(geom, "visual", None), "material", None)
    if mat is None:
        return None
    return getattr(mat, "image", None) or getattr(mat, "baseColorTexture", None)


def tex_info(geom) -> dict:
    """这片贴图的尺寸与**像素级**指纹。

    ★ 用像素算指纹，不用编码后的字节 —— 实测 trimesh 导出时会把 JPEG **解码又重编码**
      （89704 B → 89700 B），字节必然不同；**字节变了不等于像素变了**，
      而「贴图有没有变样」问的是像素。字节比对会把这件事实报成假的「贴图丢了」。
    """
    import io as _io

    img = visual_image(geom)
    if img is None:
        return {"size": None, "sha256_px": None}
    try:
        px = img.convert("RGB")
        buf = _io.BytesIO()
        px.save(buf, format="PNG")       # 无损重编码 ⇒ 同一像素必然同一哈希
        return {"size": list(img.size),
                "sha256_px": hashlib.sha256(buf.getvalue()).hexdigest()[:16]}
    except Exception as exc:             # noqa: BLE001 —— 读不动要如实报
        return {"size": None, "sha256_px": None, "error": f"{type(exc).__name__}: {exc}"}


FOOT_CELL_M = 0.25          # 栅格边长（m）＝ 现有 `fly2024_dsm_025.tif` 的像素大小，不是随手取的数
FOOT_MAX_CELLS = 32_000_000  # 栅格单元上限（约 32 MB/张 bool）；超了就把格子放大并**如实报出放大后的格边长**


def projected_tris(scene) -> "object":
    """场景全部几何**投影到水平面**（glb 的 x,z）后的三角形，形状 (N,3,2)。

    ★ 水平面取 (x,z)：glTF 是 Y-up（实测 `gltfUpAxis:Y`，翻转式 `(x,-z,y)` 已被 meta bbox 独立证实）。
    """
    import numpy as np

    out = []
    for g in scene.geometry.values():
        if len(g.faces):
            out.append(np.asarray(g.vertices, dtype=np.float64)[g.faces][:, :, [0, 2]])
    return np.concatenate(out, axis=0) if out else np.zeros((0, 3, 2))


def _rasterize(T, origin, shape, cell) -> "object":
    """格心落在任一投影三角形内 ⇒ 该格被盖住。逐三角形在其**包围盒内**狭义光栅化。"""
    import numpy as np

    ny, nx = shape
    grid = np.zeros((ny, nx), dtype=bool)
    if not len(T):
        return grid
    for t in T:
        a, b, c = t
        x0 = max(0, int(np.floor((min(a[0], b[0], c[0]) - origin[0]) / cell)) - 1)
        x1 = min(nx, int(np.ceil((max(a[0], b[0], c[0]) - origin[0]) / cell)) + 2)
        y0 = max(0, int(np.floor((min(a[1], b[1], c[1]) - origin[1]) / cell)) - 1)
        y1 = min(ny, int(np.ceil((max(a[1], b[1], c[1]) - origin[1]) / cell)) + 2)
        if x1 <= x0 or y1 <= y0:
            continue
        d = (b[0] - a[0]) * (c[1] - a[1]) - (c[0] - a[0]) * (b[1] - a[1])
        if abs(d) < 1e-14:      # 退化三角形：近垂直的立面投到水平面本来就不该贡献面积
            continue
        xs = origin[0] + (np.arange(x0, x1) + 0.5) * cell
        ys = origin[1] + (np.arange(y0, y1) + 0.5) * cell
        PX, PY = np.meshgrid(xs, ys)
        w0 = ((b[0] - PX) * (c[1] - PY) - (c[0] - PX) * (b[1] - PY)) / d
        w1 = ((c[0] - PX) * (a[1] - PY) - (a[0] - PX) * (c[1] - PY)) / d
        grid[y0:y1, x0:x1] |= (w0 >= 0) & (w1 >= 0) & (w0 + w1 <= 1)
    return grid


def footprint_compare(scenes: dict, cell: float = FOOT_CELL_M) -> dict:
    """★ 覆盖判据：把两侧**投到同一张栅格**上，数格比面积，并给出**缺格地图**。

    用法：`footprint_compare({"frontier": <前沿合并场景>, "root": <根片场景>})`。

    ★ 为什么是这两个对象：**前沿**（每块最深可用 LOD 合面）与**根片**（同块最粗那片）是
      **同块的两组不同文件**。★ 不能拿 `meta.json` 的 `bbox` 当覆盖参照物 —— 实测三块
      `根片ENU − meta.bbox = [0,0,0,0,0,0]`，`meta.bbox` 就是**根片**包围盒，
      是**退化参照**（铁律 192：参照物必须与交付件同作用域）。

    ★★ 为什么是**栅格**而不是多边形求并 —— 这条尺子换过三版，前两版都栽过，记录在此以免重犯：
      · 第一版：逐三角 `shapely.unary_union`。**算对**，但在真实块（20 万–80 万面）上跑不动，
        于是加了 20 万面上限 ⇒ **12 块里 8 块「量不到」**。一把对多数样本瞎的尺子等于没有（铁律 158）。
      · 第二版：`trimesh.path.polygons.projected()` 逐片求轮廓再并。**能 scale，但是错的**：
        同一块读出覆盖比 0.924513，而栅格读 **1.000000** ⇒ 它把近垂直立面投成的退化细条
        交给「投影点三角化后取轮廓」那条路径，**少算 7.5%**。
        ★ 关键教训：我拿**平面**人造输入给第二版做过正对照，四个真值全中 —— 平面输入**没有退化投影**，
        所以那把正对照**抓不住这个错**。**「对简单输入正确」证明不了「对复杂输入正确」。**
      · 第三版（本版）：0.25 m 栅格数格。**又对又能 scale**，还顺带产出缺格地图。

    ★ 盲区声明（本尺子对哪几类东西看不见/量不准）：
      ① **边界欠算**：格心落在图形外就不计该格 ⇒ 绝对面积**系统性偏小**，量级 ≈ 周长 × 半个格边长。
         本函数**只用来做同比**（前沿 vs 根片），两侧在**同一张栅格**上、共享同一套边界偏差，
         比值里相消 ⇒ 这是「比值可信、绝对数只是读数」的原因，两个字段分开印、不许混。
      ② 对**比一个格还窄**的窄条（< 0.25 m 的墙线）**看不全**；若该窄条只在其中一侧出现，
         比值会被它拉动。
      ③ 只在**水平投影**上说话：立面、悬挑、桥下空洞在投影里被压平 ⇒ **盖住 ≠ 有几何**。
    """
    import numpy as np

    if not scenes:
        return {"status": "NO_INPUT"}
    T = {}
    for k, sc in scenes.items():
        try:
            T[k] = projected_tris(sc)
        except Exception as exc:                # noqa: BLE001
            return {"status": "ERROR", "error": f"{type(exc).__name__}: {exc}", "on": k}
    if not any(len(v) for v in T.values()):
        return {"status": "EMPTY", "n_tri": {k: len(v) for k, v in T.items()}}

    allT = np.concatenate([v for v in T.values() if len(v)], axis=0)
    lo = allT.reshape(-1, 2).min(axis=0)
    hi = allT.reshape(-1, 2).max(axis=0)
    span = np.maximum(hi - lo, cell)
    # 网格过大就放大格子 —— ★ 放大后**如实报出**，不许默默换尺子
    need = int(np.ceil(span[0] / cell)) * int(np.ceil(span[1] / cell))
    cell_used = cell
    if need > FOOT_MAX_CELLS:
        cell_used = float(np.ceil(np.sqrt(need / FOOT_MAX_CELLS) * cell * 100) / 100)
    nx = int(np.ceil(span[0] / cell_used)) + 1
    ny = int(np.ceil(span[1] / cell_used)) + 1

    masks = {k: _rasterize(v, lo, (ny, nx), cell_used) for k, v in T.items()}
    A = cell_used * cell_used
    out = {"status": "OK", "cell_m": round(cell_used, 4),
           "cell_requested_m": cell, "grid": [ny, nx], "origin_xz": [round(float(lo[0]), 3), round(float(lo[1]), 3)],
           "n_tri": {k: int(len(v)) for k, v in T.items()},
           "area_note": "面积是**栅格数出**的读数（边界系统性偏小 ≈ 周长×半格）；判据只用**比值**"}
    for k, m in masks.items():
        out[k] = {"n_cells": int(m.sum()), "area_m2": round(float(m.sum()) * A, 3)}
    if "frontier" in masks and "root" in masks:
        gf, gr = masks["frontier"], masks["root"]
        inter, union = int((gf & gr).sum()), int((gf | gr).sum())
        miss, extra = gr & ~gf, gf & ~gr
        out["ratio_frontier_over_root"] = round(gf.sum() / max(int(gr.sum()), 1), 6)
        # ★ 这把比值的**分辨率下限** = 1/根片格数：分母只有几百格时，差一格就是千分之几。
        #   不声明它，小块的量化噪声会被当成「离群」——那是判旗在它自己量不出的量级上说话。
        out["ratio_resolution"] = round(1.0 / max(int(gr.sum()), 1), 6)
        out["iou"] = round(inter / max(union, 1), 6)
        out["missing_cells"], out["missing_m2"] = int(miss.sum()), round(float(miss.sum()) * A, 3)
        out["extra_cells"], out["extra_m2"] = int(extra.sum()), round(float(extra.sum()) * A, 3)
        # ★ 缺格**落在哪**：面积比一个数说不出来，连通块形状说得出来 —— 细长贴边 vs 方整居中
        try:
            from scipy import ndimage
            lab, n = ndimage.label(miss)
            blobs = []
            for i in range(1, n + 1):
                ys, xs = np.nonzero(lab == i)
                w, hgt = int(xs.max() - xs.min() + 1), int(ys.max() - ys.min() + 1)
                blobs.append({"cells": int(len(ys)), "m2": round(len(ys) * A, 3),
                              "n_bbox_cells": [w, hgt], "m_bbox": [round(w * cell_used, 2), round(hgt * cell_used, 2)],
                              "fill_ratio": round(len(ys) / max(w * hgt, 1), 3),
                              "at_xz": [round(float(lo[0] + xs.min() * cell_used), 2),
                                        round(float(lo[1] + ys.min() * cell_used), 2)]})
            blobs.sort(key=lambda b: -b["cells"])
            out["missing_blobs"] = blobs[:8]
            out["missing_n_blobs"] = n
        except Exception as exc:                # noqa: BLE001 —— 连通块分不出就只报总数，不许装成 0 块
            out["missing_blobs"] = None
            out["missing_blobs_error"] = f"{type(exc).__name__}: {exc}"
    return out


def restore_glb_images(glb_path: str, ordered_images: list) -> dict:
    """把 trimesh **重编码过**的贴图换回**原始字节**（逐位不变）。

    ★ 为什么非做不可：实测 trimesh 导出 glb 时把 JPEG **解码又重编码**，
      单次往返逐像素最差 **max 53/255、约 25% 像素有差**（12 块实测，样例块只有 10 是运气）。
      规范对用户承诺的是「改完还能看」⇒ 地基这一环**不许有损**，多趟往返会累积。

    ★ 换回后**逐像素差必须为 0**（调用方当场量），不是「差不多」。
    ★ 映射按**我加几何的顺序**（`sorted(uris)`），**不按像素猜** —— 猜是循环论证；
      顺序错了会被「换完必须全 0」这条**独立**检查当场抓住。
    """
    import pygltflib as P

    g = P.GLTF2().load(glb_path)
    imgs = g.images or []
    if len(imgs) != len(ordered_images):
        return {"status": "COUNT_MISMATCH", "n_master_images": len(imgs),
                "n_source_images": len(ordered_images),
                "note": "张数对不上 ⇒ **一个都不换**（宁可保留有损，也不许错位换）"}
    if not g.buffers:
        return {"status": "NO_BUFFER"}

    blob = bytes(g.binary_blob())
    piece_of_view = {im.bufferView: j for j, im in enumerate(imgs) if im.bufferView is not None}

    out = bytearray()
    for idx, bv in enumerate(g.bufferViews or []):
        data = (ordered_images[piece_of_view[idx]] if idx in piece_of_view
                else blob[bv.byteOffset: bv.byteOffset + bv.byteLength])
        out.extend(b"\x00" * ((-len(out)) % 4))          # 每个 bufferView 4 字节对齐
        bv.byteOffset = len(out)
        bv.byteLength = len(data)
        out.extend(data)
    out.extend(b"\x00" * ((-len(out)) % 4))              # BIN chunk 尾部 4 字节对齐
    g.buffers[0].byteLength = len(out)
    g.set_binary_blob(bytes(out))
    g.save(glb_path)
    return {"status": "OK", "n_replaced": len(piece_of_view), "bin_bytes": len(out)}


def source_image_bytes(path: str) -> list:
    """一个源叶件 glb 里**原始编码好的**贴图字节（不解码、不重编码）。"""
    import pygltflib as P

    g = P.GLTF2().load(path)
    blob = bytes(g.binary_blob())
    out = []
    for im in g.images or []:
        if im.bufferView is None:
            out.append(None)
            continue
        bv = g.bufferViews[im.bufferView]
        out.append(blob[bv.byteOffset: bv.byteOffset + bv.byteLength])
    return out


def compare_images(a, b):
    """两张 PIL 图逐像素比。返回 None 表示不可比（缺图/尺寸不同），否则给差值读数。"""
    import numpy as np

    if a is None or b is None:
        return None
    if tuple(a.size) != tuple(b.size):
        return {"size_mismatch": [list(a.size), list(b.size)]}
    da = np.asarray(a.convert("RGB")).astype(int)
    db = np.asarray(b.convert("RGB")).astype(int)
    d = np.abs(da - db)
    return {"max": int(d.max()), "mean": round(float(d.mean()), 5),
            "pct_pixels_differ": round(float(100 * (d.sum(axis=2) > 0).mean()), 4)}


# --------------------------------------------------------------------------- 读树

def walk(node, depth, st, frontier, anc, xc):
    """★ 前沿 = 有 content 且其下没有更深 content 的节点。

    ★★ **真实的祖先链取自树，不取自文件名**：第一版拿文件名前缀判祖先，跨 LOD 时
       字符串前缀根本接不上（`..._L14_0u` 不是 `..._L19_0uuuu20` 的前缀），
       于是把 13,830 个**正常祖先**误报成孤儿（铁律 158：尺子看不见的关系类型必须先声明）。
    """
    uri = (node.get("content") or {}).get("uri")
    if node.get("transform") is not None:
        xc["nodes_with_transform"] += 1
        if depth > 0:
            xc["non_root_with_transform"].append(uri or f"<depth {depth} 无 content>")

    st["n_nodes"] += 1
    self_has = uri is not None
    if self_has:
        st["n_content"] += 1
        b = block_of(uri)
        if b:
            st["by_block"][b].append(uri)
        st["anc"][uri] = list(anc)
        st["depth"][uri] = depth

    child_has = False
    for c in node.get("children") or []:
        if walk(c, depth + 1, st, frontier, anc + ([uri] if self_has else []), xc):
            child_has = True

    if self_has and not child_has:
        frontier.append(uri)          # 本条支上最深的一片
    return self_has or child_has


# --------------------------------------------------------------------------- 合面

def build_block(block: str, uris: list, src: str, out_root: str, st: dict) -> dict:
    """把一块的**前沿片**合面成一个主件 glb（逐片一个子网格，各自贴图）。

    ★ 主件**保持源叶件的坐标框架（glTF Y-up）**，**不做任何翻转** ⇒ 回切无需逆变换；
      「Y-up ↔ ENU」只在**核对**时用（翻转式 `(x,-z,y)` 已被 meta bbox 独立证实）。
    """
    import numpy as np
    import trimesh

    pieces, errors, missing = [], [], []
    ordered_imgs, multi_geom = [], 0        # ★ 原始贴图字节，**按加几何的顺序**排
    scene = trimesh.Scene()

    for uri in sorted(uris):
        rel = uri.replace("\\", "/")
        p = os.path.join(src, rel.replace("/", os.sep))
        stem = os.path.splitext(os.path.basename(rel))[0]
        if not os.path.exists(p):
            missing.append(rel)
            continue
        try:
            m = trimesh.load(p, force="scene")
        except Exception as exc:                # noqa: BLE001 —— 读不动要如实报，不许静默丢件
            errors.append({"uri": rel, "error": f"{type(exc).__name__}: {exc}"})
            continue

        # 一片 glb 里可能有多个 geometry；全部保留，名字前缀带 stem 以保证唯一
        geoms = list(m.geometry.items()) if hasattr(m, "geometry") else [("g", m)]
        nbytes = os.path.getsize(p)
        if len(geoms) > 1:
            multi_geom += 1
        try:
            src_imgs = source_image_bytes(p)
        except Exception:                       # noqa: BLE001
            src_imgs = []
        for gi, (gname, g) in enumerate(geoms):
            name = f"{stem}__{gname}" if len(geoms) > 1 else stem
            scene.add_geometry(g, node_name=name, geom_name=name)
            ordered_imgs.append(src_imgs[gi] if gi < len(src_imgs)
                                else (src_imgs[0] if src_imgs else None))
            pieces.append({
                "name": name, "uri": rel, "lod": lod_of(stem),
                "depth": st["depth"][uri],
                "ancestors": [a.rstrip("/").split("/")[-1] for a in st["anc"][uri]],
                "bytes": nbytes, "n_v": int(len(g.vertices)), "n_f": int(len(g.faces)),
                "bounds": np.asarray(g.bounds).round(3).tolist(),
                "has_uv": bool(getattr(g.visual, "uv", None) is not None),
                "texture": tex_info(g),
            })

    out_dir = os.path.join(out_root, block)
    os.makedirs(out_dir, exist_ok=True)
    glb_path = os.path.join(out_dir, f"{block}.glb")

    master = {"n_geom": len(scene.geometry), "bytes": None, "sha256": None,
              "n_v": None, "n_f": None, "bounds": None, "n_geom_readback": None}
    if len(scene.geometry) == 0:
        errors.append({"uri": "<块>", "error": "前沿片一片都没读进来"})
        return {"block": block, "ok": False, "errors": errors, "missing": missing,
                "pieces": pieces, "master": master}

    blob = scene.export(file_type="glb")
    with open(glb_path, "wb") as f:
        f.write(blob)
    master["bytes"] = os.path.getsize(glb_path)
    master["sha256"] = sha256_file(glb_path)

    # ---- ★ 把 trimesh 重编码过的贴图**换回原始字节**（无损）----
    if multi_geom:
        restore = {"status": "SKIPPED_MULTI_GEOM_PIECE", "n_multi_geom_pieces": multi_geom,
                   "note": "一片内含多个 geometry 时「几何↔图」的对应关系本版**量不准** ⇒ 不换，不猜"}
    else:
        try:
            restore = restore_glb_images(glb_path, ordered_imgs)
        except Exception as exc:                # noqa: BLE001
            restore = {"status": "ERROR", "error": f"{type(exc).__name__}: {exc}"}
        if restore.get("status") == "OK":
            master["bytes"] = os.path.getsize(glb_path)
            master["sha256"] = sha256_file(glb_path)
    master["image_restore"] = restore

    # ★ 第二把尺子：**落盘后重新读回来**再量一次（铁律 187：基线与期望值必须来自两次不同读数）
    back = trimesh.load(glb_path, force="scene")
    bs = [np.asarray(g.bounds) for g in back.geometry.values()]
    if bs:
        lo = np.array([b[0] for b in bs]).min(axis=0)
        hi = np.array([b[1] for b in bs]).max(axis=0)
        master["bounds"] = np.stack([lo, hi]).round(3).tolist()
    master["n_v"] = int(sum(len(g.vertices) for g in back.geometry.values()))
    master["n_f"] = int(sum(len(g.faces) for g in back.geometry.values()))
    master["n_geom_readback"] = len(back.geometry)

    # ---- ★ 往返判据（贴图那一半）：**逐像素**比，不按字节 ----
    # ★ 实测：trimesh 导出时把 JPEG 解码又重编码（89704 B → 89700 B）⇒ **字节必然不同**，
    #   而「贴图有没有变样」问的是像素。拿字节当尺子会把「几乎没变」报成「贴图丢了」。
    tex_rt, worst_max, worst_pct = [], -1, -1.0
    for name in sorted(scene.geometry):
        dst = back.geometry.get(name)
        c = compare_images(visual_image(scene.geometry[name]),
                           None if dst is None else visual_image(dst))
        if c is None:
            continue
        tex_rt.append({"name": name, **c})
        worst_max = max(worst_max, c.get("max", -1))
        worst_pct = max(worst_pct, c.get("pct_pixels_differ", -1.0))
    master["n_tex_src"] = sum(1 for g in scene.geometry.values() if visual_image(g) is not None)
    master["n_tex_readback"] = sum(1 for g in back.geometry.values() if visual_image(g) is not None)
    master["tex_roundtrip"] = tex_rt
    master["tex_worst"] = ({"max": worst_max, "pct_pixels_differ": worst_pct}
                           if tex_rt else None)

    # ---- ★ 覆盖判据：前沿足迹 vs 根片足迹（同块、**两组不同文件**）----
    # ★ 为何不拿 meta.bbox 当覆盖参照物：实测三块 `根片ENU − meta.bbox = [0,0,0,0,0,0]`，
    #   meta.bbox **就是根片包围盒** ⇒ 拿它当准绳＝拿粗 LOD 量深 LOD，是**退化参照**（铁律 192）。
    root_p = os.path.join(src, "Data", block, f"{block}.glb")
    inputs = {"frontier": scene}
    cov_root_err = None
    if os.path.exists(root_p):
        try:
            rs = trimesh.load(root_p, force="scene")
            inputs["root"] = rs
            rb = [np.asarray(g.bounds) for g in rs.geometry.values()]
            if rb:
                rlo = np.array([b[0] for b in rb]).min(axis=0)
                rhi = np.array([b[1] for b in rb]).max(axis=0)
                master["root_bbox_enu"] = enu_bbox(np.stack([rlo, rhi]))
        except Exception as exc:                # noqa: BLE001
            cov_root_err = f"{type(exc).__name__}: {exc}"
    else:
        cov_root_err = "NO_ROOT_TILE"
    master["coverage"] = footprint_compare(inputs)
    if cov_root_err:
        master["coverage"]["status"] = "NO_ROOT_TILE"
        master["coverage"]["root_error"] = cov_root_err
        master["coverage"]["note"] = (f"根片 {root_p} 不可用（{cov_root_err}）"
                                      " ⇒ **两侧对不起来，覆盖判据不成立**（只留前沿单侧读数）")

    return {"block": block, "ok": not errors and not missing, "errors": errors,
            "missing": missing, "pieces": pieces, "master": master}


# --------------------------------------------------------------------------- 主流程

def main() -> int:
    ap = argparse.ArgumentParser(description="瓦片 → 可编辑主件（LOD 前沿合面）")
    ap.add_argument("--tiles", default=DEFAULT_TILES)
    ap.add_argument("--out", default=DEFAULT_OUT)
    ap.add_argument("--blocks", default="", help="逗号分隔的块名；缺省配 --all")
    ap.add_argument("--all", action="store_true", help="全库")
    ap.add_argument("--limit", type=int, default=0, help="配合 --all，只做前 N 块")
    a = ap.parse_args()

    ts_path = os.path.join(a.tiles, "tileset.json")
    if not os.path.exists(ts_path):
        print(f"[FATAL] 没有 tileset.json：{ts_path}", file=sys.stderr)
        return RC_NOGAUGE
    with open(ts_path, "r", encoding="utf-8") as f:
        ts = json.load(f)

    st = {"n_nodes": 0, "n_content": 0, "by_block": defaultdict(list), "anc": {}, "depth": {}}
    frontier, xc = [], {"nodes_with_transform": 0, "non_root_with_transform": []}
    walk(ts["root"], 0, st, frontier, [], xc)

    os.makedirs(a.out, exist_ok=True)
    ledger: dict = {
        "schema": SCHEMA, "tiles_dir": a.tiles, "out_dir": a.out,
        "tileset": {"path": ts_path, "sha256": sha256_file(ts_path),
                    "asset": ts.get("asset"),
                    "geometricError": ts.get("geometricError"),
                    "root_transform_ecef": (ts.get("root") or {}).get("transform"),
                    "root_bounding_sphere": ((ts.get("root") or {}).get("boundingVolume") or {}).get("sphere"),
                    "refine": (ts.get("root") or {}).get("refine"),
                    "n_nodes": st["n_nodes"],      # ★ 取自 walk 的那一份，**不另立第二个估计器**（铁律 194）
                    "note": "★ 本快照是跨仓引用的凭据（源真源在 gym3d 仓）；"
                            "root_transform_ecef 是回切必须**逐位复现**的那 16 个数（规范 §2.1）"},
        "n_nodes": st["n_nodes"], "n_content": st["n_content"], "n_frontier": len(frontier),
        "xform_census": xc,
    }
    idx = os.path.join(a.out, "_index.json")

    # ---------- 前置自检 ①：逐节点 transform ----------
    if xc["non_root_with_transform"]:
        print("=" * 72)
        print(f"★ 前置自检不过：有 {len(xc['non_root_with_transform'])} 个**非根**节点自带 transform。")
        print("  本版按「全库共享一个局部坐标系」直接合面 ⇒ 带变换的片会被**错位**，")
        print("  而错位症状是「看起来有件、几何叠不上」，比不出件更难查。")
        for u in xc["non_root_with_transform"][:10]:
            print(f"    · {u}")
        print("  ⇒ **拒绝出件**（rc=4）：量不到就不出结论。")
        print("=" * 72)
        dump_bytes(idx, {**ledger, "pass": False, "rc": RC_NOGAUGE})
        return RC_NOGAUGE

    # ---------- 前置自检 ②：前沿非空、块非空 ----------
    fby = defaultdict(list)
    for u in frontier:
        b = block_of(u)
        if b:
            fby[b].append(u)
    ledger["n_frontier_blocks"] = len(fby)
    ledger["blocks_with_zero_frontier"] = sorted(set(st["by_block"]) - set(fby))
    if not frontier or ledger["blocks_with_zero_frontier"]:
        print(f"★ 前置自检不过：前沿 {len(frontier)} 片；前沿为 0 的块 "
              f"{ledger['blocks_with_zero_frontier'][:6]}", file=sys.stderr)
        dump_bytes(idx, {**ledger, "pass": False, "rc": RC_NOGAUGE})
        return RC_NOGAUGE

    # ---------- 选块 ----------
    if a.blocks:
        want = [b.strip() for b in a.blocks.split(",") if b.strip()]
    elif a.all:
        want = sorted(fby)
        if a.limit:
            want = want[:a.limit]
    else:
        print("[FATAL] 要么 --blocks，要么 --all", file=sys.stderr)
        return RC_NOGAUGE
    unknown = [b for b in want if b not in fby]
    if unknown:
        print(f"★ 点名的块在前沿里不存在（铁律 174：计数取自独立清单，不许抹平）：{unknown}",
              file=sys.stderr)
        return RC_NOGAUGE

    print("=" * 72)
    print(f"tileset 节点 {st['n_nodes']}  带 content {st['n_content']}  前沿 {len(frontier)}  "
          f"块 {len(fby)}")
    print(f"★ 逐节点 transform 自检：非根带变换 {len(xc['non_root_with_transform'])} 个 ⇒ 通过")
    print(f"要做 {len(want)} 块：{want[:6]}{' …' if len(want) > 6 else ''}")

    # ---------- 逐块 ----------
    results, t0 = [], datetime.datetime.now()
    for i, blk in enumerate(want, 1):
        r = build_block(blk, fby[blk], a.tiles, a.out, st)
        m = r["master"]
        rb = f"（读回 {m['n_geom_readback']}）" if m["n_geom_readback"] else ""
        print(f"  [{i}/{len(want)}] {blk}: 前沿 {len(fby[blk])} 片 → 子网格 {m['n_geom']}{rb}"
              f"  v={m['n_v']} f={m['n_f']}  {m['bytes']} B"
              f"{'  ★缺 ' + str(len(r['missing'])) if r['missing'] else ''}"
              f"{'  ★错 ' + str(len(r['errors'])) if r['errors'] else ''}")
        tw = m["tex_worst"]
        print(f"        贴图：源 {m['n_tex_src']} 张 → 读回 {m['n_tex_readback']} 张"
              + (f"  ★ 往返逐像素最差：max={tw['max']} 异像素={tw['pct_pixels_differ']}%"
                 if tw else "  （本块无贴图可比）"))
        cvg = m.get("coverage") or {}
        cr, cs = cvg.get("ratio_frontier_over_root"), cvg.get("status")
        print(f"        覆盖：前沿足迹/根片足迹 = {cr}  缺格 {cvg.get('missing_cells')}"
              f" 格 = {cvg.get('missing_m2')} m²  格边长 {cvg.get('cell_m')} m"
              + ("" if cs == "OK" else f"  ★ 两侧对不起来（{cs}）：{cvg.get('note')}"))

        line = {
            "schema": SCHEMA, "block": blk,
            "src_tileset": ledger["tileset"],
            "frame": {"gltf_up_axis": (ts.get("asset") or {}).get("gltfUpAxis", "Y"),
                      "note": "主件与源叶件同坐标框架，未做任何翻转 ⇒ 回切无需逆变换；"
                              "Y-up↔ENU 只在核对时用 (x,-z,y)"},
            "n_pieces": len(r["pieces"]), "pieces": r["pieces"],
            "missing_on_disk": r["missing"], "errors": r["errors"],
            "master": m, "ok": r["ok"],
        }
        # ★★ 三条读数**各自贴自己的标签**（铁律 174：两个同名的量必须死掉一个）：
        #   ① meta 声明 vs 根片  → **自洽核对**（实测应为全 0；不为 0 说明这块的 meta 不可信）
        #   ② 前沿 vs 根片       → **LOD 粗细差**（信息量，不是错）
        #   ③ 前沿足迹 vs 根片足迹 → **覆盖判据**（这才是「有没有漏块」）
        if m["bounds"]:
            line["master_bbox_enu"] = enu_bbox(m["bounds"])
        if m.get("root_bbox_enu"):
            if m["bounds"]:
                line["frontier_vs_root_delta"] = [round(line["master_bbox_enu"][k]
                                                        - m["root_bbox_enu"][k], 3)
                                                  for k in range(6)]
        line["coverage"] = m.get("coverage")
        # ★ meta.json 只用来取 `bbox` 与核对，**绝不用它取文件名**（它的 children_files 全写 .osgb）
        mp = os.path.join(a.tiles, "Data", blk, f"{blk}.meta.json")
        if os.path.exists(mp):
            try:
                with open(mp, "r", encoding="utf-8") as f:
                    mb = [round(float(x), 3) for x in json.load(f).get("bbox", [])]
                line["meta_bbox_declared"] = mb
                if len(mb) == 6 and m.get("root_bbox_enu"):
                    line["meta_vs_root_delta"] = [round(m["root_bbox_enu"][k] - mb[k], 3)
                                                  for k in range(6)]
            except Exception as exc:                # noqa: BLE001
                line["meta_read_error"] = f"{type(exc).__name__}: {exc}"
        dump_bytes(os.path.join(a.out, blk, f"{blk}.lineage.json"), line)
        results.append({"block": blk, "ok": r["ok"], "n_pieces": len(r["pieces"]),
                        "n_geom": m["n_geom"], "n_geom_readback": m["n_geom_readback"],
                        "bytes": m["bytes"], "missing": len(r["missing"]),
                        "errors": len(r["errors"]),
                        "n_tex_src": m["n_tex_src"], "n_tex_readback": m["n_tex_readback"],
                        "tex_worst": m["tex_worst"],
                        "coverage_ratio": (line.get("coverage") or {}).get("ratio_frontier_over_root"),
                        "coverage_status": (line.get("coverage") or {}).get("status"),
                        "coverage_missing_m2": (line.get("coverage") or {}).get("missing_m2"),
                        "coverage_missing_cells": (line.get("coverage") or {}).get("missing_cells"),
                        "coverage_resolution": (line.get("coverage") or {}).get("ratio_resolution"),
                        "meta_vs_root_max_abs": max((abs(v) for v in
                                                     (line.get("meta_vs_root_delta") or [0])), default=None)})

    # ★★ 覆盖判据的**判旗**：阈值**必须由本批实测分布算出**，不许手打 ——
    #    手打的阈值会把「这批块的分布本来就这样」报成「代码有副作用」（铁律 103）。
    ratios = sorted(x["coverage_ratio"] for x in results if x.get("coverage_ratio") is not None)
    cov_flag, cov_note, cov_below_res = [], "", []
    if len(ratios) >= 3:
        med = ratios[len(ratios) // 2]
        dev = sorted(abs(r - med) for r in ratios)
        mad = dev[len(dev) // 2] * 1.4826
        thr = 10 * mad
        if thr <= 0:
            cov_note = (f"本批 {len(ratios)} 块比值**完全一致**（MAD=0）⇒ 这把尺子在本批"
                        "**分不出离群**，只报读数、不判旗（不许把「分不出」说成「都合格」）")
        else:
            # ★ 离群要**同时**越过两条线：① 分布线 10×MAD；② 这块自己的**分辨率下限** 1/根片格数。
            #   少了②，栅格只有几百格的小块（差一格 = 千分之几）会被当成离群 ——
            #   那不是「覆盖出问题」，是判旗在它量不出的量级上说话。实测：Tile_+004_+004 全块
            #   只有 324 格（20 m²），比值 1.003096 全部来自**一格**之差。
            for x in results:
                r, res = x.get("coverage_ratio"), x.get("coverage_resolution")
                if r is None:
                    continue
                d = abs(r - med)
                if d > thr and res is not None and d > res:
                    cov_flag.append(x["block"])
                elif d > thr:
                    cov_below_res.append({"block": x["block"], "ratio": r, "dev": round(d, 6),
                                          "resolution": res,
                                          "root_cells": (round(1.0 / res) if res else None)})
            cov_note = f"中位 {med:.6f}　MAD×1.4826 {mad:.6f}　阈值 10×MAD {thr:.6f}"
    elif ratios:
        cov_note = (f"只量到 {len(ratios)} 块，**少于 3 块不足以由分布定阈值**（铁律 103）"
                    "⇒ 只报读数、不判旗")
    else:
        cov_note = "本批一块都没量到覆盖比（见各块 coverage.status）"
    skipped = [x["block"] for x in results if x.get("coverage_status") != "OK"]
    # ★ 缺格的**读数列**（不是统计，是直读）：即便比值全是 1.0，只要真漏了一块，
    #   缺格就会在这一列上冒出来 —— 这是比值说不出的那种失败（缺栋面积分给邻居，比值照样平）。
    with_missing = [(x["block"], x["coverage_missing_m2"], x["coverage_missing_cells"])
                    for x in results if x.get("coverage_missing_cells")]

    bad = [x["block"] for x in results if not x["ok"]]
    ledger["results"] = results
    ledger["n_ok"] = len(results) - len(bad)
    ledger["n_failed"] = len(bad)
    ledger["failed_blocks"] = bad               # ★ 点名，不许只说「有块失败」
    ledger["coverage_flag_blocks"] = cov_flag
    ledger["coverage_note"] = cov_note
    ledger["coverage_not_measured_blocks"] = skipped
    ledger["coverage_missing_blocks"] = with_missing      # [(块, m², 格数), ...] —— 直读，不是统计
    ledger["coverage_flag_below_resolution"] = cov_below_res   # 越过分布线、但没越过自己的分辨率下限
    ledger["elapsed_s"] = round((datetime.datetime.now() - t0).total_seconds(), 1)
    ledger["pass"] = not bad
    ledger["rc"] = RC_PASS if not bad else RC_FAIL
    dump_bytes(idx, ledger)

    print("-" * 72)
    print(f"成 {ledger['n_ok']} / 败 {ledger['n_failed']}  用时 {ledger['elapsed_s']} s")
    if bad:
        print(f"★ 失败的块（点名）：{bad}")
    mv = max((x["meta_vs_root_max_abs"] or 0) for x in results) if results else None
    print(f"★ meta 声明 vs 根片包围盒 最大绝对差：{mv} m"
          f"{'（自洽核对通过 ⇒ meta.bbox 确实是根片 bbox）' if mv is not None and mv < 0.01 else ''}")
    print(f"★ 覆盖判据（前沿足迹 / 根片足迹）：{cov_note}")
    if cov_flag:
        print(f"  ★ 离群（点名）：{cov_flag}")
    if cov_below_res:
        print("  ★ 越过分布线、但**没越过自己的分辨率下限** ⇒ 不判离群（读数照报）：")
        for r in cov_below_res:
            print(f"      {r['block']}: 比值 {r['ratio']} 偏差 {r['dev']} "
                  f"分辨率 {r['resolution']}（根片只有 {r['root_cells']} 格 ⇒ 差一格就是这么大声）")
    if skipped:
        print(f"  ★ 本尺子对这些块**量不到**（不取样、不猜）：{skipped}")
    if with_missing:
        print(f"  ★ 缺格**直读**（根片盖住、前沿没盖住；比值看不出这种漏）：")
        for b, m2, nc in with_missing[:8]:
            print(f"      {b}: {nc} 格 = {m2} m²")
    else:
        print("  ★ 缺格直读：**每块都是 0 格**（前沿在栅格层面上完整盖住根片）")
    tmax = max((x["tex_worst"]["max"] for x in results if x.get("tex_worst")), default=None)
    tsrc = sum(x.get("n_tex_src") or 0 for x in results)
    tdst = sum(x.get("n_tex_readback") or 0 for x in results)
    print(f"★ 贴图：源 {tsrc} 张 → 读回 {tdst} 张；往返逐像素最差 max={tmax}"
          "（★ trimesh 导出会重编码 JPEG，字节必变、像素微变 —— 见规范 §盲区）")
    print(f"→ {idx}")
    print("=" * 72)
    return ledger["rc"]


if __name__ == "__main__":
    raise SystemExit(main())
