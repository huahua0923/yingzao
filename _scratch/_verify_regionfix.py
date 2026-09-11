# -*- coding: utf-8 -*-
"""add_region 瘦身改动的 A/B 体检：几何是否等价、体积降了多少。

判据（按重要性排）：
  1. **有向体积守恒** —— 老写法每个三角形挤一个棱柱，相邻棱柱的公共面法线
     相反、在带符号体积里互相抵消，所以「∑有向体积」只统计真实外表。新写法
     只出外表。两者应当**近似相等**：这是「外表逐点没变、少掉的只是内部接缝」
     最直接的数值证据。
     若新值只剩一半 → 侧壁丢了；若符号为负 → 法线整体翻向、会被背面剔除吃掉。
  2. **bbox 逐轴相同** —— 外形轮廓没变。
  3. 面数 / 字节数下降幅度。
用法：python _verify_regionfix.py <新glb> <旧glb>
"""
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import trimesh  # noqa: E402


def look(path):
    m = trimesh.load(path, force="mesh", process=False)
    lo, hi = m.bounds
    return {
        "bytes": os.path.getsize(path),
        "faces": len(m.faces),
        "verts": len(m.vertices),
        "bbox": (tuple(lo), tuple(hi)),
        "vol": float(m.volume),
    }


new_p, old_p = sys.argv[1], sys.argv[2]
n, o = look(new_p), look(old_p)

print("%-10s %14s %14s %9s" % ("", "旧", "新", "变化"))
for k, lab in (("bytes", "字节"), ("faces", "三角面"), ("verts", "顶点")):
    print("%-10s %14d %14d %8.1f%%"
          % (lab, o[k], n[k], 100.0 * (n[k] - o[k]) / o[k] if o[k] else 0))

print("\n有向体积   旧 %.1f m³   新 %.1f m³   差 %.2f%%"
      % (o["vol"], n["vol"], 100.0 * (n["vol"] - o["vol"]) / o["vol"] if o["vol"] else 0))

same_bbox = all(abs(a - b) < 1e-6 for a, b in zip(n["bbox"][0], o["bbox"][0])) and \
            all(abs(a - b) < 1e-6 for a, b in zip(n["bbox"][1], o["bbox"][1]))
print("bbox 逐轴相同 :", "PASS" if same_bbox else "FAIL")
print("  旧", [round(x, 3) for x in o["bbox"][0]], "->", [round(x, 3) for x in o["bbox"][1]])
print("  新", [round(x, 3) for x in n["bbox"][0]], "->", [round(x, 3) for x in n["bbox"][1]])

vd = abs(n["vol"] - o["vol"]) / o["vol"] if o["vol"] else 1.0
print("体积符号为正  :", "PASS" if n["vol"] > 0 else "**FAIL 法线翻向**")
print("体积守恒<1%%   : %s（差 %.2f%%）" % ("PASS" if vd < 0.01 else "**FAIL**", 100 * vd))
