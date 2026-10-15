# -*- coding: utf-8 -*-
r"""可编辑主件 → 瓦片（**回切**；规范见 规范/实景主件格式-v1.md §5）。

**为什么要有它**：整条实景链今天是**单向**的（影像 → MVS → 瓦片 → 展示）。本工具补那条**反向箭头**，
与 `tools/scene_to_editable.py`（拆）成一对；两者合起来才是「可以修改完善」的技术定义（规范 §1）。

**判据一句话**：把主件按**谱系表**回写成一套与源件**同锚定**的 3D Tiles（glb 内容，**不经 OSGB**），
并使「**同 LOD 比同 LOD**」的往返读数落在容差内；★ **丢一片 / 改一名 / 丢一块都必须点名**。

**量具（哪个程序、量哪个量、单位、阈值）**
  · `trimesh` 读**主件此刻**的几何 与 **写出去再读回**的瓦片几何，逐片量 `n_v / n_f / bounds`。
    判据量的是**同名片**的 **包围盒分量最大绝对差（m）** 与 **面数差（个）**。
    ★ 两侧**都在 glb(Y-up) 帧里比** —— 谱系表 `pieces[].bounds` 记的就是 glb 帧；
      直接拿它减 ENU 是**跨帧相减**（同为「数」、不同为「量」）。
  · **锚定**：`py3dtiles` 建树并序列化后，**用 `json` 重新读回** `<out>/tileset.json`，
    量 `root.transform` 的那 **16 个数** —— 与**源 tileset.json 现场读出的** 16 个数**逐元素 `==`**
    （是「逐位」，不是「接近」；规范 §5.1）。
  · 逐片**归属核对**：主件的**几何名集合**与谱系表的 **`pieces[].name` 集合**双向对账，两侧都**点名**。
  · **叶名真源 = 程序现列文件系统**（规范 §4 第 3 条：`meta.json` 的 `children_files` 全写 `.osgb` 而实物是 `.glb`）
    ⇒ ★ 本工具**不读任何 `meta.json`**。

**阈值 `TOL_M` 是怎么来的（铁律 103：容差必须由实测算出，不许手打）**
  谱系表的 `bounds` 只记到 **3 位小数**（规范 §2.3），所以「两侧可比到的最小刻度」＝ **1 mm**。
  同一主件回切两遍是**确定性**的 —— ★ 实测（`_scratch/_pc_roundtrip.py` 丙类读数，同一 out 目录跑两遍）：
  **交付件**（`tileset.json` ＋ 5 个 `Data/*.glb`，共 6 件）两遍**逐字节相同**；
  **台账 `_index.json`** 本次两遍**也完全相同**。台账里**声明允许**变动的只有 `elapsed_s` 一个字段，
  且「空 diff」必须靠 **differ 分辨力自检**才算数（喂它一个 `elapsed_s` 差、须认出）——
  否则「真的一样」与「我的 differ 是瞎的」是同一个读数（铁律 137）。
  ⇒ 两遍方差＝**0** —— 但 **0 不能拿来当容差**：那会把「没量到」与「没差别」写成同一个数。
  ⇒ 容差取**记录精度** `1e-3 m`，并把「两遍方差」当作**独立读数**照报（不是阈值）。
  ★ 这个容差**只够证明「该回来的回来了」**，**不足以证明「改得对」** —— 后者是人判。

**盲区（这把尺子对哪几类东西看不见）**
  1. 只比**包围盒与面数**。**看不出来**片内部被移动了一个顶点、法线被翻、UV 被重排（规范 §3.3 盲区）。
  2. 只比**同名片**。多一片/少一片会被「双向对账」抓住，但**一片被切成两片再分别命名**看不出来。
  3. 树的**子节点顺序**不保证与源件一致（源件的 `children` 次序没有进谱系表，且回切件是**新件**）。
  4. ★ 回切件**不含粗 LOD 祖先片的内容**（主件只取 LOD 前沿，规范 §0.1）⇒ 低细节档位下本件比源件「薄」。
     这是**已声明的性质**，不是错：`geometricError` 沿用源值，渲染器会直接下潜到前沿片。
  5. 源件 `tileset.json` 的逐片包围球是**外部参照**（另一条链写的），但规范 §4 第 9 条实测**它被手工改过**
     ⇒ 它只能抓**粗错**（坐标系翻了、锚定错了），**不能**给「精确合格」盖章。故只作读数、不判旗。
  6. 贴图只核**「换回原始字节」这件事成没成**（张数与状态），**不核**像素 —— 逐字节相同则像素必相同。

**正对照（必配，实跑见 `_scratch/_pc_roundtrip.py`）**
  · 丙 空白：正常回切 ⇒ 逐片差必须**恰好 0**、面数差 0。
  · 甲 丢一片：从主件里去掉一片（或谱系多了不存在的一片）⇒ **双向对账必须点名**。
  · 乙 改一名：把某片改名 ⇒ 两侧各自**点名**，不许静默。
  · 丁 丢一块：块目录缺 `.glb` 或 `.lineage.json` ⇒ **必须点名这一块**，不许把缺块的回切件当完整的。
  · 戊 锚定漂移：源 `tileset.json` 的 sha256 与谱系表记的快照不一致 ⇒ **拒绝出件**（rc=4）。

用法：
  python tools/editable_to_tiles.py --blocks Tile_+003_+005      # 单块（快）
  python tools/editable_to_tiles.py --all --limit 4
  python tools/editable_to_tiles.py --all                        # 全库（慢，建议后台）
输出：`<out>/Data/<block>/<片名>.glb` ＋ `<out>/tileset.json` ＋ `<out>/_index.json`
退出码：`0` 全成 / `1` 有块失败或被点名的块（**点名**） / `4` 前置或版本自检不过（**量不到就不出结论**）
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import sys

import numpy as np

sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import scene_to_editable as S2E  # noqa: E402 —— 复用**已经量过**的那几把尺子（哈希/字节写盘/ENU 翻转/贴图换回）

SCHEMA = "cdut3d-reality-master/1"

DEFAULT_EDIT = r"D:/项目/cdut3d/_edit"
DEFAULT_OUT = r"D:/项目/cdut3d/_回切_tiles"
DEFAULT_SRC = r"D:/项目/gym3d/gym3d/_scratch/_fly2024_tiles"

RC_PASS, RC_FAIL, RC_NOGAUGE = 0, 1, 4

TOL_M = 1e-3        # 容差（m）＝谱系表 bounds 的记录精度；来历见文件头 docstring，★ 不是手打的


# --------------------------------------------------------------------------- 小工具

def glb6(bounds2x3) -> list:
    """trimesh 的 `[[x0,y0,z0],[x1,y1,z1]]` → `[x0,y0,z0,x1,y1,z1]`（glb / Y-up 帧，不做任何翻转）。"""
    b = np.asarray(bounds2x3, dtype=np.float64)
    return [float(v) for v in (list(b[0]) + list(b[1]))]


def max_abs_delta(a: list, b: list):
    """同帧两六元组的**分量最大绝对差**；长度不是 6 或有一侧为 None ⇒ `None`（＝没量到，不是 0）。"""
    if not a or not b or len(a) != 6 or len(b) != 6:
        return None
    return max(abs(float(a[k]) - float(b[k])) for k in range(6))


# --------------------------------------------------------------------------- 源件身份

def read_src_identity(src: str) -> dict:
    """源 `tileset.json` 的**现场读数**：版本、锚定、逐 content 节点的几何误差与包围球。

    ★ 逐片包围球是**外部参照**（另一条链写的，不是我算的）⇒ 给「回切件的坐标系对不对」一个**外部**读数
      （判断四 / 铁律 192：参照物必须与交付件不同源）。
    ★ 但它**不是判据**：规范 §4 第 9 条实测这份 tileset **被手工改过包围盒** ⇒ 只能抓粗错。见文件头盲区 5。
    """
    ts_path = os.path.join(src, "tileset.json")
    with open(ts_path, "r", encoding="utf-8") as f:
        ts = json.load(f)

    nodes, n = {}, {"v": 0}

    def walk(nd, depth):
        n["v"] += 1
        uri = (nd.get("content") or {}).get("uri")
        if uri:
            nodes[uri.replace("\\", "/")] = {
                "geometry_error": nd.get("geometricError"),
                "sphere": ((nd.get("boundingVolume") or {}).get("sphere")),
                "depth": depth}
        for c in nd.get("children") or []:
            walk(c, depth + 1)

    walk(ts.get("root", {}), 0)
    return {"path": ts_path, "sha256": S2E.sha256_file(ts_path), "asset": ts.get("asset"),
            "geometricError": ts.get("geometricError"),
            "root_transform": (ts.get("root") or {}).get("transform"),
            "refine": (ts.get("root") or {}).get("refine") or "REPLACE",
            "n_nodes": n["v"], "content": nodes}


# --------------------------------------------------------------------------- 读主件

def master_images(glb_path: str) -> dict:
    """主件 glb 里 `{网格名: [该网格各 primitive 用的**原始贴图字节**]}`。

    ★ 走 glTF 结构（mesh → primitive.material → pbrMetallicRoughness.baseColorTexture
      → textures[i].source → images[j].bufferView），**不按顺序猜** —— 规范 §3.3 原话：「猜是循环论证」。
      实测样例块（`_scratch/_probe_master_gltf.py`）：5 个网格 / 5 张 JPEG，**1:1 不共用**，5/5 走得通。
    """
    import pygltflib as P

    g = P.GLTF2().load(glb_path)
    blob = bytes(g.binary_blob())
    out, unmapped = {}, []

    def bytes_of_image(j):
        if j is None:
            return None
        bv_i = g.images[j].bufferView
        if bv_i is None:
            return None
        bv = g.bufferViews[bv_i]
        return blob[bv.byteOffset: bv.byteOffset + bv.byteLength]

    for m in g.meshes or []:
        imgs = []
        for pr in m.primitives:
            mat = g.materials[pr.material] if pr.material is not None else None
            pbr = getattr(mat, "pbrMetallicRoughness", None) if mat is not None else None
            bct = getattr(pbr, "baseColorTexture", None) if pbr is not None else None
            if bct is None:
                imgs.append(None)
                continue
            imgs.append(bytes_of_image(getattr(g.textures[bct.index], "source", None)))
        if m.name in out:
            unmapped.append({"name": m.name, "why": "网格名重复"})
            continue
        out[m.name] = imgs
        if any(i is None for i in imgs):
            unmapped.append({"name": m.name, "why": "有 primitive 走不到贴图"})
    return {"images": out, "unmapped": unmapped}


def rebuild_tree(pieces: list) -> tuple:
    """由谱系表的 `ancestors`（**取自树**，规范 §2.2）重建块内节点树。键 = 文件名（**含 `.glb`**）。

    ★ 不许用文件名前缀判祖先（规范 §2.2 实测：跨 LOD 时字符串前缀接不上，曾把 13,830 个正常祖先误报成孤儿）。
    """
    nodes: dict = {}

    def touch(fn):
        return nodes.setdefault(fn, {"name": fn, "children": [], "uri": None, "lod": None})

    for p in pieces:
        fn = p["name"] + ".glb"
        touch(fn)["uri"] = p["uri"].replace("\\", "/")
        touch(fn)["lod"] = p["lod"]
        prev = None
        for a in list(p["ancestors"]) + [fn]:
            touch(a)
            if prev is not None and a not in nodes[prev]["children"]:
                nodes[prev]["children"].append(a)
            prev = a
    roots = set(nodes)
    for nd in nodes.values():
        roots -= set(nd["children"])
    return nodes, sorted(roots)


def merge_box(acc, box):
    """把 `[xmin,ymin,zmin,xmax,ymax,zmax]`（ENU）并进 `acc`（`acc` 可为 None）。"""
    if box is None:
        return acc
    if acc is None:
        return list(box)
    for k in (0, 1, 2):
        acc[k] = min(acc[k], box[k])
    for k in (3, 4, 5):
        acc[k] = max(acc[k], box[k])
    return acc


# --------------------------------------------------------------------------- 出一块

def convert_block(block: str, edit_root: str, out_root: str, src: dict) -> dict:
    """一块：读主件 → 逐片回写 → 建树 → 交回读数（**不写 tileset.json**，全局那份在 main 里写）。"""
    import trimesh

    d = os.path.join(edit_root, block)
    glb_p = os.path.join(d, f"{block}.glb")
    lin_p = os.path.join(d, f"{block}.lineage.json")
    r = {"block": block, "ok": False, "missing_files": [], "errors": [], "refused": False,
         "schema_ok": None, "name_only_in_master": [], "name_only_in_lineage": [],
         "lod_mismatch": [], "multi_geom_pieces": [], "n_pieces": 0,
         "pieces": [], "nodes": {}, "roots": [], "img_unmapped": []}

    for p, why in ((glb_p, "主件 glb"), (lin_p, "谱系表")):
        if not os.path.exists(p):
            r["missing_files"].append({"path": p, "why": why})
    if r["missing_files"]:
        return r

    try:
        with open(lin_p, "r", encoding="utf-8") as f:
            lg = json.load(f)
    except Exception as exc:                       # noqa: BLE001 —— 读不动要如实报
        r["errors"].append({"uri": lin_p, "error": f"{type(exc).__name__}: {exc}"})
        return r

    # ★ 版本闸：**不认识的主件版本必须明确拒绝**，不许按 v1 的形状硬读（规范正本第 5 行）
    r["schema_ok"] = lg.get("schema") == SCHEMA
    if not r["schema_ok"]:
        r["refused"] = True          # ★ 「拒绝」不是「不合格」：前者＝这输入根本处理不了（rc=4）
        r["errors"].append({"uri": lin_p,
                            "error": f"schema={lg.get('schema')!r} ≠ {SCHEMA!r} ⇒ **拒绝出件**"})
        return r

    # ★ 锚定闸：谱系记的快照 vs 源件**此刻**的读数；不一致 ⇒ 拒绝（新旧层叠不上，正是 §5.1 要防的）
    snap = lg.get("src_tileset") or {}
    r["src_sha_recorded"], r["src_sha_now"] = snap.get("sha256"), src["sha256"]
    if snap.get("sha256") != src["sha256"]:
        r["refused"] = True          # ★ 同上：锚定对不上＝这输入根本处理不了（rc=4）
        r["errors"].append({"uri": "src_tileset",
                            "error": f"源 tileset 的 sha256 已变（谱系记 {snap.get('sha256')} / "
                                     f"现在 {src['sha256']}）⇒ **拒绝出件**（rc=4）"})
        return r

    try:
        scene = trimesh.load(glb_p, force="scene")
    except Exception as exc:                       # noqa: BLE001
        r["errors"].append({"uri": glb_p, "error": f"{type(exc).__name__}: {exc}"})
        return r
    if not hasattr(scene, "geometry"):
        r["errors"].append({"uri": glb_p, "error": "主件不是一个 Scene（几何名无从谈起）"})
        return r

    try:
        imgs = master_images(glb_p)
        r["img_unmapped"] = imgs.get("unmapped") or []
    except Exception as exc:                       # noqa: BLE001
        imgs = {"images": {}}
        r["errors"].append({"uri": glb_p, "error": f"读主件贴图失败 {type(exc).__name__}: {exc}"})

    # ★★ 双向对账：**两侧都点名**（正对照「改一名」靠这条；铁律 137/158）
    m_names = set(scene.geometry)
    l_names = {p["name"] for p in lg["pieces"]}
    r["name_only_in_master"] = sorted(m_names - l_names)
    r["name_only_in_lineage"] = sorted(l_names - m_names)
    if r["name_only_in_master"] or r["name_only_in_lineage"]:
        return r

    # ★ 一片＝一文件。某片若内含多个 geometry（拆件那侧会写成 `<stem>__<geom>`），
    #   文件名就与片名不再一一对应 ⇒ 本版**拒绝**，不许「差不多能对上」地回写。
    for p in lg["pieces"]:
        if os.path.splitext(os.path.basename(p["uri"]))[0] != p["name"]:
            r["multi_geom_pieces"].append({"name": p["name"], "uri": p["uri"]})
    if r["multi_geom_pieces"]:
        r["errors"].append({"uri": "<块>", "error":
                            f"有 {len(r['multi_geom_pieces'])} 片的名字与文件名不对应"
                            f"（一片含多 geometry）⇒ **拒绝出件**"})
        return r

    # ---------- 逐片回写 ----------
    out_block = os.path.join(out_root, "Data", block)
    os.makedirs(out_block, exist_ok=True)
    recs = []
    for p in sorted(lg["pieces"], key=lambda x: x["name"]):
        name = p["name"]
        fn = os.path.basename(p["uri"].replace("\\", "/"))
        dst = os.path.join(out_block, fn)
        gm = scene.geometry[name]
        master6 = [round(v, 6) for v in glb6(gm.bounds)]        # glb / Y-up 帧

        s = trimesh.Scene()
        s.add_geometry(gm, node_name=name, geom_name=name)
        with open(dst, "wb") as f:
            f.write(s.export(file_type="glb"))

        # ★ 贴图换回**原始字节**：trimesh 导出会解码又重编码 JPEG（规范 §3.3）。
        #   张数对不上就**一个都不换**（宁可保留有损，也不许错位换）。
        want = imgs["images"].get(name)
        try:
            rs = (S2E.restore_glb_images(dst, want) if want else {"status": "NO_SOURCE_IMAGE"})
        except Exception as exc:                   # noqa: BLE001
            rs = {"status": "ERROR", "error": f"{type(exc).__name__}: {exc}"}

        # ★ 第二把尺子：**写出后重新读回**再量（铁律 187：两次不同读数）
        back = trimesh.load(dst, force="scene")
        bg = list(back.geometry.values())
        if bg:
            lo = np.array([np.asarray(g.bounds)[0] for g in bg]).min(axis=0)
            hi = np.array([np.asarray(g.bounds)[1] for g in bg]).max(axis=0)
            tile2 = np.stack([lo, hi])
            tile6 = glb6(tile2)
            enu6 = [float(v) for v in S2E.enu_bbox(tile2)]
        else:
            tile6, enu6 = None, None
        nv = int(sum(len(g.vertices) for g in bg))
        nf = int(sum(len(g.faces) for g in bg))
        lod_w = S2E.lod_of(os.path.splitext(fn)[0])
        rec = {
            "name": name, "uri": p["uri"].replace("\\", "/"), "lod": p["lod"],
            "depth": p.get("depth"), "out": fn, "bytes": os.path.getsize(dst),
            "n_v": nv, "n_f": nf,
            "bounds_glb": (None if tile6 is None else [round(v, 6) for v in tile6]),
            "bounds_enu": (None if enu6 is None else [round(v, 3) for v in enu6]),
            "delta_bounds_max": (None if tile6 is None else max_abs_delta(tile6, master6)),
            "delta_n_v": nv - int(p.get("n_v") or 0),
            "delta_n_f": nf - int(p.get("n_f") or 0),
            # ★ 主件**此刻** vs 谱系**提取时**记的（都在 glb 帧）⇒ 非 0 就是「这片被改过」
            #   谱系 `pieces[].bounds` 是 **2×3**（不是平的 6 元），故两侧都过 `glb6` 归一
            "edit_delta_max": max_abs_delta([round(v, 6) for v in glb6(gm.bounds)],
                                            [round(float(v), 3) for v in glb6(p["bounds"])]
                                            if p.get("bounds") else None),
            "lod_written": lod_w,
            "texture_restore": rs,
        }
        recs.append(rec)
        if lod_w != p["lod"]:
            r["lod_mismatch"].append({"name": name, "lod_lineage": p["lod"], "lod_written": lod_w})

    r["pieces"] = recs
    r["n_pieces"] = len(recs)
    nodes, roots = rebuild_tree(lg["pieces"])
    r["nodes"], r["roots"] = nodes, roots
    r["ok"] = bool(recs) and not r["errors"] and not r["lod_mismatch"]
    return r


# --------------------------------------------------------------------------- 全局 tileset

def build_tileset(out_root: str, blocks: list, converted: dict, src: dict,
                  all_blocks: list) -> dict:
    """把各块的树挂到**一个**根下，序列化 `<out>/tileset.json`，并**读回自检**。

    ★ 根 `transform` = 源件那 16 个数，**逐位复现**（规范 §5.1）：新旧瓦片必须叠得上。
    ★ 包围盒**现算**（规范 §5.2）：源件的包围盒被手工改过（§4 第 9 条）⇒ 不许照抄。
    ★ `asset` 逐字沿用源件（含 `gltfUpAxis:Y`）＋ `extras` 点明「本件是**部分**回切」——件自己带着警告。
    """
    from py3dtiles.tileset.bounding_volume_box import BoundingVolumeBox
    from py3dtiles.tileset.tile import Tile
    from py3dtiles.tileset.tileset import TileSet

    box_cache: dict = {}

    def node_box(block, fn):
        """自底向上算 ENU AABB。★ 用**回读出的瓦片**包围盒（交付件本尊），不用主件里记的（铁律 192）。"""
        key = (block, fn)
        if key in box_cache:
            return box_cache[key]
        acc = None
        nd = converted[block]["nodes"][fn]
        if nd["uri"]:
            base = os.path.basename(nd["uri"])
            for rec in converted[block]["pieces"]:
                if rec["out"] == base:
                    acc = merge_box(acc, rec["bounds_enu"])
                    break
        for c in nd["children"]:
            acc = merge_box(acc, node_box(block, c))
        box_cache[key] = acc
        return acc

    fallbacks: list = []

    def make_tile(block, fn):
        nd = converted[block]["nodes"][fn]
        b = node_box(block, fn)
        uri = f"Data/{block}/{fn}"
        ge = (src["content"].get(uri) or {}).get("geometry_error")
        if ge is None:
            fallbacks.append(uri)
            ge = src["geometricError"]
        t = Tile(geometric_error=float(ge),
                 bounding_volume=(BoundingVolumeBox.from_mins_maxs(b) if b else None),
                 refine_mode="REPLACE",
                 content_uri=(f"Data/{block}/{os.path.basename(nd['uri'])}" if nd["uri"] else None))
        t.children = [make_tile(block, c) for c in nd["children"]]
        return t

    kids, top_box = [], None
    for blk in blocks:
        for rn in converted[blk]["roots"]:
            kids.append(make_tile(blk, rn))
            top_box = merge_box(top_box, node_box(blk, rn))

    flat = np.array(src["root_transform"], dtype=np.float64)
    ts = TileSet(geometric_error=float(src["geometricError"]))
    root = Tile(geometric_error=float(src["geometricError"]),
                bounding_volume=(BoundingVolumeBox.from_mins_maxs(top_box) if top_box else None),
                # ★ 源件的 16 个数是**列主序**展平的 ⇒ 原样 reshape 回去，`to_dict` 再展平时逐位还原
                transform=flat.reshape((4, 4), order="F"),
                refine_mode="REPLACE")
    root.children = kids
    ts.root_tile = root

    d = ts.to_dict()
    d["asset"] = dict(src["asset"] or {})          # ★ 逐字沿用（含 gltfUpAxis:Y）；不用 py3dtiles 写的时间戳
    ex = dict(d["asset"].get("extras") or {})
    ex["generator"] = "cdut3d/editable_to_tiles.py"
    ex["source_tileset_sha256"] = src["sha256"]
    ex["converted_blocks"] = len(blocks)
    not_conv = sorted(set(all_blocks) - set(blocks))
    ex["not_converted_blocks"] = not_conv
    d["asset"]["extras"] = ex

    path = os.path.join(out_root, "tileset.json")
    S2E.dump_bytes(path, d)
    return {"path": path, "sha256": S2E.sha256_file(path), "geo_err_fallback": fallbacks,
            "root_box_enu": ([round(float(v), 3) for v in top_box] if top_box else None),
            "n_content_written": sum(1 for b in blocks
                                     for n in converted[b]["nodes"].values() if n["uri"])}


def verify_tileset(path: str, src: dict) -> dict:
    """**读回**写出的 tileset.json 并核四件事：锚定逐位、每个 content 都在盘上、节点数、refine。

    ★ 这是**独立复算**：走 `json` 而非 py3dtiles（同一条链读自己写的件＝没核）。
    """
    with open(path, "r", encoding="utf-8") as f:
        d = json.load(f)
    out = {"asset": d.get("asset"), "n_content": 0, "n_content_on_disk": 0,
           "missing_content": [], "refine_set": set(), "n_nodes": 0,
           "transform_bitmatch": None, "transform_delta": None}

    def walk(nd):
        out["n_nodes"] += 1
        if nd.get("refine"):
            out["refine_set"].add(nd["refine"])
        uri = (nd.get("content") or {}).get("uri")
        if uri:
            out["n_content"] += 1
            if os.path.exists(os.path.join(os.path.dirname(path), uri)):
                out["n_content_on_disk"] += 1
            else:
                out["missing_content"].append(uri)
        for c in nd.get("children") or []:
            walk(c)

    walk(d.get("root", {}))
    out["refine_set"] = sorted(out["refine_set"])

    ft, st = (d.get("root") or {}).get("transform"), src["root_transform"]
    if ft is None or st is None:
        out["transform_bitmatch"] = (ft is None) == (st is None)
    else:
        a, b = np.array(ft, dtype=np.float64), np.array(st, dtype=np.float64)
        a16 = a.reshape((4, 4), order="F").flatten("F") if a.size == 16 else a.flatten("F")
        b16 = b.reshape((4, 4), order="F").flatten("F") if b.size == 16 else b.flatten("F")
        out["transform_delta"] = float(np.max(np.abs(a16 - b16)))
        out["transform_bitmatch"] = bool(np.array_equal(a16, b16))
    return out


# --------------------------------------------------------------------------- 主流程

def main() -> int:
    ap = argparse.ArgumentParser(description="可编辑主件 → 瓦片（回切）")
    ap.add_argument("--edit", default=DEFAULT_EDIT)
    ap.add_argument("--out", default=DEFAULT_OUT)
    ap.add_argument("--src", default=DEFAULT_SRC)
    ap.add_argument("--blocks", default="", help="逗号分隔的块名；缺省配 --all")
    ap.add_argument("--all", action="store_true", help="列 <edit>/ 下所有块目录")
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args()

    if not os.path.exists(os.path.join(a.src, "tileset.json")):
        print(f"[FATAL] 源 tileset.json 不存在：{a.src}", file=sys.stderr)
        return RC_NOGAUGE
    src = read_src_identity(a.src)

    t0 = datetime.datetime.now()
    ledger: dict = {"schema": SCHEMA, "edit_dir": a.edit, "out_dir": a.out,
                    "src_tileset": {"path": src["path"], "sha256": src["sha256"],
                                    "asset": src["asset"], "refine": src["refine"],
                                    "geometricError": src["geometricError"],
                                    "n_nodes": src["n_nodes"]},
                    "tolerance_m": TOL_M,
                    "tolerance_note": "容差＝谱系表 bounds 的记录精度（3 位小数）；"
                                      "两遍回切实测方差为独立读数，见 _pc_roundtrip.py"}

    # ---------- 选块：★ 真源 = **程序现列文件系统**（规范 §4 第 3 条：不信 meta.json）----------
    disk_blocks = sorted(n for n in os.listdir(a.edit)
                         if os.path.isdir(os.path.join(a.edit, n))
                         and os.path.exists(os.path.join(a.edit, n, f"{n}.lineage.json")))
    if a.blocks:
        want = [b.strip() for b in a.blocks.split(",") if b.strip()]
    elif a.all:
        want = disk_blocks[:a.limit] if a.limit else disk_blocks
    else:
        print("[FATAL] 要么 --blocks，要么 --all", file=sys.stderr)
        return RC_NOGAUGE

    absent = [b for b in want if b not in disk_blocks]
    ledger["blocks_on_disk"] = len(disk_blocks)
    ledger["blocks_requested"] = want
    ledger["blocks_named_but_absent"] = absent
    if absent:
        print(f"★ 点名的块在 <edit>/ 下**没有主件**（铁律 174：计数取自独立清单，不许抹平）：{absent}",
              file=sys.stderr)

    print("=" * 74)
    print(f"源 tileset : {src['path']}")
    print(f"             sha256 {src['sha256'][:16]}…  节点 {src['n_nodes']}  refine {src['refine']}")
    print(f"主件目录   : {a.edit}  （盘上 {len(disk_blocks)} 块）")
    print(f"回切到     : {a.out}")

    # ---------- 逐块 ----------
    converted, results = {}, []
    todo = [b for b in want if b not in absent]
    for i, blk in enumerate(todo, 1):
        r = convert_block(blk, a.edit, a.out, src)
        if r["ok"]:
            converted[blk] = r
        tag = []
        if r["missing_files"]:
            tag.append("★ 缺件 " + str([x["why"] for x in r["missing_files"]]))
        if r["errors"]:
            tag.append("★ 错 " + str(len(r["errors"])))
        if r["name_only_in_master"]:
            tag.append("★ 只在主件 " + str(r["name_only_in_master"][:3]))
        if r["name_only_in_lineage"]:
            tag.append("★ 只在谱系 " + str(r["name_only_in_lineage"][:3]))
        print(f"  [{i}/{len(todo)}] {blk}: 片 {r['n_pieces']}  " + "  ".join(tag))
        for e in r["errors"]:
            print(f"        · {e['uri']}: {e['error']}")
        if r["pieces"]:
            dm = max((p["delta_bounds_max"] or 0) for p in r["pieces"])
            dv = max(abs(p["delta_n_v"]) for p in r["pieces"])
            df = max(abs(p["delta_n_f"]) for p in r["pieces"])
            same_lod = sum(1 for p in r["pieces"] if p["lod_written"] == p["lod"])
            print(f"        往返：逐片包围盒最大差 {dm:.6f} m（容差 {TOL_M}）"
                  f"  顶点差 ≤{dv}  面数差 ≤{df}  同 LOD 回写 {same_lod}/{len(r['pieces'])}")
            if r["lod_mismatch"]:
                print(f"        ★ LOD 变了：{r['lod_mismatch'][:3]}")
            ok_tex = sum(1 for p in r["pieces"] if p["texture_restore"].get("status") == "OK")
            bad_tex = [p for p in r["pieces"] if p["texture_restore"].get("status") != "OK"]
            print(f"        贴图：换回原始字节 {ok_tex}/{len(r['pieces'])} 片"
                  + ("  ★ 未换回：" + str([(p["name"][-10:], p["texture_restore"].get("status"))
                                           for p in bad_tex[:3]]) if bad_tex else ""))
            edited = [p for p in r["pieces"]
                      if p["edit_delta_max"] is not None and p["edit_delta_max"] > TOL_M]
            print(f"        主件 vs 谱系（提取时的读数）：被改过的片 {len(edited)}"
                  + (" —— " + str([p["name"][-12:] for p in edited[:4]]) if edited
                     else "（主件与提取时一致 ⇒ 本次没有编辑）"))
        results.append(r)

    # ---------- 全局 tileset ----------
    ok_blocks = sorted(converted)
    if ok_blocks:
        ts_key = build_tileset(a.out, ok_blocks, converted, src, disk_blocks)
        v = verify_tileset(ts_key["path"], src)
        print("-" * 74)
        print(f"回切 tileset : {ts_key['path']}  sha256 {ts_key['sha256'][:16]}…")
        print(f"  ★ 锚定逐位复现 source root.transform ? {v['transform_bitmatch']}"
              f"（最大差 {v['transform_delta']}）")
        print(f"  content 节点 {v['n_content']}  其中**盘上存在** {v['n_content_on_disk']}"
              + ("  ★ 缺 " + str(v["missing_content"][:4]) if v["missing_content"] else ""))
        print(f"  节点数 {v['n_nodes']}  refine {v['refine_set']}")
        print(f"  根包盒（ENU，**现算**）{ts_key['root_box_enu']}")
        if ts_key["geo_err_fallback"]:
            print(f"  ★ 有 {len(ts_key['geo_err_fallback'])} 个节点在源里查不到 geometricError"
                  f" ⇒ 退回根值：{ts_key['geo_err_fallback'][:4]}")
        ledger["tileset"] = {"path": ts_key["path"], "sha256": ts_key["sha256"],
                             "verify": v, "root_box_enu": ts_key["root_box_enu"],
                             "geo_err_fallback": ts_key["geo_err_fallback"],
                             "n_content_written": ts_key["n_content_written"]}
    else:
        print("-" * 74)
        print("★ 一块都没回切成功 ⇒ **不写 tileset.json**（量不到就不出结论）")

    # ---------- 台账 ----------
    bad_blocks = [x["block"] for x in results
                  if x["missing_files"] or x["errors"] or x["name_only_in_master"]
                  or x["name_only_in_lineage"] or x["lod_mismatch"]]
    ledger["n_requested"] = len(want)
    ledger["n_converted"] = len(ok_blocks)
    ledger["converted_blocks"] = ok_blocks
    ledger["failed_blocks"] = bad_blocks + absent
    ledger["failed_detail"] = [{"block": x["block"], "missing_files": x["missing_files"],
                                "errors": x["errors"],
                                "only_in_master": x["name_only_in_master"],
                                "only_in_lineage": x["name_only_in_lineage"],
                                "lod_mismatch": x["lod_mismatch"],
                                "multi_geom_pieces": x["multi_geom_pieces"]}
                               for x in results if x["block"] in bad_blocks]
    ledger["results"] = []
    for x in results:
        pk = x["pieces"] or []
        ledger["results"].append({
            "block": x["block"], "ok": x["ok"], "n_pieces": len(pk),
            "max_delta_bounds_m": (max((p["delta_bounds_max"] or 0) for p in pk) if pk else None),
            "max_abs_delta_n_f": (max(abs(p["delta_n_f"]) for p in pk) if pk else None),
            "n_pieces_edited": sum(1 for p in pk
                                   if p["edit_delta_max"] is not None and p["edit_delta_max"] > TOL_M),
            "n_tex_restored": sum(1 for p in pk if p["texture_restore"].get("status") == "OK"),
        })
    ledger["elapsed_s"] = round((datetime.datetime.now() - t0).total_seconds(), 1)
    # ★ 三态**优先级**：`拒绝`(4) > `不合格`(1) > `通过`(0)。
    #   有块被拒绝 ⇒ 本次产物**不完整且不可信**，此时回 1（更像「跑完了但有几块不行」）是**错的**：
    #   调用方会把「按对了形状读了一遍、得出一堆 0」当成结论。★ 正对照戊就是这么把它抓出来的。
    refused_blocks = [x["block"] for x in results if x["refused"]]
    ledger["refused_blocks"] = refused_blocks
    if refused_blocks:
        ledger["rc"] = RC_NOGAUGE
    elif bad_blocks or absent:
        ledger["rc"] = RC_FAIL
    else:
        ledger["rc"] = RC_PASS if ok_blocks else RC_NOGAUGE
    ledger["pass"] = ledger["rc"] == RC_PASS
    os.makedirs(a.out, exist_ok=True)
    S2E.dump_bytes(os.path.join(a.out, "_index.json"), ledger)

    print("-" * 74)
    if refused_blocks:
        print(f"★ 被**拒绝**出件的块（{len(refused_blocks)}）：{refused_blocks}"
              f" —— 这不是「不合格」，是「这输入根本处理不了」⇒ rc=4，本次产物**不可当作结论**")
    print(f"回切 {len(ok_blocks)} / 点名 {len(want)} 块；失败或被点名的块：{ledger['failed_blocks']}")
    print(f"用时 {ledger['elapsed_s']} s   → {os.path.join(a.out, '_index.json')}")
    print("=" * 74)
    return ledger["rc"]


if __name__ == "__main__":
    raise SystemExit(main())
