# -*- coding: utf-8 -*-
"""两个库：**每层 DXF 索引** + **房间统计**（可改，改动单独存，重建不丢）。

为什么是「索引」不是「拷贝」：
  · 每层 DXF 的**真源**就在 `<root>/06_su/contours/<层>.dxf`（`export_contours.py` 的产物）。
    再拷一份进构件库 = 第二个真源，改完谁新谁旧看不出来（铁律 018）。
  · 所以 `图纸库.json` 只记**路径 + 字节 + sha256 + mtime + 图层条数**，文件不动；
    要用一份集中副本时跑 `--导出 <dir>` 现拷（拷完仍以索引里的 sha256 为准）。

房间统计：
  · 来源 = `<root>/02_recognize/房间表.json`（`build_rooms.py` 的产物，一栋一份）。
  · **人工改动**存 `rebuild/构件库/房间_改动.json`（键 = `bid|层|房间号`），
    `房间库.json` = 算得值 + 改动覆盖后的**合并视图**。重建（`--房间`）只重算
    「算得值」，改动原样保留 —— 否则改一次、跑一次链就没了。
  · 没跑过 `build_rooms.py` 的楼**如实记 `无房间表`**，不编 0。

用法：
    python -X utf8 -I rebuild/tools/build_libraries.py            # 两个库都重建
    python -X utf8 -I rebuild/tools/build_libraries.py --图纸
    python -X utf8 -I rebuild/tools/build_libraries.py --房间
    python -X utf8 -I rebuild/tools/build_libraries.py --导出 D:\\临时\\dxf库
落盘：
    rebuild/构件库/图纸库.json
    rebuild/构件库/房间库.json
"""
from __future__ import annotations

import datetime
import hashlib
import json
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REBUILD = os.path.dirname(HERE)
LIB = os.path.join(REBUILD, "构件库")
PROFILE = os.path.join(LIB, "楼栋.json")
DRAW_LIB = os.path.join(LIB, "图纸库.json")
ROOM_LIB = os.path.join(LIB, "房间库.json")
ROOM_OVR = os.path.join(LIB, "房间_改动.json")

sys.path.insert(0, HERE)
import building as B  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)


def _now():
    return datetime.datetime.now().isoformat(timespec="seconds")


