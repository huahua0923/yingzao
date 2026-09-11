# -*- coding: utf-8 -*-
"""把 c006 完整重识别到临时目录 _tmp_c006_arc(**绝不碰交付 data**)。

用途: 弧墙带(classify_line ARC → curve_walls.pair_arc_bands → geometry 实心墙) +
基准轮廓换成「总越界最小」之后, 在临时目录里量「轮廓外墙体」是否回到健康值,
以及轮廓/墙/门/窗/房间/柱/楼梯井 等计数相对交付版的变化。

用法: python _run_c006_tmp.py
"""
import os, sys, json, glob, shutil
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path[:0] = [r"D:\gym3d", r"D:\gym3d\backend"]

from shapely.geometry import Polygon
from run_building import load_profile

TMP = r"D:\gym3d\_tmp_c006_arc"
DELIV = r"D:\gym3d\data\buildings\c006\floors"


def walls_outside(fl):
    T = Polygon(fl["outline"])
    if not T.is_valid:
        T = T.buffer(0)
    tot = out = 0.0
    for w in fl["walls"]:
        q = w.get("poly") or []
        if len(q) < 3:
            continue
        P = Polygon(q)
        if not P.is_valid:
            P = P.buffer(0)
        if P.is_empty:
            continue
        for h in w.get("holes", []) or []:
            if len(h) >= 3:
                H = Polygon(h)
                if H.is_valid and not H.is_empty:
                    P = P.difference(H)
        if P.is_empty:
            continue
        tot += P.area
        out += P.area - P.intersection(T).area
    return 100.0 * out / tot if tot else 0.0


def load(d):
    return {int(os.path.basename(f)[5:-5]): json.load(open(f, encoding="utf-8"))
            for f in glob.glob(os.path.join(d, "floor*.json"))}


def main():
    p = load_profile("c006")
    old_out = p.out_dir
    shutil.rmtree(TMP, ignore_errors=True)
    os.makedirs(TMP, exist_ok=True)
    p.out_dir = TMP          # @dataclass, 直接改
    print("原 out_dir = %s" % old_out)
    print("临时 out_dir = %s" % p.out_dir)
    assert os.path.abspath(p.out_dir) == os.path.abspath(TMP), "守卫: 输出目录必须是临时目录!"

    from backend.recognizer.recognize import recognize
    recognize(p)

    new, old = load(TMP), load(DELIV)
    print("\n%-5s | %-22s | %-22s | %s" % ("层", "交付(旧)", "新", "越界%"))
    for F in sorted(new):
        n, o = new[F], old.get(F)
        def c(f, k):
            return len(f.get(k) or [])
        print("  F%-2d | 墙%3d 门%3d 窗%3d 房%3d 柱%3d 井%2d | 墙%3d 门%3d 窗%3d 房%3d 柱%3d 井%2d | 旧%5.2f%% 新%5.2f%%"
              % (F,
                 c(o, "walls") if o else -1, c(o, "doors") if o else -1, c(o, "windows") if o else -1,
                 c(o, "rooms") if o else -1, c(o, "columns") if o else -1, c(o, "stairwells") if o else -1,
                 c(n, "walls"), c(n, "doors"), c(n, "windows"),
                 c(n, "rooms"), c(n, "columns"), c(n, "stairwells"),
                 walls_outside(o) if o else -1, walls_outside(n)))


if __name__ == "__main__":
    main()
