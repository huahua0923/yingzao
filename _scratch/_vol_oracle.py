# -*- coding: utf-8 -*-
"""独立体积 oracle：直接用 floors/*.json 的材料量算体积，不碰 GLB、不碰三角化。

口径严格照 build_standard_glb 的建法：
  楼板   = (outline - 楼梯井洞) 面积 × slab_t           z .. z+slab_t
  房间垫 = 房间面积 × ROOM_PAD                          z+slab_t .. +pad
  墙     = 墙面积 × wall_h                              z+slab_t .. z+slab_t+wall_h
  柱     = w×d × wall_h                                 同墙
  门     = 门扇盒子体积（小，略）
  屋面   = 顶层面轮廓 × roof_t
  女儿墙 = (外扩 parapet_t 面积 - 原面积) × parapet_h

signed volume 给闭合网格用；这个 oracle 给「材料体积」。两者应同量级且接近
（细部会因交叠/斜接有百分之几出入）。c084 从 7835 涨到 10801，拿它判谁对。
"""
import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from shapely.geometry import Polygon, box

BSD = r"D:\gym3d\backend\modeling"
sys.path.insert(0, BSD)

import build_standard_glb as bsg  # noqa: E402


def _g(poly, holes=None):
    """两种表示都收：纯外环 [[x,y],...] 或 [外环, 洞1, ...]；holes 另给也收。

    ⚠️ 墙的 poly 是**纯外环**，洞在兄弟字段 `holes` 里。c084 的 outer 墙外环面积
    2035.8 m²（= 整层轮廓），漏掉 holes 会把它当成实心块，墙体积虚高 5 倍。
    """
    if not poly:
        return None
    nested = isinstance(poly[0][0], (list, tuple))
    if nested:
        g = Polygon(poly[0], poly[1:])
    else:
        g = Polygon(poly, holes or [])
    return g.buffer(0) if not g.is_valid else g


def vol(name, S):
    d = os.path.join(r"D:\gym3d\data\buildings", name)
    fd = os.path.join(d, "floors")
    files = sorted((f for f in os.listdir(fd) if f.startswith("floor") and f.endswith(".json")),
                   key=lambda f: int(f[5:-5]))
    parts = {"slab": 0.0, "room": 0.0, "wall": 0.0, "col": 0.0, "door": 0.0,
             "roof": 0.0, "parapet": 0.0}
    pad = getattr(bsg, "ROOM_PAD", 0.0)
    for fn in files:
        fj = json.load(open(os.path.join(fd, fn), encoding="utf-8"))
        num = fj["floor"]
        z = num * S["floor_h"]
        # 楼板：首层不挖楼梯井（与 build_slab 一致）
        sl = _g(fj["outline"])
        if sl is not None and num > 0:
            for s in fj.get("stairwells") or []:
                sl = sl.difference(box(s["x0"], s["yBot"], s["x1"], s["yTop"]))
        if sl is not None:
            parts["slab"] += sl.area * S["slab_t"]
        for r in fj.get("rooms") or []:
            g = _g(r.get("poly"))
            if g is not None:
                parts["room"] += g.area * pad
        for w in fj.get("walls") or []:
            g = _g(w.get("poly"), w.get("holes"))
            if g is not None:
                parts["wall"] += g.area * (w.get("height") or S["wall_h"])
        for c in fj.get("columns") or []:
            parts["col"] += abs(c["w"] * c["d"]) * S["wall_h"]
        for dd in fj.get("doors") or []:
            parts["door"] += dd["w"] * dd.get("h", S["door_h"]) * S["door_panel_t"]
    # 屋面 + 女儿墙
    top = json.load(open(os.path.join(fd, files[-1]), encoding="utf-8"))
    roof_y = len(files) * S["floor_h"]
    g = _g(top["outline"])
    if g is not None:
        parts["roof"] += g.area * S["roof_t"]
        parts["parapet"] += g.buffer(S["parapet_t"], join_style=2,
                                     mitre_limit=2.0).difference(g).area * S["parapet_h"]
    return sum(parts.values()), parts, len(files)


if __name__ == "__main__":
    names = sys.argv[1:] or ["c084"]
    for n in names:
        try:
            S = bsg.load_spec()
        except Exception:
            S = {}
        try:
            os.environ["BSD_DATA"] = os.path.join(r"D:\gym3d\data\buildings", n)
            bsg.DATA = os.path.join(r"D:\gym3d\data\buildings", n)
            S = bsg.load_spec()
            tot, parts, nf = vol(n, S)
        except Exception as e:
            import traceback
            print(f"{n}: 失败 {e}")
            traceback.print_exc()
            continue
        det = "  ".join(f"{k}={v:,.0f}" for k, v in parts.items() if v)
        print(f"{n}  {nf}层  材料体积={tot:,.1f} m³\n     {det}")
