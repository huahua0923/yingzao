# -*- coding: utf-8 -*-
"""批量重出后的体检报告：体积对照、超阈值清单、GLB 完整性。

对照基准 = _backup_glb_20260910/MANIFEST.json（改前的交付件字节数）。
"""
import json
import os
import struct
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

B = r"D:\gym3d\data\buildings"
MANI = r"D:\gym3d\_backup_glb_20260910\MANIFEST.json"
MB = 1048576.0

with open(MANI, encoding="utf-8") as f:
    old = json.load(f)


def header_ok(path):
    """GLB 头校验：magic/version/length 与实际文件长度一致。"""
    sz = os.path.getsize(path)
    with open(path, "rb") as f:
        head = f.read(12)
    if len(head) < 12:
        return False, "文件不足 12 字节"
    magic, ver, length = struct.unpack("<III", head)
    if magic != 0x46546C67:
        return False, "magic 不是 glTF"
    if ver != 2:
        return False, "version=%d" % ver
    if length != sz:
        return False, "声明长度 %d != 实际 %d（截断）" % (length, sz)
    return True, "ok"


names = sorted(d for d in os.listdir(B) if os.path.isdir(os.path.join(B, d)))
rows = []
tot_old = tot_new = 0.0
bad = []
big = []
for n in names:
    p = os.path.join(B, n, "%s-building.glb" % n)
    ok, msg = header_ok(p)
    new = os.path.getsize(p)
    o = old.get("%s/%s-building.glb" % (n, n)) or {}
    ob = o.get("bytes") or 0
    rows.append((n, ob / MB, new / MB, (new / ob if ob else 0)))
    tot_old += ob / MB
    tot_new += new / MB
    if not ok:
        bad.append((n, msg))
    if new / MB > 50:
        big.append((n, new / MB))

rows.sort(key=lambda r: -r[3])
print("按放大倍数排序（前 15）:")
print("%-6s %10s %10s %8s" % ("楼栋", "改前MB", "改后MB", "倍数"))
for n, a, b, r in rows[:15]:
    print("%-6s %10.1f %10.1f %7.1fx" % (n, a, b, r))

print("\n体积汇总：改前 %.1f MB → 改后 %.1f MB（%.1f 倍）"
      % (tot_old, tot_new, tot_new / tot_old))

print("\n超过 50MB 的楼栋（%d 栋）:" % len(big))
for n, s in sorted(big, key=lambda x: -x[1]):
    print("   %-6s %8.1f MB" % (n, s))

print("\nGLB 头校验失败：%s" % (bad if bad else "无，49 栋全部完整"))

# 未变大的（说明这些楼的交付件本来就是新的）
flat = [r for r in rows if r[3] < 1.05]
print("\n体积基本没变的（交付件本来就新）%d 栋: %s"
      % (len(flat), [r[0] for r in flat]))
