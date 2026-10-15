# -*- coding: utf-8 -*-
"""A1 侦察尺：量一份 DXF 的「可迁移性」—— 链写死的那些约定，在这份图上还成不成立。

用法:  python probe_dxf.py <dxf路径>  [--top N]

★ 量什么（逐条对应 c006 链写死的东西，见方案 §9.2 A1 行）：
  ① 图层名表        → 链查 `4.2墙体` / `4.1结构柱`，这份图有没有、叫不叫这个
  ② 块名前缀        → 链查 `$DorLib2D$`（门）、后缀 `130`（层门）
  ③ 图纸标题 TEXT   → 链把「层→图纸矩形」写死成规则网格；标题点才是通用锚
  ④ 空间分块        → 把模型空间按大间隙切块，数「这图有几张平面图」、各自 bbox

★ 量具盲区（必须声明）：
  ① 只读模型空间（msp）实体，paper space / 块定义内部**不单独展开**（除非被 INSERT 引用）。
  ② 图层统计按**每实体一次**计，块引用只算 1 次、不摊开内部图元 ⇒ 「墙段数」不等于链里的 seg 数。
  ③ 标题识别靠正则打「层/平面图/标高」等词，**非标准命名会漏**（漏了不等于没有）。
  ④ 分块用固定间隙阈值，**图幅间距小于阈值就会并成一块**（阈值写死在 GAP，换图可能要调）。
"""
import sys
import re
import collections
import os

sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
import ezdxf

GAP = 60000.0        # 分块间隙阈值（C006 图幅间距 ~10000/290000，取 60000 能分开）

TITLE_RE = re.compile(r"(地下\d*层|\d+层|平面图|标高|屋面|夹层|机房|首层|架空层|屋顶)")


def layer_census(msp):
    lc = collections.Counter()
    for e in msp:
        lc[e.dxf.layer] += 1
    return lc


def block_prefixes(msp, layer):
    pfx = collections.Counter()
    for e in msp:
        if e.dxftype() == "INSERT" and e.dxf.layer == layer:
            nm = e.dxf.name or ""
            pfx[nm[:12]] += 1
    return pfx


def titles(msp):
    out = []
    for e in msp:
        t = e.dxftype()
        if t == "TEXT":
            s = e.dxf.text
            p = (e.dxf.insert.x, e.dxf.insert.y)
        elif t == "MTEXT":
            s = e.text
            p = (e.dxf.insert.x, e.dxf.insert.y)
        else:
            continue
        s = (s or "").strip()
        if s and TITLE_RE.search(s):
            out.append((s, p))
    return out


def clusters(msp):
    """把实体锚点按大间隙做一维并查（先按 X 再按 Y 切），返回每块的 (n, bbox)。"""
    pts = []
    for e in msp:
        t = e.dxftype()
        try:
            if t in ("LINE",):
                pts += [(e.dxf.start.x, e.dxf.start.y), (e.dxf.end.x, e.dxf.end.y)]
            elif t in ("LWPOLYLINE", "POLYLINE"):
                for p in e.get_points():
                    pts.append((p[0], p[1]))
            elif t in ("TEXT", "MTEXT", "INSERT", "CIRCLE", "POINT"):
                ins = e.dxf.insert if t != "CIRCLE" else e.dxf.center
                pts.append((ins.x, ins.y))
            elif t == "ARC":
                pts.append((e.dxf.center.x, e.dxf.center.y))
        except Exception:
            continue
    if not pts:
        return []
    # 网格粗分块：把点吸到 GAP/2 的格上，再做 8 连通
    cell = GAP / 2.0
    grid = {}
    for x, y in pts:
        grid.setdefault((int(x // cell), int(y // cell)), []).append((x, y))
    seen = set()
    out = []
    for key in list(grid):
        if key in seen:
            continue
        stack = [key]
        seen.add(key)
        cells = []
        while stack:
            k = stack.pop()
            cells.append(k)
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    nk = (k[0] + dx, k[1] + dy)
                    if nk in grid and nk not in seen:
                        seen.add(nk)
                        stack.append(nk)
        cp = [p for c in cells for p in grid[c]]
        xs = [p[0] for p in cp]
        ys = [p[1] for p in cp]
        out.append((len(cp), (min(xs), min(ys), max(xs), max(ys))))
    out.sort(key=lambda r: -r[0])
    return out


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    src = sys.argv[1]
    if not os.path.isfile(src):
        print("MISSING:", src)
        return 2
    doc = ezdxf.readfile(src)
    msp = doc.modelspace()
    print("DXF :", os.path.basename(src), " %.1f MB" % (os.path.getsize(src) / 1e6))
    print("DWG version :", doc.dxfversion)
    print("units :", getattr(doc.header, "$INSUNITS", "?"))

    lc = layer_census(msp)
    print("\n== ① 图层（%d 个，按实体数） ==" % len(lc))
    KEY = ("墙", "柱", "门", "窗", "梯", "电梯", "楼板", "梁", "轴", "标")
    for name, n in lc.most_common(40):
        tag = " ★" if any(k in name for k in KEY) else ""
        print("  %-28s %7d%s" % (name[:28], n, tag))

    print("\n== ② 门/柱 的块名前缀 ==")
    for lyr in ("4.2墙体", "4.1结构柱", "墙", "柱"):
        if lyr in lc:
            pfx = block_prefixes(msp, lyr)
            print("  [%s] 块 %d 种:" % (lyr, len(pfx)), dict(pfx.most_common(6)))

    print("\n== ③ 图纸标题类 TEXT（前 30） ==")
    ts = titles(msp)
    print("  命中 %d 条" % len(ts))
    for s, (x, y) in ts[:30]:
        print("    (%9.0f, %9.0f)  %s" % (x, y, s[:48]))

    print("\n== ④ 空间分块（GAP=%.0f） ==" % GAP)
    cl = clusters(msp)
    print("  块数 %d" % len(cl))
    for n, (x0, y0, x1, y1) in cl[:20]:
        print("    %8d 点  bbox x[%9.0f,%9.0f] y[%9.0f,%9.0f]  %.1f x %.1f m"
              % (n, x0, x1, y0, y1, (x1 - x0) / 1000, (y1 - y0) / 1000))
    return 0


sys.exit(main())
