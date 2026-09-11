# -*- coding: utf-8 -*-
"""c019 重识别到临时目录 _tmp_c019_door(**绝不碰交付 data**)，验证门洞真的被挖穿。

门 = gap 不是 hole：判据 = 从门心沿「墙走向」±0.4m 处**不再落在任何墙内**，
且门心本身已不在墙内。旧版（门洞盒被 door_by_points 关着）这两条必然失败。

用法: python _run_c019_tmp.py [name=c019]
"""
import os, sys, json, glob, shutil
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path[:0] = [r"D:\gym3d", r"D:\gym3d\backend"]

from shapely.geometry import Polygon, Point
from run_building import load_profile

NAME = sys.argv[1] if len(sys.argv) > 1 else "c019"
TMP = r"D:\gym3d\_tmp_%s_door" % NAME
DELIV = r"D:\gym3d\data\buildings\%s\floors" % NAME


def W(w):
    P = Polygon(w["poly"])
    if not P.is_valid:
        P = P.buffer(0)
    for h in w.get("holes") or []:
        if len(h) >= 3:
            H = Polygon(h)
            if H.is_valid and not H.is_empty:
                P = P.difference(H)
    return P


def walls_outside(fl):
    T = Polygon(fl["outline"])
    if not T.is_valid:
        T = T.buffer(0)
    tot = out = 0.0
    for w in fl["walls"]:
        P = W(w)
        if P.is_empty:
            continue
        tot += P.area
        out += P.area - P.intersection(T).area
    return 100.0 * out / tot if tot else 0.0


def door_cut_stats(fl):
    """返回 (门总数, 门心已出墙数, 双向 ±0.4m 都出墙数)。"""
    P = [W(w) for w in fl.get("walls", [])]
    n = n_center = n_through = 0
    for d in fl.get("doors", []):
        n += 1
        c = Point(d["x"], d["y"])
        if any(Q.contains(c) for Q in P):
            continue
        n_center += 1
        ok = True
        for sgn in (1, -1):
            q = Point(d["x"] + sgn * 0.4, d["y"]) if d["horiz"] else Point(d["x"], d["y"] + sgn * 0.4)
            if any(Q.contains(q) for Q in P):
                ok = False
                break
        if ok:
            n_through += 1
    return n, n_center, n_through


def load(d):
    return {int(os.path.basename(f)[5:-5]): json.load(open(f, encoding="utf-8"))
            for f in glob.glob(os.path.join(d, "floor*.json"))}


def main():
    p = load_profile(NAME)
    old_out = p.out_dir
    shutil.rmtree(TMP, ignore_errors=True)
    os.makedirs(TMP, exist_ok=True)
    p.out_dir = TMP
    print("原 out_dir = %s\n临时 out_dir = %s" % (old_out, p.out_dir))
    assert os.path.abspath(p.out_dir) == os.path.abspath(TMP), "守卫: 输出目录必须是临时目录!"

    from backend.recognizer.recognize import recognize
    recognize(p)

    new, old = load(TMP), load(DELIV)
    print("\n%-4s | %-34s | %-34s" % ("层", "交付(旧): 墙/门/窗/房/柱/井 门洞挖穿", "新: 同上"))
    tot_o = tot_n = tot_oc = tot_nc = 0
    for F in sorted(new):
        n, o = new[F], old.get(F)
        def c(f, k):
            return len(f.get(k) or [])
        dn, dc, dt = door_cut_stats(n)
        on, oc, ot = door_cut_stats(o) if o else (0, 0, 0)
        tot_o += on; tot_oc += oc; tot_n += dn; tot_nc += dc
        print("  F%-2d | 墙%3d 门%3d 窗%3d 房%3d 柱%3d 井%2d | 挖穿%2d/%-3d | 墙%3d 门%3d 窗%3d 房%3d 柱%3d 井%2d | 挖穿%2d/%-3d | 越界 旧%5.2f%% 新%5.2f%%"
              % (F,
                 c(o, "walls") if o else -1, on, c(o, "windows") if o else -1,
                 c(o, "rooms") if o else -1, c(o, "columns") if o else -1, c(o, "stairwells") if o else -1,
                 ot, on,
                 c(n, "walls"), dn, c(n, "windows"), c(n, "rooms"), c(n, "columns"), c(n, "stairwells"),
                 dt, dn,
                 walls_outside(o) if o else -1, walls_outside(n)))
    print("\n合计: 交付门 %d 挖穿 %d (%.0f%%)  ->  新门 %d 挖穿 %d (%.0f%%)"
          % (tot_o, tot_oc, 100.0 * tot_oc / max(tot_o, 1),
             tot_n, tot_nc, 100.0 * tot_nc / max(tot_n, 1)))


if __name__ == "__main__":
    main()
