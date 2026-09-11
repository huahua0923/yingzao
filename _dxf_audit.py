# -*- coding: utf-8 -*-
"""对比审计：识别结果 vs 源图，数值找错。

对每层把「源图墙图层线稿采样点」与「识别出的墙/楼梯井(shapely 覆盖区)」做距离比对：
  漏墙米 ≈ 距任何识别墙>0.4m 的源墙线长度（仅统计>1.0m 的墙线实体，避开注释/小线）。
产出:
  - stdout 排序清单（漏墙率高的层 = 识别漏墙/错切嫌疑）
  - data/buildings/_dxf_audit.html  可疑层目录(带 源图vs识别 对比页直达锚点)
用法: python -u _dxf_audit.py [<name> ...]   不带=全部
"""
import os, sys, json, glob
sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
sys.path[:0] = [r"D:\gym3d\backend\web", r"D:\gym3d\backend\vision",
                r"D:\gym3d\backend", r"D:\gym3d"]
import ezdxf
import shapely.geometry as sg
from shapely.ops import unary_union
import shapely as _sh
import _dxf_cad_render as R
from recognizer.profile import to_local, floor_of

BASE = r"D:\gym3d\data\buildings"
WALL_DIST = 0.40      # 点距识别墙<=此=已识别
SAMP = 0.35           # 采样步长(m)
MIN_ENTITY = 1.0      # 只统计>=1m 的墙线实体


def _thin_core(poly, r=0.15):
    """只取墙体『壳』：薄墙内缩后消失→返回整墙；整块填充→只留靠边壳带，不白送内部。
    这样外墙若被存成含内部的大环，不会用它盖住整层、遮掉内墙漏检。"""
    try:
        inner = poly.buffer(-r)
        if inner.is_empty or inner.area <= 0:
            return poly
        return poly.difference(inner)
    except Exception:
        return poly


def _walls_geom(fl):
    """floor JSON walls + 楼梯井/楼梯 → shapely 覆盖区(墙皮壳)。"""
    gs = []
    for w in fl.get("walls", []):
        ring = [(float(p[0]), float(p[1])) for p in w.get("poly", [])]
        if len(ring) < 3:
            continue
        try:
            # 合并式楼(墙=整层环 + 房间洞)必须把洞带进来，否则把整层当实心 slab、
            # 再经 _thin_core 只剩外圈 0.15m 壳 → 内部所有隔墙/走廊墙被误判漏墙。
            holes = []
            for h in (w.get("holes", []) or []):
                hg = [(float(pp[0]), float(pp[1])) for pp in h]
                if len(hg) >= 3:
                    holes.append(hg)
            try:
                p = sg.Polygon(ring, holes) if holes else sg.Polygon(ring)
            except Exception:
                p = sg.Polygon(ring)   # 洞异常则退回无洞(不丢这面墙)
            if not p.is_valid:
                p = p.buffer(0)
            if not p.is_empty and p.area > 0:
                gs.append(_thin_core(p))
        except Exception:
            continue
    for s in fl.get("stairwells", []):
        try:
            gs.append(sg.box(s["x0"], s["yBot"], s["x1"], s["yTop"]))
        except Exception:
            pass
    for s in fl.get("stairs", []):
        if isinstance(s, dict) and s.get("poly"):
            ring = [(float(p[0]), float(p[1])) for p in s["poly"]]
            if len(ring) >= 3:
                try:
                    gs.append(sg.Polygon(ring))
                except Exception:
                    pass
    return unary_union(gs) if gs else None


def _split_runs(pts):
    """在尖角(>~35°)处把折线拆成直段 runs。"""
    runs = []
    cur = [pts[0]]
    for k in range(1, len(pts)):
        cur.append(pts[k])
        if k + 1 < len(pts):
            a = (pts[k][0] - pts[k - 1][0], pts[k][1] - pts[k - 1][1])
            b = (pts[k + 1][0] - pts[k][0], pts[k + 1][1] - pts[k][1])
            la = (a[0] ** 2 + a[1] ** 2) ** 0.5
            lb = (b[0] ** 2 + b[1] ** 2) ** 0.5
            if la > 1e-9 and lb > 1e-9:
                dot = (a[0] * b[0] + a[1] * b[1]) / (la * lb)
                ang = abs(__import__("math").acos(max(-1.0, min(1.0, dot))))
                if ang > 0.6:          # >35°
                    runs.append(cur)
                    cur = [pts[k]]
    if len(cur) >= 2:
        runs.append(cur)
    return runs


