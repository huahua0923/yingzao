# -*- coding: utf-8 -*-
"""验证「清空字段」真的能清掉：合并写 + null 删除的往返。

背景：put_profile 是合并写（{**existing, **obj}），它的副作用是**键永远删不掉**。
前端清空「逐层 Y 中心」这类字段后，旧值会被原样搬回来 —— 「留空=不启用」失效。
约定 null = 显式关闭后必须逐项验证。

只在临时楼名上测，不碰任何真实楼栋档案。
"""
import os
import sys
import json
import shutil

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, r"D:\gym3d\backend\web")
sys.path.insert(0, r"D:\gym3d\backend")
sys.path.insert(0, r"D:\gym3d")

import control  # noqa: E402

NAME = "zz_null_probe"
B = os.path.join(r"D:\gym3d\data\buildings", NAME)
shutil.rmtree(B, ignore_errors=True)
os.makedirs(B, exist_ok=True)

# 起手：一个有 floor_ys / x_range / glb_windows=false 的真实档案形态
seed = {
    "name": NAME, "title": "临时探针楼", "offset": 90025.0,
    "floor_ys": [1000.0, 2000.0, 3000.0],
    "x_range": [0.0, 50000.0],
    "outline_unify": True,
    "glb_windows": False,
}
with open(os.path.join(B, "profile.json"), "w", encoding="utf-8") as f:
    json.dump(seed, f, ensure_ascii=False, indent=1)

ok = True


def show(tag):
    d = json.load(open(os.path.join(B, "profile.json"), encoding="utf-8"))
    print("  %s → keys=%s" % (tag, sorted(d.keys())))
    return d


show("起手")

# 1. 传 null 清空 floor_ys 与 x_range，同时改 glb_windows
d = show("清空后") if False else None
control.put_profile(NAME, {**json.load(open(os.path.join(B, "profile.json"), encoding="utf-8")),
                           "floor_ys": None, "x_range": None, "glb_windows": True})
d = show("传 null 清空 floor_ys/x_range")
if "floor_ys" in d or "x_range" in d:
    print("  ✗ 清空失败：null 没能删掉键（旧值被合并搬回）")
    ok = False
else:
    print("  ✓ 清空成功：键已删除")
if d.get("glb_windows") is not True:
    print("  ✗ glb_windows 没能从 false 改成 true")
    ok = False
else:
    print("  ✓ glb_windows=false → true 保留（未被 null 规则误删）")

# 2. false 必须活着（不能被当空值删掉）
control.put_profile(NAME, {**d, "glb_windows": False})
d = show("写 glb_windows=false")
if d.get("glb_windows") is not False:
    print("  ✗ glb_windows=false 被误删了 —— 假值判断写错了")
    ok = False
else:
    print("  ✓ glb_windows=false 存活")

# 3. 合并语义仍要护住高级字段：只传 title，floor_ys 应保留
control.put_profile(NAME, {**d, "floor_ys": [7.0, 8.0]})
d = show("重设 floor_ys")
control.put_profile(NAME, {"title": "只改标题"})
d = show("只传 title")
if "name" in d and d.get("floor_ys") == [7.0, 8.0]:
    print("  ✓ 合并语义完好：只传 title 没冲掉其它键")
else:
    print("  ✗ 合并语义被破坏")
    ok = False

shutil.rmtree(B, ignore_errors=True)
print("\n清理:", "该目录已删" if not os.path.exists(B) else "残留！")
print("总结:", "全部通过 ✓" if ok else "有失败 ✗")
sys.exit(0 if ok else 1)
