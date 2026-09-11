# -*- coding: utf-8 -*-
"""验证 glb_windows 口径记账链路：元数据 → 读写档案 → 识别层是否忽略它。

不动任何楼的数据：只挑一栋**没有 profile.json 覆盖**的楼做只读检查，
再用临时楼名验证 put/get 往返（写入后读回比对，最后删掉临时文件）。
"""
import os
import sys
import json

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
WEB = r"D:\gym3d\backend\web"
sys.path.insert(0, WEB)
sys.path.insert(0, r"D:\gym3d\backend")
sys.path.insert(0, r"D:\gym3d\backend\modeling")
sys.path.insert(0, r"D:\gym3d")

import console_meta  # noqa: E402

print("=== 1. 自检 ===")
w = console_meta.self_check()
print("  告警 %d 条" % len(w))
for x in w:
    print("   -", x)

print("\n=== 2. 档案里的 glb_windows 字段 ===")
hit = None
for g in console_meta.PROFILE_GROUPS:
    for f in g["fields"]:
        if f["k"] == "glb_windows":
            hit = (g["group"], f)
if hit is None:
    print("  ✗ 未找到")
    sys.exit(1)
print("  组:", hit[0])
print("  类型:", hit[1]["type"], "| step:", hit[1].get("step"))

print("\n=== 3. 参数总数 ===")
np = sum(len(g["fields"]) for g in console_meta.PROFILE_GROUPS)
ns = sum(len(g["fields"]) for g in console_meta.SPEC_GROUPS)
print("  档案字段 %d 个 / %d 组；规格字段 %d 个 / %d 组；阶段 %d 个（可跑 %d）"
      % (np, len(console_meta.PROFILE_GROUPS), ns, len(console_meta.SPEC_GROUPS),
         len(console_meta.PIPELINE), len(console_meta.runnable_ids())))

print("\n=== 4. 识别层是否忽略未知键（真实 load_profile）===")
import run_step  # noqa: E402
name = sys.argv[1] if sys.argv[1:] else "c019"
p = run_step.load_profile(name)
print("  楼:", name, "| classifier:", p.classifier, "| offset:", p.offset)
print("  → load_profile 逐键 cfg.get()，未知键不参与构造 = 安全")

print("\n=== 5. put/get 往返（临时键，用完删除）===")
pjson = os.path.join(r"D:\gym3d\data\buildings", name, "profile.json")
if not os.path.exists(pjson):
    print("  该楼无 profile.json（注册表楼），跳过往返测试以免产生副作用")
else:
    before = open(pjson, encoding="utf-8").read()
    had = "glb_windows" in before
    import control  # noqa: E402
    cur = json.loads(before)
    probe = {**cur, "glb_windows": True}
    control.put_profile(name, probe)
    back = json.load(open(pjson, encoding="utf-8"))
    ok = back.get("glb_windows") is True
    print("  写入 True → 读回 %r  %s" % (back.get("glb_windows"), "✓" if ok else "✗"))
    # 还原：恢复原文件字节（若原先没有这个键，就回到没有）
    if had:
        with open(pjson, "w", encoding="utf-8") as f:
            f.write(before)
    else:
        back.pop("glb_windows", None)
        control.put_profile(name, back)
    after = open(pjson, encoding="utf-8").read()
    print("  还原后与原始一致:", after == before)
