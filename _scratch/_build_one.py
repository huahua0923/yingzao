# -*- coding: utf-8 -*-
"""在正确的 cwd 下跑一栋楼的某个环节，并把耗时和输出打出来。

用法：python _scratch/_build_one.py c018 glb [windows|nowindows]
存在的理由：run_step.py 依赖 cwd=backend/web 找 data/，而 Bash 工具里
`cd X && ...` 会被权限层拦；把 chdir 收进脚本里最省事。
"""
import os
import subprocess
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

WEB = r"D:\gym3d\backend\web"
name = sys.argv[1]
step = sys.argv[2] if len(sys.argv) > 2 else "glb"
extra = sys.argv[3:]

cmd = [sys.executable, "run_step.py", name, step] + extra
t = time.time()
r = subprocess.run(cmd, cwd=WEB, capture_output=True, text=True,
                   encoding="utf-8", errors="replace")
dt = time.time() - t
print("== %s %s %s  %.1fs  returncode=%d" % (name, step, " ".join(extra), dt, r.returncode))
print(r.stdout or "")
if r.stderr:
    print("--- stderr ---")
    print(r.stderr[-4000:])
