# -*- coding: utf-8 -*-
r"""全库用途配色表取数（唯一所有者，产物 `backend/modeling/purpose_palette.json`）。

为什么是"取"而不是"算"：归族与配色的规则**只有 `frontend/building.html` 那一处实现**
（`purposeFamilyOf` / `roomColor`，页面经 `window.__gym3d.purposeColorOf/purposeFamilyOf`
把它开成问答口 —— 见 building.html:1854 的注释）。SU 侧要覆盖全库 112 种用途，
若在 Python 里再抄一版正则+FNV 哈希，就变成"两边各抄一版、然后一起错"。
所以这里**只问页面要答案**，落成一张静态表；守卫 `_purpose_color_guard.py` 负责
断言这张表与页面逐值一致（页面改了而表没更新 → 守卫变红）。

用法:
  python _scratch/_purpose_palette_dump.py            # 取表并写盘
  python _scratch/_purpose_palette_dump.py --check     # 只比对不写（守卫用）
"""
import io
import json
import os
import re
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = r"D:\gym3d"
OUT = os.path.join(ROOT, "backend", "modeling", "purpose_palette.json")

CHECK = "--check" in sys.argv

# 端口从 .env 读，**不写死**（仓库有"裸端口"门禁）
port = 8123
for line in io.open(os.path.join(ROOT, ".env"), encoding="utf-8"):
    m = re.match(r"\s*GYM3D_LEGACY_ROOMS_PORT\s*=\s*(\d+)", line)
    if m:
        port = int(m.group(1))
BASE = "http://127.0.0.1:%d/" % port


def fleet_purposes():
    """全库 floors 里出现过的用途串（含空串），排序后返回 —— 与 _purpose_color_guard 同口径。"""
    idx = json.load(io.open(os.path.join(ROOT, "data", "buildings", "index.json"), encoding="utf-8"))
    blds = idx if isinstance(idx, list) else (idx.get("buildings") or [])
    P = set()
    for b in blds:
        if not isinstance(b, dict):
            continue
        n = b.get("name")
        d = b.get("dir") or ""
        base = os.path.join(ROOT, d) if d in ("data", "data/") else os.path.join(ROOT, "data", "buildings", n)
        fd = os.path.join(base, "floors")
        if not os.path.isdir(fd):
            continue
        for f in sorted(os.listdir(fd)):
            if not (f.startswith("floor") and f.endswith(".json")):
                continue
            try:
                dd = json.load(io.open(os.path.join(fd, f), encoding="utf-8"))
            except Exception:
                continue
            for r in (dd.get("rooms") or []):
                P.add(r.get("purpose") or "")
    return sorted(P)


PURPS = fleet_purposes()
print("全库用途串 %d 种（含空串）" % len(PURPS))

from playwright.sync_api import sync_playwright  # noqa: E402

ASK = r"""(list) => {
  const g = window.__gym3d;
  const out = {};
  for (const p of list) {
    out[p] = { color: g.purposeColorOf(p), family: g.purposeFamilyOf(p) };
  }
  return out;
}"""

with sync_playwright() as p:
    br = p.chromium.launch(args=["--enable-unsafe-swiftshader", "--use-gl=swiftshader"])
    pg = br.new_page(viewport={"width": 1024, "height": 768})
    # 配色规则与楼无关，随便开一栋；等握手盖章（几何真换了）再问，避免问到半初始化的页
    pg.goto(BASE + "?building=c054", wait_until="load", timeout=60000)
    pg.wait_for_function(
        "() => { const g = window.__gym3d; return !!g && g.builtToken === g.buildToken"
        " && g.geometryBuilding === 'c054'; }", timeout=90000)
    table = pg.evaluate(ASK, PURPS)
    anchors = pg.evaluate("() => window.__gym3d.familyAnchors()")
    br.close()

bad = {k: v for k, v in table.items() if not re.match(r"^#[0-9a-f]{6}$", v["color"] or "")}
if bad:
    print("✗ 有 %d 个用途的色值形状不对（roomColor 返回类型被改坏？）：%s"
          % (len(bad), list(bad.items())[:5]))
    sys.exit(2)

doc = {
    "_note": "由 _scratch/_purpose_palette_dump.py 从 frontend/building.html 的 "
             "window.__gym3d.purposeColorOf/purposeFamilyOf 取数。规则唯一实现在页面，本表是快照。",
    "source": "frontend/building.html",
    "count": len(table),
    "anchors": anchors,
    "colors": {k: v["color"] for k, v in table.items()},
    "families": {k: v["family"] for k, v in table.items()},
}

if CHECK:
    old = json.load(io.open(OUT, encoding="utf-8")) if os.path.exists(OUT) else None
    if old is None:
        print("✗ 表还不存在：%s" % OUT)
        sys.exit(2)
    dc = {k: v for k, v in doc["colors"].items() if old["colors"].get(k) != v}
    df = {k: v for k, v in doc["families"].items() if old["families"].get(k) != v}
    miss = [k for k in old["colors"] if k not in doc["colors"]]
    print("色值不符 %d 个%s" % (len(dc), ("：" + str(list(dc.items())[:5])) if dc else ""))
    print("族不符   %d 个%s" % (len(df), ("：" + str(list(df.items())[:5])) if df else ""))
    print("表里有、全库已不存在的旧串 %d 个%s" % (len(miss), ("：" + str(miss[:5])) if miss else ""))
    sys.exit(1 if (dc or df) else 0)

with io.open(OUT, "w", encoding="utf-8") as f:
    json.dump(doc, f, ensure_ascii=False, indent=1, sort_keys=True)
print("→ %s（%d 种用途，%d 个族锚色）" % (OUT, len(table), len(anchors)))
