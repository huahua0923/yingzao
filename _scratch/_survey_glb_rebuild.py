# -*- coding: utf-8 -*-
"""重出 GLB 前的安全普查（只读，绝不写）。

回答四件事：
  1. 49 栋各自 GLB 是否存在、多大、多少三角面 —— 作为重出后的比对基线
  2. 哪些楼有 .orig（= 人工改过 floors）—— glb 步不碰 floors，但要心里有数
  3. 每栋 floor JSON 里 synthetic 窗有多少 —— 决定加窗后该涨多少面
  4. GLB 总体积 —— 决定备份和耗时的量级
"""
import glob
import hashlib
import json
import os
import struct
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

B = r"D:\gym3d\data\buildings"


def glb_bin(path):
    """读出 GLB 里 BIN chunk 的字节数（不信 JSON 里的声明，按实际文件算）。"""
    with open(path, "rb") as f:
        data = f.read()
    if len(data) < 20 or data[:4] != b"glTF":
        return None, None
    off, total = 12, 0
    while off + 8 <= len(data):
        clen, ctype = struct.unpack_from("<II", data, off)
        if ctype == 0x004E4942:      # 'BIN\0'
            total = clen
        off += 8 + clen
    return total, len(data)


rows = []
for name in sorted(os.listdir(B)):
    d = os.path.join(B, name)
    if not os.path.isdir(d) or not os.path.exists(os.path.join(d, "profile.json")):
        continue
    glb = os.path.join(d, f"{name}-building.glb")
    floors = sorted(glob.glob(os.path.join(d, "floors", "floor*.json")))
    has_orig = os.path.isdir(os.path.join(d, ".orig"))
    orig_n = len(os.listdir(os.path.join(d, ".orig"))) if has_orig else 0

    wins = 0
    for fp in floors:
        try:
            fl = json.load(open(fp, encoding="utf-8"))
        except Exception:
            continue
        wins += len(fl.get("windows") or [])

    gsize = os.path.getsize(glb) if os.path.exists(glb) else 0
    rows.append((name, len(floors), wins, gsize, os.path.exists(glb), has_orig, orig_n))

tot_glb = sum(r[3] for r in rows)
print("%-8s %5s %6s %11s %6s %7s" % ("楼", "层", "合成窗", "GLB(MB)", "有GLB", "有.orig"))
print("-" * 54)
for r in rows:
    print("%-8s %5d %6d %11.2f %6s %7s"
          % (r[0], r[1], r[2], r[3] / 1048576.0, "是" if r[4] else "缺",
             ("是(%d)" % r[6]) if r[5] else "-"))

n_glb = sum(1 for r in rows if r[4])
n_win = sum(1 for r in rows if r[2] > 0)
print("\n共 %d 栋 | 有 GLB %d | 有合成窗 %d 栋 | GLB 合计 %.1f MB"
      % (len(rows), n_glb, n_win, tot_glb / 1048576.0))
print("有 .orig 的楼:", ",".join(r[0] for r in rows if r[5]) or "无")
