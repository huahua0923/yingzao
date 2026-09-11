# -*- coding: utf-8 -*-
"""审计增强：在漏墙率基础上给可疑楼层做「错位/缺墙」判别，输出人话分组报告。

对漏墙率>=15% 的层扫 ±3m(step0.5) 平移：
  对齐OK       覆盖>=85%
  平移错位      平移后>=80% 且比0偏移 +20% 以上  → 墙都在,只是对错副本/整体平移(给偏移量)
  错位+缺墙     平移只到 50~80% 或提升 10~20%    → 一部分平移,另一部分真缺
  真缺墙/不一致 平移后仍<50% 或几乎不提升         → 源图有墙,识别真没有(或识别本身错乱)
并额外给出「已盖/真漏」各自的空间中心与范围，方便肉眼对照 compare 页。
用法: python -u _dxf_audit_report.py [<name> ...]   (不带=全部楼；只重写 _dxf_audit_report.html)

产物归属：_dxf_audit.html 归 _dxf_audit.py（也是控制台 audit 阶段直接写的文件），
本脚本只写 _dxf_audit_report.html —— 两者不可共用一个路径。
"""
import os, sys, json, glob
sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
sys.path[:0] = [r"D:\gym3d\backend\web", r"D:\gym3d\backend\vision",
                r"D:\gym3d\backend", r"D:\gym3d"]
import shapely.geometry as sg
import _dxf_audit as A
import run_step, ezdxf

BASE = r"D:\gym3d\data\buildings"
THRESH = 15.0                # 只判别漏墙率>=15% 的层
GRID = [round(v * 0.5, 1) for v in range(-8, 9)]   # ±4m step0.5
MAXP = 350


