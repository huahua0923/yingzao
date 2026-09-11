# -*- coding: utf-8 -*-
"""c041 层序倒置修复(数据重映射): 用 .orig/before_floorflip 的薄墙层按新层序装回。

事实: 旧 floor_b.json 的本地坐标相对旧层心 cy+b*offset; 新 profile 的 floor_ys 为降序,
新层 F 的层心 = cy+(N-1-F)*offset。取 F = N-1-b 时两者相等 -> 旧层几何对新层原样有效。
        (outline 各层全同, 已核; roof 只是 spec 常量, 归新顶层)

即: new[F] = old[N-1-F], 再把 roof 键从旧顶层挪到新顶层。

用法: python _c041_apply_remap.py [--dry]
"""
import os, sys, json, glob, shutil

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
NAME = "c041"
D = os.path.join(r"D:\gym3d\data\buildings", NAME)
FD = os.path.join(D, "floors")
BAK = os.path.join(D, ".orig", "before_floorflip", "floors")
DRY = "--dry" in sys.argv

srcs = sorted(glob.glob(os.path.join(BAK, "floor*.json")))
N = len(srcs)
assert N >= 2, "备份层数不足"
old = {}
for fp in srcs:
    old[int(os.path.basename(fp)[5:-5])] = json.load(open(fp, encoding="utf-8"))
assert sorted(old) == list(range(N)), "备份层号不连续: %s" % sorted(old)

roof = old[N - 1].get("roof") or {"roofT": 0.2, "parapetH": 0.9, "parapetT": 0.5}

# 先备份"当前 recognize 写坏的"版本, 便于回看
bad = os.path.join(D, ".orig", "floors.recognize_blob_afterflip")
if not DRY and not os.path.isdir(bad):
    shutil.copytree(FD, bad)

plan = []
for F in range(N):
    b = N - 1 - F
    fl = dict(old[b])
    fl.pop("roof", None)
    if F == N - 1:
        fl["roof"] = roof
    plan.append((F, b, len(fl["walls"]), len(fl.get("doors", [])),
                 len(fl.get("rooms", [])), len(fl.get("stairwells", [])),
                 "有" if "roof" in fl else "无"))
    if not DRY:
        json.dump(fl, open(os.path.join(FD, "floor%d.json" % F), "w", encoding="utf-8"),
                  ensure_ascii=False)

print("层序重映射 (新F <- 旧b)   N=%d" % N)
for F, b, nw, nd, nr, nsw, rf in plan:
    print("  新F%d <- 旧F%d   墙=%3d 门=%2d 房=%2d 梯井=%d roof=%s" % (F, b, nw, nd, nr, nsw, rf))
print("(预期: 新F0=真实1层 应门最多/有值班室; 新F5=真实6层 roof=有)")
print("DRY-RUN 未写盘" if DRY else "已写盘: %s" % FD)