def _sagitta(run):
    """直段对弦线的最大垂直偏离。"""
    x0, y0 = run[0]; x1, y1 = run[-1]
    dx, dy = x1 - x0, y1 - y0
    L2 = dx * dx + dy * dy
    if L2 < 1e-12:
        return 0.0
    dev = 0.0
    for x, y in run[1:-1]:
        d = abs(dy * (x - x0) - dx * (y - y0)) / (L2 ** 0.5)
        if d > dev:
            dev = d
    return dev



def _seg_dense(a, b, dist):
    """直线段 a→b 按 dist 插值(含两端点)。"""
    x0, y0 = a; x1, y1 = b
    L = ((x1 - x0) ** 2 + (y1 - y0) ** 2) ** 0.5
    if L <= dist + 1e-9:
        return [a]
    n = max(1, int(L / dist))
    return [(x0 + (x1 - x0) * t / n, y0 + (y1 - y0) * t / n) for t in range(n)] + [b]


def _dense_pts(e, dist):
    """把 LINE/LWPOLYLINE 每一直段按 dist 插值密化(原始dxf坐标)。
    ezdxf path.flattening 只加密曲线、直线仍按原顶点→长外墙按顶点计,
    使长墙欠采样且端点噪声主导漏墙率。直线必须按长度插值。"""
    if e.dxftype() == "LINE":
        try:
            a = (e.dxf.start.x, e.dxf.start.y); b = (e.dxf.end.x, e.dxf.end.y)
        except Exception:
            return []
        return _seg_dense(a, b, dist)
    if e.dxftype() == "LWPOLYLINE":
        try:
            raw = e.get_points("xy"); closed = bool(e.closed)
        except Exception:
            return []
        if len(raw) < 2:
            return []
        try:
            if any(abs(v[2]) > 1e-9 for v in e.get_points("xyb")):
                import ezdxf.path as _ezp
                return [(float(v.x), float(v.y)) for v in _ezp.make_path(e).flattening(dist)]
        except Exception:
            pass
        pts = []
        budget = 0
        for i in range(len(raw) - 1):
            seg = _seg_dense(raw[i], raw[i + 1], dist)[:-1]
            budget += len(seg)
            if budget > 200000:      # 单实体展开上限(超长装饰/尺寸线类, 非墙)
                return []
            pts += seg
        pts.append(raw[-1])
        if closed:
            seg = _seg_dense(raw[-1], raw[0], dist)[:-1]
            if budget + len(seg) > 200000:
                return []
            pts += seg
            pts.append(raw[0])
        return pts
    return []
def _dense_local(lv, dist, closed):
    """局部坐标点列 lv 按 dist(米)插值密化。必须在『局部/米』坐标做——
    原图坐标 ~1000× 局部尺(1m≈1000raw), 在 raw 上插值会把每面墙展开上万点。"""
    out = []
    budget = 0
    segs = [(lv[i], lv[i + 1]) for i in range(len(lv) - 1)]
    if closed and len(lv) > 2:
        segs.append((lv[-1], lv[0]))
    for (a, b) in segs:
        x0, y0 = a; x1, y1 = b
        L = ((x1 - x0) ** 2 + (y1 - y0) ** 2) ** 0.5
        n = int(L / dist) if L > 0 else 0
        budget += n
        if budget > 400000:          # 单实体上限(非墙的巨折线)
            return []
        for t in range(n):
            out.append((x0 + (x1 - x0) * t / n, y0 + (y1 - y0) * t / n))
    # 相邻去重(joint点重复无意义)
    ded = []
    for q in out:
        if ded and abs(q[0] - ded[-1][0]) < 1e-9 and abs(q[1] - ded[-1][1]) < 1e-9:
            continue
        ded.append(q)
    if ded and len(ded) < 2:
        return []
    return ded


