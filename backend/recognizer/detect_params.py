# -*- coding: utf-8 -*-
"""从一栋楼的 DXF 自动探测 BuildingProfile 参数，输出可落盘的 profile.json。

只信「墙图层」的 LWPOLYLINE（排除 0/1图框 等图框层），
用周期检测求 OFFSET（楼层在 Y 上等距重复），X 中心求 CX，0 层 Y 中心求 CY。

**两处不做猜测、宁可报错**（都是实测踩过的「静默给错值」）:
  1. 图纸横向并排多块时（全仓 49 栋里 17 栋如此），不猜哪块是楼体 ——
     逐块报 {x_range, walls, width_m, cx}，要求用 --x-range LO HI 指定后重跑。
  2. OFFSET 撞在搜索边界上（8000/300000）= 周期检测失败，报 offset_unreliable。

用法:
  python detect_params.py <dxf路径> <name> <title> [--out profile.json] [--x-range LO HI]
"""
import json
import os
import sys
from collections import Counter

import ezdxf

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")))    # backend/
from paths import BUILDINGS  # noqa: E402

# 与 profiles/lihua.py 一致的算法默认值（门/台阶/墙厚/窗等）
ALGO_DEFAULTS = {
    "door_min_points": 10, "stair_points": 5,
    "wall_min": 0.08, "wall_max": 0.35, "wall_extend": 0.15, "wall_fallback": 0.15,
    "door_w_single": 1.1, "door_w_double": 2.4, "door_depth": 0.5,
    "outline_buf": 0.15, "open_r": 0.35, "parapet_margin": 0.5,
    "layer_height": 4.2, "slab": 0.2,
}

WALL_KEYWORDS = ("墙体", "4.2", "4墙", "4.3", "封墙")
COL_KEYWORDS = ("结构柱", "4.1柱", "柱")


