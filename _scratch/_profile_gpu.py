# -*- coding: utf-8 -*-
"""找出建模流水线的真实热点，回答「GPU 该加在哪」。

为什么不能猜
------------
这套流水线没有神经网络，全是几何规则 + 建筑制图约定 —— 直觉上「GPU 没用」。
但直觉也会反过来骗人：真正吃时间的可能是双线配对的 O(n²) 距离矩阵（GPU 友好），
也可能是 Python 逐元素循环（GPU 完全不友好，只有向量化能救）。两者结论相反，
所以先测。

安全第一
--------
把 p.out_dir 指到 _scratch 下再跑 recognize()，**不覆盖任何真实产物**。
（绝不直接跑 run_building.py：45 栋有 .orig 手工修复，重识别会把它们冲掉。）

用法
----
    python _scratch/_profile_gpu.py c019 c043 lihua
"""
import cProfile
import copy
import io
import os
import pstats
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for sub in ("backend", "backend/web", "backend/modeling", "backend/vision"):
    sys.path.insert(0, os.path.join(ROOT, sub))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

SCRATCH = os.path.join(ROOT, "_scratch", "_profile_out")
TOPN = 18


def profile_one(name):
    from run_step import load_profile
    from recognizer import recognize

    p = load_profile(name)
    if not p.dxf or not os.path.exists(p.dxf):
        print("[%s] 无 dxf（%s），跳过" % (name, p.dxf))
        return None

    real_out = p.out_dir
    p = copy.copy(p)
    p.out_dir = os.path.join(SCRATCH, name)
    os.makedirs(p.out_dir, exist_ok=True)

    n_floor_json = len([f for f in os.listdir(real_out)
                        if f.startswith("floor") and f.endswith(".json")]) \
        if os.path.isdir(real_out) else 0

    buf = io.StringIO()
    t0 = time.time()
    pr = cProfile.Profile()
    pr.enable()
    try:
        floors = recognize(p)
    finally:
        pr.disable()
    wall = time.time() - t0

    made = len([f for f in os.listdir(p.out_dir)
                if f.startswith("floor") and f.endswith(".json")])
    print("\n" + "=" * 74)
    print("[%s] 墙钟 %.1fs，%d 层（真实产物 %d 层 -> 校验 %s）"
          % (name, wall, len(floors), n_floor_json,
             "一致" if made == n_floor_json else "**不一致 %d**" % made))

    st = pstats.Stats(pr, stream=buf)
    st.sort_stats("tottime")
    st.print_stats(TOPN)
    lines = buf.getvalue().splitlines()
    # 只留表头 + 前 TOPN 行，去掉 pstats 那一大坨说明
    keep, started = [], False
    for ln in lines:
        if "ncalls" in ln:
            started = True
        if started:
            keep.append(ln)
    print("\n".join(keep[:TOPN + 6]))
    return real_out


def main():
    names = sys.argv[1:] or ["c019", "c043"]
    print("输出目录（临时，不碰真实产物）: %s" % SCRATCH)
    for n in names:
        profile_one(n)


if __name__ == "__main__":
    main()
