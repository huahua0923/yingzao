# -*- coding: utf-8 -*-
"""glb_common 去 numpy 化的输出等价性验证（第二轮，金标准）。

判据 A（决定性）：c019 关窗版重出，必须与**交付备份**逐字节相同。
    交付备份是改前代码产的，md5=191e82ca90adb7ecc70a7fe6834710c6。2,036,892 面
    里只要有一个绕序被翻，md5 就对不上。
判据 B：同参数连建两次，md5 必须一致（确定性）。
判据 C（参考，非判据）：c116 与 win_probe 里的旧文件比 —— 那两文件 mtime 同为
    19:52，而单栋实际要 18 分钟，不可能是同一次顺序跑出来的，先当它不可信。
"""
import hashlib
import json
import os
import struct
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, r"D:\gym3d\backend\web")

import run_step                      # noqa: E402
import build_standard_glb as bsg     # noqa: E402

SCRATCH = r"D:\gym3d\_scratch\win_probe"
BK = r"D:\gym3d\_backup_glb_20260910"
os.makedirs(SCRATCH, exist_ok=True)


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


def build(name, win, tag):
    p = run_step.load_profile(name)
    bsg.DATA = os.path.dirname(p.out_dir)
    bsg.INCLUDE_SYNTHETIC_WINDOWS = win
    bsg.SKIP_FLOORS = set()
    dst = os.path.join(SCRATCH, "_v2_%s.glb" % tag)
    bsg.OUT = dst
    t = time.time()
    bsg.main()
    el = time.time() - t
    print("  -> %-14s %7.1fs  %8d 面  md5=%s" % (tag, el, tri_count(dst), md5(dst)), flush=True)
    return dst


print("=== A: c019 关窗 vs 交付备份（决定性）===", flush=True)
d = build("c019", False, "c019_off")
ref = os.path.join(BK, "c019", "c019-building.glb")
a, b = md5(d), md5(ref)
print("A %s  新=%s 交付=%s" % ("PASS 逐字节相同" if a == b else "FAIL 不同", a, b), flush=True)

print("\n=== B: c116 开窗 连建两次（确定性）===", flush=True)
x1 = build("c116", True, "c116_on_1")
x2 = build("c116", True, "c116_on_2")
print("B %s" % ("PASS 两次一致" if md5(x1) == md5(x2) else "FAIL 两次不一致"), flush=True)

print("\n=== C: c116 关窗 连建两次（确定性）===", flush=True)
y1 = build("c116", False, "c116_off_1")
y2 = build("c116", False, "c116_off_2")
print("C %s" % ("PASS 两次一致" if md5(y1) == md5(y2) else "FAIL 两次不一致"), flush=True)

print("\n=== 参考：与 win_probe 旧文件对比（旧文件 mtime 可疑，不作判据）===", flush=True)
for tag, old in (("c116_on_1", "c116_win1.glb"), ("c116_off_1", "c116_win0.glb")):
    op = os.path.join(SCRATCH, old)
    np_ = os.path.join(SCRATCH, "_v2_%s.glb" % tag)
    if os.path.exists(op):
        print("  %-12s 旧 %8d 面 md5=%s | 新 %8d 面 md5=%s"
              % (old, tri_count(op), md5(op)[:16], tri_count(np_), md5(np_)[:16]), flush=True)