def _source_wall_points(doc, p, F, box):
    """该层源图『墙图层』主副本**直墙脸**采样点(局部坐标, m)。
    门开启弧/踏步等以多段折线逼近、整体弯曲 → 直段偏离>0.12m 剔除；房间矩形四边各算直墙。"""
    layer = getattr(p, "wall_layer", None) or "4.2墙体"
    x0, y0, x1, y1 = box
    bw = (x1 - x0) + 5.0
    bh = (y1 - y0) + 5.0
    out = []
    pool = []
    for e in doc.modelspace():
        if e.dxftype() == "INSERT":
            pool.extend(e.virtual_entities() or [])
        elif e.dxftype() in ("LWPOLYLINE", "LINE", "ARC", "CIRCLE", "SPLINE"):
            pool.append(e)
    CURVED = ("ARC", "CIRCLE", "SPLINE")
    for e in pool:
        if (getattr(e.dxf, "layer", "") or "") != layer:
            continue
        if e.dxftype() in CURVED:
            # 曲要素(圆弧/圆/样条)识别器从不建模（直墙= LWPOLYLINE/LINE），
            # 计作“漏墙”是假阳性（c041/c026/c079…曾被 ~千% 虚漏刷屏）。跳过。
            continue
        xy = R._entity_floor(e)
        if xy is None:
            continue
        try:
            f = int(round(floor_of(p, xy[0], xy[1])))
        except Exception:
            continue
        if f != F:
            continue
        try:
            if e.dxftype() == "LINE":
                rv = [(e.dxf.start.x, e.dxf.start.y), (e.dxf.end.x, e.dxf.end.y)]
            else:
                rv = list(e.get_points("xy"))
        except Exception:
            continue
        if len(rv) < 2:
            continue
        lv = [to_local(p, float(a), float(b), F) for a, b in rv]
        if e.dxftype() == "LWPOLYLINE" and getattr(e, "closed", False):
            # 闭口整面填充… 原始顶点算(密化前)，省掉对超大图形的展开
            try:
                lc = lv + [lv[0]]
                pg = sg.Polygon(lc)
                if pg.is_valid and pg.area > 1e-6 and pg.area / pg.length > 1.0:
                    continue
            except Exception:
                pass
        # 主副本：先在原始顶点 bBox 上过滤(便宜)，拒绝的实体不再密化
        ax = min(q[0] for q in lv); bx = max(q[0] for q in lv)
        ay = min(q[1] for q in lv); by = max(q[1] for q in lv)
        if (bx - ax) > bw or (by - ay) > bh:
            continue
        if bx < x0 - 1.5 or ax > x1 + 1.5 or by < y0 - 1.5 or ay > y1 + 1.5:
            continue
        closedf = (e.dxftype() == "LWPOLYLINE" and bool(getattr(e, "closed", False)))
        local = _dense_local(lv, SAMP, closedf)
        if not local:
            continue
        for run in _split_runs(local):
            L = sum(((run[i + 1][0] - run[i][0]) ** 2 +
                     (run[i + 1][1] - run[i][1]) ** 2) ** 0.5
                    for i in range(len(run) - 1))
            if L < MIN_ENTITY:
                continue
            if _sagitta(run) > 0.12:      # 弧形(门开启/曲线)非直墙
                continue
            out.extend(run)
    return out


def _door_zone_mask(fl):
    """门符号/门扇线在源图上常画成墙图层上的 1~1.5m 折线（c057 等宿舍的 14pt 门块、
    长 comb 门洞内的回折段）。识别器不把它当墙——该处模型正确地留作门洞，计作漏墙是
    假阳性（c057 F1-4 曾因此虚报 14~17%）。返回门中心圆 mask 供过滤。
    半径 = 门半宽 + 0.5m（覆盖门扇线 + 贴门洞的墙皮点，不影响真墙段）。"""
    mask = []
    for d in fl.get("doors", []):
        try:
            cx, cy = float(d["x"]), float(d["y"])
            r = max(float(d.get("w", 1.0)), 0.8) / 2 + 0.5
            mask.append((cx, cy, r))
        except Exception:
            continue
    return mask


def _in_any_door_zone(x, y, mask):
    for cx, cy, r in mask:
        dx, dy = x - cx, y - cy
        if dx * dx + dy * dy <= r * r:
            return True
    return False


