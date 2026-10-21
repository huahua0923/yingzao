# -*- coding: utf-8 -*-
r"""把**任意一栋**按 cdut3d 链现做的产物打成模型包 `packs/cdut-main/<楼号>/`。

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

用法：CDUT_BUILDING=c001 python -I demo/build_pack_bid.py <楼号>
（楼号缺省取 CDUT_BUILDING；数据根 = rebuild/<楼号>）
退出码：0 成功 · 1 判据不过 · 4 缺件（SU 出的 GLB 还没生成）
"""
import hashlib
import json
import os
import re
import shutil
import sys
import time

sys.stdout.reconfigure(encoding="utf-8")

CDUT = r"D:\项目\cdut3d"
BUILDING = (sys.argv[1] if len(sys.argv) > 1 else os.environ.get("CDUT_BUILDING") or "").strip().lower()
if not BUILDING:
    raise SystemExit("★ 要给楼号：CDUT_BUILDING=c001 python -I demo/build_pack_bid.py c001")
# ★★ 2026-10-17 C105：楼号必须在**任何 import 之前**写进环境。
#   `building.BID` 是模块导入时读一次的环境变量；后面各函数里的
#   `os.environ.setdefault(...)` 已经晚了 —— 谁先 `import building`（实测 `_params()`），
#   谁就把 BID 钉成默认的 c006 ⇒ `build3d.FLOORS` 变成 c006 的 11 层 + 「地下1层」，
#   症状是打包时报「缺 raw\地下1层.dxf」（层名对不上，而不像「楼号错了」）。
os.environ["CDUT_BUILDING"] = BUILDING
sys.path.insert(0, os.path.join(CDUT, "rebuild", "tools"))
import building as _B                                              # noqa: E402
# ★★ 2026-10-18（用户「地下一楼也没有出来」）：数据根**只认** `building.root_for()`。
#   这里原来是 `rebuild/<楼号>`，而 c006 的件在 `rebuild/` 根下 ⇒ 装包器找
#   `rebuild/c006/06_su/c006_fc.glb`（不存在）当场 rc=4 ⇒ **c006 从没进过共用装包器**，
#   包一直是旧版 `demo/build_pack.py` 打的（11 份基线、无 B1）⇒ 地下一层零色块。
REB = _B.root_for(BUILDING)
os.environ["CDUT_REBUILD_ROOT"] = REB
# ★ 2026-10-17 换链（用户令「现在开工换 FreeCAD」）：建件机由 SketchUp 换成 FreeCAD，
#   目的是可复现（同一份 contours 连跑两趟，OBJ 逐字节相同）。
#   两条件逐 (层,类) 比过：c005 **25/25 件**、包围盒偏差 **0.000 m**。
#   SU 件留作退路，但**不静默回退**：要它得显式 `CDUT_PACK_SRC=su`。
SRC_KIND = (os.environ.get("CDUT_PACK_SRC") or "fc").lower()
GLB_NAME = "%s_fc.glb" % BUILDING if SRC_KIND == "fc" else "%s_su.glb" % BUILDING
GLB = os.path.join(REB, "06_su", GLB_NAME)
BUILD_JSON = os.path.join(REB, "05_build", "build.json")
CONT_INDEX = os.path.join(REB, "06_su", "contours", "index.json")
RAW = os.path.join(REB, "01_cad", "raw")

CAMPUS = "cdut-main"
PACK = os.path.join(CDUT, "packs", CAMPUS, BUILDING)
GEN = os.path.join(CDUT, "demo", "_gen")
STAGE = os.path.join(GEN, BUILDING + "-stage")
ARCHIVE = os.path.join(CDUT, "_archive", "pack-%s-gym3d-20261017" % BUILDING)

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


def _title():
    """楼栋显示名：档案 title（唯一来源），没写就用楼号。"""
    sys.path.insert(0, os.path.join(CDUT, "rebuild", "tools"))
    import building as B                                            # noqa: E402
    return B.profile(BUILDING).get("title") or BUILDING


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
                           # ★ 2026-10-20：这里原来写 `h`（未定义）—— 只在「缺节点/0 面」
                           #   这条缺陷分支里执行 ⇒ 尺子**正好在它要报红的时候崩掉**（铁律 199：
                           #   崩溃与「没量到」不许同形）。层高按 `hs[k]`，与上面 docstring 一致。
                           "want": round(z0[k] + hs[k], 3), "got": None})
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


