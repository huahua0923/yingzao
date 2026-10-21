# -*- coding: utf-8 -*-
r"""在 **ASCII 暂存区**里跑 freecadcmd（轮廓 → 实体那一步）。

为什么必须暂存（2026-10-17 实测两趟）：
  · `freecadcmd.exe D:\项目\cdut3d\rebuild\tools\contours_to_fc.py`
      ⇒ **一个字都不打印、rc=0、什么也没建**（脚本根本没被执行）。
  · 同一份文件复制到 `C:\sutest\fctest\t.py` 再跑
      ⇒ 正常执行（连报错都正常印出来：`Exception while processing file: …`）。
  ⇒ 与 SketchUp 同一个坑：**Windows 下 native 程序的 argv 走窄字符**，非 ASCII 脚本路径会被
     搞坏；坏法不是报错，而是「什么都没发生」。所以脚本、以及它 import 的 building.py，
     都搬到纯 ASCII 目录再给 freecadcmd。
  ★ 数据路径**不用搬**：环境变量在 Windows 上是宽字符，实测中文路径经 env 传进去 `isdir=True`，
     `mesh.write()` 写中文路径也正常（`_scratch/fc_cn.obj` 实测写成功）。

用法：
    python -I -X utf8 rebuild/tools/run_freecad.py                 # c006（默认）
    CDUT_BUILDING=c005 python -I -X utf8 rebuild/tools/run_freecad.py

产物（由子脚本写，本脚本只负责隔离开跑 + 判有没有真产出）：
    <ROOT>/06_su/<NAME>_fc.obj、fc_parts/*.obj、fc_recon.json
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import building as B  # noqa: E402

FREECAD = os.environ.get("FREECAD_CMD") or \
    r"C:\Users\Administrator\AppData\Local\Programs\FreeCAD 1.1\bin\freecadcmd.exe"
STAGE = os.environ.get("CDUT_FC_STAGE") or r"C:\sutest\fcstage"
WORKER = "contours_to_fc.py"
DEPS = ("building.py",)

NAME = B.out_name()
ROOT = B.ROOT
OUT_OBJ = os.path.join(ROOT, "06_su", "%s_fc.obj" % NAME)
OUT_RECON = os.path.join(ROOT, "06_su", "fc_recon.json")


def main() -> int:
    for p in (FREECAD, os.path.join(HERE, WORKER)):
        if not os.path.exists(p):
            print("MISSING " + p)
            return 4
    os.makedirs(STAGE, exist_ok=True)
    for f in (WORKER,) + DEPS:
        shutil.copy2(os.path.join(HERE, f), os.path.join(STAGE, f))

    env = dict(os.environ)
    env["CDUT_BUILDING"] = B.BID
    env["CDUT_REBUILD_ROOT"] = ROOT
    # ★★ 2026-10-17 C105：档案不写 floor_names 时 `building.profile()` 要现读标题栏，
    #   那条路要 import floor_from_title → ezdxf，而 **FreeCAD 自带 Python 没有 ezdxf**
    #   （实测症状：rc=0、子进程 stderr 一行 `No module named 'ezdxf'`、件不在）。
    #   ⇒ 在**宿主进程**（有 ezdxf）里先把档案解析好（层名/地下层已填进去），
    #   写一份「已解析档案」进暂存区，FreeCAD 侧读它就不再需要推导。
    #   c005/c006 的档案本来就写着 floor_names ⇒ 解析结果与原文同值，行为不变。
    resolved = os.path.join(STAGE, "profile.resolved.json")
    with open(resolved, "w", encoding="utf-8") as f:
        json.dump({B.BID: B.profile()}, f, ensure_ascii=False, indent=1)
    # building.py 在暂存区里靠 __file__ 推不出 …/rebuild ⇒ 档案路径显式传
    env["CDUT_PROFILE"] = resolved

    t0 = time.time()
    proc = subprocess.run([FREECAD, WORKER], cwd=STAGE, env=env,
                          capture_output=True, text=True, encoding="utf-8",
                          errors="replace")
    for ln in proc.stdout.splitlines():
        # FreeCAD 把写盘进度印成 `(37 %)` 一路刷屏，滤掉；其余原样
        if ln.strip().startswith("(") and "%" in ln:
            continue
        print(ln)
    if proc.stderr.strip():
        print("---- stderr ----")
        print(proc.stderr[-4000:])

    rc = proc.returncode
    if rc != 0:
        print("RC %d（%.1fs）—— 子进程没跑成" % (rc, time.time() - t0))
        return rc
    if not os.path.exists(OUT_OBJ):
        # 「没产出」与「建出来是错的」分开报（铁律 199）
        print("NO_OUTPUT %s —— rc=0 但件不在；这**不是**通过" % OUT_OBJ)
        return 5
    print("OK %s bytes=%d recon=%s elapsed=%.1fs"
          % (OUT_OBJ, os.path.getsize(OUT_OBJ), OUT_RECON, time.time() - t0))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
