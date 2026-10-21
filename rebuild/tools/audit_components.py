# -*- coding: utf-8 -*-
"""**构件识别自检**：逐栋逐层，把「认到了什么」与「图上有什么」并排打印，标出异常。

1. 调用方：**没有生产文件 import 它**，只在命令行手动跑（本次由我执行）。
   已有件都不做这件事：`compare3d.py` 比的是参照件 vs 正式件两份三维出件、
   `lint_detached.py` 量的是重画墙里的孤立小图、`audit` 类没有。故新建本件。
2. 只读、不写任何文件。
3. 读：`rebuild/构件库/楼栋.json`（dict，键=bid，字段 keep_layers/drawing/src_dxf）、
   `rebuild/<bid>/01_cad/raw/<层>.dxf`（DXF，无日期字段）、
   `rebuild/<bid>/05_build/build.json`（floors[] 里的 n_door_void / n_step 整数）。
4. 用户指令：「很多建筑需要你自检一下，再完善各个构件的识别」

为什么要它（2026-10-18）：门/柱的**图层名是从源图图层表现认的**（`building.layer()`），
而识别实际读的是 `01_cad/raw/<层>.dxf` —— **导出时被丢掉、又没进 `keep_layers` 的层，
在 raw 里不存在**。于是「选的层名在源图存在、在 raw 不存在」= 0 樘门而**不报错**。
实测：c007 选到 `4.3门窗`、c075 选到 `4.3门标注`，两栋 **0 樘门**；墙层上其实有 239 / 数百樘。

判词（每栋一行，异常打 ★）：
  墙     墙层实体数（raw 逐层最小值）
  门     墙层上认到的 符号/弧/块
  门层   实际选用的门层，以及它在 raw 里出现了几层
  柱     选用柱层上认到的柱块 + 多段线
  洞     建件里实际抠出的门洞数（build.json）
  ★ 门槛：门 0 而墙层有几何；或 门层不在 raw；或 柱 0；或 认到门但没抠出洞

用法：
  python -I rebuild/tools/audit_components.py                # 全部楼栋
  python -I rebuild/tools/audit_components.py c007 c075      # 指定楼栋
退出码：0 无异常 · 4 有异常（汇总在最后）
"""
from __future__ import annotations

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

import ezdxf                                                       # noqa: E402

BASE = os.path.dirname(os.path.dirname(HERE))                      # D:\项目\cdut3d
REBUILD = os.path.join(BASE, "rebuild")
PROF = os.path.join(REBUILD, "构件库", "楼栋.json")


def _raw_dir(bid):
    d = os.path.join(REBUILD, bid, "01_cad", "raw")
    return d if os.path.isdir(d) else None


def _floors(raw):
    return sorted(f[:-4] for f in os.listdir(raw) if f.lower().endswith(".dxf"))


def _census(doc):
    """层 → {实体类型: 数}（一次遍历）。"""
    out = {}
    for e in doc.modelspace():
        d = out.setdefault(e.dxf.layer, {})
        t = e.dxftype()
        d[t] = d.get(t, 0) + 1
    return out


