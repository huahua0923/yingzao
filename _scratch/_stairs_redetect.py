# -*- coding: utf-8 -*-
"""改进楼梯井检测原型(只读): 在 DXF 原片段上跑检测, 加"每行x覆盖<=6m"物理门,
对比现状 floor JSON 的井。决定哪些楼能安全重导出、哪些是走廊链式误判。
"""
import sys, math, json, os
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import ezdxf
from run_building import load_profile
from backend.recognizer import classify
from backend.recognizer.profile import to_local, floor_of

ALL = sorted(os.listdir(r"D:\gym3d\data\buildings"))
SCOPE = ["c017","c026","c043","c044","c045","c046","c054","c055","c056","c057",
         "c072","c073","c079","c080","c083","c084","c085","c086","c109",
         "ny27","ny28","ny29","c018","c019","c031","c032","c033"]  # 后几个为对照组(sane)
MAXROW = 6.0   # 一行(同一y)的水平段x覆盖上限 -> 超=走廊/房间墙链

def cands_for(p, walls, F):
    out = []
    for pts in walls:
        cx = sum(q[0] for q in pts) / len(pts)
        if not any(abs(floor_of(p, cx, y) - F) < 0.5 for y in [q[1] for q in pts]):
            continue
        local = [to_local(p, x, y, F) for x, y in pts]
        for i in range(len(local) - 1):
            a, b = local[i], local[i + 1]
            dx, dy = b[0] - a[0], b[1] - a[1]
            L = math.hypot(dx, dy)
            if L < 0.05 or min(abs(dx), abs(dy)) > 0.02:
                continue
            if abs(dx) >= abs(dy) and 0.8 <= L <= 3.0:
                out.append(((a[0] + b[0]) / 2, a[1], min(a[0], b[0]), max(a[0], b[0])))
    return out

def detect(cands):
    n = len(cands)
    parent = list(range(n))
    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]; x = parent[x]
        return x
    def merge(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb
    for i in range(n):
        cxi, cyi, _, _ = cands[i]
        for j in range(i + 1, n):
            cxj, cyj, _, _ = cands[j]
            if abs(cyi - cyj) <= 0.35 and abs(cxi - cxj) <= 3.0:
                merge(i, j)
    groups = {}
    for i in range(n):
        groups.setdefault(find(i), []).append(cands[i])
    res = []
    for g in groups.values():
        if len(g) < 4:
            continue
        # 新门: 每行x覆盖
        rowcov = {}
        for cx, cy, x0, x1 in g:
            rowcov.setdefault(cy, []).append((x0, x1))
        worst = 0.0
        for cy, spans in rowcov.items():
            cov = max(x1 for _, x1 in spans) - min(x0 for x0, _ in spans)
            worst = max(worst, cov)
        xs = [c[2] for c in g] + [c[3] for c in g]
        ys = [c[1] for c in g]
        span = max(ys) - min(ys)
        if span < 1.5:
            continue
        if worst > MAXROW:   # 某一行横跨>6m -> 墙链, 非楼梯
            continue
        res.append((round(min(xs), 2), round(max(xs), 2), round(min(ys), 2),
                    round(max(ys), 2), span, len(rowcov)))
    return res

for name in SCOPE:
    d = r"D:\gym3d\data\buildings\%s" % name
    if not os.path.isdir(d):
        continue
    p = load_profile(name)
    doc = ezdxf.readfile(p.dxf)
    walls, doors, stairs, cols = classify.classify(doc.modelspace(), p)
    floors = sorted({floor_of(p, sum(q[0] for q in w) / len(w), sum(q[1] for q in w) / len(w)) for w in walls})
    n_exist = 0
    for F in floors:
        fp = os.path.join(d, "floors", f"floor{F}.json")
        exist = []
        if os.path.exists(fp):
            exist = json.load(open(fp, encoding="utf-8")).get("stairwells", [])
        n_exist += len(exist)
        prop = detect(cands_for(p, walls, F))
        pf = ",".join("x%.1f-%.1fy%.1f-%.1f" % (a, b, c, e) for a, b, c, e, s, n in prop)
        ef = ",".join("x%.1f-%.1fy%.1f-%.1f" % (w["x0"], w["x1"], w["yBot"], w["yTop"]) for w in exist)
        flag = "" if len(exist) == len(prop) else "  <== 数量差"
        print("%s F%-2d 现状[%d]%s\n       建议[%d]%s%s" % (name, F, len(exist), ef, len(prop), pf, flag))
    print("----")
