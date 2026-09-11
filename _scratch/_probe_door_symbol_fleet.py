# -*- coding: utf-8 -*-
"""#90 闭合门符号判据的全舰队验证(只读) —— 定判据 + 查误吞窗户。

判据(由 c019/c054 实测形状推出, 单位 mm):
  一条 flag-closed LWPOLYLINE 若满足下面全部, 就是「门扇画在开启位」的门符号:
    A. 含 1~2 个「小方框」(连续 4~5 点回到起点, 各边 ∈ [100,400]mm) —— 门垛/门框块;
    B. 除方框外还有一条长段 L ∈ [600,2400]mm —— 门扇线(闭位);
    C. 该长段方向与方框的「短边轴」一致 —— 门洞沿墙走向。
  宽度 = L, 中心 = 该段中点, horiz = 该段沿 X。
  窗户画法是「墙线上几条平行线/细长矩形」, 没有小方框 → A 不成立, 天然排除。

输出每栋: 命中数 + 推断门宽分布; 以及「有方框但长段方向与短轴不符」的数量(判据是否漏)。
若某栋命中数异常大或门宽分布离群 → 高度可疑(可能误吞窗户), 人工复核。

用法: python _probe_door_symbol_fleet.py            # 全部非冻结楼
      python _probe_door_symbol_fleet.py c019 c054
"""
import sys, os, math, collections
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path[:0] = [r"D:\gym3d", r"D:\gym3d\backend", r"D:\gym3d\backend\web"]

import ezdxf
from backend.recognizer import classify as C

ROOT = r"D:\gym3d\data\buildings"
FROZEN = {"c006", "c009", "c103", "c104"}
BOX_LO, BOX_HI = 100.0, 400.0      # 门垛块边长(mm)
LEAF_LO, LEAF_HI = 600.0, 2400.0   # 门扇线长(mm)
SPAN_MAX = 3000.0                  # 整符号 bbox 跨度上限(mm)


def seg(a, b):
    return math.hypot(b[0] - a[0], b[1] - a[1])


def find_boxes(pts):
    """找门垛小方框: 连续 4~5 点回到起点且各边 ∈ [BOX_LO,BOX_HI]。

    返回 (boxes, box_segs): boxes=[(起点idx, 点数, bbox)], box_segs=方框各边对应的段下标集合。
    只标记「方框的边」而不是「方框的顶点」——c019 的闭位门扇线两端正好落在两个方框的顶点上,
    按顶点标记会把它一起剔掉, 只剩开启位那条。
    """
    n = len(pts)
    boxes, box_segs = [], set()
    i = 0
    while i < n:
        hit = 0
        for k in (4, 5):
            if i + k >= n or seg(pts[i], pts[i + k]) > 1e-6:
                continue
            sides = [seg(pts[i + j], pts[i + j + 1]) for j in range(k)]
            if all(BOX_LO <= s <= BOX_HI for s in sides[:4]):
                xs = [pts[i + j][0] for j in range(k)]
                ys = [pts[i + j][1] for j in range(k)]
                boxes.append((i, k, (min(xs), min(ys), max(xs), max(ys))))
                box_segs.update((i + j) % n for j in range(k))
                hit = k
                break
        i += hit if hit else 1
    return boxes, box_segs


def door_symbol_info(pts):
    """命中返回 (cx, cy, w_m, horiz); 否则 None。"""
    n = len(pts)
    if n < 5:
        return None
    boxes, box_segs = find_boxes(pts)
    if not (1 <= len(boxes) <= 2):
        return None
    box_w, box_h = boxes[0][2][2] - boxes[0][2][0], boxes[0][2][3] - boxes[0][2][1]
    short_is_x = box_w <= box_h          # 门垛块「短边轴」= 沿墙走向(长边轴 = 墙法向)
    if len(boxes) == 2:
        # 两个门垛: 门洞 = 两垛中心连线, 宽 = 中心距 - 该轴上垛自身尺寸
        c1 = ((boxes[0][2][0] + boxes[0][2][2]) / 2.0, (boxes[0][2][1] + boxes[0][2][3]) / 2.0)
        c2 = ((boxes[1][2][0] + boxes[1][2][2]) / 2.0, (boxes[1][2][1] + boxes[1][2][3]) / 2.0)
        dx, dy = c2[0] - c1[0], c2[1] - c1[1]
        horiz = abs(dx) >= abs(dy)
        if horiz != short_is_x:
            return None
        gap = abs(dx) if horiz else abs(dy)
        ext = box_w if horiz else box_h
        w = gap - ext
        if not (LEAF_LO <= w <= LEAF_HI):
            return None
        return ((c1[0] + c2[0]) / 2.0, (c1[1] + c2[1]) / 2.0, w / 1000.0, horiz)
    # 一个门垛: 闭位门扇线沿垛的短边轴, 宽 = 扇长, 中心 = 扇中点
    best = None
    for i in range(n):
        if i in box_segs:
            continue
        j = (i + 1) % n
        dx, dy = pts[j][0] - pts[i][0], pts[j][1] - pts[i][1]
        if min(abs(dx), abs(dy)) > 20.0:      # 非轴对齐(闭合回边是斜的, 必须滤)
            continue
        L = math.hypot(dx, dy)
        horiz = abs(dx) >= abs(dy)
        if horiz != short_is_x or not (LEAF_LO <= L <= LEAF_HI):
            continue
        if best is None or L > best[0]:
            best = (L, pts[i], pts[j])
    if best is None:
        return None
    L, a, b = best
    return ((a[0] + b[0]) / 2.0, (a[1] + b[1]) / 2.0, L / 1000.0, abs(b[0] - a[0]) >= abs(b[1] - a[1]))


def run(name):
    from run_building import load_profile
    p = load_profile(name)
    doc = ezdxf.readfile(p.dxf)
    msp = doc.modelspace()
    n_all = n_hit = n_boxonly = 0
    widths = collections.Counter()
    for e in msp:
        if e.dxftype() != "LWPOLYLINE" or e.dxf.layer != p.wall_layer:
            continue
        raw = [tuple(q[:2]) for q in e.get_points()]
        if len(raw) < 5:
            continue
        dup = abs(raw[0][0] - raw[-1][0]) <= 1e-6 and abs(raw[0][1] - raw[-1][1]) <= 1e-6
        if not (e.closed or dup):
            continue
        if not C._in_x_range(raw, p):
            continue
        xs = [q[0] for q in raw]
        ys = [q[1] for q in raw]
        if max(max(xs) - min(xs), max(ys) - min(ys)) > SPAN_MAX:
            continue
        n_all += 1
        r = door_symbol_info(raw)
        if r:
            n_hit += 1
            widths[round(r[2] * 10) / 10.0] += 1
        elif len(find_boxes(raw)[0]) in (1, 2):
            n_boxonly += 1
    print("%-6s 小闭合线%4d  判为门%4d  有方框但方向不符%3d   门宽分布%s"
          % (name, n_all, n_hit, n_boxonly, dict(sorted(widths.items()))))


names = sys.argv[1:]
if not names:
    names = [n for n in sorted(os.listdir(ROOT))
             if n.startswith("c") and n[1:].isdigit() and n not in FROZEN]
for nm in names:
    try:
        run(nm)
    except Exception as e:  # noqa: BLE001
        print("%-6s 失败: %s" % (nm, e))
