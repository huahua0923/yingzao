# -*- coding: utf-8 -*-
"""临时验证：recognizer 输出的楼层 JSON 是否与 extract_floors.py 既有产物一致。"""
import os
import sys
import shutil
from dataclasses import replace

# Windows GBK 控制台打不出 ✓/✗，统一 UTF-8 输出，避免 print 崩
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import recognizer.profiles            # noqa: F401  注册 profile
from recognizer import recognize, get_profile

BASE = r"D:\gym3d\data\floors"
TMP = r"D:\gym3d\data\_verify_floors"

p = get_profile("lihua")
if os.path.exists(TMP):
    shutil.rmtree(TMP)
os.makedirs(TMP)

# 用临时目录跑，不覆盖已知-good 产物
recognize(replace(p, out_dir=TMP))

ok = True
for name in sorted(os.listdir(BASE)):
    if not name.endswith(".json"):
        continue
    a = open(os.path.join(BASE, name), encoding="utf-8").read()
    bpath = os.path.join(TMP, name)
    if not os.path.exists(bpath):
        ok = False
        print(f"[{name}] 缺新产物 ✗")
        continue
    b = open(bpath, encoding="utf-8").read()
    if a == b:
        print(f"[{name}] 一致 ✓")
    else:
        ok = False
        print(f"[{name}] 不一致 ✗  (旧 {len(a)}B / 新 {len(b)}B)")

print("RESULT:", "全部一致" if ok else "存在差异")
