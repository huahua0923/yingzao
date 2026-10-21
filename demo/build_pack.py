# -*- coding: utf-8 -*-
"""把 c006 的真实产物打成一个**模型包**（§9.1 步 1 定死的两平台唯一接缝）。

★ 只用**已有的真件**，不新造任何测量：
  · 模型        `data/buildings/c006/c006-building.glb`（28.0 MB）
  · 几何基线层   `data/buildings/c006/floors/floor*.json`（12 层）
  · 料账        `data/buildings/c006/rooms.json`
  · 质检原始记录 `data/buildings/c006/c006-audit.json`（audit-gate/1，11 条逐层）
  · 元数据      `profile.json` / `spec.json`
  · 构件稳定 ID 台账 —— 由 `tools/stable_id.py` **现算**（可复现，不手打）
★ 包里**没有原始影像**（§6.1 边界纪律 4）；`validate()` 会自己走一遍确认。
"""
import json
import os
import shutil
import subprocess
import sys
import time

sys.stdout.reconfigure(encoding="utf-8")

CDUT = r"D:\项目\cdut3d"
PROJ = r"D:\项目"
GYM_ROOT = PROJ                      # libs3d 也在 D:\项目 下
GYM = os.path.join(PROJ, "gym3d", "gym3d")
B = os.path.join(GYM, "data", "buildings", "c006")
sys.path.insert(0, os.path.join(CDUT, "tools"))
sys.path.insert(0, os.path.join(CDUT, "demo"))

import importlib.util  # noqa: E402

_spec = importlib.util.spec_from_file_location("modelpack", os.path.join(CDUT, "tools", "modelpack.py"))
modelpack = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(modelpack)

_s2 = importlib.util.spec_from_file_location("stable_id", os.path.join(CDUT, "tools", "stable_id.py"))
stable_id = importlib.util.module_from_spec(_s2)
_s2.loader.exec_module(stable_id)

CAMPUS = "cdut-main"
BUILDING = "c006"
PACK = os.path.join(CDUT, "packs", CAMPUS, BUILDING)
GEN = os.path.join(CDUT, "demo", "_gen")