def _rooms_ledger(plans=None):
    """从切图后的每一张图幅现取房间台账（`a1/rooms.py::load_rooms`）。

    ★ 2026-10-17：楼层名单从建件读（`build3d.FLOORS`），不再写死 `range(5)` + `"%d层"`。
      这样 C001 的 D1 层与别的楼的 3/6/11 层都自动跟着走。

    ★ 2026-10-17 改落盘形状：**列表**（与 c006 同款），不再包一层 dict。
      原版写 `{schema, n_rows, per_sheet, rows}`，而 `demo/building.html:721` 判的是
      `Array.isArray(d)` —— dict 落进 else 分支，屏上印「**台账是空的：0 行 —— 真没有**」，
      而件里明明有 118 行（**假否定**，铁律 158）。字段名也照 c006 映射：阅读器按
      `r.number` 取节点、`r.dept` 补使用单位（`demo/index.html:765`），用原名取不到。
    ★ **没有 centroid/boundary**：源件只有文字属性，没有房间多边形 ⇒ 房间色块铺不了；
      这不是「配准失败」，是**来源里没有面**。
    """
    import rooms as roomlib                                         # noqa: E402
    import build3d as B3                                            # noqa: E402
    rows, per = [], []
    for k, (sheet, _z, _h) in enumerate(B3.FLOORS):
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
    src_note = "rebuild/%s/01_cad/raw/<层>.dxf（切图后的逐层图幅，非原始整图）" % BUILDING
    if not rows and plans:
        # ★★ 2026-10-20 c015：源图**没有房间号层** ⇒ 上面 `load_rooms` 0 行（不是读不到，
        #   是图上没编号）。而本包的 baseline 分区里**有房间**（用途字落点）。
        #   台账若照样落 0 行，`demo/building.html` 的楼层条就只剩「全部」、
        #   房间面板写「真没有」—— 与「这栋楼没有房间」同形（铁律 199）。
        #   ⇒ 改由同一趟的 `plans` 生成：number=null（不编房号），purpose/面积取实测。
        per = []                       # 上面那三份全是 0 行（房号层不存在），留着会印成「三次都没量到」
        for k, doc in enumerate(plans):
            _sheet = B3.FLOORS[k][0] if k < len(B3.FLOORS) else ("floor%d" % k)
            n0 = len(rows)
            for r in (doc.get("rooms") or []):
                rows.append({
                    "id": len(rows) + 1,
                    "building": BUILDING,
                    "floor": k,
                    "number": r.get("number"),
                    "name": None,
                    "area": (str(r["stated_m2"]) if r.get("stated_m2") is not None else None),
                    "area_m2": r.get("stated_m2") if r.get("stated_m2") is not None else r.get("area_m2"),
                    "purpose": r.get("purpose"),
                    "dept": r.get("dept"),
                    "sheet": _sheet,
                    "src_dist_mm": None,
                })
            per.append({"sheet": _sheet, "level": k, "n_rows": len(rows) - n0,
                        "stats": {"来源": "baseline 分区 + 用途字（源图无房间号层）"}})
        src_note += ("；★ 源图**没有房间号层**（keep_layers 里无 6房间号）⇒ 本台账由 "
                     "baseline/floors 的分区 + 8房间用途 字现生成：number 一律 null（不编房号），"
                     "area_m2 取图上标注面积，purpose 取图上原文")
    src = {"schema": "cdut3d-roomledger/1", "building_id": BUILDING,
           "source": src_note,
           "tol_mm": 1500.0, "n_rows": len(rows), "per_sheet": per,
           "blind_spot": "本台账只有文字属性（房间号/面积/用途/使用单位）；房间**面片**在 "
                         "baseline/floors/floor<k>.json 的 rooms（来自 redraw 分区），两份不合并。"}
    return rows, src


# ★ 2026-10-18（用户令「你逐步的参数化，这样修改起来快一些，也可以快速定位」）：
#   下面这五个数**全部走楼栋档案** `rebuild/构件库/楼栋.json` 的 `pack` 段；
#   默认值 = 原来写死的值 ⇒ 不写 `pack` 的楼栋行为一字不变。调某一栋只改那一栋。
_PK = _B.profile().get("pack", {})
MIN_REGION_M2 = float(_PK.get("min_region_m2", 1.0))   # 分区下限（m²）：再小的是井道/柱缝，不是房间
SEAL_MM = float(_PK.get("seal_mm", 250.0))             # 门洞封口带宽（mm）：只补墙带附近的缺口，不拿门扇去改房间面积
# 文字落点半径：字锚点落在分区外这么近仍算这一间。
# ★ 2026-10-17 C105：50 mm 时有 4 条（1层 1、3层 2、5层 1）房间号的字心**压在墙上**，
#   离最近分区 62.6~86.0 mm ⇒ 恰好被 50 判成落空。实测这 4 条都是贴着薄墙标注的房间，
#   提到 100 mm 全部落进（其余读数不变：0 落空、0 一区多字）。
LABEL_HIT_R_MM = float(_PK.get("label_hit_r_mm", 100.0))
# 「贴墙标注」再落一次的上限：C105 那批实测 62.6~86.0 mm 已由 `LABEL_HIT_R_MM` 100 覆盖；
# C103 的 4 条离最近分区 **5381 mm** —— 那不是贴墙，是**楼板内一大片没有墙围合的区域**
# （或标注画在了别处），不许当成「落回该分区」，5 米外的房间和 5 米外的墙一样是猜的。
SNAP_MAX_MM = float(_PK.get("snap_max_mm", 500.0))
ROOF_OWN_SHARE = float(_PK.get("roof_own_share", 0.5))   # 一个分区有这么大比例落在裙房屋面区里 ⇒ 它是屋面，不是交通
# ★ 2026-10-20：源图**整层没有房间号**时，许可用「用途」字当房间的身份（c015 实测）。
#   默认开；某栋若用途字连走廊都写，就在档案 `pack.room_from_use` 里关掉。
ROOM_FROM_USE = bool(_PK.get("room_from_use", True))
# 房间面片比图上面积大出「健康肩上沿」时，先做一次**闭运算找隔断**（见 `_leak_split`）。
# 阈值只认 `参数.json::房间面积_黄`（由 calibrate_room_area.py 现算）；取不到就**不做**，
# 不拿一个自拟的兜底数往下切（铁律 018/174）。
SPLIT_SEALS_MM = (300.0, 450.0, 600.0, 800.0)


