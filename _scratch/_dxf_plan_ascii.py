# -*- coding: utf-8 -*-
"""DXF 平面 ASCII 渲染(只读): 把指定楼层的 LWPOLYLINE 墙段/梯级画成字符地图。
用法: _dxf_plan_ascii.py c017 1 [y0 y1] [res]
默认自动取该楼层 outline 的 x 范围与"y 取覆盖该层所有墙段的中带"，可传 y0 y1 截取。
字符: #=墙/梯段线条经过, 空格=空; 另叠加 floor JSON 的 stairwell 盒(用 s)、房间质心(.)。
输出到 _plan_<name>_f<F>.txt 同时打印前几行坐标说明。
"""
import sys, math, json, os
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import ezdxf
from run_building import load_profile
from backend.recognizer import classify
from backend.recognizer.profile import to_local, floor_of

name = sys.argv[1]
F = int(sys.argv[2])
p = load_profile(name)
doc = ezdxf.readfile(p.dxf)
msp = doc.modelspace()
walls, doors, stairs, cols = classify.classify(msp, p)

# 层带: 该楼层所有墙段(整条polyline质心落F)的 local y
seg_local = []   # (x0,y0,x1,y1)
for pts in walls:
    cx = sum(q[0] for q in pts) / len(pts)
    if not any(abs(floor_of(p, cx, y) - F) < 0.5 for y in [q[1] for q in pts]):
        continue
    loc = [to_local(p, x, y, F) for x, y in pts]
    for i in range(len(loc) - 1):
        a, b = loc[i], loc[i + 1]
        dx, dy = b[0] - a[0], b[1] - a[1]
        if math.hypot(dx, dy) < 0.1:
            continue
        seg_local.append((a[0], a[1], b[0], b[1]))

xs = [v for s in seg_local for v in (s[0], s[2])]
ys = [v for s in seg_local for v in (s[1], s[3])]
x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
# 可选窗口: x0 x1 y0 y1 res
if len(sys.argv) > 3 and sys.argv[3] != "-":
    x0 = float(sys.argv[3])
if len(sys.argv) > 4:
    x1 = float(sys.argv[4])
if len(sys.argv) > 5:
    y0 = float(sys.argv[5])
if len(sys.argv) > 6:
    y1 = float(sys.argv[6])
res = float(sys.argv[7]) if len(sys.argv) > 7 else 0.4
# 房间质心 (floor JSON)
fjson = os.path.join(r"D:\gym3d\data\buildings", name, "floors", f"floor{F}.json")
rooms = []
wells = []
if os.path.exists(fjson):
    fl = json.load(open(fjson, encoding="utf-8"))
    rooms = [(r["poly"], r.get("number", "")) for r in fl.get("rooms", [])]
    wells = fl.get("stairwells", [])

ncols = int((x1 - x0) / res) + 1
nrows = int((y1 - y0) / res) + 1
grid = [[" " for _ in range(ncols)] for _ in range(nrows)]

def put(cx, cy, ch):
    ix = int((cx - x0) / res); iy = int((cy - y0) / res)
    if 0 <= ix < ncols and 0 <= iy < nrows:
        if grid[iy][ix] == " ":
            grid[iy][ix] = ch

for a, b, c, d in seg_local:
    n = max(2, int(math.hypot(c - a, d - b) / res * 2))
    for k in range(n + 1):
        t = k / n
        put(a + (c - a) * t, b + (d - b) * t, "#")
# 房间: 质心标 r, 井盒标 S
for poly, num in rooms:
    xm = sum(q[0] for q in poly) / len(poly); ym = sum(q[1] for q in poly) / len(poly)
    put(xm, ym, ".")
for s in wells:
    for yy in range(int(s["yBot"] / res) * 0, 0):  pass
    xs_ = [s["x0"], s["x1"]]; ys_ = [s["yBot"], s["yTop"]]
    for yy in (s["yBot"], s["yTop"]):
        for xx in range(int((s["x0"] - x0) / res), int((s["x1"] - x0) / res) + 1):
            if 0 <= xx < ncols:
                iy = int((yy - y0) / res)
                if 0 <= iy < nrows:
                    grid[iy][xx] = "S"
    for xx in (s["x0"], s["x1"]):
        for yy in range(int((s["yBot"] - y0) / res), int((s["yTop"] - y0) / res) + 1):
            if 0 <= yy < nrows:
                ix = int((xx - x0) / res)
                if 0 <= ix < ncols:
                    grid[yy][ix] = "S"

outf = f"_plan_{name}_f{F}.txt"
with open(outf, "w", encoding="utf-8") as fo:
    fo.write(f"# {name} F{F}  x:{x0:.1f}~{x1:.1f} y:{y0:.1f}~{y1:.1f} res={res}m  字符: #=线条 .房间质心 S=floorJSON楼梯井盒\n")
    for iy in range(nrows - 1, -1, -1):
        yv = y0 + iy * res
        if yv > y1:
            continue
        line = "".join(grid[iy])
        fo.write(line + "\n")
print("已写", outf, "尺寸", ncols, "x", nrows)
