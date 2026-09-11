# -*- coding: utf-8 -*-
"""把「斜墙/曲墙配对」接进薄墙路径(默认关, 按楼 opt-in)。二进制写盘以保住 LF。

三处改动, 全部向后兼容:
  1) profile.py:    BuildingProfile 末尾加 pair_curved: bool = False
  2) run_building.py: load_profile 透传 cfg["pair_curved"]
  3) _wall_thin_batch.py: rebuild_floor 在 pair_wall_faces 之后, 若该楼开启则把
     「斜段」交给 curve_walls.pair_curved_faces, 结果并入同一 rects/singles。
     轴对齐段仍只走旧配对(_flatten_all_segments 的轴桶已验与旧函数逐段等价),
     因此不开启的楼一个字节都不变。
幂等: 已打过的文件跳过。
"""
import os, sys, shutil

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = r"D:\gym3d"
REC = os.path.join(ROOT, "backend", "recognizer")

FILES = [os.path.join(REC, "profile.py"),
         os.path.join(ROOT, "run_building.py"),
         os.path.join(ROOT, "_wall_thin_batch.py")]
for f in FILES:
    src = open(f, encoding="utf-8").read()
    assert "\r" not in src, "%s 含 CRLF, 先处理" % f

# ---------- 1) profile.py ----------
P1 = os.path.join(REC, "profile.py")
s1 = open(P1, encoding="utf-8").read()
A1 = "    door_by_points: bool = False\n"
NEW1 = '''    door_by_points: bool = False

    # 可选：True = 薄墙配对时额外识别「斜墙 / 曲墙」。默认配对(pair_wall_faces)把每段按
    # |dx|>=|dy| 塞进水平/垂直两桶, 斜段与弧离散出的短弦会被直接丢弃 → 曲墙识别不出来。
    # 开启后, 轴对齐段仍走原配对(逐段等价), 剩下的斜段交给 curve_walls.pair_curved_faces
    # 用线段自身方向配对(同 wall_min/wall_max 间距、投影重叠 >0.3m)。
    # 默认 False: 无斜墙/曲墙的楼一个字节都不变。
    pair_curved: bool = False
'''
if "pair_curved" in s1:
    print("profile.py 已有 pair_curved, 跳过")
else:
    assert s1.count(A1) == 1, "profile.py 锚点不匹配"
    shutil.copy2(P1, os.path.join(REC, ".orig_engine", "profile.py.before_paircurved"))
    open(P1, "w", encoding="utf-8", newline="").write(s1.replace(A1, NEW1))
    print("已改 profile.py")

# ---------- 2) run_building.py ----------
P2 = os.path.join(ROOT, "run_building.py")
s2 = open(P2, encoding="utf-8").read()
A2 = '        outline_unify_floors=[int(v) for v in cfg["outline_unify_floors"]] if cfg.get("outline_unify_floors") else None,\n'
if "pair_curved" in s2:
    print("run_building.py 已有 pair_curved, 跳过")
else:
    assert s2.count(A2) == 1, "run_building.py 锚点不匹配"
    shutil.copy2(P2, os.path.join(REC, ".orig_engine", "run_building.py.before_paircurved"))
    open(P2, "w", encoding="utf-8", newline="").write(
        s2.replace(A2, A2 + '        pair_curved=bool(cfg.get("pair_curved", False)),\n'))
    print("已改 run_building.py")

# ---------- 3) _wall_thin_batch.py ----------
P3 = os.path.join(ROOT, "_wall_thin_batch.py")
s3 = open(P3, encoding="utf-8").read()
A3i = "from backend.recognizer import geometry as G\n"
A3b = """    rects, singles = G.pair_wall_faces(segs, p)
"""
NEW3 = """    rects, singles = G.pair_wall_faces(segs, p)
    if getattr(p, "pair_curved", False):
        # 斜墙/曲墙(opt-in): 轴对齐段已由上面配走, 这里只吃斜段, 两边不重叠。
        # 厚度取两皮实测间距(该楼无 wall_thicknesses snap 时不冲突; 有 snap 的楼不启用本项)。
        _axis2, _diag = CW._flatten_all_segments(_keep)
        cr, cs = CW.pair_curved_faces(_diag, p)
        rects = list(rects) + list(cr)
        singles = list(singles) + list(cs)
"""
if "pair_curved" in s3:
    print("_wall_thin_batch.py 已有 pair_curved, 跳过")
else:
    assert s3.count(A3i) == 1, "import 锚点不匹配"
    assert s3.count(A3b) == 1, "rebuild_floor 锚点不匹配"
    shutil.copy2(P3, os.path.join(REC, ".orig_engine", "_wall_thin_batch.py.before_paircurved"))
    s3 = s3.replace(A3i, A3i + "from backend.recognizer import curve_walls as CW\n")
    s3 = s3.replace(A3b, NEW3)
    open(P3, "w", encoding="utf-8", newline="").write(s3)
    print("已改 _wall_thin_batch.py")

print("完成.")
