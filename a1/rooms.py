# -*- coding: utf-8 -*-
"""A1：**房间台账** —— 从 CAD 的**人写属性文字**里抽出「房间号 + 面积 + 用途 + 使用单位」。

背景（A1 全库图层名普查 `a1/probe_layers.py` → `_out/layers_census.json`）：
  · **房间属性是独立图层**（不同于门/窗/梯/板/梁 —— 那些连层都没有）：
    `5面积`(98 份/12982 条) · `6房间号`(97/13432) · `8房间用途`(31) · `7使用单位`(49) · `7用途类型`(19)
  · 正文样例：房间号 `6-C-D1-01` / `109-05-02`；面积 `106.91m{}` / `17.54m{}`（MTEXT 域花括号）
  · ★ **两者是「成对摆放」的**：实测「房间号→最近面积」的距**几乎恒定**（C006 全 650 mm、
    C109 全 750 mm、C001 中位 807）⇒ 空间配对**可靠**，不是稠密场里的巧合。

★ **为什么这是「外部量」**：`5面积` 是**人写的数字**，建模链**读不到它**（链只吃 `4.2墙体` 几何）
  ⇒ 它是 §10.1「房间/面积：按列算的面积 vs **台账/图纸面积**，逐层对账」里的**参考侧**。
  ★ 本件**只建台账（参考侧）**；「按列算的面积」（模型侧）要等链建出房间多边形，**本条不假装做了**。

★ 本件产出一行一房间：`{room_id, bldg, floor, seq, area_m2, dist_mm, use, unit}`。

★ 量具盲区（必须声明）：
  ① 只读 `ROOM_ID_LAYERS`/`AREA_LAYERS`/`USE_LAYERS`/`UNIT_LAYERS` 列出的层名 —— 画在别的层全盲。
  ② **成对摆放的偏移不是全库常数**（C006 650 / C109 750 / C001 807）⇒ `TOL` 取 1500 是**判据参数**；
     换图集可能不够。**近邻配对**在「一个面积文字离两个房间号都 < TOL」时会**配错而无声**。
  ③ 面积是**人写数**，本身可能写错；本件**原样转录、不校对**（「台账对不上模型」时，两边都不许默认对）。
  ④ `5面积` 里混着**非数值**（C001 `{露台}`/`{7.50m}`）⇒ 解析失败的**如实记为 None 并计数**，不猜。

用法: python rooms.py <dxf> [--json o.json] [--tol 1500]
"""
import sys
import os
import re
import json
import argparse

sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
import ezdxf

ROOM_ID_LAYERS = ("6房间号", "6房间号2")
AREA_LAYERS = ("5面积",)
USE_LAYERS = ("8房间用途", "7用途类型", "8用途", "7房间用途", "8功能", "8房间说明", "7用途分类")
UNIT_LAYERS = ("7使用单位", "8使用单位", "8单位", "8.2使用单位", "7使用单位2", "9调整单位")

TOL = 1500.0                      # 房间号↔属性 的配对距离（mm），见盲区②
FMT = re.compile(r"\\[A-Za-z][^;]*;")
NUM = re.compile(r"([0-9]+(?:\.[0-9]+)?)")


def _clean(s):
    return FMT.sub("", s or "").replace("{", "").replace("}", "").strip()


def _xy(e):
    try:
        p = e.dxf.insert
        return p.x, p.y
    except Exception:
        return None


def collect(dxf):
    """把四类属性文字按用途收集：返回 dict(ids/areas/uses/units) → [(text, (x,y))]。
    ★ 单列出来是为了让**判据能喂打乱/删改的输入**（对照必须在同一段代码上跑）。"""
    doc = ezdxf.readfile(dxf)
    msp = doc.modelspace()
    out = {"ids": [], "areas": [], "uses": [], "units": []}
    for e in msp:
        if e.dxftype() not in ("TEXT", "MTEXT"):
            continue
        lay = e.dxf.layer
        p = _xy(e)
        if p is None:
            continue
        s = _clean(e.dxf.text if e.dxftype() == "TEXT" else e.text)
        if not s:
            continue
        if lay in ROOM_ID_LAYERS:
            out["ids"].append((s, p))
        elif lay in AREA_LAYERS:
            out["areas"].append((s, p))
        elif lay in USE_LAYERS:
            out["uses"].append((s, p))
        elif lay in UNIT_LAYERS:
            out["units"].append((s, p))
    return out


