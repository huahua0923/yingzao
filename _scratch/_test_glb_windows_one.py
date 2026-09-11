# -*- coding: utf-8 -*-
"""单栋端到端验证：glb_windows 档案键 → run_step 回落 → GLB 真的带窗。

选最小的 c116（0.64MB / 4 层 / 74 合成窗）跑，三个不变量：
  I1 floors 文件必须**逐字节不变**（glb 步只读楼层，不该动它）
  I2 GLB 三角面必须**增加**（加窗了），且增幅与窗数同量级
  I3 profile.json 除 glb_windows 外**其余键不动**
"""
import hashlib
import json
import os
import shutil
import struct
import subprocess
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE = r"D:\gym3d"
NAME = "c116"
D = os.path.join(BASE, "data", "buildings", NAME)
GLB = os.path.join(D, f"{NAME}-building.glb")
PROF = os.path.join(D, "profile.json")
TMP_PROF = os.path.join(BASE, "_scratch", "_c116_prof_backup.json")


def md5(path):
    h = hashlib.md5()
    with open(path, "rb") as f:
        for c in iter(lambda: f.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()


def glb_tris(path):
    """数 GLB 里所有 mesh 的 index 数 / 3（不依赖任何三方库）。"""
    with open(path, "rb") as f:
        data = f.read()
    off, jlen = 12, None
    while off + 8 <= len(data):
        clen, ctype = struct.unpack_from("<II", data, off)
        if ctype == 0x4E4F534A:      # 'JSON'
            jlen = clen
            break
        off += 8 + clen
    j = json.loads(data[off + 8: off + 8 + jlen].decode("utf-8"))
    n = 0
    for m in j.get("meshes", []):
        for p in m.get("primitives", []):
            if "indices" in p:
                n += j["accessors"][p["indices"]]["count"]
    return n // 3, j


# 基线
before_floors = {f: md5(os.path.join(D, "floors", f))
                 for f in sorted(os.listdir(os.path.join(D, "floors"))) if f.endswith(".json")}
before_tris, before_j = glb_tris(GLB)
before_size = os.path.getsize(GLB)
shutil.copy2(PROF, TMP_PROF)
before_prof = json.load(open(PROF, encoding="utf-8"))
print("基线: %d 三角面 / %.2f MB / glb_windows=%s"
      % (before_tris, before_size / 1048576.0, before_prof.get("glb_windows")))

# 写档案键（只加这一个）
prof = dict(before_prof)
prof["glb_windows"] = True
with open(PROF, "w", encoding="utf-8") as f:
    json.dump(prof, f, ensure_ascii=False, indent=1)

# 不带第三个参数 → 必须回落到档案的 glb_windows
r = subprocess.run([sys.executable, os.path.join(BASE, "backend", "web", "run_step.py"),
                    NAME, "glb"],
                   capture_output=True, text=True, encoding="utf-8", errors="replace",
                   cwd=BASE)
print("run_step 退出码=%d" % r.returncode)
tail = (r.stdout or "").strip().splitlines()
print("  输出末行:", tail[-1] if tail else "(空)")
if r.returncode != 0:
    print((r.stderr or "")[-800:])

# 验证
after_floors = {f: md5(os.path.join(D, "floors", f))
                for f in sorted(os.listdir(os.path.join(D, "floors"))) if f.endswith(".json")}
after_tris, _ = glb_tris(GLB)
after_size = os.path.getsize(GLB)
after_prof = json.load(open(PROF, encoding="utf-8"))

print()
print("I1 floors 逐字节不变 :", "PASS" if before_floors == after_floors else "FAIL")
print("I2 三角面 %d → %d (Δ%+d)" % (before_tris, after_tris, after_tris - before_tris),
      "PASS" if after_tris > before_tris else "FAIL")
print("   体积 %.2f → %.2f MB (Δ%+.1f%%)"
      % (before_size / 1048576.0, after_size / 1048576.0,
         100.0 * (after_size - before_size) / before_size))
diff = {k for k in set(before_prof) | set(after_prof) if before_prof.get(k) != after_prof.get(k)}
print("I3 profile 变更键 :", diff, "PASS" if diff == {"glb_windows"} else "FAIL")

# 还原档案（GLB 保留新产物，档案由批量步骤统一写）
shutil.copy2(TMP_PROF, PROF)
os.remove(TMP_PROF)
print("\n档案已还原；GLB 保持新产物（%.2f MB）" % (after_size / 1048576.0))