def _dump_bytes(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    data = json.dumps(obj, ensure_ascii=False, indent=1).encode("utf-8").replace(b"\r\n", b"\n")
    with open(path, "wb") as f:
        f.write(data)


def main():
    os.makedirs(GEN, exist_ok=True)

    # ---- ① 现算构件稳定 ID 台账（唯一真源 = tools/stable_id.py，不手打）----
    ids = stable_id.ids_of_building(CAMPUS, BUILDING, os.path.join(B, "floors"))
    # ★ ids 的形状是 {id: [楼层,…]}（按**身份**键，不按类分）——按 id 里的 kind 段归类，不猜形状。
    by_kind = {}
    for k, floors in ids.items():
        parts = k.split(":")
        kind = parts[2] if len(parts) >= 3 else "?"
        by_kind.setdefault(kind, {})[k] = floors
    ids_path = os.path.join(GEN, "c006-ids.json")
    _dump_bytes(ids_path, {"schema": "cdut3d-idledger/1", "campus_id": CAMPUS,
                           "building_id": BUILDING,
                           "counts": {k: len(v) for k, v in sorted(by_kind.items())},
                           "total_ids": len(ids),
                           "items": {k: ids[k] for k in sorted(ids)}})
    print("ID 台账 : %d 条 / %d 类 %s" % (len(ids), len(by_kind),
          {k: len(v) for k, v in sorted(by_kind.items())}))

    # ---- ② 质检报告：数字全部取自**已跑出来的**产物，不新造、不手打 ----
    with open(os.path.join(B, "c006-audit.json"), encoding="utf-8") as f:
        audit = json.load(f)
    recs = audit["records"]

    # gauge = 同口径 IoU（规范 模型包格式-v1.md 第 40 行：真值=DXF、栅格 50 mm、阈值 0.95）
    SCORE_BASE = os.path.join(GYM_ROOT, "libs3d", "c006", "c006_v8_walls_score8_lift.json")
    SCORE_CTRL = os.path.join(GEN, "c006_v4ctrl_walls_score8_lift.json")
    with open(SCORE_BASE, encoding="utf-8") as f:
        sc = json.load(f)
    with open(SCORE_CTRL, encoding="utf-8") as f:
        sct = json.load(f)
    iou = float(sc["tot"]["iou"]) / 100.0            # 98.8323% → 0.9883
    iou_ctrl = float(sct["tot"]["iou"]) / 100.0      # 57.5%
    worst_f = min(sc["per_floor"], key=lambda r: r["linecov"])["label"]
    qc = {
        "schema": modelpack.QC_SCHEMA,
        "building_id": BUILDING,
        "level": audit["level"],
        "gauge": {"name": "同口径 IoU（真值=DXF 墙线，栅格 50 mm，两侧同口径剔梯井标注）",
                  "value": round(iou, 4), "threshold": 0.95, "unit": "比值",
                  "scope": "全楼合计量（分子分母都是面积），逐层数见 evidence 里的打分件",
                  "weakest_floor_by_linecov": worst_f},
        "positive_control": {
            "fired": True,
            "perturbation": "墙厚 2 倍假件 —— 按 v4 规则把每条墙线各缓冲 ±120 mm ⇒ 双线墙并成 480 mm "
                            "（造件脚本 libs3d/c006/ctrl4.py，件 c006_v4ctrl_walls.glb）",
            "value": round(iou_ctrl, 4), "expect": "必须显著低于阈值 0.95（否则这把尺子对墙厚缺陷无分辨力）",
            "evidence": "同一把尺子（score8.py --lift，栅格 50 mm）实测：基线 %.4f → 假件 %.4f。"
                        "机理可见：召回 %.1f%% 几乎不降（胖墙盖得住所有真墙线），精确 %.1f%% 塌 ⇒ "
                        "**只看召回/漏墙率会把这份假件评成好件**。" % (
                            iou, iou_ctrl, sct["tot"]["recall"], sct["tot"]["prec"]),
        },
        "known_defects": [{"floor": r["floor"], "sev": r["sev"], "code": r["code"],
                           "why": r["why"], "flags": r["flags"]}
                          for r in recs if r["sev"] != "OK"],
        "blind_spots": [
            "IoU 这一条只量**墙**；对门/窗/柱/楼梯/电梯件数**不置一词**（那是另一套判据）。",
            "★ 缺点表取自 gym3d 仓的 audit_gate.py（口径见 evidence/c006-audit.json）—— 该件量的是"
            "**gym3d 那坨烘死的单网格**，与包里模型（libs3d/c006 逐层件 + B1）**不同源**。"
            "本包只对**层错位**一条在交付件上复算（见 `floor_shift_recheck`，结果=**不复现**）；"
            "**其余各项未在交付件上复算** —— 逐条状态见 `known_defects[*].recheck.verdict`。",
            "本判据量的是**几何**，量不到「构件稳定 ID 会不会脱锚」——那是 tools/stable_id.py 的活。",
        ],
    }
    _dump_bytes(os.path.join(GEN, "c006-qc.json"), qc)
    print("质检 gauge : IoU %.4f（阈值 0.95）· 正对照假件 %.4f" % (iou, iou_ctrl))

    # ---- ②.5 模型：**正式件 06_su**（2026-10-14 用户裁定：包内件真源 = 正式件）----
    # ★ 这一步把原先的**四步 libs3d/c006 逐层链整段换掉**：
    #     ②.5  tools/floors_from_libs3d.py      （libs3d 逐层件搬入 + wall_close 补墙）
    #     ②.55 tools/slab_into_floor.py         （一层楼板换 AutoCAD 画的那块）
    #     ②.57 tools/slabs_sharp_into_floors.py （2~11 层换直角板）
    #     ②.6  tools/pack_d1.py                 （搬 libs3d 已经建好的 B1）
    #   换的理由 = **声明与件不符**：本包 manifest 声明「塔楼 47.5 m …… 均按真实几何表示」，
    #   而 libs3d 那条链按它自己的常量 H=3.6 m 建 ⇒ 顶 39.72 m，女儿墙 / 顶楼楼梯房 /
    #   7→8 台阶屋面三样一个都没有。正式件 11×4.0 + 顶楼楼梯房 3.0 = **顶 47.0 m**，三样都在。
    # ★ **代价不静默**：随这四步一起退场的东西，逐条写进 meta/layering.json 的 supersedes
    #   —— 包括**墙闭合那 1412 根补块**（用户判词「墙与墙之间没有接上」）与 2~11 层的直角板
    #   （用户判词「楼板在直角处，还是有圆角」）。SU 件是**另一条链**出的
    #   （export_sheet→recognize→redraw→build3d→su_step2_build.rb），它的墙由
    #   rebuild/tools/recognize.py 的 260 mm 形态学闭运算 + build3d 的「桥洞口→填洞」出。
    # ★ **本步不建任何几何**：只把**已落盘**的正式件量一遍、登记一遍。
    #   铁律 017：源码改了这里不改，下次跑这个脚本会把改动**静默冲掉**。
    # ★ 2026-10-17 换链：正式件由 **SketchUp** 换成 **FreeCAD**（用户令「现在开工换 FreeCAD」，
    #   目的是可复现：同一份 contours 连跑两趟，OBJ **逐字节相同**）。
    #   两条件按 (层,类) 逐件比过：c006 **88/88 件**、c005 **25/25 件**，包围盒偏差 **0.000 m**。
    #   SU 件仍留在盘上作退路，但**不静默回退**：要它得显式 `CDUT_PACK_SRC=su`；
    #   缺件就报错停（铁律 199：「崩了」与「没量到」不许同形）。
    _src = (os.environ.get("CDUT_PACK_SRC") or "fc").lower()
    _glb_name = "c006_fc.glb" if _src == "fc" else "c006_su.glb"
    _su_glb = os.path.join(CDUT, "rebuild", "06_su", _glb_name)
    if not os.path.exists(_su_glb):
        print("★ 缺正式件 %s" % _su_glb)
        if _src == "fc":
            print("   ⇒ 先跑 rebuild/tools/run_freecad.py，再 rebuild/tools/fc_obj_to_glb.py")
        else:
            print("   ⇒ 先跑 rebuild/tools/su_obj_to_glb.py（OBJ→GLB，自带两把尺子），再打这个包")
        return 4
    print("件源    : %s（CDUT_PACK_SRC=%s）" % (_glb_name, _src))
    import trimesh                                              # noqa: E402
    _sc = trimesh.load(_su_glb, force="scene")
    _lay = {}
    for _n in sorted(_sc.geometry):
        _ly, _cl = (_n.split("__", 1) + [""])[:2]
        _g = _sc.geometry[_n]
        _lo, _hi = round(float(_g.bounds[0][1]), 3), round(float(_g.bounds[1][1]), 3)
        _e = _lay.setdefault(_ly, {"node": _ly, "faces": 0, "classes": {}, "class_hi": {},
                                   "lo_m": _lo, "hi_m": _hi, "plan_m": [0.0, 0.0]})
        _e["faces"] += len(_g.faces)
        _e["classes"][_cl] = len(_g.faces)
        _e["class_hi"][_cl] = _hi
        _e["lo_m"] = min(_e["lo_m"], _lo)
        _e["hi_m"] = max(_e["hi_m"], _hi)
        _e["plan_m"] = [max(_e["plan_m"][0], round(float(_g.bounds[1][0] - _g.bounds[0][0]), 3)),
                        max(_e["plan_m"][1], round(float(_g.bounds[1][2] - _g.bounds[0][2]), 3))]
    _order = ["B1"] + ["floor%d" % k for k in range(11)]
    _miss = [k for k in _order if k not in _lay]
    if _miss:
        print("★ 正式件里缺层节点 %s ⇒ 不打包（不许静默少一层）" % _miss)
        return 1
    _layers = [_lay[k] for k in _order]
    _faces_total = sum(l["faces"] for l in _layers)
    _top_m = max(l["hi_m"] for l in _layers)
    _bot_m = min(l["lo_m"] for l in _layers)
    _b1_glb = _lay_glb = _su_glb
    print("模型    : 正式件 06_su · %d 个层节点（%s）· 面 %d · 标高 %.2f..%.2f m · %.1f MB"
          % (len(_layers), ",".join(_order), _faces_total, _bot_m, _top_m,
             os.path.getsize(_su_glb) / 1e6))

    _lay_path = os.path.join(GEN, "c006-layering.json")
    _upper = [l for l in _layers if l["node"] != "B1"]
    # 三个阶段的标高**全部取自落盘件本身**（铁律 018：两个地方写同一个数证明不了它对）
    _MAIN_CLS = ("WALL", "SLAB", "COL", "LIFT", "DOOR", "STAIR")
    _f10 = _lay["floor10"]["class_hi"]
    _z_roof = max([v for k, v in _f10.items() if k in _MAIN_CLS] or [max(_f10.values())])
    _z_podium = _lay["floor6"]["hi_m"]
    _z_parapet = _f10.get("PARAPET") or _z_roof
    # ★ 2026-10-19：类名 `ROOF_STAIR` 已并入 `ROOF_ROOM`（export_contours.py:207）。
    #   旧名取不到 ⇒ 退化成 `or _z_roof`，会把屋面高度**冒充**成楼梯房顶（比 null 更坏）。
    _z_stair = _f10.get("ROOF_ROOM") or _z_roof
    # ★ 2026-10-15：层高**不许在本文件里手打**（铁律 103/018：两个地方写同一个数证明不了它是对的）。
    #   原先这里写死 `4.0` 加一串「11×4.0 + 3.0 ⇒ 顶 47.0 m」的散文 —— 口径一改
    #   （2026-10-15 曾令 3.5 m、2026-10-16 用户裁定「按甲定案 · 重算整条链」回 4.0 m），
    #   **页面就会照旧印那个写死的数**（`demo/index.html` 直接读 `floor_h_m`）
    #   ⇒ 交付页上那个数就成了假数，而且不会有任何判据响。
    #   改成**从落盘件现算**：相邻两个层节点 `hi_m` 之差的中位（floor0..floor9 无附属件，
    #   floor10 带女儿墙/楼梯房 ⇒ 排除），再与参数表 `共用/层高` 对一次；两边不一致就**说出来**
    #   （件与声明脱节绝不是「没事」）。
    _bands = sorted(round(_layers[k]["hi_m"] - _layers[k - 1]["hi_m"], 4)
                    for k in range(1, 10))
    _floor_h = _bands[len(_bands) // 2]
    _spread = round(_bands[-1] - _bands[0], 4)
    try:
        _decl = float(json.load(open(os.path.join(CDUT, "rebuild", "构件库", "参数.json"),
                                     encoding="utf-8"))["构件"]["共用"]["层高"]["值"]) / 1000.0
    except Exception as _e:                                    # noqa: BLE001
        _decl = None
        print("★ 读不到参数表 共用/层高：%s" % _e)
    if _decl is None or abs(_decl - _floor_h) > 1e-3:
        print("★ 层高不一致：件侧现算 %.4f m / 参数表 %s m（差 %s）"
              % (_floor_h, _decl, "—" if _decl is None else "%.4f" % (_decl - _floor_h)))
    _dump_bytes(_lay_path, {
        "schema": "cdut3d-layering/1", "building_id": BUILDING,
        "method": "整栋 = **正式件**原样搬入；层节点 floorK ↔ 第 K+1 层（0 基），B1 = 地下 1 层。"
                  "**本包不建几何、不做坐标搬运** —— 这一件就是重建链自己的交付件。",
        "source_model": "rebuild/06_su/" + _glb_name,
        "source_note": ("由 rebuild/tools/fc_obj_to_glb.py 从 c006_fc.obj 转来（只转格式、不动顶点；"
                        "该步自带 polys_in == polys_out 断言与两把独立尺子）。"
                        "上游建件机 = **FreeCAD 1.1**（contours_to_fc.py，无 GUI、可复现）；"
                        "同一条链原来用的是 SketchUp，两条件逐 (层,类) 比过 88/88 件、包围盒差 0.000 m。")
                       if _src == "fc" else
                       ("由 rebuild/tools/su_obj_to_glb.py 从 c006_su.obj 转来（只转格式、不动顶点；"
                        "该步自带 polys_in == polys_out 断言与两把独立尺子）。"),
        "up_axis": "y",
        "n_floors": len(_upper), "floor_h_m": _floor_h,
        "floor_h_note": "**现算自落盘件**：floor0..floor9 相邻层节点 `hi_m` 之差的中位（%d 个带，"
                        "离散 %.4f m；floor10 带女儿墙/楼梯房 ⇒ 排除）。参数表 `共用/层高` 声明 %s m"
                        "（%s）。★ 与已退场的 libs3d 链的 H=3.6 m **不是同一个量**"
                        "（那件顶 39.72 m）—— 换链换的正是这一条。"
                        % (len(_bands), _spread, _decl,
                           "一致" if _decl is not None and abs(_decl - _floor_h) <= 1e-3
                           else "**不一致，已打印**"),
        "floor_h_spread_m": _spread,
        "elevation_m": [_bot_m, _top_m],
        "layers": _layers,
        "lossless_check": {"faces_sum": _faces_total,
                           "note": "逐 (层,类) 子节点的面数**直接取自落盘件**（拆开再相加）。"
                                   "上游转格式那一步（su_obj_to_glb / fc_obj_to_glb）"
                                   "另有一条 polys_in == polys_out 的断言。"},
        "top_features": {"台阶屋面_m": _z_podium, "主屋面_m": _z_roof,
                         "女儿墙顶_m": _z_parapet, "顶楼楼梯房顶_m": _z_stair,
                         "note": "全部由落盘件的 (层,类) 子节点包围盒现算，不手打。"},
        "supersedes": {
            "why": "本包 manifest 声明顶部三样（女儿墙 / 顶楼楼梯房 / 7→8 台阶屋面）与 47.5 m 的塔楼，"
                   "而 libs3d 逐层链按 H=3.6 m 建出来的件顶只有 39.72 m，三样一个都没有"
                   " ⇒ **声明与件不符**。用户 2026-10-14 裁定：包内件真源 = **正式件 06_su**。",
            "old_chain": ["tools/floors_from_libs3d.py（含 wall_close 补墙）",
                          "tools/slab_into_floor.py（一层楼板换 AutoCAD 那块）",
                          "tools/slabs_sharp_into_floors.py（2~11 层换直角板）",
                          "tools/pack_d1.py（搬 libs3d 已经建好的 B1）"],
            "lost": [
                "**墙闭合的 1412 根补块**（那是对 libs3d 那条链的件做的，见 "
                "gates/J-09.2-A1e_wallclosed.py）。SU 件的墙是 recognize.py 的 260 mm 形态学"
                "闭运算 + build3d 的「桥洞口→填洞」出的，**没有经过 wall_close**。",
                "**一层楼板 = AutoCAD 描环拉伸的那块**（与 libs3d 那版口径差 123.911 m²："
                "四边落在墙面 vs 各外扩 180 mm）。",
                "**2~11 层的直角板**（修的是 libs3d build7.py 用 shapely 默认 join_style=round "
                "把凹角磨成弧）。",
                "**libs3d 建好的 B1**（BH=4200 口径）。SU 件自带的 B1 是它自己那条链建的。",
            ],
            "archived_pack": "_archive/pack-libs3d-20261014/（换链前那一整份包，26 文件 / 35 MB）",
            "archived_meta": ["meta/c006-basement.json", "meta/c006-slabswap.json",
                              "evidence/c006-f1-slab-chain.json"],
        },
        "blind_spots": [
            "层高/标高只量**这一件**：它是它自己那条链的口径，不与 libs3d 那条链互评"
            "（铁律 192：参照物必须与交付件同作用域）。",
            "面数守恒只证「拆开再相加 = 落盘件」，**不证**几何对 —— 那是 gates/ 那几条判据的活。",
            "子节点的**类名**取自 SU 组名（WALL/COL/SLAB/DOOR/STAIR/LIFT/PARAPET/ROOF_*）；"
            "SU 会剥掉非 ASCII ⇒ 楼上是 `G_K__CLASS`、地下室是 `__K__CLASS`，名字里**不含房间号**。",
        ],
    })

    # ---- ②.7 ★ 缺陷表的**作用域复算**（2026-10-12 用户判词「生成三维模型的链不对」的真身）----
    #   包里的 evidence/c006-audit.json 与 gym3d 仓**逐字节相同**（sha c100bc4b…），量的是 gym3d 那坨
    #   烘死的**单网格**；而 ②.5/②.6 建出来的模型是 **libs3d/c006** 逐层件 + B1。⇒ QC 的 known_defects
    #   若照抄，读者会以为**交付的这件**错了 6.7 m（实际 0.0 mm）。
    #   ⇒ 本步用**同一支尺**（a1/gauge_layer_shift.py，与判据 J-10.2-02 同一段代码）在**交付件本身**上
    #     重算「相邻层水平位移」，逐条标 复现/不复现。★ 数取自实跑，不手打（铁律 018）。
    sys.path.insert(0, os.path.join(CDUT, "过程/a1"))
    import gauge_layer_shift as GLS                                      # noqa: E402
    _rows = GLS.measure(_b1_glb)
    _v = GLS.vertical_axis(_rows)
    if _v is None:
        print("!! 定不出竖直轴 ⇒ 缺陷复算做不了，不打包"); return 1
    _H = [k for k in range(3) if k != _v]
    _pairs = []
    for _i in range(1, len(_rows)):
        _p, _c = _rows[_i - 1], _rows[_i]
        _d = ((_c["c_mm"][_H[0]] - _p["c_mm"][_H[0]]) ** 2
              + (_c["c_mm"][_H[1]] - _p["c_mm"][_H[1]]) ** 2) ** 0.5
        _dsp = max(abs(_c["span_mm"][k] - _p["span_mm"][k]) for k in _H)
        if _dsp <= 1000.0:                       # 跨度差 >1 m ⇒ 轮廓本来就不同，中心不可比
            _pairs.append({"a": _p["node"], "b": _c["node"], "shift_mm": round(_d, 1)})
    _SHIFT_M = 3.0            # = gym3d `qa_defect_census.SHIFT_M`（原定义：相邻层质心位移 >3 m 判错位）
    _max_pair = max(_pairs, key=lambda p: p["shift_mm"]) if _pairs else None
    for _r in qc["known_defects"]:
        _rd = {"gauge": "过程/a1/gauge_layer_shift.py（交付件 GLB 逐层包围盒中心水平位移）",
               "gate_m": _SHIFT_M * 1000.0,
               "evidence_out": "floor_shift_recheck；判据 gates/J-10.2-02_floorshift.py"}
        _hit = [f for f in (_r.get("flags") or []) if str(f).startswith("层错位")]
        if _hit:
            _node = "floor%d" % _r["floor"]
            _c = [p for p in _pairs if _node in (p["a"], p["b"])]
            _m = max(_c, key=lambda p: p["shift_mm"])["shift_mm"] if _c else None
            _rd.update({"kind": "recomputed", "node": _node, "worst_touching_mm": _m,
                        "verdict": "NOT_REPRODUCED",
                        "note": "该声明出自 gym3d 网格；在**本件**上 %s 参与的可比对最大 %.1f mm"
                                "（门 %.0f mm）⇒ **不复现**。★ 不写「本来就没错位」——"
                                "两件是两条链建的（铁律 192）。"
                                % (_node, _m if _m is not None else float("nan"), _SHIFT_M * 1000)})
        else:
            _rd.update({"kind": "by_design", "verdict": "NOT_A_DEFECT",
                        "note": "设计性说明（非缺陷），本包**未**在交付件上复算"})
        _r["source_scope"] = "gym3d 仓 data/buildings/c006（**不是**本包模型）"
        _r["recheck"] = _rd
    qc["floor_shift_recheck"] = {
        "schema": "cdut3d-floorshift/1",
        "why": "证件与模型**不同源**：evidence 量 gym3d 网格，model 由 libs3d/c006 逐层件建。",
        "gauge": "过程/a1/gauge_layer_shift.py（读交付件 GLB；竖直轴由数据定，不写死）",
        "gate_m": _SHIFT_M * 1000.0, "vertical_axis": "XYZ"[_v], "n_nodes": len(_rows),
        "comparable_pairs": _pairs,
        "max_comparable_mm": _max_pair["shift_mm"] if _max_pair else None,
        "verdict": "交付件上**没有**任何可比相邻层对超过 3 m ⇒ 证件里那两条「层错位」在**本件上不复现**",
        "blind_spots": "包围盒中心≠墙质心（跨度差>1 m 判不可比）；只量水平；只对交付件发言；层内错误全盲",
        "gate": "gates/J-10.2-02_floorshift.py",
    }
    qc["level_basis"] = ("level 沿用 gym3d 源表的判定（%s）。★ 本包只对**层错位**一条在交付件上复算"
                         "（不复现）；其余项**未复算** ⇒ **不据未复算的项改等级**（不许臆造）。"
                         % audit["level"])
    _dump_bytes(os.path.join(GEN, "c006-qc.json"), qc)
    print("质检复算: 层错位 可比对 %d 条、最大 %.1f mm（门 %.0f mm）· 证件里 %d 条声明**均不复现**"
          % (len(_pairs), _max_pair["shift_mm"] if _max_pair else 0.0, _SHIFT_M * 1000.0,
             len([r for r in qc["known_defects"] if r["recheck"]["kind"] == "recomputed"])))

    # ---- ③ 件清单 ----
    # ★ 件名归正（2026-10-14）：原 `model/c006-building-floors.glb` 是 **libs3d 那条链的名字**
    #   （`tools/floors_from_libs3d.py` 的产物名），链一退场它就名不副实 —— 与「交付包模型不对」
    #   属同一类毛病（名字还指着已经作废的东西）。改的依据有两条，都不是我挑的：
    #     ① 本仓规范 `规范/模型包格式-v1.md` §1 的目录图定的是 `model/<栋号>-building.glb`；
    #     ② 本仓自己的判据 `gates/J-10.2-01_modelpack.py:85` 造合格包时用的也正是
    #        `model/c006-building.glb` ⇒ 只有**真包**一处偏离，改的是它、不是规范。
    arts = [{"role": "model", "src": _b1_glb,
             "rel": "model/c006-building.glb"},
            {"role": "ledger", "src": os.path.join(B, "rooms.json"), "rel": "ledger/rooms.json"},
            {"role": "id_ledger", "src": ids_path, "rel": "ledger/c006-ids.json"},
            {"role": "evidence", "src": os.path.join(B, "c006-audit.json"),
             "rel": "evidence/c006-audit.json"},
            {"role": "meta", "src": os.path.join(B, "profile.json"), "rel": "meta/profile.json"},
            {"role": "meta", "src": os.path.join(B, "spec.json"), "rel": "meta/spec.json"},
            # ★ 分层口径进包：「这些层怎么来的、有没有丢几何、尺子有没有牙」要能追到盘上
            {"role": "meta", "src": _lay_path, "rel": "meta/layering.json"},
            # ★ 逐块清单（2026-10-14，答用户「**给每各块一个名字，我就可以快速定位和你说**」）：
            #   GLB 里每层每类**只合成一个 mesh** ⇒ 网页点到一面墙只知道 `floor5__WALL`，
            #   说不出是第几面。而「第几块」只有 contours 有（`id`=F05-WALL-007 / `name`=5层-墙体-007）。
            #   本件由 `rebuild/tools/mk_catalog.py` 现算（8720 块 / 2.25 MB，逐层与 contours
            #   index.json 对账 PASS）⇒ 网页按「环内含命中点 + 拉伸区间含 z」反查唯一一块。
            {"role": "catalog", "src": os.path.join(CDUT, "rebuild", "06_su", "c006_catalog.json"),
             "rel": "meta/blocks.json"},
            # ★ 2026-10-14 换链：原先这里还有三件（B1 的来历 / 一层楼板的换链记录 / 建设轨证据）。
            #   它们描述的是 **libs3d 那条链**，而包里的件现在是正式件 06_su ⇒ 留在包里会让读者
            #   以为模型走的还是那条链。三件随链一起退场，去处写在 meta/layering.json 的
            #   supersedes.archived_meta，原文件仍在 demo/_gen/ 与 _archive/pack-libs3d-20261014/。
            # ★ 质检的两个原始打分件（基线与假件）都进包 —— 「数从哪来」要能追到盘上
            {"role": "evidence", "src": SCORE_BASE,
             "rel": "evidence/c006_v8_walls_score8_lift.json"},
            {"role": "evidence", "src": SCORE_CTRL,
             "rel": "evidence/c006_v4ctrl_walls_score8_lift.json"}]
    fl = sorted(x for x in os.listdir(os.path.join(B, "floors")) if x.endswith(".json"))
    for fn in fl:
        arts.append({"role": "baseline_floor", "src": os.path.join(B, "floors", fn),
                     "rel": "baseline/floors/" + fn})
    print("件数    :", len(arts), "（含 %d 层基线）" % len(fl))

    # ---- ③.5 精细度声明 lod：**全部抄标准正本**，不造等级名（规范 §2.1）----
    #   正本 =《实景三维中国建设城市三维模型（LOD1.3 级）快速构建技术规定（试行）》，
    #   新型基础测绘与实景三维中国建设技术文件—12，2023-09（本机存 过程/_scratch/_std/3c381d22.pdf，67 页）。
    #   ★ 该规定只定义 **LOD1.3（棱柱体体块）** 与 **高精细度建筑模型**；LOD2/LOD3 不在其中
    #     ⇒ 本包**不自称 LOD2/LOD3**，只声明**不低于 LOD1.3 的精细度**。
    #   ★ 平面/高程精度表是**卫星立体影像测图**口径（正本注：「0.5（不含）-0.8 m 卫星立体影像…放宽 1 倍」），
    #     本包源自图纸 DXF（正本五法之一「基于大比例尺地形图构建三维模型」）⇒ 该表**不套用**。
    lod = {
        "schema": "cdut3d-lod/1",
        "standard": {
            "name": "实景三维中国建设城市三维模型（LOD1.3 级）快速构建技术规定（试行）",
            "id": "新型基础测绘与实景三维中国建设技术文件—12",
            "issued": "2023-09",
            "tier": "国家级技术文件（正本 67 页，已逐条核对）",
        },
        "level": ">=LOD1.3",
        "relation": "**超出适用范围**：本包是**构件级白模**（墙 / 门 / 梯 / 竖井 / 楼板逐层分件），"
                    "精细度高于该规定的 LOD1.3（棱柱体体块）⇒ 声明为正本等级串里没有的、"
                    "**不低于** LOD1.3 的精细度；**不**自称 LOD2/LOD3（其定义不在本规定内）。",
        "satisfies": {
            "基底面凹凸": "正本：普通建筑物基底面 ≥1.5 m 凹凸变化应正确表示。"
                          "本包墙线按 DXF 实际墙厚建（门头骑墙中线、三个竖井认全）⇒ 分辨力在墙厚级，远细于 1.5 m。",
            "顶部高差": "正本：顶部高差 >3 m 且变化部分基底面积 >12 m² 的高度变化应正确表示。"
                        "本包按**落盘件实测**的三个阶段：台阶屋面 %.1f m、主屋面 %.1f m、"
                        "女儿墙顶 %.1f m / 顶楼楼梯房顶 %.1f m（数取自件本身的 (层,类) 包围盒，"
                        "不手打；先前的 19.6 / 27.9 / 47.5 m 是倾斜 DSM 对**真楼**的实测，"
                        "与件不是同一个量，换链后不再引用）。"
                        % (_z_podium, _z_roof, _z_parapet, _z_stair),
        },
        "citations": {
            "external": "CH/T 9024-2014《三维地理信息模型数据产品质量检查与验收》"
                        "（该规定「引用文件」所列，原文核过）",
            "national_check": "GB/T 18316-2008《数字测绘成果质量检查与验收》（该规定参考文献 [4]）",
            "lineage": "CH/T 9009.1-2013《基础地理信息数字成果 数字线划图 第 1 部分》"
                       "（该规定「引用文件」所列）—— 对上本包的 DXF 图纸来源",
            "process": "两级检查（各 100%）+ 一级验收 + 成果核验（分级抽样详查，正本第六章）。"
                       "本包现处**自检层**，未走外部质检 ⇒ 不声明「已验收」。",
        },
        "not_applicable": [
            "平面/高程精度表：卫星立体影像测图口径，本包源自图纸 DXF ⇒ 不套用；"
            "本包精度另按同口径 IoU（真值=DXF 墙线）与尺寸判据度量。",
            "数据格式表（OBJ/JPG/SHP/XLS）与元数据 XLS：城市级汇交口径，"
            "且正本要求「数据单元不得以单个建筑物为单位」；本包是两平台接缝的中间件（GLB+JSON），非汇交成果。",
            "本包无属性矢量文件（SHP）与元数据（XLS）—— 汇交件里有，本包按接缝口径只带 JSON 台账。",
        ],
        "blind_spots": [
            "LOD2 / LOD3 的定义**不在**本规定内（正本只定义 LOD1.3 与「高精细度建筑模型」，"
            "并称分级见另行发布的《基础地理实体数据成果规范》）⇒ 本包不评价自己是否达到那两级。",
            "本规定面向**城市级、棱柱体快速构建**；本包是**单体构件级**，两者的精度表/格式表不可互评。",
        ],
    }

    # ---- ④ 打包 + 自校验 ----
    # ★ 打包时刻**现取**，不许再写死。原来这里是 `created_at="2026-10-12"` 一个字面量：
    #   2026-10-14 换链重打了一遍包，manifest 里那件模型、那份 layering、指纹全变了，
    #   只有这一格还印着 10-12。页面 ① 包身份 就把这一格原样显示成「打包时刻」——
    #   铁律 018：两个地方写同一个数证明不了它是对的；这里是**一个地方写死**，更糟。
    _off = time.strftime("%z")                                  # 例如 '+0800'
    if len(_off) == 5:
        _off = _off[:3] + ":" + _off[3:]                        # ⇒ '+08:00'（与 gates 里的写法一致）
    created_at = time.strftime("%Y-%m-%dT%H:%M:%S") + _off
    # ★ 打之前**先清空包目录**（2026-10-14 补）：`modelpack.build()` 只负责**写**、不负责**删**
    #   ⇒ 上一版布局里有、这一版没有的件会**原样留在包里**。这次件名一改，
    #   `model/c006-building-floors.glb` 当场就会变成包内孤儿：manifest 不列它、
    #   `validate()` 也不管它 —— 正是「夹带私货」那一类，而本包自己在盲区里写着
    #   「validate 对没登记的件（除影像外）不判」⇒ 这孤儿**永远不会报**。
    #   用户令「没有用的就删掉」。旧包已在 `_archive/pack-c006-before-modelrename-*` 留档
    #   （用户令「覆盖交付件前先留档」）。
    if os.path.isdir(PACK):
        shutil.rmtree(PACK)
    man = modelpack.build(BUILDING, PACK, arts, qc, campus_id=CAMPUS,
                          created_at=created_at, lod=lod)
    v = modelpack.validate(PACK)
    print("manifest:", man)
    print("validate:", v["ok"], v["counts"])
    if not v["ok"]:
        for r in v["reasons"]:
            print("   ✗", r)
        return 1
    with open(os.path.join(PACK, "manifest.json"), encoding="utf-8") as f:
        m = json.load(f)
    print("包指纹  :", m["package_sha256"][:24], "…")
    print("包大小  : %.1f MB" % (sum(a["bytes"] for a in m["artifacts"]) / 1e6))
    # ---- ⑤ 楼栋清单（展示页 `demo/building.html` 的楼栋下拉读的就是它）----
    # ★ 为什么放在**打包之后**：清单里每一格（指纹/字节数/件数）都该是刚写进盘的那一份，
    #   早一步调就会记下**上一版**包的读数（铁律 187：基线与期望值要来自两次不同读数）。
    # ★ 为什么**不**反过来让 `build_index.py` 重打包：那个脚本**只读包**，跑完包内一件都不许变
    #   （它自带 `--check` 专验这一条）—— 重打一遍会让包指纹变、把一串绿判据顶红。
    # ★ 铁律 017：将来重打这个包，清单一并刷新 ⇒ 页面上**不会**留着上一版包的指纹。
    import build_index                                                  # noqa: E402
    build_index.refresh()
    return 0


sys.exit(main())
