# -*- coding: utf-8 -*-
"""验证「窗洞改几何匹配」：既修好 41 栋崩溃，又不改变原来的正确结果。

判据（全部对着**已备份的交付件**比，不碰交付目录）：
  V1 c019 windows=False → 与备份的交付 GLB **逐字节相同**（关窗路径零回归）
  V2 c019/c116 windows=True → **不再崩溃**、总窗>0、且与关窗版不同
  V3 开窗版三角面落在关窗版的 ±10% 内

为什么不用「三角面必须增加」当判据：挖窗洞会**去掉**墙的几何，
可以盖过玻璃+窗框新增的量（实测 c116 开窗后反而少 868 面）。
也不再用 2,050,772 当基线 —— 那是旧 id 匹配的产物，判据换了不可比。
"""
import hashlib
import json
import os
import struct
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, r"D:\gym3d\backend\web")

import run_step            # noqa: E402
import build_standard_glb as bsg  # noqa: E402

SCRATCH = r"D:\gym3d\_scratch\win_probe"
BK = r"D:\gym3d\_backup_glb_20260910"
os.makedirs(SCRATCH, exist_ok=True)

C019_BASELINE_WITH_WINDOWS = 2050772   # 改前用 id 匹配实测值


def tri_count(path):
    with open(path, "rb") as f:
        data = f.read()
    off = 12
    while off + 8 <= len(data):
        clen, ctype = struct.unpack_from("<II", data, off)
        if ctype == 0x4E4F534A:
            j = json.loads(data[off + 8: off + 8 + clen].decode("utf-8"))
            n = 0
            for m in j.get("meshes", []):
                for p in m.get("primitives", []):
                    if "indices" in p:
                        n += j["accessors"][p["indices"]]["count"]
            return n // 3
        off += 8 + clen
    return None


def md5(path):
    h = hashlib.md5()
    with open(path, "rb") as f:
        for c in iter(lambda: f.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()


results = {}
for name in ("c116", "c019"):   # 小的先跑，尽早拿到正确性信号
    p = run_step.load_profile(name)
    parent = os.path.dirname(p.out_dir)
    bsg.DATA = parent
    print("=== %s ===" % name)
    for win in (False, True):
        bsg.INCLUDE_SYNTHETIC_WINDOWS = win
        dst = os.path.join(SCRATCH, "%s_win%d.glb" % (name, int(win)))
        bsg.OUT = dst
        try:
            bsg.main()
            t = tri_count(dst)
            results[(name, win)] = (t, os.path.getsize(dst), md5(dst))
            print("  windows=%-5s → %9d 三角  %8.2f MB" % (win, t, os.path.getsize(dst) / 1048576.0))
        except Exception as e:
            results[(name, win)] = None
            print("  windows=%-5s → 崩溃 %s: %s" % (win, type(e).__name__, e))
    print()

print("---- 判据 ----")
ok = True

# V1: c019 关窗应与备份交付件逐字节相同
d = os.path.join(BK, "c019", "c019-building.glb")
delivered_md5 = md5(d)
got = results.get(("c019", False))
v1 = got is not None and got[2] == delivered_md5
print("V1 c019 关窗 == 交付备份(逐字节) :", "PASS" if v1 else "FAIL")
if not v1:
    print("    交付 md5=%s  重建 md5=%s" % (delivered_md5, got[2] if got else "崩溃"))
ok &= v1

# V2: 两栋开窗都不再崩、且与关窗版不同
for n in ("c019", "c116"):
    g_on, g_off = results.get((n, True)), results.get((n, False))
    good = g_on is not None and g_off is not None and g_on[2] != g_off[2]
    print("V2 %s 开窗不崩且与关窗版不同 : %s (开窗 %s)"
          % (n, "PASS" if good else "FAIL", ("%d 三角" % g_on[0]) if g_on else "崩溃"))
    ok &= good

# V3: 开窗版三角面落在关窗版 ±10% 内（挖洞减法 vs 玻璃加法，方向不定）
for n in ("c019", "c116"):
    g_on, g_off = results.get((n, True)), results.get((n, False))
    if g_on is None or g_off is None:
        print("V3 %s : SKIP（有崩溃）" % n)
        ok = False
        continue
    ratio = g_on[0] / g_off[0]
    good = 0.90 <= ratio <= 1.10
    print("V3 %s 开窗/关窗 三角面比 = %.4f : %s" % (n, ratio, "PASS" if good else "FAIL"))
    ok &= good

print("\n" + ("全部 PASS" if ok else "存在 FAIL —— 不要往下跑批量"))
