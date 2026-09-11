# -*- coding: utf-8 -*-
"""九教(c009) 去掉一楼：只改 GLB 导出档位，楼层数据一个字节不动。

做法：profile.json 加 "skip_floors": [0]（0 基，即首层）。
build_standard_glb 的 load_floors 会跳过它，并把保留的层按序号重新落到地面。
可逆：删掉这个键再重出 GLB 即恢复。

验证：楼层 JSON 哈希前后不变 + GLB bbox 最高点从 4 层高降到 3 层高。
"""
import glob
import hashlib
import json
import os
import shutil
import struct
import subprocess
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

B = r"D:\gym3d\data\buildings\c009"
WEB = r"D:\gym3d\backend\web"
PROF = os.path.join(B, "profile.json")
GLB = os.path.join(B, "c009-building.glb")
BK = r"D:\gym3d\_backup_glb_20260910\c009"


def floors_hash():
    h = hashlib.md5()
    for fn in sorted(os.listdir(os.path.join(B, "floors"))):
        if fn.startswith("floor") and fn.endswith(".json"):
            h.update(fn.encode())
            with open(os.path.join(B, "floors", fn), "rb") as f:
                h.update(f.read())
    return h.hexdigest()


def bbox(path):
    with open(path, "rb") as f:
        data = f.read()
    off = 12
    while off + 8 <= len(data):
        clen, ctype = struct.unpack_from("<II", data, off)
        if ctype == 0x4E4F534A:
            j = json.loads(data[off + 8: off + 8 + clen].decode("utf-8"))
            lo = [1e18] * 3
            hi = [-1e18] * 3
            for m in j.get("meshes", []):
                for p in m.get("primitives", []):
                    a = j["accessors"][p["attributes"]["POSITION"]]
                    for k in range(3):
                        lo[k] = min(lo[k], a["min"][k])
                        hi[k] = max(hi[k], a["max"][k])
            return lo, hi
        off += 8 + clen
    return None, None


spec = json.load(open(os.path.join(B, "spec.json"), encoding="utf-8"))
fh = spec.get("floor_h", 4.2)

h0 = floors_hash()
lo0, hi0 = bbox(GLB)
print("改前: 楼层哈希 %s  高 %.2f m（%.0f 层 × %.1f）"
      % (h0[:12], hi0[1], hi0[1] / fh, fh))
print("       GLB %.1f MB" % (os.path.getsize(GLB) / 1048576.0))

cfg = json.load(open(PROF, encoding="utf-8"))
before = cfg.get("skip_floors")
cfg["skip_floors"] = [0]
with open(PROF, "w", encoding="utf-8") as f:
    json.dump(cfg, f, ensure_ascii=False, indent=1)
print("已写 skip_floors=[0]（原值 %r）→ %s" % (before, PROF))

t = time.time()
r = subprocess.run([sys.executable, "run_step.py", "c009", "glb"],
                   cwd=WEB, capture_output=True, text=True,
                   encoding="utf-8", errors="replace")
print("重建 %.1fs  ok=%s" % (time.time() - t, '"ok": true' in (r.stdout or "")))

h1 = floors_hash()
lo1, hi1 = bbox(GLB)
print("改后: 楼层哈希 %s  高 %.2f m（%.0f 层 × %.1f）"
      % (h1[:12], hi1[1], hi1[1] / fh, fh))
print("       GLB %.1f MB" % (os.path.getsize(GLB) / 1048576.0))
print()
print("楼层数据未被改动 :", "PASS" if h0 == h1 else "**FAIL 被改了**")
# 注意别按层数硬编码断言：c009 是 6 层（0~5），剔掉一层后是 5 层。
# 正确判据是**高度差恰好等于一个层高**（屋顶跟随，绝对高度会一起降）。
drop = hi0[1] - hi1[1]
print("高度恰好降一层    : %s（降了 %.2f m，层高 %.1f）"
      % ("PASS" if abs(drop - fh) < 0.05 else "FAIL", drop, fh))
print("（备份：档案 %s\\profile.json，GLB %s）" % (BK, BK))
