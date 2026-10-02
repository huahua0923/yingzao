# -*- coding: utf-8 -*-
"""只重建 GLB（**不重跑 recognize**）。用于手工修过 floors 的楼——run_building.py --glb
会先 recognize 把手工改动冲掉。

用法: python _glb_only.py <name> [--windows]

导出档位（合成窗 / 剔除楼层）**从该楼档案读**，与 `run_building.py --glb` 同一条规则、
同一份实现（`run_step.glb_opts_from_profile`）。`--windows` 只用于**压过档案强开**。
（2026-09-28 改口；此前是写死「不加 --windows 就没窗」，与全库 96/96 栋说自己要窗相反。）
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
sys.path.insert(0, r"D:\gym3d\backend\web")
import build_standard_glb as bsg
from run_step import glb_opts_from_profile
bsg.DATA = os.path.dirname(p.out_dir)
bsg.OUT = os.path.join(bsg.DATA, "%s-building.glb" % NAME)

# ★ 2026-09-28 改口：导出档位**从该楼档案读**，不再写死。
#   旧写法 `bsg.INCLUDE_SYNTHETIC_WINDOWS = DO_WIN`（= 不加 --windows 就没窗）写于
#   `run_building.py` 还把这件事硬编码成 False 的时候；它 2026-09-26 已改口成
#   「导出档位从 profile.json 读」（见该文件里那句注释），于是这一行成了**第三个默认值**，
#   而上面那句「对齐 run_building.py --glb 的默认」正好反向。
#   实测（2026-09-28）：**全库 96/96 栋档案都写 `glb_windows: true`**，而 README 标准链路
#   第 4 步就是本脚本 ⇒ 按旧写法全库重出 GLB，96 栋的合成窗会被**静默剥掉**、与各自档案相反。
#   这里不另写一份规则：唯一实现是 `run_step.glb_opts_from_profile` —— 它按 `load_profile`
#   同一条链读「楼档案 → 覆盖档」，缺键取模块默认，且那个默认值**只有一处定义**
#   （`_default_glb_windows()` 读 `bsg.INCLUDE_SYNTHETIC_WINDOWS` 本身）。
#   `skip_floors` 同一个函数一并返回，别只修一半（铁律 41：两份清单必须成对）。
_opts = glb_opts_from_profile(NAME)
bsg.INCLUDE_SYNTHETIC_WINDOWS = _opts["windows"]
if _opts["skip_floors"]:
    bsg.SKIP_FLOORS = set(_opts["skip_floors"])
    print("  按档案剔除楼层：%s" % sorted(bsg.SKIP_FLOORS))
if DO_WIN:                                   # 显式意图：命令行压过档案
    bsg.INCLUDE_SYNTHETIC_WINDOWS = True
print("  导出档位：合成窗=%s（来源：%s）"
      % ("开" if bsg.INCLUDE_SYNTHETIC_WINDOWS else "关",
         "命令行 --windows" if DO_WIN else "该楼档案"))
bsg.main()
print("GLB -> %s" % bsg.OUT)
sys.exit(1 if problems else 0)
