# -*- coding: utf-8 -*-
"""对比 classify 打补丁前后的分类结果:
   - 无真曲墙的楼(宿舍): 墙/门/柱 条数与点数必须「完全一致」(补丁必须惰性)
   - 有真曲墙的楼: 墙的折线段数应显著增加(弧被离散进来了)
临时把备份的旧版复制成包内模块来对比, 跑完删掉。
"""
import os, sys, shutil, importlib

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path[:0] = [r"D:\gym3d", r"D:\gym3d\backend", r"D:\gym3d\backend\web"]
import ezdxf
from run_building import load_profile

REC = r"D:\gym3d\backend\recognizer"
BAK = os.path.join(REC, ".orig_engine", "classify.py.before_curve")
TMP = os.path.join(REC, "classify_old_tmp.py")

old_src = open(BAK, encoding="utf-8").read().replace(
    "from .profile import in_floor_x_range", "from .profile import in_floor_x_range")
open(TMP, "w", encoding="utf-8", newline="").write(old_src)

from backend.recognizer import classify as NEW
from backend.recognizer import classify_old_tmp as OLD


def stat(clf, msp, p):
    walls, doors, stairs, cols = clf.classify(msp, p)
    npts = sum(len(w) for w in walls)
    return len(walls), npts, len(doors), len(stairs), len(cols)


TESTS = sys.argv[1:] or ["c019", "c030", "c054", "c041", "c072", "c073"]
print("%-7s %-28s %-28s %s" % ("楼", "原版 (墙/点数/门/梯/柱)", "补丁后", "判定"))
for nm in TESTS:
    try:
        p = load_profile(nm)
        doc = ezdxf.readfile(p.dxf)
        msp = doc.modelspace()
        a = stat(OLD, msp, p)
        b = stat(NEW, msp, p)
    except Exception as e:  # noqa: BLE001
        print("%-7s 失败 %s" % (nm, str(e)[:60]))
        continue
    if a[:1] + a[2:] == b[:1] + b[2:]:
        verdict = "惰性(一致)" if a[1] == b[1] else "墙数同但点数变了?"
    else:
        verdict = "有变化"
    print("%-7s %-28s %-28s %s" % (nm, "%d/%d/%d/%d/%d" % a, "%d/%d/%d/%d/%d" % b, verdict))

os.remove(TMP)
print("\n(临时模块已删除)")