def classify(name, F, base_stats):
    """返回 dict(cls, off, bestcov, regions...) 或在源点不足时 cls='-'. """
    try:
        p = run_step.load_profile(name)
        doc = ezdxf.readfile(p.dxf)
        fj = os.path.join(BASE, name, "floors", f"floor{F}.json")
        fl = json.load(open(fj, encoding="utf-8"))
        ol = fl.get("outline")
        if not ol:
            return dict(cls="无轮廓")
        box = (min(q[0] for q in ol), min(q[1] for q in ol),
               max(q[0] for q in ol), max(q[1] for q in ol))
        cov = A._walls_geom(fl)
        if cov is None or cov.is_empty:
            return dict(cls="无识别墙几何")
        src = A._source_wall_points(doc, p, F, box)
        if len(src) < 60:
            return dict(cls="源点少")
        pts = src[::max(1, len(src) // MAXP)]

        def hit(dx, dy):
            return sum(1 for (x, y) in pts
                       if cov.distance(sg.Point(x - dx, y - dy)) <= A.WALL_DIST) / len(pts)

        c0 = hit(0.0, 0.0)
        best = (c0, 0.0, 0.0)
        for dx in GRID:
            for dy in GRID:
                if dx == 0 and dy == 0:
                    continue
                c = hit(dx, dy)
                if c > best[0]:
                    best = (c, dx, dy)
        bc, bdx, bdy = best
        gain = bc - c0
        if c0 >= 0.85:
            cls = "对齐OK"
        elif bc >= 0.80 and gain >= 0.20:
            cls = "平移错位"
        elif gain >= 0.10 and bc >= 0.55:
            cls = "错位+缺墙"
        else:
            cls = "真缺墙/不一致"
        off = "" if cls == "对齐OK" else f"(最优平移{bdx:+.1f},{bdy:+.1f}m→覆盖{bc*100:.0f}%)"
        # 已盖/真漏 空间分布
        covp = [(x, y) for (x, y) in pts if cov.distance(sg.Point(x, y)) <= A.WALL_DIST]
        misp = [(x, y) for (x, y) in pts if cov.distance(sg.Point(x, y)) > A.WALL_DIST]
        reg = ""
        for tag, grp in (("已盖", covp), ("真漏", misp)):
            if len(grp) >= 8:
                gx = [q[0] for q in grp]; gy = [q[1] for q in grp]
                reg += (f"{tag}{len(grp)*100//len(pts)}%"
                        f"@(x{min(gx):.0f}~{max(gx):.0f},y{min(gy):.0f}~{max(gy):.0f}) ")
        return dict(cls=cls, off=off, reg=reg, base=round(c0 * 100, 1))
    except Exception as e:  # noqa: BLE001
        return dict(cls=f"ERR {str(e)[:60]}")


def html_rows(groups):
    """groups: {cls: [ (r, diag), ...] } → html"""
    head = ("<!DOCTYPE html><html lang=zh><head><meta charset=utf-8>"
            "<title>识别对比审计：错位/缺墙判别</title><style>"
            "body{font-family:sans-serif;background:#eef0f3;padding:18px}"
            "h1{font-size:18px;color:#222}p.leg{font-size:12px;color:#555}"
            "h2{font-size:14px;color:#222;margin:18px 0 6px;border-bottom:1px solid #ccc}"
            "a{color:#0366d6;text-decoration:none}li{margin:4px 0;font-size:13px}"
            "small{color:#777}</style></head><body>"
            "<h1>源图 vs 识别 · 判别报告（漏墙率≥15% 的层）</h1>"
            "<p class=leg>对源墙采样点做平移扫描：对齐OK=已吻合；平移错位=墙都在只是整层对错副本/偏移，"
            "属对齐修复；错位+缺墙=一部分平移可救、另一部分真缺；真缺墙/不一致=识别与源图大面积对不上，"
            "需按图重建模。点链接到对比页逐层核对（括号=判别明细）。</p>")
    body = head
    for cls, rows in groups.items():
        body += f"<h2>{cls}（{len(rows)} 层）</h2><ul>"
        for r, d in rows:
            base = f"漏墙{r['miss_pct']}%"
            detail = (d.get("off", "") + " " + d.get("reg", "")).strip()
            body += (f'<li><a href="{r["building"]}/compare.html">{r["building"]} · {r["F"]+1}层</a> '
                     f'门{r["doors"]} 梯井{r["stairs"]} 墙{r["nwalls"]} {base} '
                     f'<small>{detail}</small></li>')
        body += "</ul>"
    return body + "</body></html>"


def main():
    names = sorted(d for d in os.listdir(BASE)
                   if os.path.isdir(os.path.join(BASE, d, "floors")))
    if sys.argv[1:]:
        names = [n for n in names if n in sys.argv[1:]]
    allres = []
    for i, name in enumerate(names, 1):
        allres += A.audit_building(name)
        print(f"[{i}/{len(names)}] {name:6s} scan ({len(allres)} floors)", flush=True)
    pool = [r for r in allres if r["src_m"] >= 50 and r["miss_pct"] >= THRESH]
    pool.sort(key=lambda r: -r["miss_pct"])
    groups = {}
    print(f"\n=== 判别（{len(pool)} 个可疑层）===")
    for r in pool:
        d = classify(r["building"], r["F"], r)
        r["cls"] = d["cls"]
        groups.setdefault(d["cls"], []).append((r, d))
        print(f"  {r['building']:6s} {r['F']+1:>2d}层 漏墙{r['miss_pct']:4.1f}% "
              f"→ {d['cls']} {d.get('off','')} {d.get('reg','')}", flush=True)
    order = ["真缺墙/不一致", "错位+缺墙", "平移错位", "对齐OK", "无识别墙几何", "无轮廓", "源点少"]
    groups = {k: groups[k] for k in order if k in groups}
    for k, v in groups.items():
        if not k.startswith("对齐") and not k.startswith("无") and not k.startswith("源"):
            print(f"\n[{k}] {len(v)} 层: " +
                  "、".join(f"{r['building']}·{r['F']+1}层" for r, _ in v))
    # 产物归属：_dxf_audit.html 归 _dxf_audit.py（控制台 audit 阶段直接写它）。
    # 本脚本是它的增强层，必须写**自己**的文件 —— 否则在控制台对单栋跑一次
    # audit，就会把这份全仓分组报告整个盖掉（2026-09-10 图纸事故同类）。
    out = os.path.join(BASE, "_dxf_audit_report.html")
    with open(out, "w", encoding="utf-8") as f:
        f.write(html_rows(groups))
    print(f"\n写 data/buildings/_dxf_audit_report.html（分组判别报告）")


if __name__ == "__main__":
    main()
