# -*- coding: utf-8 -*-
"""只重建 GLB（**不重跑 recognize**）。用于手工修过 floors 的楼——run_building.py --glb
会先 recognize 把手工改动冲掉。

用法: python _glb_only.py <name> [--windows]
"""
import os, sys, json, glob
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path[:0] = [r"D:\gym3d", r"D:\gym3d\backend"]

NAME = sys.argv[1]
DO_WIN = "--windows" in sys.argv
from run_building import load_profile, validate

p = load_profile(NAME)
floors = {}
for fp in sorted(glob.glob(os.path.join(p.out_dir, "floor*.json"))):
    floors[int(os.path.basename(fp)[5:-5])] = json.load(open(fp, encoding="utf-8"))

problems = validate(NAME, floors)
print("[%s] 楼层数=%d  校验问题=%d" % (NAME, len(floors), len(problems)))
for pr in problems:
    print("  x " + pr)
if not problems:
    print("  PASS")

sys.path.insert(0, r"D:\gym3d\backend\modeling")
import build_standard_glb as bsg
bsg.DATA = os.path.dirname(p.out_dir)
bsg.OUT = os.path.join(bsg.DATA, "%s-building.glb" % NAME)
# 对齐 run_building.py --glb 的默认：合成窗不进 GLB，加 --windows 才导出。
# （模块默认是 True，不显式关掉会和交付版口径不一致。）
bsg.INCLUDE_SYNTHETIC_WINDOWS = DO_WIN
bsg.main()
print("GLB -> %s" % bsg.OUT)
sys.exit(1 if problems else 0)
