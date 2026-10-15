# -*- coding: utf-8 -*-
"""A1：量**构件大类**在 105 份 DXF 里的图层名与实体构成 —— 「通用化必须补，先量有几种表示」。

覆盖类：门 / 窗 / 楼梯(梯) / 电梯 / 楼板 / 梁 / 台阶 / 轴线 / 标注。
对每类：聚合「哪些图层名命中」「各图层的实体类型构成」「块名前缀」「多少份有」。

用法: python batch_classes.py [dxf目录] [--json out.json]

★ 量具盲区（必须声明）：
  ① 按**图层名含关键词**归并 ⇒ 图层名不带这些字的**全盲**（「没找到」≠「没有」）。
  ② 实体构成只数**顶层实体**（INSERT 只算 1 次、**不展开块内部**）⇒ 门可能是块里的一条弧，本尺看不见。
  ③ 报的是「图层名/实体类型的分布」，**说不出「这一块是不是门」**（几何语义归 §10.1）。
  ④ 关键词表 `KEYS` 写死；换个科室的命名习惯要重调。
"""
import sys
import os
import json
import glob
import argparse
import collections

sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
import ezdxf

# ★ 顺序即优先级（dict 保序）：把「电梯」放在「楼梯」**前**，否则「电梯」层因含「梯」被判成楼梯。
#   危险短串（LT / DT / 单字「板」「梯」）一律不用 —— 会串到 DETAIL/饰面板 之类的无关层。
KEYS = {
    "门": ("门",),
    "窗": ("窗",),
    "电梯": ("电梯", "ELEV"),
    "楼梯": ("楼梯", "STAIR"),
    "楼板": ("楼板", "SLAB"),
    "梁": ("梁",),
    "台阶": ("台阶", "坡道", "散水"),
    "轴线": ("轴",),
}


def classify_layer(name):
    for cls, kws in KEYS.items():
        for k in kws:
            if k in name or k.upper() in name.upper():
                return cls
    return None


def scan(path):
    try:
        msp = ezdxf.readfile(path).modelspace()
    except Exception as e:
        return {"dxf": os.path.basename(path), "err": "READ:%s" % type(e).__name__}
    per = collections.defaultdict(collections.Counter)   # cls -> layer -> n
    types = collections.defaultdict(collections.Counter)  # cls -> etype -> n
    blocks = collections.defaultdict(collections.Counter)  # cls -> block prefix -> n
    for e in msp:
        cls = classify_layer(e.dxf.layer)
        if not cls:
            continue
        t = e.dxftype()
        per[cls][e.dxf.layer] += 1
        types[cls][t] += 1
        if t == "INSERT":
            blocks[cls][(e.dxf.name or "")[:14]] += 1
    return {"dxf": os.path.basename(path), "per": {k: dict(v) for k, v in per.items()},
            "types": {k: dict(v) for k, v in types.items()},
            "blocks": {k: dict(v) for k, v in blocks.items()}}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("dir", nargs="?", default=r"D:\项目\gym3d\材料\dxf_output")
    ap.add_argument("--json", default=None)
    a = ap.parse_args()
    files = sorted(glob.glob(os.path.join(a.dir, "*.dxf")))
    if not files:
        print("!! 无 dxf:", a.dir)
        return 2
    print("扫 %d 份 ...\n" % len(files))
    res = []
    for i, f in enumerate(files, 1):
        r = scan(f)
        res.append(r)
        if "err" in r:
            print("%3d %-42s !! %s" % (i, r["dxf"][:42], r["err"]))
        else:
            cls = sorted(r["per"].keys())
            print("%3d %-42s 命中类: %s" % (i, r["dxf"][:42], ",".join(cls) or "无"))

    ok = [r for r in res if "err" not in r]
    if not ok:
        print("!! 全读失败")
        return 3

    print("\n===== 各类汇总 =====")
    for cls in KEYS:
        nfile = sum(1 for r in ok if cls in r["per"])
        lay = collections.Counter()
        typ = collections.Counter()
        blk = collections.Counter()
        for r in ok:
            for l, n in r["per"].get(cls, {}).items():
                lay[l] += n
            for t, n in r["types"].get(cls, {}).items():
                typ[t] += n
            for b, n in r["blocks"].get(cls, {}).items():
                blk[b] += n
        print("\n【%s】%d/%d 份有" % (cls, nfile, len(ok)))
        if not lay:
            print("     （无）")
            continue
        print("     图层名:", dict(lay.most_common(6)))
        print("     实体类型:", dict(typ.most_common(8)))
        if blk:
            print("     块名前缀:", dict(blk.most_common(6)))

    if a.json:
        p = os.path.dirname(a.json)
        if p:
            os.makedirs(p, exist_ok=True)
        json.dump({"dir": a.dir, "n": len(res), "rows": res},
                  open(a.json, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print("\n写出:", a.json)
    return 0


if __name__ == "__main__":
    sys.exit(main())
