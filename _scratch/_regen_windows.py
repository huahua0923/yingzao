# -*- coding: utf-8 -*-
"""逐栋重生成 GLB（开窗 + 铝合金窗框 + 玻璃），不重新识别，只读现有 floors/spec。

用法:
  python -u _regen_windows.py            # 全部 data/buildings 下的楼
  python -u _regen_windows.py c006 c009  # 只跑指定楼

每栋一行 `[i/N] name OK 面=.. 尺寸=..`，flush 立即写日志，可 tail 看进展。
"""
import contextlib
import io
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
sys.path.insert(0, r"D:\gym3d\backend\modeling")

import build_standard_glb as bsg

BASE = r"D:\gym3d\data\buildings"


def regen(name):
    name = name.rstrip("/\\")
    d = os.path.join(BASE, name)
    bsg.DATA = d
    bsg.OUT = os.path.join(d, f"{name}-building.glb")
    bsg.INCLUDE_SYNTHETIC_WINDOWS = True
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        bsg.main()
    import trimesh
    sc = trimesh.load(bsg.OUT, process=False)
    nfaces = sum(len(g.faces) for g in sc.geometry.values() if hasattr(g, "faces"))
    b = sc.bounds
    return (f"OK 面={nfaces} 尺寸={b[1][0]-b[0][0]:.0f}x{b[1][1]-b[0][1]:.0f}"
            f"x{b[1][2]-b[0][2]:.0f}m")


def main():
    names = sys.argv[1:]
    if not names:
        names = sorted(d for d in os.listdir(BASE)
                       if os.path.isdir(os.path.join(BASE, d))
                       and os.path.exists(os.path.join(BASE, d, "profile.json")))
    N = len(names)
    ok, fail = [], []
    for i, name in enumerate(names, 1):
        sys.stdout.write(f"[{i}/{N}] {name:6s} ...")
        sys.stdout.flush()
        try:
            r = regen(name)
            sys.stdout.write(f"\r[{i}/{N}] {name:6s} {r}\n")
            sys.stdout.flush()
            ok.append(name)
        except Exception as e:
            sys.stdout.write(f"\r[{i}/{N}] {name:6s} FAIL {type(e).__name__}: {e}\n")
            sys.stdout.flush()
            fail.append(name)
    print(f"\n汇总: 成功 {len(ok)} / 失败 {len(fail)}")
    if fail:
        print("失败:", ", ".join(fail))


if __name__ == "__main__":
    main()
