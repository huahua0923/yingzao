# -*- coding: utf-8 -*-
r"""把理化楼（c005）按 cdut3d 链**现做的产物**打成模型包 `packs/cdut-main/c005/`。

用户令（2026-10-17）：「你先把理化楼按照流程做出来」。

★ 与旧版（2026-10-17 上午那版「原样搬入」）的差别，一句话：
  旧版把 gym3d 的 `c005-building.glb`（单网格、无逐层节点）原样搬进包，并在 QC 里
  写真话 `positive_control.fired=false` ⇒ `tools/modelpack.py::validate` 拒包。
  本版打的是**本仓链自己的交付件** `rebuild/c005/06_su/c005_fc.glb`
  （源 DXF → 切图幅 → 识别 → build3d → **FreeCAD** → GLB），顶层节点 = `floor0..floor4`；
  （2026-10-17 用户令「现在开工换 FreeCAD」；SU 件 `c005_su.glb` 留作退路，
   设 `CDUT_PACK_SRC=su` 才用，不静默回退）
  质检 = **同一把尺子**量真件与扰动假件，正对照真的会响。

★ 本脚本**只读** `rebuild/c005/`（含 `01_cad/raw/`），**只写**包目录 + `demo/_gen/`。
★ 数全部现算/现读：层数、层高、标高、面数一个都不手打（铁律 103/018）。

用法：python -I demo/build_pack_c005.py
退出码：0 成功 · 1 判据不过 · 4 缺件（SU 出的 GLB 还没生成）
"""
import hashlib
import json
import os
import shutil
import sys
import time

sys.stdout.reconfigure(encoding="utf-8")

CDUT = r"D:\项目\cdut3d"
REB = os.path.join(CDUT, "rebuild", "c005")
# ★ 2026-10-17 换链（用户令「现在开工换 FreeCAD」）：建件机由 SketchUp 换成 FreeCAD，
#   目的是可复现（同一份 contours 连跑两趟，OBJ 逐字节相同）。
#   两条件逐 (层,类) 比过：c005 **25/25 件**、包围盒偏差 **0.000 m**。
#   SU 件留作退路，但**不静默回退**：要它得显式 `CDUT_PACK_SRC=su`。
SRC_KIND = (os.environ.get("CDUT_PACK_SRC") or "fc").lower()
GLB_NAME = "c005_fc.glb" if SRC_KIND == "fc" else "c005_su.glb"
GLB = os.path.join(REB, "06_su", GLB_NAME)
BUILD_JSON = os.path.join(REB, "05_build", "build.json")
CONT_INDEX = os.path.join(REB, "06_su", "contours", "index.json")
RAW = os.path.join(REB, "01_cad", "raw")

CAMPUS = "cdut-main"
BUILDING = "c005"
PACK = os.path.join(CDUT, "packs", CAMPUS, BUILDING)
GEN = os.path.join(CDUT, "demo", "_gen")
STAGE = os.path.join(GEN, "c005-stage")
ARCHIVE = os.path.join(CDUT, "_archive", "pack-c005-gym3d-20261017")

sys.path.insert(0, os.path.join(CDUT, "tools"))
sys.path.insert(0, os.path.join(CDUT, "demo"))
sys.path.insert(0, os.path.join(CDUT, "过程/a1"))

import modelpack                                                    # noqa: E402

# 主体类：**顶标高判据**只看这几类。女儿墙/顶楼楼梯房/屋面台阶是**附属**，
#   它们比层顶高（c005 顶楼：主体 20.0 m、女儿墙 20.9 m、楼梯房顶 23.0 m）——
#   拿它们当层顶会恒红（c006 那份也是同一个名单）。
MAIN_CLS = ("WALL", "SLAB", "COL", "LIFT", "DOOR", "STAIR")
TOL_M = 0.05                    # 标高容差（米）
THRESHOLD = 0.95                # 质检通过率门槛（与 c006 包同一口径）
CONTROL_NODE = "floor1"         # 正对照要扰动的层节点（= 2 层，0 基）
CONTROL_SHIFT_M = 2.0           # 整层抬起 2 m —— 节点仍在、标高必错


def _read(p):
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def _dump_bytes(path, obj):
    """★ 铁律 79：字节层写盘 + 强制 LF（文本模式在 Windows 上会翻成 CRLF）。"""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    data = json.dumps(obj, ensure_ascii=False, indent=1).encode("utf-8").replace(b"\r\n", b"\n")
    with open(path, "wb") as f:
        f.write(data)


