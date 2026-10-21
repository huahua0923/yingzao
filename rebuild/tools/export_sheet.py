# -*- coding: utf-8 -*-
"""把每一层图幅里的**真实线条**搬成一份 SU 能直接打开的 DXF（一层一个文件）。

★ 本文件**一个字几何都不建**：只做三件事 —— 按图幅窗口**挑**实体、连块定义一起**搬**
  （`Importer`，柱子是 INSERT 不能只搬线）、把图幅左下角**挪到原点**方便在 SU 里画。
  所有几何都还是 AutoCAD 图上画的那条线，**没有 buffer、没有闭运算、没有配对、没有合并**。

★ 正对照（每次跑都算）：搬完逐层复核 —— 每个图层的实体数必须与源窗口内**逐层相等**，
  且墙层数必须 > 0。对不上即 rc=1（判红），不许静默少搬。

输出：
  rebuild/01_cad/raw/<层名>.dxf    给 SU / Blender 的底图（mm，图幅左下角在原点）
  rebuild/01_cad/raw/<层名>.json   元数据：图幅窗口、平移量、逐层实体数（供搬回时还原）
用法：
  python rebuild/tools/export_sheet.py --all
  python rebuild/tools/export_sheet.py --one "1层"
"""
from __future__ import annotations

import argparse
import collections
import json
import os
import sys

import ezdxf
from ezdxf import bbox
from ezdxf.addons import Importer
from ezdxf.math import Matrix44

sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import building as B                                                    # noqa: E402
import sheet_windows as SW                                            # noqa: E402

# ★ 2026-10-17：数据根与图层白名单改从楼栋档案读（不设环境变量 = c006，行为不变）。
ROOT = B.ROOT
OUTDIR = os.path.join(ROOT, "01_cad", "raw")

# 搬哪些层：几何 + 轴线 + 房间标注（读图要用的）。排除图框/尺寸/表格等出图元素。
_PROF = B.profile()
KEEP = set(_PROF["keep_layers"])
DROP = set(_PROF.get("drop_layers") or [])


def pick(doc, w):
    """窗口内（按 bbox 相交）且在 KEEP 里的实体，按层归好。"""
    got = collections.defaultdict(list)
    for e in doc.modelspace():
        lay = e.dxf.layer
        if lay in DROP or lay not in KEEP:
            continue
        bb = bbox.extents([e])
        if not bb.has_data:
            continue
        if (bb.extmin.x <= w["x1"] and bb.extmax.x >= w["x0"]
                and bb.extmin.y <= w["y1"] and bb.extmax.y >= w["y0"]):
            got[lay].append(e)
    return got


def export_one(doc, w):
    src = collections.defaultdict(list)
    for e in doc.modelspace():
        bb = bbox.extents([e])
        if not bb.has_data:
            continue
        if (bb.extmin.x <= w["x1"] and bb.extmax.x >= w["x0"]
                and bb.extmin.y <= w["y1"] and bb.extmax.y >= w["y0"]):
            src[e.dxf.layer].append(e)

    keep = {k: v for k, v in src.items() if k in KEEP}

    out = ezdxf.new("R2013", setup=True)
    # ★★ 2026-10-13 实测：ezdxf 默认给出 `$INSUNITS = 6`（**米**），而本文件的坐标是 **mm**
    #    量级。SU 的 DXF 导入**认这个声明** —— 实测把 130.7 m 的平面导成了 **130700 m**
    #    （1000 倍）。底图是给 SU / Blender 吃的，所以必须显式声明成 **4 = 毫米**。
    out.header["$INSUNITS"] = 4        # 4 = 毫米（mm）
    out.header["$MEASUREMENT"] = 1     # 1 = 公制
    imp = Importer(doc, out)
    n = 0
    for lay, ents in keep.items():
        for e in ents:
            imp.import_entity(e)
            n += 1
    imp.finalize()

    dx, dy = -w["x0"], -w["y0"]
    for e in out.modelspace():                        # Modelspace 没有 transform()
        try:
            e.translate(dx, dy, 0)
        except AttributeError:
            pass

    os.makedirs(OUTDIR, exist_ok=True)
    dxf = os.path.join(OUTDIR, "%s.dxf" % w["name"])
    out.saveas(dxf)

    # 正对照：重开写出的文件，逐层数实体
    chk = ezdxf.readfile(dxf)
    back = collections.Counter(e.dxf.layer for e in chk.modelspace())
    want = collections.Counter({k: len(v) for k, v in keep.items()})
    ok = (back == want) and want.get(SW.WALL_LAYER, 0) > 0

    meta = {"name": w["name"], "col": w["col"], "row": w["row"],
            "window": [w["x0"], w["y0"], w["x1"], w["y1"]],
            "origin": [dx, dy], "units": "mm",
            "imported": n, "per_layer": dict(back), "ok": bool(ok)}
    with open(os.path.join(OUTDIR, "%s.json" % w["name"]), "w",
              encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=1)
    return meta, want, back


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--one", help="只做这一层")
    ap.add_argument("--all", action="store_true")
    a = ap.parse_args()

    r = SW.build()
    todo = r["sheets"] if a.all else [s for s in r["sheets"] if s["name"] == a.one]
    if not todo:
        print("★ 没量到：没有匹配的层（--one %r）" % a.one)
        return 4

    doc = ezdxf.readfile(SW.SRC)
    bad = 0
    for w in todo:
        meta, want, back = export_one(doc, w)
        tag = "ok" if meta["ok"] else "★判红"
        print("%-8s 搬 %5d 条  %s  %s" % (
            w["name"], meta["imported"], tag,
            " ".join("%s:%d" % (k, v) for k, v in sorted(back.items()))))
        if not meta["ok"]:
            bad += 1
            for k in sorted(set(want) | set(back)):
                if want.get(k, 0) != back.get(k, 0):
                    print("      ★ %s 应 %d 实 %d"
                          % (k, want.get(k, 0), back.get(k, 0)))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