def _ratio_mid():
    try:
        with open(os.path.join(CDUT, "rebuild", "构件库", "参数.json"), encoding="utf-8") as fh:
            v = (json.load(fh).get("缺陷扫描") or {}).get("房间面积_黄")
        return float(v) if isinstance(v, (int, float)) else None
    except Exception:                                                    # noqa: BLE001
        return None


def _leak_split(g, stated_m2, pt, mid):
    """一片「房间+过道」连在一起的分区 → 只留下**房间那一块**（其余回交通）。

    为什么这么切（2026-10-20 c085 香樟园5号公寓 2 层实测）：
      图上 9.9 m² 的杂物间，同一位置 2 层以上**少画了 900 mm 墙**（与 1 层差 2 条墙段，
      实测 diff），于是「楼板 − 墙带」把房间与走廊并成一片 153.9 m² 的连通区，
      房号落进去 ⇒ 模型把整条过道画成杂物间（用户：「这个杂物间有 100 多平方」）。
      这不是识别错，是**图上那个缺口**；但把 153.9 m² 当一间房是错的。
    做法：对该片做闭运算（先腐蚀 seal、再膨胀回来），缺口小于 2×seal 的地方被掐断；
      取**离房号最近**的一块，面积落在 [0.5, mid]×图上面积就认它，其余部分返回给交通。
      seal 从小到大试，第一个切出合理房间的赢 —— 不猜、不硬切。
    返回 (房间片, [剩余块...]) 或 None（切不出来就如实不切，交给 D-24 报红）。
    """
    for seal in SPLIT_SEALS_MM:
        er = g.buffer(-seal)
        if er.is_empty:
            return None
        parts = list(er.geoms) if hasattr(er, "geoms") else [er]
        if len(parts) < 2:
            continue
        cands = sorted((p.buffer(seal).intersection(g) for p in parts),
                       key=lambda z: z.distance(pt))
        for c in cands:
            a = c.area / 1e6
            if 0.5 * stated_m2 <= a <= mid * stated_m2:
                rest = g.difference(c)
                rest_parts = list(rest.geoms) if hasattr(rest, "geoms") else [rest]
                return c, [q for q in rest_parts if q.area > 1e6]
    return None
