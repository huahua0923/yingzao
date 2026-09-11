# -*- coding: utf-8 -*-
"""c041 层序核对: 用 DXF『6房间号』文本的楼层前缀(XX-FF-NN)反推每层真实层号。
只读诊断, 不改任何数据。"""
import sys, re, collections
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path[:0] = [r"D:\gym3d", r"D:\gym3d\backend", r"D:\gym3d\backend\web"]
import ezdxf
from run_building import load_profile

NAME = sys.argv[1] if len(sys.argv) > 1 else "c041"
p = load_profile(NAME)
doc = ezdxf.readfile(p.dxf)
msp = doc.modelspace()

def plain(s):
    return re.sub(r"\\[A-Za-z][^;]*;", "", s or "").strip()

rows = []
for e in msp:
    if e.dxftype() not in ("MTEXT", "TEXT"):
        continue
    if "房间号" not in e.dxf.layer:
        continue
    t = plain(e.text)
    ins = e.dxf.insert
    rows.append((ins[1], ins[0], t))

rows.sort(reverse=True)  # 从 Y 大(高)到小(低)
band = collections.OrderedDict()
for y, x, t in rows:
    b = int(round((y - p.cy) / p.offset))
    m = re.match(r"^(\d+)-(\d+)", t)
    ff = int(m.group(2)) if m else None
    band.setdefault(b, []).append((t, ff))

print("楼: %s   楼层带宽=%d  cy=%s" % (NAME, p.offset, p.cy))
print("真实层号 FF 与模型层索引的对应 (Y带 k, 模型 F=k):")
bad = 0
for k in sorted(band, reverse=True):
    ffs = [f for _, f in band[k] if f]
    nums = sorted({t for t, _ in band[k]})
    mode = collections.Counter(ffs).most_common(1)[0][0] if ffs else None
    flag = ""
    if mode is not None and mode != k + 1:
        flag = "  <== 与模型不同(F%d 应为 %d 层, 实为 %d 层)" % (k, k + 1, mode)
        bad += 1
    print("  Y带%2d -> 模型F%-2d  真实=%-4s  样例 %s%s"
          % (k, k, mode, " ".join(nums[:6]), flag))
print("倒置判定: %s" % ("是(层序反了)" if bad and set(band) == set(range(len(band))) else "否"))
