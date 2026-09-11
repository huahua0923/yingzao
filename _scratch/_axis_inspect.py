# -*- coding: utf-8 -*-
"""探查源 DXF 里「轴线」图层/线型特征，为渲染过滤做准备。"""
import os, sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
sys.path[:0] = [r"D:\gym3d\backend\web", r"D:\gym3d\backend\vision",
                r"D:\gym3d\backend", r"D:\gym3d"]
import ezdxf

def scan_all():
    """列出每栋 DXF 图层名，标出疑似轴线图层。"""
    import run_step
    base = r"D:\gym3d\data\buildings"
    names = sorted(d for d in os.listdir(base)
                   if os.path.isdir(os.path.join(base, d, "floors")))
    import re
    pat = re.compile(r"轴|center|dote|axis", re.I)
    for nm in names:
        try:
            p = run_step.load_profile(nm)
            doc = ezdxf.readfile(p.dxf)
            lays = set()
            for e in doc.modelspace():
                if e.dxftype() in ("DIMENSION", "ACAD_TABLE", "MULTILEADER", "HATCH", "ATTDEF"):
                    continue
                lays.add(getattr(e.dxf, "layer", "?") or "?")
            hit = [l for l in lays if pat.search(l)]
            tag = ("  轴:" + ",".join(sorted(hit))) if hit else ""
            print(f"{nm:6s} {len(lays):3d}层{tag}")
        except Exception as e:
            print(f"{nm:6s} ERR {str(e)[:60]}")


def main():
    import run_step
    name = sys.argv[1] if len(sys.argv) > 1 else "c019"
    p = run_step.load_profile(name)
    doc = ezdxf.readfile(p.dxf)
    from collections import Counter, defaultdict
    lay_cnt = Counter()
    linetype_names = set()
    # layer name -> set(linetype)
    lay_lin = defaultdict(set)
    lay_dxf = defaultdict(Counter)
    lay_color = defaultdict(Counter)
    n = 0
    for e in doc.modelspace():
        t = e.dxftype()
        if t in ("DIMENSION", "ACAD_TABLE", "MULTILEADER", "HATCH", "ATTDEF"):
            continue
        lay = getattr(e.dxf, "layer", "?") or "?"
        lay_cnt[lay] += 1
        lt = getattr(e.dxf, "linetype", "ByLayer") or "ByLayer"
        linetype_names.add(lt)
        lay_lin[lay].add(lt)
        try:
            lay_dxf[lay][t] += 1
        except Exception:
            pass
        try:
            col = int(e.dxf.color or 7)
        except Exception:
            col = 7
        lay_color[lay][col] += 1
        n += 1
    print(f"=== {name} modelspace 实体数 {n} ===")
    print("\n-- 图层分布(top 25) --")
    for lay, c in lay_cnt.most_common(25):
        print(f"  {lay:24s} {c:5d}  dxf={dict(lay_dxf[lay])}")
        print(f"      linetype={sorted(lay_lin[lay])}  color={dict(lay_color[lay])}")
    print("\n-- 全部线型 --")
    for lt in sorted(linetype_names):
        print("  ", repr(lt))

if __name__ == "__main__":
    main()