# 用途字里出现这些词 ⇒ 它是交通空间，不上色（只在「无房号」分支里用）。
CIRC_WORD = re.compile(r"走廊|过道|门厅|楼梯|梯间|梯井|电梯|前室|通道|连廊|门斗|卫生间|厕所|盥洗")


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
    from shapely.geometry import Point, Polygon, box                # noqa: E402
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
        # ★ 2026-10-17 C001 实测：有的楼把墙线在**门口断开**（c006/c005 都不断），
        #   门洞在分区上就是真缺口 —— 直接 difference 会让房间顺门口流进走廊，
        #   两个相距 28 m 的 21 m² 办公室并成一块 608 m²（判词「一个分区塞了多间房」）。
        #   门洞是**墙上的开口**，不是「没有墙」：分区时按门洞矩形补回缺口
        #   （只取落在墙带 SEAL_MM 邻域里的那一条，不拿门扇/开启弧去改房间面积）。
        _voids = [g for g in (_poly(r) for r in (v.get("door_voids") or [])) if g is not None]
        if _voids and not walls.is_empty:
            # ★★ 2026-10-17 C105 实测：`walls.buffer(SEAL_MM)` 必须**先算一次**。
            #   原来写在列表推导里 ⇒ 每扇门重算一遍墙带缓冲（1 层 109528 个顶点，
            #   一次 17.5 s × 146 樘 ≈ 42 min）。这不是「慢一点」，是一层要跑三刻钟。
            _wbuf = walls.buffer(SEAL_MM)
            _seal = unary_union([g.intersection(_wbuf) for g in _voids])
            if not _seal.is_empty:
                walls = unary_union([walls, _seal])
        # ★★ 2026-10-18（用户「色块就是不对」「后面其他的建筑就不能再出现这些问题」）：
        #   块画法的门**没有** `door_voids`（块里的弧两端都是「开着的位置」，没有贴墙端点）
        #   ⇒ 上面那段一次都不跑 ⇒ 一排房间顺着门洞连成一片（c006 1 层：33 个房间号
        #   挤进 4 个连通区 14/14/4/1，一层只出 4 片房垫）。补条由 `redraw.block_door_plugs`
        #   现算（门块的两根开启弧圆心 = 门洞两端，单弧块按插入点对称补另一半），
        #   这里只负责并进墙带 —— 判据在 redraw，别在这里再写一份。
        _plugs = [box(*r) for r in (v.get("door_plugs") or [])]
        if _plugs:
            walls = unary_union([walls] + _plugs)
            print("  ▷ %s 门洞补条 %d 根（块画法）并入墙带" % (name, len(_plugs)))
        # ★★ 2026-10-17 C103 实测：`difference()` 回来的**已经是有效几何**，再套一个
        #   `.buffer(0)` 会**静默删掉 380.6 m²、86 块**（C103 1 层：6664.7 → 6284.1 m²），
        #   被删的那块里正压着 103-B-01-07/09/11/13 四个房间号 ⇒ 症状是
        #   「字落在楼板内、却离最近分区 5381 mm」，而字心周边 2 m 内墙带 0%、楼板 100%
        #   —— 判词指向「标注画错」，实际是量具把房间删了。
        #   buffer(0) 只在**无效**时才用（修自交），有效几何一律原样取块。
        _cut = plate.difference(walls)
        if not _cut.is_valid:
            _cut = _cut.buffer(0)
        # 单块时 `geoms` 不存在（Polygon 没有这个属性）—— 原来 `getattr(..., [])` 会
        # 把它当成「零个分区」直接判红；这里显式取一块。
        regs = [g for g in (list(_cut.geoms) if hasattr(_cut, "geoms") else [_cut])
                if g.area > MIN_REGION_M2 * 1e6]
        if not regs:
            raise SystemExit("★ %s 一个分区都没有（楼板 %.1f m² / 墙带 %.1f m²）⇒ 不许静默出空表"
                             % (name, plate.area / 1e6, walls.area / 1e6))
        # ★★ 2026-10-20：档案判成**屋面平面**的层（c006「7层」）—— 塔楼以外是屋面，不是房间/交通。
        #   与 `build3d.roof_plan_split` 同一个塔楼足迹（下一层楼板并集），不另算一份。
        _rp = (B3.B.profile().get("roof_plans") or {}).get(name)
        if _rp and _rp.get("塔楼层"):
            _tv = RD.geometry(_rp["塔楼层"])
            _tower = unary_union([g for g in (_poly(s) for s in _tv["plate"]) if g is not None])
            _keep = [g for g in regs if g.intersection(_tower).area > 0.5 * g.area]
            if not _keep:
                raise SystemExit("★ %s 是屋面平面层，但按 %s 的楼板切完一个塔内分区都不剩"
                                 "（塔楼足迹 %s）" % (name, _rp["塔楼层"],
                                                      [round(x / 1000.0, 1) for x in _tower.bounds]))
            print("  ▷ %s 屋面平面：分区 %d ⇒ 塔内 %d（塔外 %d 块判为屋面，不上色）"
                  % (name, len(regs), len(_keep), len(regs) - len(_keep)))
            regs = _keep
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
        by_pos = {}
        orphan = {}
        for kind, items in txts.items():
            m, mp = {}, {}
            for it in items:
                b = Point(it["xy"]).buffer(LABEL_HIT_R_MM)
                hit = [i for i, g in enumerate(regs) if g.intersects(b)]
                if not hit:
                    orphan.setdefault(kind, []).append({"文": it["文"], "xy": it["xy"], "it": it})
                    continue
                best = max(hit, key=lambda i: regs[i].intersection(b).area)
                m.setdefault(best, []).append(it["文"])
                mp.setdefault(best, []).append(it["xy"])
            by_kind[kind] = m
            by_pos[kind] = mp
        # ★ 2026-10-17 C105 D1：**字落在楼板外**与**字压在墙/缝隙里**是两件事，不许同形（铁律 199）。
        #   · 楼板外：源图把房间号标注画在走廊/开敞环带上（D1 实测 10/14 条距楼板 6~11 m，
        #     图上该层是「柱 + 少量墙」的大开敞书库）——台账照样保留文字行，只是这一间没有面片；
        #   · 楼板内却落不进任何分区：字压在墙带或 <1 m² 的缝里 ⇒ 几何变了，仍然判红。
        _o_room = orphan.get("房间号") or []
        _outside = [o for o in _o_room if not plate.contains(Point(o["xy"]))]
        _hard = [o for o in _o_room if plate.contains(Point(o["xy"]))]
        if _outside:
            print("▷ %s 有 %d 条房间号落在墙围合楼板之外（源图开敞/标注画在走廊侧）"
                  "⇒ 台账保留、面片无这一间：%s"
                  % (name, len(_outside), [o["文"] for o in _outside]))
        if _hard:
            # ★★ 2026-10-17 C103：4 条房间号（103-B-01-07/09/11/13）压在墙带上，离最近分区
            #   超过 `LABEL_HIT_R_MM`（100 mm）⇒ 旧逻辑整栋判红。而 C105 那次已经定性：
            #   这类是「**贴着墙标注**的房间」，不是几何坏了。区别只在于**离墙多远**。
            #   ⇒ 落不进的，按**实测距离**再落一次（半径 = 到最近分区距离 + 10 mm），
            #     并把每条的距离打出来（不静默）；真正落不到的仍然判红。
            _snap, _stay = [], []
            for o in _hard:
                pt = Point(o["xy"])
                d = min(g.distance(pt) for g in regs)
                b = pt.buffer(d + 10.0)
                hit = [i for i, g in enumerate(regs) if g.intersects(b)]
                if hit and d <= SNAP_MAX_MM:
                    best = max(hit, key=lambda i: regs[i].intersection(b).area)
                    by_kind["房间号"].setdefault(best, []).append(o["it"]["文"])
                    _snap.append((o["文"], round(d, 1)))
                else:
                    _stay.append(o)
            if _snap:
                print("▷ %s 有 %d 条房间号字心压在墙带上（离最近分区 %s mm）"
                      "⇒ 按实测距离落回该分区" % (name, len(_snap), [d for _t, d in _snap]))
            _hard = _stay
        if _hard:
            raise SystemExit("★ %s 有 %d 条房间号字心落在楼板内、却落不进任何分区"
                             "（压在墙带或 <%.0f m² 的缝里）：%s"
                             % (name, len(_hard), MIN_REGION_M2,
                                [o["文"] for o in _hard][:5]))
        # ★ 2026-10-17 C001：开敞区（C001 4层/5层各 1 处「教师工作室」）在源图上**没有隔墙**，
        #   几个房间号落在同一分区里。这是图纸事实，不是量具瞎了 —— 判红会把「图上确实开敞」
        #   报成「墙丢了」。改法：**不丢任何一个号**，整区记一条，主号取排序第一个，
        #   其余全部收进 `numbers` 并在终端逐处报出（读数可见），面积仍是这个开敞区的实测面积。
        multi = dict((i, sorted(v_)) for i, v_ in by_kind.get("房间号", {}).items() if len(v_) > 1)
        for i, v_ in multi.items():
            print("▷ %s 分区#%d 有 %d 个房间号共用一个无墙开敞区（源图未画隔墙）：%s"
                  % (name, i, len(v_), v_))

        rooms, circ, roof_n = [], [], 0
        _mid = _ratio_mid()
        _nsplit = 0
        for i, g in enumerate(regs):
            if roof_zone is not None and g.intersection(roof_zone).area > ROOF_OWN_SHARE * g.area:
                roof_n += 1
                continue
            nums = sorted(by_kind.get("房间号", {}).get(i) or [])
            num = nums[0] if nums else None
            _st0 = next((x for x in (BR.parse_area(t) for t in by_kind.get("面积", {}).get(i, [])) if x), None)
            # ★ 一区一号却远大于图上面积 ⇒ 先试着把房间从过道里掐出来（见 `_leak_split`）。
            #   多字区（开敞区）不切：分母不可靠，切了等于编。
            if _mid and num and len(nums) == 1 and _st0 and g.area / 1e6 > _mid * _st0:
                _pt = Point(by_pos.get("房间号", {}).get(i, [(None, None)])[0])
                _sp = _leak_split(g, _st0, _pt, _mid)
                if _sp is not None:
                    g, _rest = _sp
                    _nsplit += 1
                    for q in _rest:
                        circ.append({"poly": _ring(q), "area_m2": round(q.area / 1e6, 2),
                                     "src": "分区剩余（房间与过道在图上没隔开，按闭运算分出房间后回交通）"})
                    print("  ▷ %s 分区#%d 面积远大于图上 %s m² ⇒ 闭运算分出房间 %.1f m²，其余 %d 块回交通"
                          % (name, i, _st0, g.area / 1e6, len(_rest)))
            rec = {"poly": _ring(g), "area_m2": round(g.area / 1e6, 2)}
            if list(g.interiors):
                rec["holes"] = [[[round(x / 1000.0, 3), round(y / 1000.0, 3)] for x, y in r.coords]
                                for r in g.interiors]
            if not num:
                # ★★ 2026-10-20 c015 芙蓉综合楼（用户「看不到每层的」）：源图上**没有房间号层**
                #   （`keep_layers` = 5面积 / 8房间用途，没有 6房间号）⇒ 三层 143 个分区全落这里，
                #   屏上 0 块房垫、台账 0 行。「**图上没编号**」不等于「不是房间」（铁律 158：
                #   量具只认房号，就是对着用途字全盲）。
                #   ⇒ 本层一条房号都没有、而该分区有用途字、且用途不是交通空间的词 ⇒ 按一间出：
                #     `number=None`（不编房号）、`purpose` 取图上原文、`sid` 用「层+分区序号」。
                #   有房号的楼一字不改（本分支只在**整层 0 条房号**时走）。
                _use = ((by_kind.get("用途", {}).get(i) or [""])[0] or "").strip()
                # ★ `plain()` 只剥「\\字母…;」形的格式码，`\\P`（MTEXT 段落符，无分号）
                #   会原样留下（c015 实测「一卡通\\P充值大厅」）。屏上按**人读的字**写。
                _use = re.sub(r"\\[Pp]", " ", _use).strip()
                if ROOM_FROM_USE and not by_kind.get("房间号") and _use \
                        and not CIRC_WORD.search(_use):
                    _stated = [BR.parse_area(t) for t in by_kind.get("面积", {}).get(i, [])]
                    rec.update({
                        "number": None,
                        "purpose": _use,
                        "dept": (by_kind.get("单位", {}).get(i) or [""])[0],
                        "stated_m2": next((x for x in _stated if x), None),
                        "sid": "%s:%s:room:u%02d-%03d" % (CAMPUS, BUILDING, k, i),
                        "src": "redraw 分区 + 用途字落点（源图无房间号层，不编号）",
                    })
                    rooms.append(rec)
                    continue
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
            if len(nums) > 1:
                rec["numbers"] = nums
                rec["src"] = "开敞区（源图无隔墙）：%d 个房间号共用本区；面积为本区实测" % len(nums)
            rooms.append(rec)
        outline_g = max((_poly(s) for s in v["plate"] if _poly(s) is not None),
                        key=lambda g: g.area, default=None)
        if outline_g is None:
            raise SystemExit("★ %s 楼板轮廓为空 ⇒ 帧变换无参照物" % name)
        # ★★ 2026-10-17 C105 实测：`outline` 只装**最大的那一块楼板多边形**（D1 79.7×63.2 m），
        #   而整层房间/交通面的外包是 150.2×42.2 m —— 差得离谱。查看器「无柱楼」的配准
        #   （`frameByPlanBBox`）要拿图纸侧的外包框去比模型墙面的外包框，拿这个数会**静默铺偏**。
        #   ⇒ 另写一个 `plan_bbox`：**所有楼板多边形**的并集外包（米，[x0,y0,x1,y1]）。
        #   `outline` 一字不动（2D 平面图与单网格配准仍在用它）。
        _all_pl = [p for p in (_poly(s) for s in v["plate"]) if p is not None]
        _u = unary_union(_all_pl).bounds if _all_pl else None
        plan_bbox = ([round(_u[0] / 1000.0, 3), round(_u[1] / 1000.0, 3),
                      round(_u[2] / 1000.0, 3), round(_u[3] / 1000.0, 3)] if _u else None)
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
            "plan_bbox": plan_bbox,          # 米；所有楼板的并集外包（无柱楼配准用）
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
                    "房间切出": _nsplit,
                    "orphan": orphan})
        if _nsplit:
            print("  ▷ %s 房间从过道里切回 %d 间（图上缺口 ≤2×seal，见 _leak_split）" % (name, _nsplit))
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
    # ★ 节点名映射：地下层 → `B1`，地上第 i 个 → `floor<i>`（与 fc_obj_to_glb 的命名一致）。
    #   原来按下标一律 floor0..N-1 ⇒ 有地下室的楼会多出一个 floor<N>，打包时判「缺层」。
    sys.path.insert(0, os.path.join(CDUT, "rebuild", "tools"))
    import building as _B
    _base = _B.profile(BUILDING).get("basement")
    order, _gi = [], 0
    for _r in ci:
        if _base and _r["floor"] == _base:
            order.append("B1")
        else:
            order.append("floor%d" % _gi)
            _gi += 1
    ctrl_node = CONTROL_NODE if CONTROL_NODE in order else order[-1]
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
    # ★ 2026-10-19：层高改**逐层**（c001 首层 6.0、其余 4.0）⇒ 这条对账不能再拿一个标量
    #   互相比。声明值取 `build.json::floor_h_m`（老件没这一键 ⇒ 逐层退回 storey_m），
    #   然后**按多重集**比：件侧层带（相邻层节点 lo_m 之差）== 声明的前 n−1 个，
    #   轮廓侧 h_m == 声明全表（含地下室）。任一边不同 ⇒ 「★ 不一致」，不取中位数糊过去。
    _base_h = float(bj["basement_m"] or 0.0)
    _n_above = len(ci) - (1 if _base_h > 1e-9 else 0)
    _dec_h = [float(v) for v in (bj.get("floor_h_m") or [float(bj["storey_m"])] * _n_above)]
    _dec_all = ([_base_h] if _base_h > 1e-9 else []) + _dec_h
    _got_bands = sorted(round(x, 3) for x in bands)
    _want_bands = sorted(round(x, 3) for x in _dec_all[:-1])
    _got_ci = sorted(round(float(r["h_m"]), 3) for r in ci)
    _want_ci = sorted(round(x, 3) for x in _dec_all)
    agree = (floor_h is not None and _got_bands == _want_bands and _got_ci == _want_ci)
    print("层高    : 件侧层带 %s（%d 个）· 声明 %s · 轮廓 %s ⇒ %s"
          % (_got_bands, len(bands), _want_ci, _got_ci,
             "一致" if agree else "★ 不一致"))
    z_bot, z_top = min(los), max(l["hi_m"] for l in layers)
    print("标高    : %.3f .. %.3f m（build.json: %.3f .. %.3f）"
          % (z_bot, z_top, -abs(float(bj["basement_m"])), float(bj["z_max_m"])))

    # ── ③ 质检：同一把尺子量真件 + 扰动假件 ──────────────────────────────
    base = _gauge(scan, order, z0, hs)
    ctrl_glb = os.path.join(GEN, "%s_ctrl_%s_plus%.0fm.glb" % (BUILDING, ctrl_node, CONTROL_SHIFT_M))
    n_moved = _control_glb(GLB, ctrl_glb, ctrl_node, CONTROL_SHIFT_M)
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
        "perturbation": {"kind": "整层平移", "node": ctrl_node,
                         "shift_m": CONTROL_SHIFT_M, "meshes_moved": n_moved,
                         "glb": ctrl_glb, "sha256": _sha(ctrl_glb)},
        "control": {"score": round(ctrl["score"], 6), "passed": ctrl["passed"],
                    "total": ctrl["total"], "fails": ctrl["fails"]},
        "fired": fired,
        "note": "假件由本脚本从真件现造（不改真件）；两件走**同一段** _gauge 代码。"
                "假件只抬起一层 ⇒ 节点数不变，考的是标高量具本身。",
    }
    _dump_bytes(os.path.join(GEN, "%s-qc-control.json" % BUILDING), ctrl_ev)

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
    _dump_bytes(os.path.join(GEN, "%s-chain.json" % BUILDING), chain_ev)

    top = layers[-1]
    tf = {"主屋面_m": _top_main(top),
          "女儿墙顶_m": top["class_hi"].get("PARAPET"),
          # ★ 2026-10-19：类名已由 `ROOF_STAIR` 并入 `ROOF_ROOM`
          #   （见 export_contours.py:207 / gates/J-10.8-02_su.py:217）——
          #   这里还按旧名取值 ⇒ c005 顶层明明有 ROOF_ROOM（class_hi 23.12 m），
          #   包里却写成「顶楼楼梯房顶 None m」。旧名从此取不到，别再加回去。
          "顶楼楼梯房顶_m": top["class_hi"].get("ROOF_ROOM"),
          "note": "全部由落盘件的 (层,类) 子节点包围盒现算，不手打；缺项写 null（不写 0）。"}

    # ── ③b 逐层房间面片（房间色块 / 平面图用）───────────────────────────────
    plans, plan_stat = _floor_plans(float(bj["storey_m"]))
    # ★★ 2026-10-18（用户「地下一楼也没有出来」）：`plans` 与 `order` 必须是**同一串层**。
    #   两者来自两个不同的清单（`B3.FLOORS` 的层名 vs contours 的轮廓记录），
    #   原先靠**下标**对齐、靠查看器一句启发式盖错位 ⇒ 有地下室的楼，B1 永远拿不到基线。
    #   从今天起：份数不等就**不打包**（不许再让下标去猜）；相等时**逐份写节点名**进 manifest。
    if len(plans) != len(order):
        print("★ 基线层 %d 份 ≠ 模型层节点 %d 个 %s ⇒ 不打包"
              "（两套层号不许靠下标猜对齐）" % (len(plans), len(order), order))
        return 1
    for _k, (_doc, _nd) in enumerate(zip(plans, order)):
        _doc["node"] = _nd          # 基线件自己说清「我是哪一层的」，查看器不必再猜
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
        "source_model": "rebuild/%s/06_su/" % BUILDING + GLB_NAME,
        "source_note": ("链：源 DXF → 切图幅(%d 张) → 识别 → build3d → FreeCAD → " % len(ci) +
                        "fc_obj_to_glb.py（只转格式、不动顶点；自带 polys_in == polys_out 断言）。"
                        "同一份 contours 连跑两趟输出逐字节相同。"
                        if SRC_KIND == "fc" else
                        "链：源 DXF → 切图幅(%d 张) → 识别 → build3d → SketchUp → " % len(ci) +
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
            "层高与女儿墙高是**口径决定**（参数表 `共用/层高`），源图没有任何标高/尺寸标注可证。",
            "门窗的归类是规则：本包按墙层上的带弧多段线符号认门、只开洞不建门扇；"
            "源图没有窗图层 ⇒ 不建窗（不合成）。逐栋实况见本楼档案的 scope。",
            "baseline/floors/*.json 的 `rooms`/`circulation` 来自 `redraw.geometry` 的"
            "「楼板 − 墙带」分区 + 房间号落点（**与建件同一份几何**）；`walls`/`doors` 两键"
            "**留空**（空数组 = 本版没做，不是「量到 0」）。",
            "面数守恒只证「逐层相加 = 落盘件」，**不证**几何对 —— 那是 gates/ 的活。",
        ],
    }
    prof = {"schema": "cdut3d-profile/1", "building_id": BUILDING, "title": _title(),
            "note": "显示名取此处；层高/层数一律以 meta/layering.json 为准"
                    "（本文件不写层高，免得出现两套数）。"}
    ledger, ledger_src = _rooms_ledger(plans)
    print("房间台账: %d 行（%s）"
          % (len(ledger), "/".join(str(p["n_rows"]) for p in ledger_src["per_sheet"])))

    # ── 用途对账：baseline 的 `purpose` 与台账的 `purpose` 必须是**同一个名字** ──
    # ★ 2026-10-20 用户「c104，105 的图块，不能选择示例颜色」的根因：
    #   父页图例读 `ledger/rooms.json`，子页三维色块读 `baseline/floors`。源图**没有用途层**的楼
    #   （c104 等 20 栋）台账的 `use` 是从 `7使用单位` 借来的（`a1/rooms.py` 盲区⑦，有实测依据），
    #   而 baseline 只认用途层 ⇒ 色块 purpose 全空、屏上挤成「未标」；点图例任何一类，
    #   `setPurpose` 在色块里一个都找不到，**点了没反应**。
    #   ⇒ 在**生成时**按（层, 房号）把台账的用途补进 baseline 的**空值**（一份包一个真相）。
    #     只填空值，不覆盖 baseline 已有的用途字（那才是图上原文）；`number=None` 的行不参与
    #     —— c015 那类没有房号的楼按房号 join 会张冠李戴。
    _led_by = {}
    for _r in ledger:
        _num = _r.get("number")
        if _num is not None:
            _led_by[(_r.get("floor"), str(_num))] = _r
    _n_fill = 0
    for _k, _doc in enumerate(plans):
        for _r in (_doc.get("rooms") or []):
            _num = _r.get("number")
            if _num is None or (_r.get("purpose") or "").strip():
                continue
            _lr = _led_by.get((_k, str(_num)))
            if _lr and (_lr.get("purpose") or "").strip():
                _r["purpose"] = _lr["purpose"]
                _r["purpose_src"] = ("台账（源图无用途字，取 7使用单位 原文）"
                                     "——见 a1/rooms.py 盲区⑦；本包按（层,房号）补进 baseline")
                _n_fill += 1
    if _n_fill:
        print("用途对账: baseline 空用途按（层,房号）从台账补 %d 条"
              "（不补就是图例点不动：两边名字对不上）" % _n_fill)

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
            "perturbation": "%s 整层抬起 %.1f m —— 由本脚本从真件现造（%d 个网格），"
                            "节点数不变，专考标高量具" % (ctrl_node, CONTROL_SHIFT_M, n_moved),
            "value": round(ctrl["score"], 4),
            "expect": "必须显著低于阈值 %.2f（否则这把尺子对层标高缺陷无分辨力）" % THRESHOLD,
            "evidence": "同一段 _gauge 代码实测：真件 %.4f → 假件 %.4f；假件失败的条目：%s。"
                        "原始记录 evidence/%s-qc-control.json（含两件 sha256，假件可复现）"
                        % (base["score"], ctrl["score"],
                           "、".join(c["id"] for c in ctrl["fails"]) or "（无）", BUILDING),
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
    _dump_bytes(os.path.join(GEN, "%s-layering.json" % BUILDING), lay)
    for k, doc in enumerate(plans):                 # 房间色块 / 平面图的数据源
        _dump_bytes(os.path.join(STAGE, "baseline", "floors", "floor%d.json" % k), doc)

    arts = [
        {"role": "model", "src": GLB, "rel": "model/%s-building.glb" % BUILDING},
        {"role": "ledger", "src": os.path.join(STAGE, "rooms.json"), "rel": "ledger/rooms.json"},
        {"role": "meta", "src": os.path.join(STAGE, "rooms-source.json"),
         "rel": "ledger/rooms-source.json"},
        {"role": "meta", "src": os.path.join(STAGE, "profile.json"), "rel": "meta/profile.json"},
        {"role": "meta", "src": os.path.join(GEN, "%s-layering.json" % BUILDING),
         "rel": "meta/layering.json"},
        # 逐块清单：GLB 里每层每类只合成一个 mesh，网页点到一面墙只知道 floorK__WALL；
        # 「第几块」只有 contours 有 ⇒ 由 rebuild/tools/mk_catalog.py 现算（本趟 568 块，
        # 逐层与 contours/index.json 对账 PASS）。
    ]
    _cat = os.path.join(REB, "06_su", "%s_catalog.json" % BUILDING)
    if os.path.isfile(_cat):                       # 逐块清单：有的楼没跑 mk_catalog ⇒ 不带
        arts.append({"role": "catalog", "src": _cat, "rel": "meta/blocks.json"})
    arts += [
        {"role": "evidence", "src": os.path.join(GEN, "%s-qc-control.json" % BUILDING),
         "rel": "evidence/%s-qc-control.json" % BUILDING},
        {"role": "evidence", "src": os.path.join(GEN, "%s-chain.json" % BUILDING),
         # ★ 2026-10-17 C105：这里原来写死 `evidence/c005-chain.json` ⇒ 每栋楼的链证据
         #   都顶着 c005 的名字落盘（c001、c105 实测都是这个名）。文件名按楼栋现拼。
         "rel": "evidence/%s-chain.json" % BUILDING},
    ] + [{"role": "baseline_floor",
          # ★ `node` = 模型里的层节点名（`B1` / `floorK`），与 `order` 同下标。
          #   查看器按它取层，**不再拿文件序号去猜**（2026-10-18 B1 无色块的病根）。
          "node": order[k],
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
                               "pack-%s-" % BUILDING + time.strftime("%Y%m%d-%H%M%S"))
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
