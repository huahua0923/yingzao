# -*- coding: utf-8 -*-
"""判定某栋「已交付 GLB」是不是带合成窗导出的。

方法：把同一份 floor JSON 分别按 windows=False / True 重建到 _scratch/ 临时路径
（**不碰交付件**），与交付件的三角数比对，谁接近谁就是当年的口径。

为什么必须实测：所有 floor JSON 的窗都标 synthetic=True，而 INCLUDE_SYNTHETIC_WINDOWS
在 run_step / run_building --glb 下默认 False —— 控制台「生成 GLB」不勾选就会**静默剥掉窗**。
这个口径不记在档案里，每次重建都是重新猜。本探针把「猜」变成「量」。
"""
import os
import sys
import struct
import json

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, r"D:\gym3d")
sys.path.insert(0, r"D:\gym3d\backend")
sys.path.insert(0, r"D:\gym3d\backend\modeling")
sys.path.insert(0, r"D:\gym3d\backend\web")
import run_step            # noqa: E402
import build_standard_glb as bsg  # noqa: E402

SCRATCH = r"D:\gym3d\_scratch"


def tris(p):
    raw = open(p, "rb").read()
    clen = struct.unpack("<II", raw[12:20])[0]
    j = json.loads(raw[20:20 + clen].decode("utf-8"))
    n = 0
    for m in j.get("meshes", []):
        for pr in m["primitives"]:
            if "indices" in pr:
                n += j["accessors"][pr["indices"]]["count"] // 3
    return n


name = sys.argv[1] if sys.argv[1:] else "c019"
p = run_step.load_profile(name)
out_parent = os.path.dirname(p.out_dir)
delivered = os.path.join(out_parent, f"{name}-building.glb")

print(f"=== {name} ===")
print(f"  交付件      {os.path.getsize(delivered):>12,} B  {tris(delivered):>9,} 三角")

bsg.DATA = out_parent
for win in (False, True):
    bsg.INCLUDE_SYNTHETIC_WINDOWS = win
    dst = os.path.join(SCRATCH, f"probe_{name}_win{int(win)}.glb")
    bsg.OUT = dst
    print(f"--- 重建 windows={win} → {os.path.basename(dst)} ---", flush=True)
    bsg.main()
    print(f"  windows={win:<5} {os.path.getsize(dst):>12,} B  {tris(dst):>9,} 三角", flush=True)