def audit_building(name):
    import run_step
    p = run_step.load_profile(name)
    doc = ezdxf.readfile(p.dxf)
    fd = os.path.join(BASE, name, "floors")
    floors = sorted(int(os.path.basename(f)[5:-5])
                    for f in glob.glob(os.path.join(fd, "floor*.json")))
    res = []
    for F in floors:
        try:
            fl = json.load(open(os.path.join(fd, f"floor{F}.json"), encoding="utf-8"))
            ol = fl.get("outline")
            if not ol:
                continue
            box = (min(q[0] for q in ol), min(q[1] for q in ol),
                   max(q[0] for q in ol), max(q[1] for q in ol))
            cov = _walls_geom(fl)
            mask = _door_zone_mask(fl)
            src = [q for q in _source_wall_points(doc, p, F, box)
                   if not (mask and _in_any_door_zone(q[0], q[1], mask))]
            if not src:
                continue
            if cov is None or cov.is_empty:
                miss_m = sum(SAMP for _ in src)  # 无识别墙→全漏
                miss_pct = 1.0
            else:
                # 缓冲一次→集合隶属判定(远快于逐点 distance)
                prep = _sh.prepared.prep(cov.buffer(WALL_DIST))
                tot_m = len(src) * SAMP
                miss_m = 0.0
                for (x, y) in src:
                    if not prep.covers(sg.Point(x, y)):
                        miss_m += SAMP
                miss_pct = miss_m / max(tot_m, 1e-9)
            # 覆盖上下文：识别墙总面积 / 楼板面积
            walls = fl.get("walls", [])
            wall_area = 0.0
            for w in walls:
                if w.get("type") == "parapet":
                    continue
                ring = [(float(p[0]), float(p[1])) for p in w.get("poly", [])]
                if len(ring) < 3:
                    continue
                try:
                    pg = sg.Polygon(ring)
                    if not pg.is_valid:
                        pg = pg.buffer(0)
                    wall_area += pg.area
                except Exception:
                    continue
            ol_area = sg.Polygon(ol).area if len(ol) >= 3 else 0
            res.append(dict(building=name, F=F, miss_m=round(miss_m, 1),
                            miss_pct=round(miss_pct * 100, 1),
                            nwalls=len(walls),
                            wall_cover=round(wall_area / ol_area * 100, 1) if ol_area else 0,
                            doors=len(fl.get("doors", [])),
                            stairs=len(fl.get("stairwells", [])),
                            rooms=len(fl.get("rooms", [])),
                            src_m=round(len(src) * SAMP, 1)))
        except Exception as e:  # noqa: BLE001
            print(f"  ERR {name} F{F}: {str(e)[:90]}")
    return res


def main():
    names = sorted(d for d in os.listdir(BASE)
                   if os.path.isdir(os.path.join(BASE, d, "floors")))
    if sys.argv[1:]:
        names = [n for n in names if n in sys.argv[1:]]
    allres = []
    for i, name in enumerate(names, 1):
        allres += audit_building(name)
        print(f"[{i}/{len(names)}] {name:6s} done ({len(allres)} floors)", flush=True)
    # 只看“有实质源墙量”的层，漏墙率排序
    pool = [r for r in allres if r["src_m"] >= 50]
    pool.sort(key=lambda r: -r["miss_pct"])
    print("\n=== 漏墙率最高 25 层 (源墙>=50m) ===")
    for r in pool[:25]:
        print(f"  {r['building']:6s} {r['F']+1:>2d}层 漏墙率{r['miss_pct']:5.1f}% "
              f"({r['miss_m']}/{r['src_m']}m) 墙{r['nwalls']} 覆盖{r['wall_cover']}% "
              f"门{r['doors']} 梯井{r['stairs']} 房{r['rooms']}")
    with open(os.path.join(BASE, "_dxf_audit.html"), "w", encoding="utf-8") as f:
        f.write(_audit_html(pool))
    print(f"\n共审计 {len(allres)} 层 / 写 data/buildings/_dxf_audit.html")


def _audit_html(pool):
    lis = []
    for r in pool:
        warn = []
        if r["miss_pct"] > 15:
            warn.append(f"漏墙率{r['miss_pct']}%")
        if r["wall_cover"] > 20 and r["nwalls"] <= 12:
            warn.append(f"覆盖{r['wall_cover']}%仅{r['nwalls']}墙(疑融合块)")
        if r["doors"] == 0 and r["rooms"] > 8:
            warn.append("门=0 房多(疑漏门)")
        lis.append(
            f"<li><a href=\"{r['building']}/compare.html\">{r['building']} · {r['F']+1}层</a> "
            f"漏墙{r['miss_pct']}% 门{r['doors']} 梯井{r['stairs']} 墙{r['nwalls']} "
            f"<b style=color:#b00>{' ⚠ '.join(warn)}</b></li>")
    return ("<!DOCTYPE html><html lang=zh><head><meta charset=utf-8>"
            "<title>识别对比审计：疑似漏墙层</title><style>"
            "body{font-family:sans-serif;background:#eef0f3;padding:18px}"
            "h1{font-size:18px;color:#222}p{font-size:12px;color:#555}"
            "a{color:#0366d6;text-decoration:none}li{margin:6px 0}"
            "</style></head><body>"
            "<h1>源图 vs 识别 · 自动审计（漏墙率排序）</h1>"
            "<p>漏墙率 = 距识别墙&gt;0.4m 的源墙线占比（源墙≥50m 才统计）。点链接到该楼对比页逐层核对。</p><ul>"
            + "".join(lis) + "</ul></body></html>")


if __name__ == "__main__":
    main()
