# -*- coding: utf-8 -*-
"""批量跑 run_building 的识别+校验，紧凑输出每栋 PASS/FAIL + 楼层数 + 问题。

用法:
  python run_batch.py [--glb] [--windows] <name> [<name> ...]
    （不给名字则跑 data/buildings 下全部目录）
输出: 每栋一行 `name 楼层数=N 问题=PASS|FAIL[ ...]`，末尾 `汇总 通过/失败`。
"""
import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# 路径从本文件位置推导，代码里不出现盘符（开发机在 D 盘、服务器在 /opt）。
_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_ROOT, "backend"))       # paths.py / recognizer
from paths import BUILDINGS  # noqa: E402

BASE = str(BUILDINGS)


def main():
    args = sys.argv[1:]
    do_glb = "--glb" in args
    do_windows = "--windows" in args
    names = [a for a in args if not a.startswith("--")]
    if not names:
        names = sorted(d for d in os.listdir(BASE)
                       if os.path.isdir(os.path.join(BASE, d))
                       and os.path.exists(os.path.join(BASE, d, "profile.json")))

    import run_building as rb

    passed, failed = [], []
    for name in names:
        try:
            p = rb.load_profile(name)
            os.makedirs(os.path.dirname(p.rooms), exist_ok=True)
            if not os.path.exists(p.rooms):
                with open(p.rooms, "w", encoding="utf-8") as f:
                    json.dump([], f)
            from recognizer import recognize
            floors = recognize(p)
            problems = rb.validate(name, floors)
            if problems:
                failed.append(name)
                print(f"{name:5s} 楼层数={len(floors)} FAIL " + "; ".join(problems[:4]))
            else:
                passed.append(name)
                print(f"{name:5s} 楼层数={len(floors)} PASS")

            if do_glb and not problems:
                sys.path.insert(0, os.path.join(_ROOT, "backend", "modeling"))
                import build_standard_glb as bsg
                bsg.DATA = os.path.dirname(p.out_dir)
                bsg.OUT = os.path.join(bsg.DATA, f"{name}-building.glb")
                if do_windows:
                    bsg.INCLUDE_SYNTHETIC_WINDOWS = True
                bsg.main()
                try:
                    import trimesh
                    sc = trimesh.load(bsg.OUT, process=False)
                    b = sc.bounds
                    sx = b[1][0] - b[0][0]
                    sy = b[1][1] - b[0][1]
                    sz = b[1][2] - b[0][2]
                    nfaces = sum(len(g.faces) for g in sc.geometry.values() if hasattr(g, "faces"))
                    print(f"{name:5s} GLB ✓ 面={nfaces} X={sx:.1f}m Y={sy:.1f}m Z={sz:.1f}m "
                          f"cx={((b[0][0]+b[1][0])/2):.1f}")
                except Exception as _e:
                    print(f"{name:5s} GLB ✓ {bsg.OUT} (bbox 读取失败: {_e})")
        except Exception as e:
            failed.append(name)
            import traceback
            print(f"{name:5s} EXCEPTION {type(e).__name__}: {e}")
            traceback.print_exc()

    print(f"\n汇总: 通过 {len(passed)} / 失败 {len(failed)}")
    if failed:
        print("失败: " + ", ".join(failed))


if __name__ == "__main__":
    main()