def _load(p, default=None):
    try:
        with open(p, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return default


def _dump(p, obj):
    """字节层写盘：UTF-8、LF、缩进 1 —— 与仓里其它库一致，且不让文本模式翻 CRLF。"""
    b = (json.dumps(obj, ensure_ascii=False, indent=1) + "\n").encode("utf-8")
    tmp = p + ".tmp"
    with open(tmp, "wb") as fh:
        fh.write(b)
    os.replace(tmp, p)
    return len(b)


def _sha256(p):
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _mtime(p):
    return datetime.datetime.fromtimestamp(os.path.getmtime(p)).isoformat(timespec="seconds")


def _bids():
    return sorted((_load(PROFILE, {}) or {}).keys() - {"schema", "说明"})


def _floors_dxf(bid):
    """一栋楼的每层 DXF —— 只读 contours/index.json 与文件本身，**不重跑导出**。"""
    root = B.root_for(bid)
    cdir = os.path.join(root, "06_su", "contours")
    idx = _load(os.path.join(cdir, "index.json"))
    if not isinstance(idx, list):
        return None, root
    out = []
    for f in idx:
        name = str(f.get("floor") or "")
        dxf = os.path.join(cdir, name + ".dxf")
        if not name or not os.path.exists(dxf):
            out.append({"层": name, "z0_m": f.get("z0_m"), "h_m": f.get("h_m"),
                        "文件": None, "缺": True})
            continue
        out.append({
            "层": name, "z0_m": f.get("z0_m"), "h_m": f.get("h_m"),
            "文件": dxf, "字节": os.path.getsize(dxf), "sha256": _sha256(dxf),
            "mtime": _mtime(dxf), "polys": f.get("polys"),
            "图层": f.get("per_layer") or {}, "复核不过": f.get("ok") is False,
        })
    return out, root


def build_draw():
    lib = {"schema": "cdut3d-drawing-library/1", "生成": _now(),
           "说明": "每层 DXF 的索引。文件真源在各楼栋 06_su/contours/，本库不复制；"
                   "要集中副本用 --导出。",
           "楼栋": {}}
    n_b, n_f, n_missing = 0, 0, 0
    for bid in _bids():
        floors, root = _floors_dxf(bid)
        if floors is None:
            lib["楼栋"][bid] = {"数据根": root, "层": [], "状态": "无轮廓（06_su/contours/index.json 不在）"}
            n_missing += 1
            continue
        ok = [x for x in floors if not x.get("缺")]
        lib["楼栋"][bid] = {"数据根": root, "层": floors,
                            "层数": len(floors), "有文件": len(ok),
                            "字节合计": sum(x.get("字节") or 0 for x in ok)}
        n_b += 1
        n_f += len(ok)
        n_missing += len(floors) - len(ok)
    lib["合计"] = {"楼栋": n_b, "层": n_f, "缺文件": n_missing}
    n = _dump(DRAW_LIB, lib)
    print("图纸库：%d 栋 / %d 层 DXF / 缺文件 %d ⇒ %s（%d 字节）"
          % (n_b, n_f, n_missing, DRAW_LIB, n))
    return lib


def _room_rows(bid):
    """一栋楼的房间统计（不含顶点，顶点回源件取）。没有房间表 ⇒ None。"""
    root = B.root_for(bid)
    p = os.path.join(root, "02_recognize", "房间表.json")
    d = _load(p)
    if not isinstance(d, dict) or not isinstance(d.get("层"), list):
        return None, root, p
    floors = {}
    for f in d["层"]:
        name = str(f.get("层") or "")
        rows = []
        for i, r in enumerate(f.get("房间") or []):
            rows.append({
                "序号": i + 1,
                "房间号": r.get("房间号") or "",
                "用途": r.get("用途") or "",
                "单位": r.get("单位") or "",
                "图上面积_m2": r.get("图上面积_m2"),
                "算得面积_m2": r.get("算得面积_m2"),
                "差_m2": r.get("差_m2"),
                "情形": r.get("情形") or "",
                "中心xy": r.get("中心xy"),
            })
        floors[name] = {
            "环数": f.get("环"),
            "底面积_m2": (f.get("环面积_m2") or {}).get("合计"),
            "房间": rows,
            "合计": {"间数": len(rows),
                      "算得面积_m2": round(sum((x.get("算得面积_m2") or 0) for x in rows), 3),
                      "图上面积_m2": round(sum((x.get("图上面积_m2") or 0) for x in rows), 3)},
        }
    n = sum(len(x["房间"]) for x in floors.values())
    return {"指纹": d.get("指纹"), "层": floors, "有房间": n > 0, "间数": n,
            "墙厚_mm": d.get("墙厚_mm"), "墙厚_来源": d.get("墙厚_来源")}, root, p


def _apply_overrides(lib, ovr):
    """把人工改动盖到合并视图上 —— 改过的行带 `标注="改动"` 与原文，看得见改了什么。"""
    n = 0
    for key, patch in (ovr.get("改动") or {}).items():
        try:
            bid, floor, no = key.split("|", 2)
        except ValueError:
            continue
        b = (lib["楼栋"].get(bid) or {}).get("层", {}).get(floor)
        if not b:
            continue
        for row in b.get("房间") or []:
            if str(row.get("房间号")) != no:
                continue
            fields = {k: v for k, v in patch.items() if not k.startswith("_")}
            row["标注"] = "改动"
            row["改动前"] = {k: row.get(k) for k in fields}
            row.update(fields)
            row["改动人"] = patch.get("_人")
            row["改动时刻"] = patch.get("_时刻")
            n += 1
            break
    return n


def build_rooms():
    ovr = _load(ROOM_OVR, {}) or {}
    lib = {"schema": "cdut3d-room-library/1", "生成": _now(),
           "说明": "每栋每层房间统计。算得值来自 02_recognize/房间表.json；"
                   "人工改动在 房间_改动.json，本库是合并视图。",
           "楼栋": {}}
    have, none, empty = [], [], []
    for bid in _bids():
        res, root, src = _room_rows(bid)
        if res is None:
            lib["楼栋"][bid] = {"数据根": root, "状态": "无房间表（先跑 build_rooms.py）", "层": {}}
            none.append(bid)
            continue
        lib["楼栋"][bid] = {"数据根": root, "来源": src, "指纹": res["指纹"],
                            "层": res["层"], "有房间": res["有房间"], "间数": res["间数"],
                            "墙厚_mm": res["墙厚_mm"], "墙厚_来源": res["墙厚_来源"]}
        if res["有房间"]:
            have.append(bid)
        else:
            # ★ 表在、0 间 ≠ 这栋没有房间：墙配对没成（缝环没走到）也会落一张空表。
            #   单独立一档，不许并进「有表」里冒充统计到位。
            lib["楼栋"][bid]["状态"] = "表在、0 间（墙配对没成，量不到环）"
            empty.append(bid)
    n_ovr = _apply_overrides(lib, ovr)
    total_rooms = sum(sum(x["合计"]["间数"] for x in b.get("层", {}).values())
                      for b in lib["楼栋"].values())
    lib["合计"] = {"楼栋有表": len(have) + len(empty), "楼栋有房间": len(have),
                    "楼栋空表": len(empty), "楼栋无表": len(none),
                    "间数": total_rooms, "人工改动": n_ovr}
    n = _dump(ROOM_LIB, lib)
    print("房间库：有房间 %d 栋 / 空表 %d 栋 / 无表 %d 栋 / 房间 %d 间 / 改动 %d 条 ⇒ %s（%d 字节）"
          % (len(have), len(empty), len(none), total_rooms, n_ovr, ROOM_LIB, n))
    if empty:
        print("  空表（墙配对没成）：" + " ".join(empty))
    if none:
        print("  无表：" + " ".join(none))
    return lib


def export_dxf(out_dir):
    lib = _load(DRAW_LIB) or build_draw()
    n = 0
    for bid, b in (lib.get("楼栋") or {}).items():
        for f in b.get("层") or []:
            src = f.get("文件")
            if not src or not os.path.exists(src):
                continue
            dst_dir = os.path.join(out_dir, bid)
            os.makedirs(dst_dir, exist_ok=True)
            dst = os.path.join(dst_dir, str(f.get("层")) + ".dxf")
            shutil.copy2(src, dst)
            if _sha256(dst) != f.get("sha256"):
                raise SystemExit("★ 导出后 sha256 不符：%s" % dst)
            n += 1
    print("导出 %d 份每层 DXF ⇒ %s（逐份按索引 sha256 复核通过）" % (n, out_dir))


def main(argv):
    want_draw = "--图纸" in argv or not ("--房间" in argv or "--导出" in argv)
    want_room = "--房间" in argv or not ("--图纸" in argv or "--导出" in argv)
    if "--导出" in argv:
        i = argv.index("--导出")
        if i + 1 >= len(argv):
            print("--导出 后面要给目录")
            return 2
        export_dxf(argv[i + 1])
        return 0
    os.makedirs(LIB, exist_ok=True)
    if want_draw:
        build_draw()
    if want_room:
        build_rooms()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
