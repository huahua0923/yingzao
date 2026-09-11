# -*- coding: utf-8 -*-
"""宿舍/公寓簇房间抽取批量 dry + 面积质量门 (R9/R10 sizing)。只读, 不写任何文件。
对每个候选调 extract_rooms_generic.run(dry=True)，用「多边形面积 vs 图注面积」门筛。
写结果到 _rooms_batch_dry.txt。"""
import sys, io, re, os
sys.path.insert(0, r"D:\gym3d")
sys.path.insert(0, r"D:\gym3d\backend")
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from backend.extract import extract_rooms_generic as E

CAND = ["c017","c018","c019","c029","c030","c032","c033","c034","c043","c044",
        "c045","c046","c054","c055","c056","c057","c059","c060","c061","c062",
        "c063","c064","c065","c072","c073","c079","c080","c083","c084","c085",
        "c086","c109","c116","ny27","ny28","ny29"]

out = []
for name in CAND:
    buf = io.StringIO()
    old = sys.stdout
    sys.stdout = buf          # 吞 run() 打印
    try:
        rooms = E.run(name, dry=True)
    finally:
        sys.stdout = old
    printed = buf.getvalue()
    # 歧义行
    ambig = [l for l in printed.splitlines() if "歧义" in l]
    # 面积门
    n = len(rooms)
    checked = bad = noarea = 0
    for r in rooms:
        m = re.search(r"([\d.]+)", (r.get("area") or "").replace(",", ""))
        if not m:
            noarea += 1
            continue
        da = float(m.group(1))
        if da <= 0:
            noarea += 1
            continue
        checked += 1
        if abs(r["area_m2"] - da) / da > 0.35:
            bad += 1
    ratio = (bad / checked) if checked else 0.0
    flag = ""
    if n == 0:
        flag = " <== 0 房间, 跳过"
    elif checked and ratio > 0.2:
        flag = " <== 面积失配高(%.0f%%), 待查" % (100 * ratio)
    elif ambig:
        flag = "  [歧义: %s]" % ";".join(ambig)[:60]
    out.append((name, n, checked, bad, noarea, ratio, flag, printed.strip().splitlines()[-2] if printed.strip().splitlines() else ""))
    print(f"[{name}] 共{n:3d}间 有注{checked:3d} 失配{bad:2d} 无注{noarea:2d} {flag}")

with open("_rooms_batch_dry.txt", "w", encoding="utf-8") as f:
    for name, n, checked, bad, noarea, ratio, flag, summary in out:
        f.write(f"{name:6} n={n:3d} checked={checked:3d} bad={bad:2d} noarea={noarea:2d} {flag}\n")
print("\n明细已写 _rooms_batch_dry.txt")
