# -*- coding: utf-8 -*-
"""普查：墙有没有 id、窗有没有 wallId、两者能不能对上。

决定怎么修 build_standard_glb.py:154 的 KeyError：
  - 若普遍对得上 → 只是「墙缺 id」的个例，用 w.get("id") 兜底即可
  - 若普遍对不上 → 说明 wallId 本来就是废字段，窗户从来只能当贴面玻璃
"""
import glob
import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
B = r"D:\gym3d\data\buildings"

print("%-8s %7s %7s %8s %8s %9s %9s" %
      ("楼", "墙总数", "有id", "窗总数", "有wallId", "能匹配", "会崩"))
print("-" * 62)
tot = {"w": 0, "wi": 0, "wi_id": 0, "wi_wid": 0, "match": 0}
crash = []
for name in sorted(os.listdir(B)):
    d = os.path.join(B, name, "floors")
    if not os.path.isdir(d):
        continue
    nw = nwi = nwi_id = nwi_wid = nmatch = 0
    will_crash = False
    for fp in sorted(glob.glob(os.path.join(d, "floor*.json"))):
        fl = json.load(open(fp, encoding="utf-8"))
        walls = fl.get("walls") or []
        wins = fl.get("windows") or []
        ids = {w.get("id") for w in walls}
        nw += len(walls)
        nwi += len(wins)
        nwi_id += sum(1 for w in walls if "id" in w)
        for win in wins:
            wid = win.get("wallId")
            if wid is not None:
                nwi_wid += 1
                if wid in ids:
                    nmatch += 1
        # 崩的条件：有窗可渲染 且 存在墙缺 id 且 窗引用了 wallId
        if wins and any("id" not in w for w in walls):
            will_crash = True
    if nw == 0 and nwi == 0:
        continue
    print("%-8s %7d %7d %8d %8d %9d %9s"
          % (name, nw, nwi_id, nwi, nwi_wid, nmatch, "是" if will_crash else "-"))
    for k, v in (("w", nw), ("wi", nwi), ("wi_id", nwi_id), ("wi_wid", nwi_wid),
                 ("match", nmatch)):
        tot[k] += v
    if will_crash:
        crash.append(name)

print("\n合计: 墙 %d（有id %d）/ 窗 %d（有wallId %d）/ 能匹配 %d"
      % (tot["w"], tot["wi_id"], tot["wi"], tot["wi_wid"], tot["match"]))
print("开窗会崩的楼 %d 栋: %s" % (len(crash), ",".join(crash) or "无"))