def _sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for c in iter(lambda: f.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()


def _scan(glb, order):
    """把落盘 GLB 量一遍：逐层节点 / 逐类面数 / 包围盒。**不建几何、不猜**。

    返回 {layers: {node: {...}}, unmatched: [...], faces_all: int}
    `unmatched` = 名字解析不出层节点的网格 —— 它们**不进** layers，正因如此必须
    单独计数（铁律 137：判据名单漏掉主体则永远绿）。
    """
    import trimesh                                                  # noqa: E402
    sc = trimesh.load(glb, force="scene")
    lay = {}
    unmatched = []
    faces_all = 0
    for nm in sorted(sc.geometry):
        g = sc.geometry[nm]
        faces_all += len(g.faces)
        node, cls = (nm.split("__", 1) + [""])[:2] if "__" in nm else (nm, "")
        if node not in order:
            unmatched.append(nm)
            continue
        lo = round(float(g.bounds[0][1]), 3)          # glTF 是 Y 朝上
        hi = round(float(g.bounds[1][1]), 3)
        e = lay.setdefault(node, {"node": node, "faces": 0, "classes": {}, "class_hi": {},
                                  "lo_m": lo, "hi_m": hi, "plan_m": [0.0, 0.0]})
        e["faces"] += len(g.faces)
        e["classes"][cls] = e["classes"].get(cls, 0) + len(g.faces)
        e["class_hi"][cls] = hi
        e["lo_m"] = min(e["lo_m"], lo)
        e["hi_m"] = max(e["hi_m"], hi)
        e["plan_m"] = [max(e["plan_m"][0], round(float(g.bounds[1][0] - g.bounds[0][0]), 3)),
                       max(e["plan_m"][1], round(float(g.bounds[1][2] - g.bounds[0][2]), 3))]
    return {"layers": lay, "unmatched": unmatched, "faces_all": faces_all}


def _top_main(layer):
    """该层**主体类**的最高点（米）。没有主体类 ⇒ 返回 None（不拿附属件充数）。"""
    vals = [v for c, v in layer["class_hi"].items() if c in MAIN_CLS]
    return max(vals) if vals else None


def _gauge(scan, order, z0, hs):
    """逐层节点 ε 校验。**同一段代码**既量真件也量假件（这是正对照成立的前提）。

    每层 3 条：① 节点在且有面 ② 底标高 = z0 ③ 主体顶标高 = z0 + hs[k]
    整件 1 条：④ 构件不漏出层节点（游离网格数 = 0）
    `z0`/`hs` 由调用方从 contours/index.json 现读，本函数**不写死任何标高**。
    """
    checks = []
    for k, node in enumerate(order):
        L = scan["layers"].get(node)
        if not L or not L["faces"]:
            got = "缺节点" if not L else "0 面"
            checks.append({"id": node + "/存在", "ok": False, "want": ">0 面", "got": got})
            checks.append({"id": node + "/底标高", "ok": False, "want": z0[k], "got": None})
            checks.append({"id": node + "/顶标高(主体)", "ok": False,
                           "want": round(z0[k] + h, 3), "got": None})
            continue
        checks.append({"id": node + "/存在", "ok": L["faces"] > 0,
                       "want": ">0 面", "got": L["faces"]})
        checks.append({"id": node + "/底标高", "ok": abs(L["lo_m"] - z0[k]) <= TOL_M,
                       "want": z0[k], "got": L["lo_m"]})
        hi = _top_main(L)
        checks.append({"id": node + "/顶标高(主体)",
                       "ok": hi is not None and abs(hi - (z0[k] + hs[k])) <= TOL_M,
                       "want": round(z0[k] + hs[k], 3), "got": hi})
    checks.append({"id": "构件不漏出层节点", "ok": not scan["unmatched"],
                   "want": "0 个游离网格", "got": len(scan["unmatched"])})
    passed = sum(1 for c in checks if c["ok"])
    return {"score": passed / float(len(checks)), "passed": passed, "total": len(checks),
            "fails": [c for c in checks if not c["ok"]], "checks": checks}


def _control_glb(src, out, node, shift_m):
    """造扰动假件：把 `node` 底下的所有网格整体抬起 `shift_m` 米。

    ★ 与「直接删一层」不同：节点**还在**，所以它只考「标高量得准不准」，
      不靠「数得到几个节点」混分（那正是要防的：尺子只会数节点）。
    """
    import trimesh                                                  # noqa: E402
    sc = trimesh.load(src, force="scene")
    n = 0
    for nm in list(sc.geometry):
        if ("__" in nm and nm.split("__", 1)[0] == node) or nm == node:
            sc.geometry[nm].apply_translation([0.0, float(shift_m), 0.0])
            n += 1
    if not n:
        raise SystemExit("★ 假件没动到任何网格（节点名 %s 在件里找不到）⇒ 正对照不成立" % node)
    data = sc.export(file_type="glb")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "wb") as f:
        f.write(data)
    return n