def detect_offset(ys, lo=8000, hi=300000, step=500, bin_w=500):
    """周期检测：楼层在 Y 上等距重复，offset = 使占位直方图自对齐最大的位移。"""
    ys = [round(y) for y in ys]
    if not ys:
        return None, 0
    min_y, max_y = min(ys), max(ys)
    occ = {}
    for y in ys:
        occ[y // bin_w] = occ.get(y // bin_w, 0) + 1
    best_d, best_score = None, -1
    for d in range(lo, hi + 1, step):
        shift = round(d / bin_w)
        score = sum(1 for b in occ if b + shift in occ)
        if score > best_score:
            best_score, best_d = score, d
    return best_d, best_score


def cluster_x(boxes, gap=100000.0):
    """把各墙多段线的 X 区间按间隔并成「块」，按墙数降序返回 [{lo,hi,n}]。

    为什么必须有这一步：本模块原先直接拿**全部**墙顶点求 cx（整图 X 中点）。
    图纸横向并排多块时（如 c108：列0 是 4 层平面，列1 在 600m 外另有一块 123 面墙的
    屋顶/详图平面），那个 cx 是错的 —— 而且错得**毫无提示**，直接拿去识别会让隔壁
    整块墙混进每一层。实测 c108 真实 cx=1198645，自动值给了 1535735。
    """
    if not boxes:
        return []
    bs = sorted(boxes)
    out = [{"lo": bs[0][0], "hi": bs[0][1], "n": 1}]
    for lo, hi in bs[1:]:
        if lo - out[-1]["hi"] > gap:
            out.append({"lo": lo, "hi": hi, "n": 1})
        else:
            out[-1]["hi"] = max(out[-1]["hi"], hi)
            out[-1]["n"] += 1
    return sorted(out, key=lambda c: -c["n"])


def _block_cx(bands, b):
    """某一块内墙顶点的 X 中心（块 = 图纸上并排的一块平面）。"""
    sel = [p for lo, hi, pts in bands
           if lo >= b["lo"] - 1 and hi <= b["hi"] + 1 for p in pts]
    if not sel:
        return None
    xs = [p[0] for p in sel]
    return round((min(xs) + max(xs)) / 2, 1)


def detect(dxf_path, name, title, x_range=None):
    doc = ezdxf.readfile(dxf_path)
    msp = doc.modelspace()

    layer_etype = {}
    for e in msp:
        t = e.dxftype()
        lay = e.dxf.layer if hasattr(e.dxf, "layer") else "(none)"
        layer_etype.setdefault(lay, Counter())[t] += 1

    # 墙层：名字含「墙」且以 LWPOLYLINE 为主
    wall_layers = [l for l in layer_etype
                   if any(k in l for k in WALL_KEYWORDS)
                   and layer_etype[l].get("LWPOLYLINE", 0) > 0]
    # 主墙层 = 墙层里 LWPOLYLINE 最多的
    wall_layer = max(wall_layers, key=lambda l: layer_etype[l]["LWPOLYLINE"]) if wall_layers else ""

    # 柱层：名字含「柱」且 LWPOLYLINE>0（无则留空 = 无柱）
    col_layers = [l for l in layer_etype
                  if any(k in l for k in COL_KEYWORDS)
                  and layer_etype[l].get("LWPOLYLINE", 0) > 0]
    column_layer = max(col_layers, key=lambda l: layer_etype[l]["LWPOLYLINE"]) if col_layers else ""

    # 先按多段线收集「X 区间 + 顶点」，再分块 —— 单块楼与旧行为逐位一致。
    bands = []
    for e in msp:
        if e.dxftype() == "LWPOLYLINE" and e.dxf.layer == wall_layer:
            pts = [tuple(p[:2]) for p in e.get_points()]
            if pts:
                pxs = [p[0] for p in pts]
                bands.append((min(pxs), max(pxs), pts))

    if not bands:
        return {"name": name, "title": title, "dxf": dxf_path,
                "wall_layer": wall_layer, "column_layer": column_layer,
                "error": "墙图层无 LWPOLYLINE 数据（可能走 LINE+ARC 约定，如六教）"}

    blocks = cluster_x([(lo, hi) for lo, hi, _ in bands])
    multi = len(blocks) > 1

    # 多块图纸：**拒绝猜**。几何上分不出哪块是楼体 —— c108 的列1 有 123 面墙却
    # 一条房号都没有，别的楼可能恰好反过来（详图块墙多、楼体墙少）。
    # 这里逐块把 cx 报出来让人工选，并让调用方用 --x-range 钉死。
    # 静默取「墙最多的那块」正是 c108 踩的坑，不能换个启发式接着猜。
    if multi and x_range is None:
        info = [{"x_range": [round(b["lo"]), round(b["hi"])],
                 "walls": b["n"],
                 "width_m": round((b["hi"] - b["lo"]) / 1000.0, 1),
                 "cx": _block_cx(bands, b)} for b in blocks]
        return {"name": name, "title": title, "dxf": dxf_path,
                "wall_layer": wall_layer, "column_layer": column_layer,
                "multi_column": True, "column_blocks": info,
                "error": ("图纸横向并排 %d 块，无法自动判定哪块是楼体（不做猜测）。"
                          "请看下面各块的 width_m/cx/walls，用 --x-range LO HI 指定后重跑。"
                          % len(blocks))}

    # 单块：行为与旧版逐位一致。多块 + 指定 x_range：只取与该区间相交的墙。
    xs, ys = [], []
    for lo, hi, pts in bands:
        if x_range is not None and (hi < x_range[0] or lo > x_range[1]):
            continue   # 区间外的块（隔壁详图）整段丢弃，防混进每一层
        for x, y in pts:
            xs.append(x)
            ys.append(y)

    if not ys:
        return {"name": name, "title": title, "dxf": dxf_path,
                "wall_layer": wall_layer, "column_layer": column_layer,
                "error": "x_range %s 内没有任何墙多段线，区间给错了" % (x_range,)}

    offset, score = detect_offset(ys)
    cx = round((min(xs) + max(xs)) / 2, 1)
    # 0 层 = Y 在 [minY, minY+offset) 的顶点，取中位数做 CY
    min_y = min(ys)
    f0_ys = sorted(y for y in ys if y < min_y + offset) if offset else ys
    cy = round(f0_ys[len(f0_ys) // 2], 1)

    out = {
        "name": name, "title": title, "dxf": dxf_path,
        "wall_layer": wall_layer, "column_layer": column_layer,
        "offset": offset, "cx": cx, "cy": cy,
        "wall_x_range": [round(min(xs)), round(max(xs))],
        "wall_y_range": [round(min_y), round(max(ys))],
        "offset_score": score,
    }
    if multi:
        # 走到这里说明调用方给了 --x_range。cx 只在区间内算好了，
        # 但 profile.json 里的 x_range 必须一并写死，否则识别时会读进整张图。
        out["multi_column"] = True
        out["note"] = ("已按 x_range %s 限定（全图共 %d 块）。"
                       "profile.json 必须同时写 x_range，否则识别会读进隔壁块。"
                       % (x_range, len(blocks)))

    # offset 落在搜索边界上 = 周期检测**失败**，不是真周期。
    # 实测 c046/c054/c055 都返回 8000（= detect_offset 的 lo 下界），
    # 人工档案里它们其实写的是 127200/98900。静默拿 8000 去分层，
    # 会让每层都落到同一格里 —— 与 cx 多列坑同族，必须报出来。
    if offset in (8000, 300000):
        out["offset_unreliable"] = True
        out["note_offset"] = ("offset=%d 撞在搜索边界上，说明周期检测没找到真周期"
                              "（同族楼常见真值 63600 / 90000 / 127200）。"
                              "请对照房号标注间距人工定 offset，不要直接用。" % offset)
    return out


def main():
    if len(sys.argv) < 4:
        print("用法: python detect_params.py <dxf路径> <name> <title> "
              "[--out profile.json] [--x-range LO HI]")
        sys.exit(2)
    dxf_path, name, title = sys.argv[1], sys.argv[2], sys.argv[3]
    out_path = None
    if "--out" in sys.argv:
        out_path = sys.argv[sys.argv.index("--out") + 1]
    x_range = None
    if "--x-range" in sys.argv:
        i = sys.argv.index("--x-range")
        x_range = [float(sys.argv[i + 1]), float(sys.argv[i + 2])]

    d = detect(dxf_path, name, title, x_range=x_range)

    if d.get("multi_column") and d.get("column_blocks"):
        print("!! 图纸并排多块，各块如下（cx 是各块自己的 X 中心）:")
        for i, b in enumerate(d["column_blocks"]):
            print("   块%d: X %-24s 宽 %6.1fm 墙 %5d 面  cx=%s"
                  % (i, b["x_range"], b["width_m"], b["walls"], b["cx"]))
        print()

    if "error" in d:
        print(json.dumps(d, ensure_ascii=False, indent=1))
        sys.exit(3)

    if d.get("multi_column"):
        print("!!", d["note"])
    if d.get("offset_unreliable"):
        print("!!", d["note_offset"])

    print(json.dumps(d, ensure_ascii=False, indent=1))

    profile = dict(d)
    for k in ("wall_x_range", "wall_y_range", "offset_score",
              "multi_column", "column_blocks", "note",
              "offset_unreliable", "note_offset"):
        profile.pop(k, None)
    if x_range is not None:
        profile["x_range"] = [round(x_range[0]), round(x_range[1])]
    profile["rooms"] = str(BUILDINGS / name / "rooms.json")
    profile["out_dir"] = str(BUILDINGS / name / "floors")
    profile.update(ALGO_DEFAULTS)

    if out_path:
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(profile, f, ensure_ascii=False, indent=1)
        print("profile.json 已写:", out_path)


if __name__ == "__main__":
    main()
