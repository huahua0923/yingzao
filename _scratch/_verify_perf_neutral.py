# -*- coding: utf-8 -*-
"""验证 glb_common 去 numpy 化后**输出逐字节不变**（性能改动必须零几何影响）。

两个比对面都是「改前代码」产的，md5 已知：
  A) 交付备份 c019-building.glb          = 191e82ca90adb7ecc70a7fe6834710c6   （整楼、关窗）
  B) 改前产的 c116_win0.glb（开窗路径）  = fa7261a46a435887...                （走窗洞代码）
B 尤其重要：它证明**窗洞那条路径**也没被这次改动碰到。

两栋都重出到新文件名，不覆盖旧产物。
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


CASES = [
    ("c019", False, os.path.join(BK, "c019", "c019-building.glb")),
    ("c116", False, os.path.join(SCRATCH, "c116_win0.glb")),
    ("c116", True, os.path.join(SCRATCH, "c116_win1.glb")),
]

ok = True
for name, win, ref in CASES:
    p = run_step.load_profile(name)
    bsg.DATA = os.path.dirname(p.out_dir)
    bsg.INCLUDE_SYNTHETIC_WINDOWS = win
    bsg.SKIP_FLOORS = set()
    dst = os.path.join(SCRATCH, "_new_%s_win%d.glb" % (name, int(win)))
    bsg.OUT = dst
    t = time.time()
    bsg.main()
    el = time.time() - t
    a, b = md5(dst), md5(ref) if os.path.exists(ref) else "缺参照"
    same = a == b
    ok &= same
    print("%s win=%-5s %7.1fs  %8d 面  %s"
          % (name, win, el, tri_count(dst), "逐字节相同 PASS" if same else "**不同 FAIL**"))
    if not same:
        print("    新 md5=%s\n    旧 md5=%s" % (a, b))

print("\n" + ("全部逐字节相同 —— 性能改动零几何影响" if ok else "存在差异 —— 必须回退"))
sys.exit(0 if ok else 1)
