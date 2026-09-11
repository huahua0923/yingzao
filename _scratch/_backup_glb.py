# -*- coding: utf-8 -*-
"""重出 GLB 前的一次性备份：49 个交付 GLB + 49 个 profile.json。

D:\gym3d 不是 git 仓，覆盖交付件必须有可回滚的副本。
备份到 _backup_glb_20260910/，带 MANIFEST（相对路径 → 字节数 + md5 前16位），
还原脚本按 MANIFEST 校验着回拷，不靠文件名猜。
"""
import hashlib
import json
import os
import shutil
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

B = r"D:\gym3d\data\buildings"
BK = r"D:\gym3d\_backup_glb_20260910"


def md5_16(path):
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()[:16]


total = 0
n = 0
os.makedirs(BK, exist_ok=True)
manifest = {}

for name in sorted(os.listdir(B)):
    d = os.path.join(B, name)
    if not os.path.isdir(d) or not os.path.exists(os.path.join(d, "profile.json")):
        continue
    for rel in (f"{name}-building.glb", "profile.json"):
        src = os.path.join(d, rel)
        if not os.path.exists(src):
            continue
        dst = os.path.join(BK, name, rel)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(src, dst)
        size = os.path.getsize(src)
        manifest[f"{name}/{rel}"] = {"bytes": size, "md5_16": md5_16(src)}
        total += size
        n += 1

with open(os.path.join(BK, "MANIFEST.json"), "w", encoding="utf-8") as f:
    json.dump(manifest, f, ensure_ascii=False, indent=1)

print("已备份 %d 个文件，共 %.1f MB → %s" % (n, total / 1048576.0, BK))
glbs = [k for k in manifest if k.endswith(".glb")]
print("其中 GLB %d 个（%.1f MB）、profile %d 个"
      % (len(glbs), sum(manifest[k]["bytes"] for k in glbs) / 1048576.0,
         len(manifest) - len(glbs)))
