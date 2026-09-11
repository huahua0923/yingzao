# -*- coding: utf-8 -*-
"""楼梯井普查（按建筑规范判，不按拍脑袋的尺寸阈值）。

字段口径（先读原始记录确认过，别猜）：
  x0/x1    梯段横向范围（世界 x）
  yBot/yTop 梯段纵向范围（世界 z，即梯段跑的方向）；深度 = |yTop-yBot|
  steps     **每一跑**的踏步数，不是总踏步数
  type      double(双跑) / bifurcated(双分) / straight(直跑)
  flights   每跑各自的 x0/x1

判据（GB 50352 民用建筑设计统一标准，取宽一点的合理区间）：
  · 踢面高 r = floor_h / (steps × 跑数)：0.13~0.21 m
      跑数 = straight 取 1，其余取 2（两跑各上半个层高）
  · 踏步宽 t = 深度 / steps：0.22~0.35 m
  · 梯段净宽：每跑 x1-x0 ≥ 1.05 m
任一项越界 → 这口井画出来不是楼梯。
"""
import glob
import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

B = r"D:\gym3d\data\buildings"


def census(name):
    d = os.path.join(B, name, "floors")
    spec_p = os.path.join(B, name, "spec.json")
    fh = 4.2
    if os.path.exists(spec_p):
        fh = json.load(open(spec_p, encoding="utf-8")).get("floor_h", 4.2)
    tot = 0
    bad = []
    narrow = 0
    for fp in sorted(glob.glob(os.path.join(d, "floor*.json"))):
        fl = json.load(open(fp, encoding="utf-8"))
        for s in (fl.get("stairwells") or []):
            tot += 1
            st = s.get("steps") or 0
            if st <= 0:
                bad.append(("无踏步数", fl["floor"], s))
                continue
            t = s.get("type") or "double"
            runs = 1 if t == "straight" else 2
            r = fh / (st * runs)
            dep = abs(s["yTop"] - s["yBot"])
            tread = dep / st
            fls = s.get("flights") or []
            fw = min((f["x1"] - f["x0"]) for f in fls) if fls else (s["x1"] - s["x0"])
            why = []
            if not (0.13 <= r <= 0.21):
                why.append("踢面%.3f" % r)
            if not (0.22 <= tread <= 0.35):
                why.append("踏步%.3f" % tread)
            if fw < 1.05:
                why.append("梯段宽%.2f" % fw)
            if why:
                bad.append((",".join(why), fl["floor"], s))
            if fw < 0.6:
                narrow += 1
    return tot, bad, narrow, fh


print("%-6s %5s %6s %8s %s" % ("楼栋", "井数", "越界", "疑似假井", "最典型的越界原因"))
tot_all = bad_all = 0
rows = []
for name in sorted(os.listdir(B)):
    if not os.path.isdir(os.path.join(B, name, "floors")):
        continue
    tot, bad, narrow, fh = census(name)
    if not tot:
        continue
    tot_all += tot
    bad_all += len(bad)
    from collections import Counter
    c = Counter(b[0] for b in bad)
    top = c.most_common(1)[0] if c else None
    rows.append((name, tot, len(bad), narrow, top))

for name, tot, nb, narrow, top in rows:
    mark = "  <== " if nb else ""
    print("%-6s %5d %6d %8d %s%s"
          % (name, tot, nb, narrow,
             ("%s ×%d" % (top[0], top[1])) if top else "全合规", mark))

print("\n合计 %d 口井，%d 口越界（%.1f%%）" % (tot_all, bad_all, 100.0 * bad_all / tot_all))