def join(pools, tol=TOL):
    """房间号 ↔ 最近面积/用途/单位（空间配对）。返回 (rows, stats)。
    ★ 一切输入都从 `pools` 来 —— 判据打乱 `pools['areas']` 的坐标即可测「配对是不是真的按位置」。"""
    ids = pools["ids"]
    areas = pools["areas"]
    uses = pools["uses"]
    units = pools["units"]

    def nearest(pool, p, text_filter=None):
        best, bd = None, None
        for s, q in pool:
            if text_filter and not text_filter(s):
                continue
            d = ((p[0] - q[0]) ** 2 + (p[1] - q[1]) ** 2) ** 0.5
            if bd is None or d < bd:
                best, bd = s, d
        return best, bd

    rows = []
    n_parsed = n_far = n_nonnum = 0
    for rid, p in ids:
        aseg, adist = nearest(areas, p)
        area = None
        if aseg is None or adist is None:
            n_far += 1                      # 该图根本没有面积文字
        elif adist > tol:
            n_far += 1                      # 最近的那条也超出配对距离 ⇒ 拒配，不硬凑（盲区②）
        else:
            m = NUM.search(aseg)
            if m:
                area = float(m.group(1)); n_parsed += 1
            else:
                n_nonnum += 1               # 在范围内但非数值（`{露台}` 等）⇒ 如实记 None
        # ★ use/unit 同样过配对闸：不加这道闸，远处一条文字会被**无声**贴到这个房间上
        use, udist = nearest(uses, p)
        unit, gdist = nearest(units, p)
        if udist is None or udist > tol:
            use = None
        if gdist is None or gdist > tol:
            unit = None
        seg = rid.split("-")
        rows.append({"room_id": rid, "bldg": seg[0] if len(seg) >= 3 else None,
                     "floor": seg[-2] if len(seg) >= 2 else None,
                     "seq": seg[-1] if len(seg) >= 2 else None,
                     "area_m2": area, "area_text": aseg,
                     "dist_mm": None if adist is None else round(adist),
                     "use": use, "use_dist_mm": None if udist is None else round(udist),
                     "unit": unit, "unit_dist_mm": None if gdist is None else round(gdist)})
    stats = {"n_id": len(ids), "n_area_text": len(areas), "n_parsed": n_parsed,
             "n_far": n_far, "n_nonnum": n_nonnum,
             "n_use": sum(1 for r in rows if r["use"]), "n_unit": sum(1 for r in rows if r["unit"]),
             "n_joined": sum(1 for r in rows if r["area_m2"] is not None)}
    return rows, stats


def load_rooms(dxf, tol=TOL):
    """collect + join 的常规入口（判据要喂打乱输入时，直接用 collect/join 两个）。"""
    return join(collect(dxf), tol)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("dxf")
    ap.add_argument("--json", default=None)
    ap.add_argument("--tol", type=float, default=TOL)
    a = ap.parse_args()
    if not os.path.isfile(a.dxf):
        print("MISSING:", a.dxf); return 2
    rows, st = load_rooms(a.dxf, a.tol)
    print("DXF        :", os.path.basename(a.dxf))
    print("房间号 %d 条 / 面积文字 %d 条" % (st["n_id"], st["n_area_text"]))
    print("配到面积且解析成功 : %d  |  超配对距离/无面积 %d  |  在范围内但非数值 %d"
          % (st["n_joined"], st["n_far"], st["n_nonnum"]))
    print("用途/单位 配到 : %d / %d" % (st["n_use"], st["n_unit"]))
    floors = sorted({r["floor"] for r in rows if r["floor"]})
    print("层段(room_id 倒数第2段):", floors[:20], "共 %d 层" % len(floors))
    a2 = [r["area_m2"] for r in rows if r["area_m2"] is not None]
    if a2:
        a2.sort()
        print("面积(m²): n=%d  min %.2f / 中位 %.2f / max %.2f  合计 %.2f"
              % (len(a2), a2[0], a2[len(a2) // 2], a2[-1], sum(a2)))
    print("样例行:")
    for r in rows[:5]:
        print("   ", r)
    if a.json:
        p = os.path.dirname(a.json)
        if p:
            os.makedirs(p, exist_ok=True)
        json.dump({"dxf": a.dxf, "tol": a.tol, "stats": st, "rows": rows},
                  open(a.json, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print("写出:", a.json)
    return 0


if __name__ == "__main__":
    sys.exit(main())
