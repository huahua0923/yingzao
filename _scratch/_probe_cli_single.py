# -*- coding: utf-8 -*-
"""CLI 端到端冒烟：单块楼走完整 main() 路径（含 --out 写档），确认与改前一致。

不走 shell —— 中文 DXF 文件名在 Git Bash 里会被转 GBK，用 subprocess 列表传参。
写到 _scratch 里的临时档，绝不碰 data/buildings/**/profile.json。
"""
import json
import os
import subprocess
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE = r"D:\gym3d"
TMP = os.path.join(BASE, "_scratch", "_cli_single_out.json")
PY = [sys.executable, os.path.join(BASE, "backend", "recognizer", "detect_params.py")]

for name in ("c041", "c116"):
    prof = json.load(open(os.path.join(BASE, "data", "buildings", name, "profile.json"),
                          encoding="utf-8"))
    dxf = prof["dxf"]
    assert os.path.exists(dxf), "DXF 不存在: " + dxf
    if os.path.exists(TMP):
        os.remove(TMP)

    r = subprocess.run(PY + [dxf, name, prof.get("title", ""), "--out", TMP],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    print("=== %s  退出码=%d ===" % (name, r.returncode))
    if r.stdout:
        print(r.stdout.strip()[:400])
    if r.stderr:
        print("STDERR:", r.stderr.strip()[:300])

    if not os.path.exists(TMP):
        print("  !! 没写出 profile\n")
        continue
    got = json.load(open(TMP, encoding="utf-8"))
    for k in ("cx", "offset", "cy"):
        same = got.get(k) == prof.get(k)
        print("  %-7s 探=%-12s 档=%-12s %s"
              % (k, got.get(k), prof.get(k), "一致" if same else "**不同**"))
    print("  写出的键数 %d（档 %d）；含 x_range: %s"
          % (len(got), len(prof), "x_range" in got))
    print()

if os.path.exists(TMP):
    os.remove(TMP)
    print("临时档已清理")