def _rooms_ledger():
    """从切图后的 5 张图幅现取房间台账（`a1/rooms.py::load_rooms`）。

    ★ 2026-10-17 改落盘形状：**列表**（与 c006 同款），不再包一层 dict。
      原版写 `{schema, n_rows, per_sheet, rows}`，而 `demo/building.html:721` 判的是
      `Array.isArray(d)` —— dict 落进 else 分支，屏上印「**台账是空的：0 行 —— 真没有**」，
      而件里明明有 118 行（**假否定**，铁律 158）。字段名也照 c006 映射：阅读器按
      `r.number` 取节点、`r.dept` 补使用单位（`demo/index.html:765`），用原名取不到。
    ★ **没有 centroid/boundary**：源件只有文字属性，没有房间多边形 ⇒ 房间色块铺不了；
      这不是「配准失败」，是**来源里没有面**。
    """
    import rooms as roomlib                                         # noqa: E402
    rows, per = [], []
    for k in range(5):
        sheet = "%d层" % (k + 1)
        p = os.path.join(RAW, sheet + ".dxf")
        if not os.path.isfile(p):
            raise SystemExit("★ 缺切图后的图幅：%s" % p)
        rs, st = roomlib.load_rooms(p)
        for r in rs:
            rows.append({
                "id": len(rows) + 1,
                "building": BUILDING,
                "floor": k,
                "number": r.get("room_id"),
                "name": None,
                "area": r.get("area_text"),
                "area_m2": r.get("area_m2"),
                "purpose": r.get("use"),
                "dept": r.get("unit"),
                "sheet": sheet,
                "src_dist_mm": r.get("dist_mm"),
            })
        per.append({"sheet": sheet, "level": k, "n_rows": len(rs), "stats": st})
    src = {"schema": "cdut3d-roomledger/1", "building_id": BUILDING,
           "source": "rebuild/c005/01_cad/raw/<层>.dxf（切图后的 5 张图幅，非原始整图）",
           "tol_mm": 1500.0, "n_rows": len(rows), "per_sheet": per,
           "blind_spot": "本台账只有文字属性（房间号/面积/用途/使用单位）；房间**面片**在 "
                         "baseline/floors/floor<k>.json 的 rooms（来自 redraw 分区），两份不合并。"}
    return rows, src


MIN_REGION_M2 = 1.0            # 分区下限（m²）：再小的是井道/柱缝，不是房间
LABEL_HIT_R_MM = 50.0          # 文字落点半径：字锚点落在分区外 50 mm 内仍算这一间
ROOF_OWN_SHARE = 0.5           # 一个分区有这么大比例落在裙房屋面区里 ⇒ 它是屋面，不是交通


