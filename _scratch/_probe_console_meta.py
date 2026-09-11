# -*- coding: utf-8 -*-
"""验证控制台后端：stage_argv 构造 + building_status 逐阶段现状。只读，不改任何数据。"""
import sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, r"D:\gym3d\backend\web")
import control as C  # noqa: E402

print("VALID_STEPS =", C.VALID_STEPS)
print()
print("--- stage_argv(c019) ---")
for s in ("recognize", "glb", "thin", "doorpunch", "qa", "compare", "index", "full", "dwg2dxf"):
    a = C.stage_argv("c019", s, False)
    pretty = [x.replace("D:\\gym3d\\", "") for x in a] if a else ["<None>"]
    print("  %-11s %s" % (s, pretty))

for name in ("c019", "c022", "lihua"):
    st = C.building_status(name)
    print()
    print("=== %s  楼层数=%s  GLB过期=%s ===" % (name, st["nFloors"], st["glbStale"]))
    for s in st["stages"]:
        mark = "DONE " if s["done"] else ("STALE" if s["stale"] else "--   ")
        arts = ",".join(("%s%s" % ("OK" if a["exists"] else "缺",
                                   "(旧)" if a["stale"] else "") for a in s["artifacts"])) or "—"
        print("  %-2s %-22s %s %-8s %s" % (s["no"], s["label"], mark,
                                           "单栋" if s["scope"] == "single" else s["scope"], arts))
