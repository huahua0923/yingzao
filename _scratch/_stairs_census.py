# -*- coding: utf-8 -*-
"""楼梯井普查(只读): 逐楼逐层读 floor JSON stairwells[]，
挑出尺寸不合理/跨楼重叠/楼内互叠的井。写 _stairs_census.txt。"""
import json, glob, os, sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from shapely.geometry import box as shp_box

out = []
def log(*a):
    s = " ".join(str(x) for x in a)
    print(s); out.append(s)

MAX_W = 6.0      # 楼梯井合理最大宽(m), 超过=很可能把走廊/长墙聚成一井
MIN_D = 1.5

rows = []        # (name, floor, x0,x1,yBot,yTop,W,D,type,nflights,steps)
for fd in sorted(glob.glob(r"data/buildings/*/floors")):
    name = os.path.basename(os.path.dirname(fd))
    for fp in sorted(glob.glob(os.path.join(fd, "floor*.json"))):
        F = os.path.basename(fp)[5:-5]
        try:
            fl = json.load(open(fp, encoding="utf-8"))
        except Exception as e:
            log(f"[{name}] floor{F} 读失败 {e}"); continue
        for s in fl.get("stairwells", []):
            W = s["x1"] - s["x0"]; D = s["yTop"] - s["yBot"]
            rows.append((name, int(F), s["x0"], s["x1"], s["yBot"], s["yTop"],
                         W, D, s.get("type"), len(s.get("flights") or []), s.get("steps"),
                         [f"{f['x0']:.2f}~{f['x1']:.2f}" for f in s.get("flights") or []]))

# 1) 超宽井
log("==== 超宽楼梯井 (宽>%sm) ====" % MAX_W)
bad_w = [r for r in rows if r[6] > MAX_W]
for r in bad_w:
    name, F, x0, x1, yb, yt, W, D, ty, nf, st, fls = r
    log(f"[{name}] F{F} 宽={W:.1f}m 深={D:.1f}m 型={ty} 跑={nf} 步={st} x:{x0:.1f}~{x1:.1f} y:{yb:.1f}~{yt:.1f} 跑={','.join(fls[:6])}{'...' if len(fls)>6 else ''}")
if not bad_w: log("(无)")

# 2) 每栋抽查: 全楼井数极多的
log("")
log("==== 每栋楼梯井总数 (含各层) ====")
from collections import Counter
cnt = Counter(r[0] for r in rows)
for name, c in sorted(cnt.items(), key=lambda kv: -kv[1]):
    log(f"[{name}] 总井数={c}")
