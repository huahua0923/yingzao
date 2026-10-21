# -*- coding: utf-8 -*-
r"""房间表 → 交付包的**地板面片**（`baseline/floors/floor*.json` 的 `rooms`）。

用户令：「这个房间表呢，后面我们还要把它**合成一个地板**，来生成那种三维的展示」
        「每块可点选 / 按用途着色」。
⇒ 本脚本把 `rebuild/02_recognize/房间表.json` 的面片搬进**三维展示件自己已经在用的那份格式**，
  不另造格式。

## 为什么落点选在这里（实测，不是选出来的）
- `demo/build_pack.py:26` `B = <gym3d>/data/buildings/c006`；`:353-356` 逐层
  `floor*.json` 搬成包内 `baseline/floors/` ⇒ **包里的地板数据真源是 gym3d 那份**。
- 实测两边 **md5 逐字节相同**（floor0/1/6/10 全同）⇒ 写 gym3d 那份 = 写进包；写包那份会被下一次
  `build_pack.py` **静默覆盖**。故选 gym3d 那份，写前**先备份**。
- 包内 `rooms[]` 现有形状 = `{id, poly, purpose, number}`，`poly` 首尾**闭合**、单位 **m**。

## 帧变换：CAD 小帧(mm) → 包帧(m)
**纯平移、比例 1/1000**，由**实测**定：我的全铺装外框 vs 包自己的 `outline` 外框，
宽度差 0.24 m / 128.70 m（0.19%）、高度差 0.06 m（0.07%）⇒ 无旋转、无缩放。
偏移取**两框中心对齐**（对形状差异免疫），残差逐层记进读数、由落位判据复核。

★ 不查表、不打字：偏移**每层现算**（`offset_of`）。另有一条**独立**的包侧常量
  `pack_d1.xform = (-64.48, +36.994) m`（见 `demo/_gen/c006-slabswap.json` 的 `pack_const_m`），
  但它绑的是**大图帧**，与小帧差一个裁切原点 ⇒ **只作旁证，不拿它算**。

## 写什么
- `rooms`        ← 房间表面片（带 `purpose` / `number` / 面积 / 情形）
- `circulation`  ← 交通空间面片（**新增的同级键**；`rooms` 语义不变 —— 否则界面上的
                   「房间 N 间」会被走廊灌水）

★ 只动这两个键，其余键**原样带回**（`walls`/`doors`/`windows`/… 一个不碰）。
★ 写盘一律**字节层**（`open(...,'wb')`）—— 文本模式在 Windows 会把 `\n` 翻成 `\r\n`（铁律 79）。
  本件实测**整个文件就是一行**（LF 计数 0）⇒ 落盘也写成一行，不引入换行。
★ `id` 沿用旧值**按房号配**（房号对不上 ⇒ `id=None` 并**报数**，不静默）；另有 `sid` 走仓库
  既有的 `stable_id.room_id`（身份 = 房号），不另造一套身份。

用法：
    python rebuild/tools/rooms_to_pack.py            # 只出读数（默认，不写盘）
    python rebuild/tools/rooms_to_pack.py --apply    # 备份后写盘
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time

import shapely.geometry as sg

sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

HERE = os.path.dirname(os.path.abspath(__file__))
REBUILD = os.path.dirname(HERE)
CDUT = os.path.dirname(REBUILD)
sys.path.insert(0, os.path.join(CDUT, "tools"))
import stable_id                                                    # noqa: E402

ROOM_SRC = os.path.join(REBUILD, "02_recognize", "房间表.json")
GYM = r"D:\项目\gym3d\gym3d"
BACKUP_DIR = os.path.join(CDUT, "_archive")
CAMPUS, BUILDING = "cdut-main", "c006"
FLOORS_DIR = os.path.join(GYM, "data", "buildings", BUILDING, "floors")   # 由 --gym/--building 现算
MARGIN_M = 0.5          # 落位判据：面片顶点必须落在 `outline` 外扩这么多之内（= 帧变换容差上限）
ROUND = 3               # 落盘坐标小数位（m）—— 与包内既有精度一致


# ----------------------------------------------------------------- 楼层名 ↔ 包内文件名
def pack_index(name):
    """`N层` → `floor{N-1}.json`（0 基，见 `tools/slab_into_floor.py:48` 的 NODE 注释）。

    返回 None = 这份 floors 目录里**没有**对应的件（调用方必须**报出来**，不许静默跳过）。
    """
    if name.endswith("层") and name[:-1].isdigit():
        return int(name[:-1]) - 1
    return None


def floor_path(k):
    return os.path.join(FLOORS_DIR, "floor%d.json" % k)


# ----------------------------------------------------------------- 帧变换
def as_rings(x):
    """**面的两种写法都要认**：`[[x,y],…]`（一圈点）与 `[[[x,y],…],…]`（多圈）。

    ★ 实测：包内 `outline` 是**一圈点**（`floor1.json` 的 outline[0] = [-64.47, 43.321]），
      而我的 `轮廓xy_mm` 也是**一圈点** ⇒ 两边同形。这里仍两种都收，免得换层换了写法就崩
      （崩了是好事，静默错才要命——所以判据只认形状，不猜）。
    """
    if not x:
        return []
    return [x] if isinstance(x[0][0], (int, float)) else list(x)


def bbox(rings):
    pts = [p for r in as_rings(rings) for p in r]
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return min(xs), min(ys), max(xs), max(ys)


def offset_of(mine_polys_mm, outline):
    """我的全铺装(mm) 与包 outline(m) → 偏移；并回报**外框残差**（变换的诚实边界）。"""
    a = bbox(mine_polys_mm)
    b = bbox(outline)
    ox = (a[0] + a[2]) / 2.0 / 1000.0 - (b[0] + b[2]) / 2.0
    oy = (a[1] + a[3]) / 2.0 / 1000.0 - (b[1] + b[3]) / 2.0
    dw = (a[2] - a[0]) / 1000.0 - (b[2] - b[0])
    dh = (a[3] - a[1]) / 1000.0 - (b[3] - b[1])
    return ox, oy, dw, dh


def to_pack(ring_mm, ox, oy):
    """一圈 CAD 小帧(mm) → 包帧(m)。★ 首尾闭合照原样：包内 `poly` 就是闭合的。"""
    return [[round(p[0] / 1000.0 - ox, ROUND), round(p[1] / 1000.0 - oy, ROUND)] for p in ring_mm]


# ----------------------------------------------------------------- 一件 → 一条记录
def clip(rings, plate):
    """把一块面片**裁到楼面外框以内**，并回报**裁掉了多少**。

    ★ 为什么裁：本趟实测 1 层的**交通片**有 3 块伸到室外最远 12.24 m —— 那是上游
      「1 层栅格 `plate` 吞了室外」的老毛病（见 `识别方案.md`），**不是帧变换的错**。
      展示件里伸到室外的地板就是坏件 ⇒ 这里裁齐；但**裁掉多少必须记在件里**
      （`trimmed_m2`），不许把「裁掉了 2202 m²」这件事静默做掉。
    ★ 裁不动/裁没了 ⇒ 退回原样并**报数**，不静默给空。
    """
    a0 = abs(sg.Polygon(rings[0], rings[1:]).area) if len(rings) > 1 else abs(sg.Polygon(rings[0]).area)
    try:
        g = sg.Polygon(rings[0], rings[1:]).buffer(0).intersection(plate)
    except Exception:
        return rings, 0.0, "裁失败"
    if g.is_empty:
        return rings, 0.0, "裁没了"
    if g.geom_type == "MultiPolygon":
        g = max(g.geoms, key=lambda p: p.area)
    if g.geom_type != "Polygon":
        return rings, 0.0, "非面"
    out = [[round(x, ROUND), round(y, ROUND)] for x, y in g.exterior.coords]
    return [out] + [[[round(x, ROUND), round(y, ROUND)] for x, y in r.coords] for r in g.interiors], \
        round(a0 - g.area, 3), None


def make_room(rec, ox, oy, sid):
    out = {"id": None, "sid": sid, "poly": to_pack(rec["轮廓xy_mm"], ox, oy),
           "purpose": rec.get("用途") or "", "number": rec.get("房间号") or "",
           "area_m2": rec.get("算得面积_m2"), "stated_m2": rec.get("图上面积_m2"),
           "situation": rec.get("情形"), "src": "面积容量生长"}
    holes = [to_pack(h, ox, oy) for h in (rec.get("洞xy_mm") or []) if h]
    if holes:
        out["holes"] = holes
    return out


def make_circ(rec, ox, oy):
    return {"poly": to_pack(rec["轮廓xy_mm"], ox, oy),
            "area_m2": rec.get("算得面积_m2"), "src": "面积容量生长·未标注余格"}


def sid_of(num, floor, rec):
    """房间稳定 ID —— 走仓库**已有**的 `stable_id.room_id`（身份 = 房号），不另造。"""
    try:
        return stable_id.room_id(CAMPUS, BUILDING,
                                 {"number": num, "floor": floor, "purpose": rec.get("用途")})
    except Exception as e:                                    # ★ 失败要出声，不许静默给 None
        print("  ！stable_id 取号失败：%r" % (e,))
        return None


# ----------------------------------------------------------------- 主流程
def run(apply):
    tbl = json.load(open(ROOM_SRC, encoding="utf-8"))
    print("房间表 : %s（指纹 %s，%d 层）" % (os.path.basename(ROOM_SRC), tbl.get("指纹"), tbl.get("层数")))
    print("落点   : %s" % FLOORS_DIR)
    print("模式   : %s\n" % ("★ 写盘（先备份）" if apply else "只出读数（不写盘）"))

    per_floor, skipped = [], []
    tot = {"房": 0, "交通": 0, "顶点": 0, "越界": 0, "无旧号": 0, "旧房": 0,
           "裁_m2": 0.0, "裁_块": 0, "裁_失败": 0, "丢": 0}
    stamp = time.strftime("%Y%m%d-%H%M%S")
    backup = os.path.join(BACKUP_DIR, "floors-before-rooms-%s" % stamp)

    for fl in tbl["层"]:
        name = fl["层"]
        k = pack_index(name)
        if k is None or not os.path.exists(floor_path(k)):
            skipped.append((name, "这份 floors 目录里没有对应件（本步不造新件）"))
            continue
        pack = json.load(open(floor_path(k), encoding="utf-8"))
        outline = pack.get("outline") or []
        if len(outline) < 3:
            skipped.append((name, "包内 `outline` 缺失/退化 ⇒ 帧变换无参照物，**不敢猜**"))
            continue

        # ★ 覆盖前先取「包内原有房」的**独立读数**（覆盖后就只剩备份里那份了）
        n_old = len(pack.get("rooms") or [])
        old = {r.get("number"): r.get("id") for r in (pack.get("rooms") or []) if r.get("number")}

        mine = [r["轮廓xy_mm"] for r in fl["房间"]] + [r["轮廓xy_mm"] for r in fl["交通空间"]]
        if not mine:
            # ★ 本层一个面片都没有 ⇒ 既算不出帧变换、写下去还会把**包内现成的房间**整层抹掉。
            #   必须点名跳过（本趟实测 2 层、7 层就是这种，见 report）。
            skipped.append((name, "本层面片 0 个（房 0 / 交通 0）⇒ 无参照物，且写下去会抹掉包内现成的房间"))
            continue
        ox, oy, dw, dh = offset_of(mine, outline)
        plate0 = sg.Polygon(as_rings(outline)[0])      # 楼面外框（不 buffer）—— 裁齐用这个
        plate = plate0.buffer(MARGIN_M)                # 判据用带容差的这个

        rooms = [make_room(r, ox, oy, sid_of(r.get("房间号"), name, r)) for r in fl["房间"]]
        matched = 0
        for r, rec in zip(rooms, fl["房间"]):
            num = rec.get("房间号")
            if num in old:
                r["id"] = old[num]
                matched += 1
        circ = [make_circ(r, ox, oy) for r in fl["交通空间"]]

        # ★ 裁齐 + 记账（裁掉多少写进件里，不静默）
        cut_m2, cut_n, cut_fail = 0.0, 0, 0
        fail_names, dropped = [], 0          # ★ 失败要**点名**，不许只报个计数（报数不点名＝没法复核）
        for lst in (rooms, circ):
            out = []
            for r in lst:
                got, cut, why = clip([r["poly"]] + list(r.get("holes") or []), plate0)
                if why == "裁没了":
                    # ★ 与外框**交集为空** ⇒ 这块根本不在楼面上（实测 2 层有一块 0.01 m² 的碎渣）。
                    #   不写 —— 写下去就是一块「楼外的地板」；更坏的是它会让 `越界` 判据**洗绿**
                    #   （原样退回 ⇒ 顶点判据看不出，越界照样报 0）。丢掉的块**点名**，不许静默丢。
                    cut_fail += 1
                    dropped += 1
                    fail_names.append("%s(%s)" % (r.get("number") or "(交通)", why))
                    continue
                if why:                      # 几何退化 ⇒ 退回原样；下面的 `越界` 判据继续盯它
                    cut_fail += 1
                    fail_names.append("%s(%s)" % (r.get("number") or "(交通)", why))
                elif cut > 0:
                    r["poly"] = got[0]
                    if len(got) > 1:
                        r["holes"] = got[1:]
                    else:
                        r.pop("holes", None)
                    r["trimmed_m2"] = cut
                    cut_m2 += cut
                    cut_n += 1
                out.append(r)
            lst[:] = out                     # 就地收窄；`rooms + circ` 的总数随之变

        over = 0
        for r in rooms + circ:
            for p in r["poly"]:
                tot["顶点"] += 1
                if not plate.contains(sg.Point(p)):
                    over += 1

        pack["rooms"] = rooms
        pack["circulation"] = circ
        tot["房"] += len(rooms)
        tot["交通"] += len(circ)
        tot["越界"] += over
        tot["无旧号"] += len(rooms) - matched
        tot["旧房"] += n_old
        tot["裁_m2"] += cut_m2
        tot["裁_块"] += cut_n
        tot["裁_失败"] += cut_fail
        tot["丢"] += dropped
        per_floor.append({"层": name, "件": "floor%d.json" % k,
                          "偏移_m": [round(ox, 3), round(oy, 3)],
                          "外框残差_m": [round(dw, 3), round(dh, 3)],
                          "房": len(rooms), "交通": len(circ),
                          "包内原有房": n_old, "沿用旧号": matched,
                          "无旧号": len(rooms) - matched, "越界": over,
                          "裁_块": cut_n, "裁_m2": round(cut_m2, 1), "裁_失败": cut_fail,
                          "裁_失败_名单": fail_names})

        if apply:
            if not os.path.isdir(backup):
                os.makedirs(backup)
            shutil.copy2(floor_path(k), os.path.join(backup, "floor%d.json" % k))
            # ★ 字节层写盘（铁律 79）；本件是**一行**，落盘也写成一行
            with open(floor_path(k), "wb") as f:
                f.write(json.dumps(pack, ensure_ascii=False).encode("utf-8"))

    report(per_floor, skipped, tot, backup if apply else None)
    return 1 if tot["越界"] else 0


def report(per_floor, skipped, tot, backup):
    print("%-8s %-14s %-18s %-16s %5s %5s %7s %7s %7s %7s %8s"
          % ("层", "落点", "偏移X/Y (m)", "外框残差 (m)", "房", "交通", "原有", "沿旧", "越界",
             "裁块", "裁m²"))
    for r in per_floor:
        print("%-8s %-14s %-18s %-16s %5d %5d %7d %7d %7d %7d %8.1f"
              % (r["层"], r["件"], str(r["偏移_m"]), str(r["外框残差_m"]),
                 r["房"], r["交通"], r["包内原有房"], r["沿用旧号"], r["越界"],
                 r["裁_块"], r["裁_m2"]))
    print("\n合计：房 %d 片 · 交通 %d 片 · 顶点 %d 个 · 落位越界 %d 个（>0 就是红）"
          % (tot["房"], tot["交通"], tot["顶点"], tot["越界"]))
    print("      包内原有房合计 %d 间；沿用旧号 %d 间、无旧号 %d 间（无旧号的 `id` 落成 null）"
          % (tot["旧房"], tot["旧房"] - tot["无旧号"], tot["无旧号"]))
    print("      裁齐：%d 块、共裁掉 %.1f m²（记在各块的 `trimmed_m2` 里，未静默）；"
          "裁失败 %d 块（其中**丢掉不写** %d 块 —— 只算「与楼面外框无交集」的）"
          % (tot["裁_块"], tot["裁_m2"], tot["裁_失败"], tot["丢"]))
    fails = [(r["层"], n) for r in per_floor for n in (r.get("裁_失败_名单") or [])]
    if fails:
        print("\n★ 裁**失败**的块（点名；「裁没了」=与楼面外框无交集 ⇒ **丢掉不写**，"
              "其余=退回原样未裁）：")
        for f, n in fails:
            print("    %-8s %s" % (f, n))
    if skipped:
        print("\n★ **没写**的层（点名，不静默）：")
        for n, why in skipped:
            print("    %-8s %s" % (n, why))
    if backup:
        print("\n备份：%s" % backup)


def main(argv):
    """★ 通用：**换楼不换件** —— 落点/身份全从参数来，本件里不写死任何一栋。
    默认值只是本栋（第六教学楼）的口径，别的楼传 `--building` 即可。"""
    global ROOM_SRC, FLOORS_DIR, CAMPUS, BUILDING     # ★ 必须在本函数**任何**引用之前
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="备份后写盘（默认只出读数）")
    ap.add_argument("--table", default=ROOM_SRC, help="房间表路径")
    ap.add_argument("--gym", default=GYM, help="gym3d 根（交付包的家）")
    ap.add_argument("--campus", default=CAMPUS, help="场区名（进稳定 ID）")
    ap.add_argument("--building", default=BUILDING,
                    help="栋号 ⇒ 落点 <gym>/data/buildings/<栋>/floors，并进稳定 ID")
    a = ap.parse_args(argv)
    ROOM_SRC, CAMPUS, BUILDING = a.table, a.campus, a.building
    FLOORS_DIR = os.path.join(a.gym, "data", "buildings", a.building, "floors")
    return run(a.apply)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
