# -*- coding: utf-8 -*-
"""c041 层序倒置修复: 给 profile.json 加降序 floor_ys, 让模型 F0 对应真实 1 层。

图纸事实(用『6房间号』文本反推): Y 带 0(最低) 是 41-06(6层), Y带 5(最高) 是 41-01(1层)。
原 profile 无 floor_ys → floor_of = round((y-cy)/offset) 升序编号 → 模型 F0=6层 … F5=1层。

修法(纯配置, 不动引擎): 加 floor_ys = [cy+5*offset, ..., cy+0*offset] 降序, 使
  F0 -> 最高带(真实1层)  ... F5 -> 最低带(真实6层)
分区边界(相邻中点)与原来完全相同, 只是把层号反过来 → 每层本地几何形状不变, 只换标号 + is_top。

用法: python _c041_flip_floororder.py           # 预览(只读)
      python _c041_flip_floororder.py --apply   # 备份 profile.json 后写入
"""
import os, sys, json, shutil

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path[:0] = [r"D:\gym3d", r"D:\gym3d\backend", r"D:\gym3d\backend\web"]
from run_building import load_profile

NAME = "c041"
D = os.path.join(r"D:\gym3d\data\buildings", NAME)
PROF = os.path.join(D, "profile.json")
APPLY = "--apply" in sys.argv

p = load_profile(NAME)
if p.floor_ys or p.floor_plans:
    print("已存在 floor_ys/floor_plans, 非均匀楼 -> 本脚本不适用"); sys.exit(1)

# 现状: 模型 F 的中心 = cy + F*offset。倒置: 新 F 的中心 = cy + (N-1-F)*offset
# N: 层数由现有 floors 目录推断
import glob
N = len(sorted(glob.glob(os.path.join(D, "floors", "floor*.json"))))
desc = [round(p.cy + (N - 1 - f) * p.offset, 3) for f in range(N)]
print("楼=%s N=%d cy=%s offset=%s" % (NAME, N, p.cy, p.offset))
print("新 floor_ys(降序, 模型F0=真实1层): %s" % desc)

with open(PROF, encoding="utf-8") as f:
    t = f.read()
assert '"floor_ys"' not in t, "profile 里已有 floor_ys"
assert t.count("\r") == 0, "profile 含 CRLF, 请先查"
anchor = ' "outline_unify"'
assert t.count(anchor) == 1, "锚点不唯一"
ins = ' "floor_ys": %s,\n' % json.dumps(desc)
new = t.replace(anchor, ins + anchor)

if not APPLY:
    print("\n[预览] 将插入:\n%s" % ins.strip())
    print("[预览] 写回后 profile 前 3 行不变, 仅多一行 floor_ys。加 --apply 生效。")
    sys.exit(0)

os.makedirs(os.path.join(D, ".orig"), exist_ok=True)
bak = os.path.join(D, ".orig", "profile.json.before_floorflip")
if not os.path.exists(bak):
    shutil.copy2(PROF, bak)
with open(PROF, "w", encoding="utf-8", newline="") as f:
    f.write(new)
print("已写入 %s (备份 %s)" % (PROF, bak))
chk = json.load(open(PROF, encoding="utf-8"))
print("校验: floor_ys=%s len=%d" % (chk["floor_ys"], len(chk["floor_ys"])))