def audit(bid, prof):
    raw = _raw_dir(bid)
    if not raw:
        return {"bid": bid, "flag": ["无raw"], "line": "%s 没有 01_cad/raw" % bid}
    keep = prof.get(bid, {}).get("keep_layers") or []
    wall = keep[0] if keep else None
    floors = _floors(raw)
    if not floors:
        return {"bid": bid, "flag": ["raw空"], "line": "%s raw 里没有 dxf" % bid}

    # ★ 门/柱层**用生产件的同一个函数**取（不是本件另写一份），它读的是源图；
    #   本件随后逐层核对这个层名在 raw 里到底存不存在。
    # ★★ `redraw` 的门参数（min_pts/宽度窗/形状比/弧半径）是**模块级常量、import 时**
    #   从档案读的 ⇒ 换楼栋必须 reload，否则拿上一栋的参数量这一栋（量具与被测对象错配）。
    import importlib
    import building as B
    import redraw as RD
    os.environ["CDUT_BUILDING"] = bid
    os.environ["CDUT_REBUILD_ROOT"] = os.path.join(REBUILD, bid)
    B.BID = bid
    RD = importlib.reload(RD)
    door_layer = B.layer("door", wall) if wall else None
    col_layer = B.layer("column", "4.1结构柱")

    wmin = None
    n_sym = n_arc = n_blk = n_col = 0
    door_layer_in_raw = 0
    col_layer_in_raw = 0
    zero_door_floors = []
    for f in floors:
        path = os.path.join(raw, f + ".dxf")
        doc = ezdxf.readfile(path)
        cnt = _census(doc)
        lay = cnt.get(wall, {})
        nw = sum(lay.values())
        wmin = nw if wmin is None else min(wmin, nw)
        if door_layer in cnt:
            door_layer_in_raw += 1
        if col_layer in cnt:
            col_layer_in_raw += 1
        # 门：**只看墙层**（这批图的门符号画在墙层上；注释层是 TEXT，不是门）
        s = RD.door_symbols(doc, layer=wall) if wall else []
        a = RD.door_arcs(doc, layer=wall) if wall else []
        b = RD.blocks_wcs(path, prefix=RD.DOOR_PREFIX)
        n_sym += len(s)
        n_arc += len(a)
        n_blk += len(b)
        # ★★ 2026-10-18：**逐层**看「当前画法认到几樘」。档案把画法钉死成 symbols/arcs，
        #   而同一栋楼里别的层可能用另一种画法（c022 2层：符号 0 / 开启弧 6；c017 地下1层：
        #   符号 0 / 开启弧 23；c020 1层：符号 2 / 开启弧 12）⇒ 那些层**0 樘门**。
        #   这不是「图上没画」，是「画法选错」（铁律 158/199）。
        eff = len(s) if RD.DOOR_MODE == "symbols" else (
            len(a) if RD.DOOR_MODE == "arcs" else len(b))
        alt = max(len(s), len(a), len(b))
        if eff == 0 and alt > 0:
            zero_door_floors.append("%s(另法%d)" % (f, alt))
        n_col += len(RD.cols_lwpolyline(doc, layer=col_layer))
        n_col += len(RD.blocks_wcs(path, layer=col_layer))

    # 建件读数（已落盘的）
    bj = os.path.join(REBUILD, bid, "05_build", "build.json")
    n_void = n_step = None
    if os.path.isfile(bj):
        d = json.load(open(bj, encoding="utf-8"))
        n_void = sum(x.get("n_door_void", 0) for x in d.get("floors", []))
        n_step = sum(x.get("n_step", 0) for x in d.get("floors", []))

    flags = []
    if wmin == 0:
        flags.append("墙0")
    n_door = n_sym + n_arc + n_blk
    if n_door == 0:
        flags.append("门0")
    if door_layer and door_layer != wall and door_layer_in_raw == 0:
        flags.append("门层不在raw")
    if n_col == 0:
        flags.append("柱0")
    elif col_layer_in_raw == 0:
        flags.append("柱层不在raw")
    if n_void == 0 and n_door > 0:
        flags.append("认到门没抠洞")
    if zero_door_floors:
        flags.append("层缺门(%s)" % ",".join(zero_door_floors))

    line = ("%-6s 层%-2d 墙%-6s 门[符%4d 弧%3d 块%3d] 门层=%-10s(raw %d层) "
            "柱%4d(%s) 洞%5s 踏步%5s%s"
            % (bid, len(floors), wmin, n_sym, n_arc, n_blk,
               door_layer or "-", door_layer_in_raw,
               n_col, col_layer or "-", n_void, n_step,
               "  ★" + "/".join(flags) if flags else ""))
    return {"bid": bid, "flag": flags, "line": line,
            "n_sym": n_sym, "n_arc": n_arc, "n_blk": n_blk, "n_col": n_col,
            "n_void": n_void, "wall": wall, "door_layer": door_layer}


def main(argv):
    bids = [a for a in argv if not a.startswith("--")]
    prof = json.load(open(PROF, encoding="utf-8"))
    if not bids:
        bids = [b for b in sorted(prof)
                if isinstance(prof.get(b), dict) and prof[b].get("src_dxf")]
    bad = []
    for b in bids:
        try:
            r = audit(b, prof)
        except Exception as e:                                     # noqa: BLE001
            # ★ 崩了 ≠ 没量到（铁律 199）：单栋崩了记一行，继续量其余楼栋
            print("%-6s ★崩 %s: %s" % (b, type(e).__name__, e))
            bad.append(b)
            continue
        print(r["line"])
        if r["flag"]:
            bad.append(b)
    print("\n合计 %d 栋，异常 %d 栋：%s" % (len(bids), len(bad), ", ".join(bad) or "无"))
    return 4 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
