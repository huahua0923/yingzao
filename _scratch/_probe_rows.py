# -*- coding: utf-8 -*-
"""在 DXF 图纸坐标里逐行(楼层)量 墙/柱 的几何 bbox 中心。判断各层是否画得上下对齐。"""
import sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, r"D:\gym3d")
import ezdxf

def rows_by(walls, gap=40000):
    walls = sorted(walls, key=lambda e: e[1])
    rows=[]; cur=[]; last=None
    for e in walls:
        if last is None or e[1]-last < gap: cur.append(e); last=e[1]
        else: rows.append(cur); cur=[e]; last=e[1]
    if cur: rows.append(cur)
    return rows

def bbox_center(es):
    xs=[e[0] for e in es]; ys=[e[1] for e in es]
    return ((min(xs)+max(xs))/2,(min(ys)+max(ys))/2,(min(xs),max(xs),min(ys),max(ys)))

def wall_centers(msp, layer):
    """LWPOLYLINE+LINE 墙段中心。"""
    out=[]
    for e in msp:
        t=e.dxftype()
        if t=="LWPOLYLINE" and e.dxf.layer==layer:
            pts=[tuple(p[:2]) for p in e.get_points()]
            xs=[q[0] for q in pts]; ys=[q[1] for q in pts]
            out.append(((sum(xs)/len(xs),sum(ys)/len(ys))))
        elif t=="LINE" and e.dxf.layer==layer:
            a,b=e.dxf.start,e.dxf.end
            out.append((((a.x+b.x)/2,(a.y+b.y)/2)))
    return out

def col_centers(msp, layer):
    out=[]
    for e in msp:
        if e.dxftype()=="LWPOLYLINE" and e.dxf.layer==layer:
            pts=[tuple(p[:2]) for p in e.get_points()]
            xs=[q[0] for q in pts]; ys=[q[1] for q in pts]
            out.append((sum(xs)/len(xs),sum(ys)/len(ys)))
    return out

for name,path,wl,cl in [
    ("c027", r"D:\dxf_output\C027-第三教学楼.dxf","4.2墙体","4.1结构柱"),
    ("c103", r"D:\dxf_output\C103-第十一教学楼（东1教）.dxf","4.2墙体","4.1结构柱"),
]:
    doc=ezdxf.readfile(path); msp=doc.modelspace()
    W=wall_centers(msp,wl); C=col_centers(msp,cl)
    print("="*80); print(name, f"墙中心数{len(W)} 柱中心数{len(C)}")
    for tag,es in [("墙",W),("柱",C)]:
        print(f"--{tag}逐行 bbox中心 (图纸坐标, 单位mm):")
        for i,r in enumerate(rows_by(es)):
            cx,cy,b=bbox_center(r)
            print(f"  行{i}: n={len(r)} 中心X={cx:9.0f} 中心Y={cy:9.0f}  bbox x[{b[0]:.0f},{b[1]:.0f}] y[{b[2]:.0f},{b[3]:.0f}] 宽{b[1]-b[0]:.0f} 深{b[3]-b[2]:.0f}")