def _floor_plans(layer_h):
    """逐层房间面片 → `baseline/floors/floor<k>.json`（与件**同源**的那把尺子）。

    ★ 为什么不用 `rebuild/tools/build_rooms.py`：它走「线对 → 墙带 → 环」，对本楼实测
      **判否**（间距谱主峰 120 mm ≠ 表 240 mm —— 被 300 mm 踏步线与 120 系谱污染）。
      本件改用 `redraw.geometry(层)` 的「楼板 − 墙带」分区：与建件（build3d/export_contours）
      是同一份几何，坐标不再二次换算。
    ★ 落点判据实测（5 层 118 间）：每条 `6房间号` **各自唯一落进一个分区**，
      0 落空、0 一区多字。任何一条落不进去 ⇒ 直接报错退出（几何变了，不许静默少一间）。
    ★ 顶层裙房屋面：用 `B3.podium_roof_trim`（建件的**同一个函数**）切出屋面区，
      落在里面的分区既不进 `rooms` 也不进 `circulation`（它是屋面，不是地面）。
    """
    os.environ.setdefault("CDUT_BUILDING", BUILDING)
    os.environ.setdefault("CDUT_REBUILD_ROOT", REB)
    sys.path.insert(0, os.path.join(CDUT, "rebuild", "tools"))
    import ezdxf                                                    # noqa: E402
    from shapely.geometry import Point, Polygon                     # noqa: E402
    from shapely.ops import unary_union                             # noqa: E402
    import build3d as B3                                            # noqa: E402
    import build_rooms as BR                                        # noqa: E402
    import redraw as RD                                             # noqa: E402

    def _poly(pts, holes=()):
        p = Polygon(pts, holes)
        if not p.is_valid:
            p = p.buffer(0)
        return None if p.is_empty else p

    def _ring(g):
        """多边形 → 包内写法 [[x,y]…]（米，闭合由首尾点承担；与 c006 同形）。"""
        return [[round(x / 1000.0, 3), round(y / 1000.0, 3)] for x, y in g.exterior.coords]

    names = [n for n, _z, _h in B3.FLOORS]
    out, per = [], []
    for k, name in enumerate(names):
        v = RD.geometry(name)
        plate = unary_union([p for p in (_poly(s) for s in v["plate"]) if p is not None])
        walls = unary_union([p for p in (_poly(s, h) for s, h in v["walls"]) if p is not None])
        regs = [g for g in getattr(plate.difference(walls).buffer(0), "geoms", [])
                if g.area > MIN_REGION_M2 * 1e6]
        if not regs:
            raise SystemExit("★ %s 一个分区都没有（楼板 %.1f m² / 墙带 %.1f m²）⇒ 不许静默出空表"
                             % (name, plate.area / 1e6, walls.area / 1e6))
        # 顶层：屋面区（与建件同一函数、同一读数）
        roof_zone, rdiag = None, None
        if B3.B.profile().get("podium_roof") and name == B3.TOP_FLOOR:
            _sp, _wp, rdiag = B3.podium_roof_trim(v, B3.slab_polys(v), B3.wall_polys(v), name)
            _cut = plate.difference(unary_union(_sp))       # `plate` 已是几何（上面 4 行算的）
            roof_zone = None if _cut.is_empty else _cut
        # 文字 → 分区
        doc = ezdxf.readfile(os.path.join(RAW, name + ".dxf"))
        txts = BR.texts(doc)
        by_kind = {}
        orphan = {}
        for kind, items in txts.items():
            m = {}
            for it in items:
                b = Point(it["xy"]).buffer(LABEL_HIT_R_MM)
                hit = [i for i, g in enumerate(regs) if g.intersects(b)]
                if not hit:
                    orphan.setdefault(kind, []).append(it["文"])
                    continue
                best = max(hit, key=lambda i: regs[i].intersection(b).area)
                m.setdefault(best, []).append(it["文"])
            by_kind[kind] = m
        if orphan.get("房间号"):
            raise SystemExit("★ %s 有 %d 条房间号文字一个分区都没落进：%s"
                             % (name, len(orphan["房间号"]), orphan["房间号"][:5]))
        multi = [i for i, v_ in by_kind.get("房间号", {}).items() if len(v_) > 1]
        if multi:
            raise SystemExit("★ %s 有 %d 个分区塞了多间房（没被墙隔开）：%s"
                             % (name, len(multi), multi[:5]))

        rooms, circ, roof_n = [], [], 0
        for i, g in enumerate(regs):
            if roof_zone is not None and g.intersection(roof_zone).area > ROOF_OWN_SHARE * g.area:
                roof_n += 1
                continue
            rec = {"poly": _ring(g), "area_m2": round(g.area / 1e6, 2)}
            if list(g.interiors):
                rec["holes"] = [[[round(x / 1000.0, 3), round(y / 1000.0, 3)] for x, y in r.coords]
                                for r in g.interiors]
            num = (by_kind.get("房间号", {}).get(i) or [None])[0]
            if not num:
                circ.append(dict(rec, src="redraw 分区·未标房号（走廊/门厅/梯井）"))
                continue
            stated = [BR.parse_area(t) for t in by_kind.get("面积", {}).get(i, [])]
            rec.update({
                "number": num,
                "purpose": (by_kind.get("用途", {}).get(i) or [""])[0],
                "dept": (by_kind.get("单位", {}).get(i) or [""])[0],
                "stated_m2": next((x for x in stated if x), None),
                "sid": "%s:%s:room:%s" % (CAMPUS, BUILDING, num),
                "src": "redraw 分区（楼板−墙带）+ 房间号落点",
            })
            rooms.append(rec)
        outline_g = max((_poly(s) for s in v["plate"] if _poly(s) is not None),
                        key=lambda g: g.area, default=None)
        if outline_g is None:
            raise SystemExit("★ %s 楼板轮廓为空 ⇒ 帧变换无参照物" % name)
        # 柱心（米，与 `rooms.poly` 同一套坐标）。查看器 `roomFrame` 要拿它跟模型里
        #   `blocks[].layer==='COL'` 的 bbox 中心**按序号**逐根对（铁律 194），投出 dx/dy。
        #   源图只首层有柱 ⇒ 2~5 层是空数组（照图，不复制）。
        cols = []
        for pts, _cl in (v.get("cols") or []):
            if not pts:
                continue
            xs = [p[0] for p in pts]
            ys = [p[1] for p in pts]
            cols.append({"x": round((min(xs) + max(xs)) / 2.0 / 1000.0, 3),
                         "y": round((min(ys) + max(ys)) / 2.0 / 1000.0, 3)})
        out.append({
            "floor": k + 1,
            "layer_height": layer_h,
            "outline": _ring(outline_g),
            "columns": cols,
            "rooms": rooms,
            # 交通面（走廊/门厅/梯井）照旧**留在数据里**：2D 平面图按灰底画它、台账也要用。
            #   三维地垫不铺它 —— 那条规则在查看器一处（用户令：「只是有功能需求的，
            #   像过道等不要标」）。别在这里删数据：删了 2D 平面图会跟着少一块。
            "circulation": circ,
            "walls": [],
            "doors": [],
            "src": "redraw.geometry(%s)：房间面片来自「楼板 − 墙带」分区，面积现算" % name,
        })
        per.append({"floor": name, "regions": len(regs), "rooms": len(rooms),
                    "circ": len(circ), "roof": roof_n, "rdiag": rdiag,
                    "orphan": orphan})
    return out, per


