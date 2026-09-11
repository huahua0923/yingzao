# -*- coding: utf-8 -*-
"""比对 GLB：体积 / 三角数 / 扩展（判断是否网格压缩过）。用法: python _scratch/_glb_probe.py <a.glb> <b.glb>"""
import json, struct, sys, os
sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def info(p):
    raw = open(p, "rb").read()
    magic, ver, length = struct.unpack("<III", raw[:12])
    clen, ctype = struct.unpack("<II", raw[12:20])
    j = json.loads(raw[20:20 + clen].decode("utf-8"))
    ext = j.get("extensionsUsed", [])
    tri = 0
    for m in j.get("meshes", []):
        for pr in m["primitives"]:
            if "indices" in pr:
                tri += j["accessors"][pr["indices"]]["count"] // 3
    mats = []
    for mt in j.get("materials", []):
        c = mt.get("pbrMetallicRoughness", {}).get("baseColorFactor")
        if c:
            mats.append((mt.get("name", "?"), "#%02X%02X%02X" % tuple(int(round(v * 255)) for v in c[:3])))
    print("  %-34s %10d B  glTF ver%d  三角 %8d  扩展 %s"
          % (os.path.basename(p), length, ver, tri, ext or "无"))
    print("      材质 %d: %s" % (len(mats), ", ".join("%s=%s" % m for m in mats)))
    return tri


for p in sys.argv[1:]:
    if os.path.exists(p):
        info(p)
    else:
        print("  缺失:", p)
