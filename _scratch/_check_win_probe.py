# -*- coding: utf-8 -*-
"""对 _scratch/win_probe 里已建好的 4 个 GLB 直接算 V1/V2/V3（不重跑建楼）。

产物是「窗洞改几何匹配」修复后建的：
  c116_win0 19:52 / c116_win1 19:52 / c019_win0 19:53 / c019_win1 20:03
比对对象是 _backup_glb_20260910（改前的交付件备份）。
"""
import hashlib
import json
import os
import struct
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

SCRATCH = r"D:\gym3d\_scratch\win_probe"
BK = r"D:\gym3d\_backup_glb_20260910"


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


res = {}
for name in ("c116", "c019"):
    for win in (0, 1):
        p = os.path.join(SCRATCH, "%s_win%d.glb" % (name, win))
        if not os.path.exists(p):
            print("%-10s 缺文件" % os.path.basename(p))
            continue
        res[(name, win)] = (tri_count(p), os.path.getsize(p), md5(p))
        print("%-10s %9d 三角面  %8.2f MB  md5=%s"
              % (os.path.basename(p), res[(name, win)][0],
                 res[(name, win)][1] / 1048576.0, res[(name, win)][2][:16]))

print("\n---- 判据 ----")
ok = True

# V1 只对 c019 断言：它的交付件就是当前管道产的（三角面 100% 吻合），
# 关窗路径必须复现出逐字节相同的文件。c116 交付件陈旧到只有重建的 4.5%，
# 逐字节相同不成立也不可能成立，拿它当判据是错的。
V1_TARGETS = ("c019",)
for n in V1_TARGETS:
    d = os.path.join(BK, n, "%s-building.glb" % n)
    if not os.path.exists(d) or (n, 0) not in res:
        continue
    m = md5(d)
    same = m == res[(n, 0)][2]
    print("V1 %s 关窗 == 交付备份(逐字节)      : %s" % (n, "PASS" if same else "FAIL"))
    if not same:
        print("     交付 md5=%s  重建 md5=%s" % (m[:16], res[(n, 0)][2][:16]))
    ok &= same

for n in ("c116", "c019"):
    g1, g0 = res.get((n, 1)), res.get((n, 0))
    good = g1 is not None and g0 is not None and g1[2] != g0[2]
    print("V2 %s 开窗版存在且与关窗版不同      : %s" % (n, "PASS" if good else "FAIL"))
    ok &= good

for n in ("c116", "c019"):
    g1, g0 = res.get((n, 1)), res.get((n, 0))
    if not g1 or not g0:
        print("V3 %s : SKIP" % n)
        ok = False
        continue
    r = g1[0] / g0[0]
    good = 0.90 <= r <= 1.10
    print("V3 %s 开窗/关窗 三角面比 = %.4f     : %s" % (n, r, "PASS" if good else "FAIL"))
    ok &= good

print()
print("交付件陈旧度对照（证明重建确有必要）：")
for n in ("c116", "c019"):
    d = os.path.join(BK, n, "%s-building.glb" % n)
    if os.path.exists(d) and (n, 0) in res:
        j = tri_count(d)
        print("  %s 交付 %8d 三角面 → 重建 %8d = %5.1f%%"
              % (n, j, res[(n, 0)][0], 100.0 * j / res[(n, 0)][0]))

print("\n" + ("全部 PASS" if ok else "存在 FAIL —— 不要往下跑批量"))