def main():
    if not os.path.isfile(GLB):
        print("★ 缺正式件 %s" % GLB)
        if SRC_KIND == "fc":
            print("   ⇒ CDUT_BUILDING=c005 CDUT_REBUILD_ROOT=rebuild/c005 "
                  "python rebuild/tools/run_freecad.py")
            print("     再 CDUT_BUILDING=c005 CDUT_REBUILD_ROOT=rebuild/c005 "
                  "python rebuild/tools/fc_obj_to_glb.py")
        else:
            print("   ⇒ 先跑 rebuild/06_su/_run_su_step2.ps1 -Dir rebuild/c005/06_su -Name c005，")
            print("     再跑 rebuild/tools/su_obj_to_glb.py（CDUT_BUILDING=c005）")
        return 4
    print("件源    : %s（CDUT_PACK_SRC=%s）" % (GLB_NAME, SRC_KIND))
    for p in (BUILD_JSON, CONT_INDEX):
        if not os.path.isfile(p):
            print("★ 缺 %s" % p)
            return 4

    # ★ 层数/底标高/层高**一律从 contours 现读**（铁律 103/018：手打的数会把
    #   「声明错了」报成「代码有副作用」）。contours 是 SU 实际建的那批轮廓。
    ci = _read(CONT_INDEX)
    ci = sorted(ci, key=lambda r: float(r["z0_m"]))
    order = ["floor%d" % k for k in range(len(ci))]
    z0 = [round(float(r["z0_m"]), 3) for r in ci]
    hs = [round(float(r["h_m"]), 3) for r in ci]

    # ── ① 量真件 ─────────────────────────────────────────────────────────
    scan = _scan(GLB, order)
    missing = [n for n in order if n not in scan["layers"]]
    if missing:
        print("★ 正式件里缺层节点 %s ⇒ 不打包（不许静默少一层）" % missing)
        return 1
    layers = [scan["layers"][n] for n in order]
    faces_total = sum(l["faces"] for l in layers)
    print("模型    : %s · %d 个层节点 · 面 %d（件内总面 %d）· %.1f MB"
          % (os.path.basename(GLB), len(layers), faces_total, scan["faces_all"],
             os.path.getsize(GLB) / 1e6))
    if scan["unmatched"]:
        print("★ 有 %d 个网格挂不到层节点：%s" % (len(scan["unmatched"]), scan["unmatched"][:5]))

    # ── ② 三个独立读数对层高/标高（铁律 018：两个地方写同一个数证明不了它对）──
    bj = _read(BUILD_JSON)
    los = [l["lo_m"] for l in layers]
    bands = sorted(round(los[k] - los[k - 1], 4) for k in range(1, len(los)))
    floor_h = bands[len(bands) // 2] if bands else None
    spread = round(bands[-1] - bands[0], 4) if bands else None
    src_h = {
        "件侧": {"floor_h_m": floor_h, "spread_m": spread,
                 "how": "相邻层节点 lo_m 之差（%d 个带）" % len(bands)},
        "轮廓侧": {"floor_h_m": sorted({round(float(r["h_m"]), 3) for r in ci}),
                   "how": "contours/index.json 的 h_m（SU 建的正是这批轮廓）"},
        "参数侧": {"storey_m": float(bj["storey_m"]), "how": "05_build/build.json"},
    }
    agree = (floor_h is not None
             and abs(floor_h - float(bj["storey_m"])) <= 1e-3
             and all(abs(float(r["h_m"]) - floor_h) <= 1e-3 for r in ci))
    print("层高    : 件侧 %.4f m（离散 %s）· 参数表 %.1f m · 轮廓 %s ⇒ %s"
          % (floor_h, spread, float(bj["storey_m"]),
             sorted({round(float(r["h_m"]), 3) for r in ci}), "一致" if agree else "★ 不一致"))
    z_bot, z_top = min(los), max(l["hi_m"] for l in layers)
    print("标高    : %.3f .. %.3f m（build.json: %.3f .. %.3f）"
          % (z_bot, z_top, -abs(float(bj["basement_m"])), float(bj["z_max_m"])))

    # ── ③ 质检：同一把尺子量真件 + 扰动假件 ──────────────────────────────
    base = _gauge(scan, order, z0, hs)
    ctrl_glb = os.path.join(GEN, "c005_ctrl_%s_plus%.0fm.glb" % (CONTROL_NODE, CONTROL_SHIFT_M))
    n_moved = _control_glb(GLB, ctrl_glb, CONTROL_NODE, CONTROL_SHIFT_M)
    ctrl = _gauge(_scan(ctrl_glb, order), order, z0, hs)
    fired = ctrl["score"] < THRESHOLD
    print("质检    : 真件 %.4f（%d/%d）· 假件 %s+%.0fm %.4f（%d 网格）⇒ 正对照 %s"
          % (base["score"], base["passed"], base["total"], CONTROL_NODE, CONTROL_SHIFT_M,
             ctrl["score"], n_moved, "FIRED" if fired else "★ 没响"))

    ctrl_ev = {
        "schema": "cdut3d-positive-control/1",
        "gauge": "逐层节点 ε 校验（节点在 + 底标高 + 主体顶标高 + 无游离网格）",
        "threshold": THRESHOLD,
        "baseline": {"score": round(base["score"], 6), "passed": base["passed"],
                     "total": base["total"], "glb": GLB, "sha256": _sha(GLB)},
        "perturbation": {"kind": "整层平移", "node": CONTROL_NODE,
                         "shift_m": CONTROL_SHIFT_M, "meshes_moved": n_moved,
                         "glb": ctrl_glb, "sha256": _sha(ctrl_glb)},
        "control": {"score": round(ctrl["score"], 6), "passed": ctrl["passed"],
                    "total": ctrl["total"], "fails": ctrl["fails"]},
        "fired": fired,
        "note": "假件由本脚本从真件现造（不改真件）；两件走**同一段** _gauge 代码。"
                "假件只抬起一层 ⇒ 节点数不变，考的是标高量具本身。",
    }
    _dump_bytes(os.path.join(GEN, "c005-qc-control.json"), ctrl_ev)

    chain_ev = {
        "schema": "cdut3d-chain-evidence/1",
        "building_id": BUILDING,
        "contours": [{"floor": r["floor"], "z0_m": r["z0_m"], "h_m": r["h_m"],
                      "polys": r["polys"], "per_layer": r["per_layer"], "ok": r["ok"]}
                     for r in ci],
        "build_json": {"storey_m": bj["storey_m"], "basement_m": bj["basement_m"],
                       "top_m": bj["top_m"], "z_max_m": bj["z_max_m"],
                       "z_max_main_m": bj.get("z_max_main_m"),
                       "n_floors": bj["building"]["n_floors"]},
        "floor_h_sources": src_h,
    }
    _dump_bytes(os.path.join(GEN, "c005-chain.json"), chain_ev)

    top = layers[-1]
    tf = {"主屋面_m": _top_main(top),
          "女儿墙顶_m": top["class_hi"].get("PARAPET"),
          # ★ 2026-10-19：类名 `ROOF_STAIR` 已并入 `ROOF_ROOM`（export_contours.py:207）。
          "顶楼楼梯房顶_m": top["class_hi"].get("ROOF_ROOM"),
          "note": "全部由落盘件的 (层,类) 子节点包围盒现算，不手打；缺项写 null（不写 0）。"}

    # ── ③b 逐层房间面片（房间色块 / 平面图用）───────────────────────────────
    plans, plan_stat = _floor_plans(float(bj["storey_m"]))
    for st in plan_stat:
        print("房间面片 %-4s 分区 %2d ⇒ 房 %2d（上色）· 交通 %2d（不上色）· 屋面 %d%s"
              % (st["floor"], st["regions"], st["rooms"], st["circ"], st["roof"],
                 ("（屋面读数 %s）" % st["rdiag"]) if st["rdiag"] else ""))

    # ── ④ 元数据 ─────────────────────────────────────────────────────────
    lay = {
        "schema": "cdut3d-layering/1",
        "building_id": BUILDING,
        "method": "整栋 = **本仓重建链的正式件**（%s 出的 %s）原样搬入；"
                  "层节点 floorK ↔ 第 K+1 层（0 基）。本包不建几何、不做坐标搬运。"
                  % ("FreeCAD 1.1" if SRC_KIND == "fc" else "SketchUp", GLB_NAME),
        "source_model": "rebuild/c005/06_su/" + GLB_NAME,
        "source_note": ("链：源 DXF → 切图幅(5 张) → 识别 → build3d → FreeCAD → "
                        "fc_obj_to_glb.py（只转格式、不动顶点；自带 polys_in == polys_out 断言）。"
                        "同一份 contours 连跑两趟输出逐字节相同。"
                        if SRC_KIND == "fc" else
                        "链：源 DXF → 切图幅(5 张) → 识别 → build3d → SketchUp → "
                        "su_obj_to_glb.py（只转格式、不动顶点；自带 polys_in == polys_out 断言）。"),
        "up_axis": "y",
        "n_floors": len(order),
        "floor_h_m": floor_h,
        "floor_h_spread_m": spread,
        "floor_h_note": "**件侧现算**：相邻层节点 lo_m 之差的中位（%d 个带）。三个独立读数："
                        "件侧 %s m / contours %s m / 参数表 %s m ⇒ %s。"
                        % (len(bands), floor_h, sorted({r["h_m"] for r in ci}),
                           bj["storey_m"], "一致" if agree else "**不一致，已打印**"),
        "elevation_m": [z_bot, z_top],
        "layers": layers,
        "lossless_check": {"faces_sum": faces_total, "faces_all_in_glb": scan["faces_all"],
                           "unmatched_meshes": scan["unmatched"],
                           "note": "面数直接从落盘件逐 (层,类) 取、再相加；"
                                   "unmatched_meshes 为空才说明**没有几何落在层节点之外**。"
                                   "上游转格式那一步（su_obj_to_glb / fc_obj_to_glb）"
                                   "另有一条 polys_in == polys_out 断言。"},
        "top_features": tf,
        "blind_spots": [
            "层高 4.0 m 与女儿墙高是**口径决定**：源图（AC1032 DXF）没有任何标高/尺寸标注可证。",
            "柱只在首层（源图首层 8 个、2~5 层 0 个；用户裁定照图，不复制、不猜）。",
            "门只开洞、不建门扇：158 个多段线符号（86 个 16 点单门 + 72 个 23 点双门）"
            "全按门处理；源图 0 个窗图元，故没有「门窗混淆」，但这条归类本身是规则。",
            "baseline/floors/*.json 的 `rooms`/`circulation` 来自 `redraw.geometry` 的"
            "「楼板 − 墙带」分区 + 房间号落点（**与建件同一份几何**）；`walls`/`doors` 两键"
            "**留空**（逐条墙写进包要多一份 `wall_polys` 导出，本版没做 —— 空数组 = 没做，"
            "不是「量到 0」）。旧包那 5 份是 gym3d 口径（4.2 m 层高、合成 531 扇窗），已不复用。",
            "面数守恒只证「逐层相加 = 落盘件」，**不证**几何对 —— 那是 gates/ 的活。",
        ],
    }
    prof = {"schema": "cdut3d-profile/1", "building_id": BUILDING, "title": "理化楼",
            "note": "显示名取此处；层高/层数一律以 meta/layering.json 为准"
                    "（本文件不写层高，免得出现两套数）。"}
    ledger, ledger_src = _rooms_ledger()
    print("房间台账: %d 行（%s）"
          % (len(ledger), "/".join(str(p["n_rows"]) for p in ledger_src["per_sheet"])))

    qc = {
        "schema": modelpack.QC_SCHEMA,
        "building_id": BUILDING,
        "level": "PASS" if (base["score"] >= 0.999 and fired) else "WARN",
        "gauge": {
            "name": "逐层节点 ε 校验（节点存在 + 底标高 + 主体顶标高 + 无游离网格 的通过率）",
            "value": round(base["score"], 4), "threshold": THRESHOLD, "unit": "通过率（比值）",
            "scope": "%d 个层节点 × 3 条 + 1 条游离网格检查 = %d 条；标高容差 %.2f m。"
                     "真值 = contours/index.json 的 z0/h（SU 建的就是这批轮廓）"
                     % (len(order), base["total"], TOL_M),
        },
        "positive_control": {
            "fired": fired,
            "perturbation": "%s（2 层）整层抬起 %.1f m —— 由本脚本从真件现造（%d 个网格），"
                            "节点数不变，专考标高量具" % (CONTROL_NODE, CONTROL_SHIFT_M, n_moved),
            "value": round(ctrl["score"], 4),
            "expect": "必须显著低于阈值 %.2f（否则这把尺子对层标高缺陷无分辨力）" % THRESHOLD,
            "evidence": "同一段 _gauge 代码实测：真件 %.4f → 假件 %.4f；假件失败的条目：%s。"
                        "原始记录 evidence/c005-qc-control.json（含两件 sha256，假件可复现）"
                        % (base["score"], ctrl["score"],
                           "、".join(c["id"] for c in ctrl["fails"]) or "（无）"),
        },
        # ★ 2026-10-17 这条已**消解**：`podium_roof` 置 true，顶层按房间名命中分区切出
        #   裙房屋面（板 + 女儿墙），件上闭合。留着旧条目就是让包说谎 —— 删掉。
        "known_defects": [],
        "blind_spots": [
            "本条只量**逐层节点的存在与标高**；对门/窗/柱/梯的**个数与位置**不置一词。",
            "已知缺陷表只列**可追到盘上**的一条（裙房屋面板）；建件链自身的偏差由 gates/ 量。",
            "level 只据本条尺子与正对照给：两者都过 = PASS；不代表外部质检通过。",
        ],
        "level_basis": "PASS 的条件 = 逐层 ε 校验满分（%d/%d）且正对照 fired；否则 WARN。"
                       % (base["passed"], base["total"]),
    }

    lod = {
        "schema": "cdut3d-lod/1",
        "standard": {
            "name": "实景三维中国建设城市三维模型（LOD1.3 级）快速构建技术规定（试行）",
            "id": "新型基础测绘与实景三维中国建设技术文件—12",
            "issued": "2023-09",
            "tier": "国家级技术文件（正本 67 页，已逐条核对）",
        },
        "level": ">=LOD1.3",
        "relation": "本包是**构件级白模**（墙 / 柱 / 梯 / 楼板逐层分件，共 %d 个层节点），"
                    "精细度高于该规定的 LOD1.3（棱柱体体块）⇒ 声明为正本等级串里没有的、"
                    "**不低于** LOD1.3 的精细度；**不**自称 LOD2/LOD3（其定义不在本规定内）。"
                    % len(order),
        "satisfies": {
            "基底面凹凸": "正本：普通建筑物基底面 ≥1.5 m 凹凸变化应正确表示。"
                          "本包墙线按 DXF 实际墙厚（240 mm）建 ⇒ 分辨力在墙厚级，远细于 1.5 m。",
            "顶部高差": "正本：顶部高差 >3 m 且变化部分基底面积 >12 m² 的高度变化应正确表示。"
                        "本包按**落盘件实测**：主屋面 %s m、女儿墙顶 %s m、顶楼楼梯房顶 %s m"
                        "（数取自件本身的 (层,类) 包围盒，不手打）。"
                        % (tf["主屋面_m"], tf["女儿墙顶_m"], tf["顶楼楼梯房顶_m"]),
        },
        "citations": {
            "external": "CH/T 9024-2014《三维地理信息模型数据产品质量检查与验收》（正本引用文件）",
            "national_check": "GB/T 18316-2008《数字测绘成果质量检查与验收》（正本参考文献 [4]）",
            "lineage": "CH/T 9009.1-2013《基础地理信息数字成果 数字线划图 第 1 部分》"
                       "—— 对上本包的 DXF 图纸来源",
            "process": "两级检查（各 100%）+ 一级验收 + 成果核验（正本第六章）。"
                       "本包现处**自检层**，未走外部质检 ⇒ 不声明「已验收」。",
        },
        "not_applicable": [
            "平面/高程精度表：卫星立体影像测图口径，本包源自图纸 DXF ⇒ 不套用。",
            "数据格式表（OBJ/JPG/SHP/XLS）与元数据 XLS：城市级汇交口径，本包是两平台接缝的中间件。",
        ],
        "blind_spots": [
            "LOD2 / LOD3 的定义**不在**本规定内 ⇒ 本包不评价自己是否达到那两级。",
            "本规定面向城市级棱柱体快速构建；本包是单体构件级，两者的精度表/格式表不可互评。",
        ],
    }

    # ── ⑤ 先写暂存件，再打包（★ 绝不把文件写进 PACK 再让 build 从 PACK 拷回 PACK）──
    os.makedirs(STAGE, exist_ok=True)
    _dump_bytes(os.path.join(STAGE, "profile.json"), prof)
    _dump_bytes(os.path.join(STAGE, "rooms.json"), ledger)
    _dump_bytes(os.path.join(STAGE, "rooms-source.json"), ledger_src)
    _dump_bytes(os.path.join(GEN, "c005-layering.json"), lay)
    for k, doc in enumerate(plans):                 # 房间色块 / 平面图的数据源
        _dump_bytes(os.path.join(STAGE, "baseline", "floors", "floor%d.json" % k), doc)

    arts = [
        {"role": "model", "src": GLB, "rel": "model/c005-building.glb"},
        {"role": "ledger", "src": os.path.join(STAGE, "rooms.json"), "rel": "ledger/rooms.json"},
        {"role": "meta", "src": os.path.join(STAGE, "rooms-source.json"),
         "rel": "ledger/rooms-source.json"},
        {"role": "meta", "src": os.path.join(STAGE, "profile.json"), "rel": "meta/profile.json"},
        {"role": "meta", "src": os.path.join(GEN, "c005-layering.json"),
         "rel": "meta/layering.json"},
        # 逐块清单：GLB 里每层每类只合成一个 mesh，网页点到一面墙只知道 floorK__WALL；
        # 「第几块」只有 contours 有 ⇒ 由 rebuild/tools/mk_catalog.py 现算（本趟 568 块，
        # 逐层与 contours/index.json 对账 PASS）。
        {"role": "catalog", "src": os.path.join(REB, "06_su", "c005_catalog.json"),
         "rel": "meta/blocks.json"},
        {"role": "evidence", "src": os.path.join(GEN, "c005-qc-control.json"),
         "rel": "evidence/c005-qc-control.json"},
        {"role": "evidence", "src": os.path.join(GEN, "c005-chain.json"),
         "rel": "evidence/c005-chain.json"},
    ] + [{"role": "baseline_floor",
          "src": os.path.join(STAGE, "baseline", "floors", "floor%d.json" % k),
          "rel": "baseline/floors/floor%d.json" % k} for k in range(len(plans))]

    # ★ 覆盖交付件前先留档（用户令「覆盖交付件前先留档」）。旧包 = gym3d 单网格那版，
    #   其 baseline/floors 与 layering 是 **4.2 m / 合成窗** 的口径，与新件不同源。
    if os.path.isdir(PACK):
        dst = ARCHIVE
        if os.path.isdir(dst):
            # ★ 2026-10-17：第一档的名字带 `gym3d`（那是**旧链那一版**的专名）。后来再归档的
            #   已经是新的链产物，再叫 gym3d 就是**名不副实**（会让人以为件还是老口径）。
            dst = os.path.join(CDUT, "_archive",
                               "pack-c005-" + time.strftime("%Y%m%d-%H%M%S"))
        shutil.move(PACK, dst)
        n_old = sum(len(fs) for _dp, _dn, fs in os.walk(dst))
        old_bytes = sum(os.path.getsize(os.path.join(dp, fn))
                        for dp, _dn, fs in os.walk(dst) for fn in fs)
        print("归档旧包: %s（%d 件 / %.1f MB）—— 不复用其中任何一件"
              % (dst, n_old, old_bytes / 1e6))

    off = time.strftime("%z")
    if len(off) == 5:
        off = off[:3] + ":" + off[3:]
    created_at = time.strftime("%Y-%m-%dT%H:%M:%S") + off
    modelpack.build(BUILDING, PACK, arts, qc, campus_id=CAMPUS, created_at=created_at, lod=lod)

    man = _read(os.path.join(PACK, "manifest.json"))
    empty = [a["path"] for a in man["artifacts"] if not a.get("bytes")]
    if empty:
        print("★ 有 0 字节的件（同路径拷贝？）：%s" % empty)
        return 1
    v = modelpack.validate(PACK)
    print("validate: ok=%s counts=%s" % (v["ok"], v.get("counts")))
    if not v["ok"]:
        for r in v["reasons"]:
            print("   ✗", r)
        return 1
    print("包指纹  : %s…" % man["package_sha256"][:24])
    print("包大小  : %.1f MB / %d 件"
          % (sum(a["bytes"] for a in man["artifacts"]) / 1e6, len(man["artifacts"])))

    import build_index                                              # noqa: E402
    build_index.refresh()
    return 0


if __name__ == "__main__":
    sys.exit(main())
