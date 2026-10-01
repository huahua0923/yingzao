# -*- coding: utf-8 -*-
"""C5 · 卫星比对图「框 ↔ 图」对口 —— 清单说的那块地，图上真的是那块地吗。

## 为什么需要它（一次真实的漏检，2026-09-25）

`data/compare/manifest.json` 里校区大图 `campus_z17.png`（1792×1792 @ z17）与它的
`campus.bbox` 是**两处各算一个值**：图是当年一条内联命令取的（中心用 AMap 配置点、
**且没过 WGS→GCJ**，而高德瓦片是 GCJ 网格），bbox 是 `build_compare.py` 按照片 GPS
聚合点换算后算的。两份元数据**各自都自洽**，页面上一片正常 —— 11 个点位照样画、
照样可点、`/api/compare/img/campus` 照样 200、字节数与 sha 也都对得上。

实测两者沿经度差 **2 块瓦片 = 512 px ≈ 526 m**（图宽 28.6%）：图上每一个点位都偏了
半个街区，而**「摆对了」和「摆错了」在屏幕上长得一模一样**。

抓到它靠的是**逐字节比瓦片**（图正中 256² 块 ≡ z17 x103452 y53793，而 bbox 蕴含的中心
是 x103454），不是读代码、不是看页面。本文件就是把那次人工比法变成常驻判据 ——
用户明令：「系统必须有自己的检查与算法；智能体的判断须沉淀回引擎变成判据」。

## 三层，各管一类，**不许合并**

  · **P2 内容**（决定性；**只依赖 `bbox` + 图幅参数**）：
    按 `bbox` 反推应取的像素原点，从瓦片**重拼**一张，与盘上那张**逐像素**比。
    这一层问的是「这张图显示的，是不是 `bbox` 说的那块地」—— 上面那个缺陷**只有它
    能抓到**。它**不需要 `center`**，所以**旧清单也能直接红**（这正是它值钱的地方）。
    ★ 图幅参数 `z`/`px`/`py` v3 起记在 `campus` 层、v1/v2 记在 `bbox` 里，两处都读
      （`_frame`）—— 只认新形状的话，偏 526 m 那份**旧清单连 P2 都量不了**，
      而它是这条判据唯一的实物阳性对照。
  · **P1 框↔中心**（要 v3 清单）：`bbox` 必须等于由 `center_gcj` + `z` + `px` 推出的框。
  · **P3 换算**（要 v3 清单）：`center_gcj` 与 `center_wgs84` 的**偏移量必须落在合理带内**。
    ★ 这是**性质检查**，不是把转换公式再写一遍：本模块刻意**不 import 产出脚本的任何
    函数** —— 验收器去调被测方的函数，测出来的就只是「它自己跟自己一致」。
    只记 GCJ 不记 WGS 的话，「到底换算没有」永远看不出来（那个缺陷的另一半正是这个）。

## 「量不到」必须与「没问题」分开（见 findings.py）

  · 清单不在（这台机器没建过这个数据域）⇒ **UNAVAILABLE**。
  · 清单在、图不在 ⇒ **GAP**（产物丢了，而清单说它在）—— 与上一条不同，别合并：
    前者是「这里本来就没有这东西」，后者是「它有、但丢了」，补救动作相反。
  · 瓦片取不到（缓存没有、网也不通）⇒ **UNAVAILABLE 并报出缺几块** ——
    「这一带没影像」与「我没取到」屏幕上是同一张图。
  · 清单 `criterion_version < 3`（没记 `center_gcj`）⇒ P1/P3 **UNAVAILABLE**（不是 PASS）：
    没记的东西量不了。但 **P2 照常跑** —— 它只需要 bbox ＋ 图幅参数（见 `_frame`）。
  · 同一份清单把图幅参数记了两处、且不一致 ⇒ **GAP**（清单自己坏了），不许挑一个用。

## 量具自带阳性对照

P2 每次跑都顺带在**中心 640² 区域**上量两个已知平移（±64 px）的 MAD，把「这个偏移量下
尺子分不分得开」写进证据（`discriminating_power`）。只报一个 MAD 而不报它的分辨力，
等于让「全绿」和「尺子没接上」共用一行字（本仓铁律 19：通过率 100% 的判据不是严格，
是没接上）。

`--selftest` 用**本地合成瓦片**（不联网、确定性）造出每个结局各一条对照，
包括「拆掉那一层它必须红」、旧形状照样量得了、以及**夹具的键路径必须在真产物里都存在**
（最后这条是防「夹具在验一份不存在的形状」—— 本文件 2026-09-25 正是这么瞎了半天）。

用法：python -m backend.checks.compare_geo --selftest
      python -m backend.checks.compare_geo            # 直接判当前 data/
"""
from __future__ import annotations

import io
import json
import math
import os
import time
import urllib.request
from pathlib import Path

import numpy as np
from PIL import Image

from .findings import Finding, Report, Status, unavailable

MEASURE = "地理配准（框 bbox ↔ 图内容；口径＝Web Mercator 全局像素，与瓦片号同一套）"

TILE_PX = 256
#: 上游瓦片口（免 Key）。**与 `_scratch/_aerial/aerial_tiles.py` 同源，但这里各自写一份**
#: —— 本模块是**验收器**，验收器去调被测方的函数，测出来的就只是「它自己跟自己一致」。
#: 而且 `_aerial/` 在 `_scratch/` 下（未进 git），判据不许依赖它。
#: ★ 4 个 host 返回的字节**实测完全相同**，所以这里选哪个 host 不影响结果，
#: 也就不必复刻产出脚本的轮换规则（`selftest` 里留了噪声地板这一条）。
TILE = "https://webst0%d.is.autonavi.com/appmaptile?style=%d&x=%d&y=%d&z=%d"
HOSTS = (1, 2, 3, 4)
STYLE_SAT = 6
SLEEP_S = 0.12
TIMEOUT_S = 25
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

MANIFEST_REL = os.path.join("compare", "manifest.json")
CACHE_REL = os.path.join("_meta", "compare_tiles")

#: 逐像素比：MAD ≤ 这个数、且全等像素占比 ≥ `EXACT_MIN` ⇒ 认定「同一窗」。
#: ★ 这不是「容差」，是**两个假设之间的空档**：同一窗实测 MAD 恒为 0.00，
#:   而平移 8 px 已到两位数、平移 64 px 到三位数（见证据 `discriminating_power`）。
#:   每次跑都把那个空档打出来，所以这个阈值**被量过**，不是拍的。
MAD_PASS = 1.0
EXACT_MIN = 0.999
NEG_SHIFT = 64          # 阳性对照的平移量（px）
NEG_REGION = 640        # 阳性对照在中心多大的区域内比（避开边缘缺块）

#: 中国大陆 GCJ-02 相对 WGS-84 的偏移量级（米）。**性质带，不是重算公式**。
#: 实测本仓那一点约 360 m；带开得宽是为了不误伤，只用来抓「偏移恰好为 0」
#: 这种「忘了换算」的特征形状。
GCJ_MIN_M, GCJ_MAX_M = 80.0, 900.0


# ── 窗口数学（独立复写，四行） ────────────────────────────────────────────
def _npx(z: int) -> float:
    return float(TILE_PX) * (2 ** z)


def px_to_lonlat(px: float, py: float, z: int) -> tuple[float, float]:
    n = _npx(z)
    return (px / n * 360.0 - 180.0,
            math.degrees(math.atan(math.sinh(math.pi * (1.0 - 2.0 * py / n)))))


def lonlat_to_px(lon: float, lat: float, z: int) -> tuple[float, float]:
    n = _npx(z)
    r = math.radians(lat)
    return ((lon + 180.0) / 360.0 * n,
            (1.0 - math.log(math.tan(r) + 1.0 / math.cos(r)) / math.pi) / 2.0 * n)


def bbox_from_origin(left: int, top: int, z: int, px: int, py: int) -> dict:
    return {"west": px_to_lonlat(left, top + py, z)[0],
            "east": px_to_lonlat(left + px, top, z)[0],
            "north": px_to_lonlat(left, top, z)[1],
            "south": px_to_lonlat(left, top + py, z)[1]}


def origin_from_bbox(bb: dict, z: int) -> tuple[int, int]:
    """`bbox` 的西北角 → 应取的全局像素原点。这就是 P2 的立论：
    **框自己就定义了它该显示哪一块地**，不需要额外记中心。"""
    x, y = lonlat_to_px(float(bb["west"]), float(bb["north"]), z)
    return int(round(x)), int(round(y))


def m_per_px(lat: float, z: int) -> float:
    return 156543.03392 * math.cos(math.radians(lat)) / (2 ** z)


def _frame(camp: dict, bb: dict) -> tuple[int, int, int, str]:
    """图幅参数 `z`/`px`/`py` ⇒ `(z, px, py, why)`；`why` 非空表示这组值**不可用**。

    ★ 它们描述的是**那张图**（分辨率、边长），不是那个框 ⇒ v3 起记在 `campus` 层。
      v1/v2 记在 `bbox` 里（现在盘上那份备份还是这个形状），那条读法长期留着 ——
      不然**旧清单**连 P2 都量不了，而「拿真产物当场红一次」正是这条判据唯一的
      **实物阳性对照**（偏 526 m 的那份就是它）。
    ★ 两处都写了就**必须相等**：同一个量记两处、还允许不一致，等于把
      「两处各算一个值」这个错请回来。（一致证明不了它是对的，但**不一致一定是错的**。）
    ★ 这条读法本身栽过一次，就记在这儿：v3 把 z 挪到了 `campus` 层，而**夹具仍写老形状**
      ⇒ 自检 12/12 全绿，真清单**一个字都量不出来**：P2 报「没记 z」，
      P1 拿 z=0 推了个半球大的框、报「差 0.1 px」——两个红灯都不是数据的问题。
      ⇒ 下面 selftest 里那条「夹具形状 ⊆ 真产物形状」的对照与它配套，别再拆开。
    """
    z, px, py = camp.get("z"), camp.get("px"), camp.get("py")
    lz, lpx, lpy = bb.get("z"), bb.get("px"), bb.get("py")
    # ★ **只比两处都声称的那个量**：老清单可能只在 bbox 里记了 z、新清单在 campus 里记了
    #   z/px/py，两边重合的只有 z —— 那就比 z。（第一版拿三个量一起 `int()`，
    #   遇到这种「只重合一半」的形状当场 TypeError；是下面那条新对照抓出来的。）
    both = [("z", z, lz), ("px", px, lpx), ("py", py, lpy)]
    clash = [(n, a, b) for n, a, b in both
             if a is not None and b is not None and int(a) != int(b)]
    if clash:
        return 0, 0, 0, ("清单把图幅参数记了**两处且不一致**：%s ⇒ 不知道该按哪一处反推，"
                         "两层都量不了。这不是「没问题」，是**清单自己坏了**"
                         % "；".join("`%s` campus=%s vs bbox=%s" % (n, a, b)
                                     for n, a, b in clash))
    return (int(z if z is not None else lz or 0),
            int(px if px is not None else lpx or 0),
            int(py if py is not None else lpy or 0), "")


# ── 取瓦片（磁盘缓存优先；缓存的是**上游原样字节**） ──────────────────────
def tile_cache_path(cache: Path, z: int, x: int, y: int) -> Path:
    return cache / ("z%d_%d_%d.img" % (z, x, y))


def get_tile(x: int, y: int, z: int, cache: Path, allow_net: bool,
             stats: dict) -> bytes | None:
    """★ 缓存文件名用 `.img` 而不是 `.jpg`：缓存的是**字节**，格式靠 PIL 嗅探。
       （重新编码过再存，就等于把「逐像素比」换成「比两张我自己的图」，判据就空了。）"""
    p = tile_cache_path(cache, z, x, y)
    if p.is_file():
        stats["cache"] = stats.get("cache", 0) + 1
        return p.read_bytes()
    if not allow_net:
        stats["offline"] = stats.get("offline", 0) + 1
        return None
    url = TILE % (HOSTS[(x + y) % len(HOSTS)], STYLE_SAT, x, y, z)
    for attempt in (1, 2):
        try:
            req = urllib.request.Request(
                url, headers={"User-Agent": UA, "Referer": "https://www.amap.com/"})
            with urllib.request.urlopen(req, timeout=TIMEOUT_S) as r:
                b = r.read()
            if b[:2] != b"\xff\xd8":
                raise RuntimeError("不是 JPEG（%d 字节）" % len(b))
            stats["net"] = stats.get("net", 0) + 1
            try:
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_bytes(b)
            except OSError:
                pass                      # 缓存写不进去不影响本次判定（下次再取一遍）
            time.sleep(SLEEP_S)
            return b
        except Exception:                 # noqa: BLE001
            if attempt == 2:
                stats["fail"] = stats.get("fail", 0) + 1
                return None
            time.sleep(0.6)
    return None


def stitch(left: int, top: int, px: int, py: int, z: int,
           cache: Path, allow_net: bool, stats: dict
           ) -> tuple[np.ndarray, list[tuple[int, int]]]:
    """按 `left`/`top` 从瓦片重拼 px×py。缺块填 (24,24,24)（与产出脚本同约定）并列出。"""
    tx0, ty0 = left // TILE_PX, top // TILE_PX
    tx1, ty1 = (left + px - 1) // TILE_PX, (top + py - 1) // TILE_PX
    h, w = (ty1 - ty0 + 1) * TILE_PX, (tx1 - tx0 + 1) * TILE_PX
    canvas = np.full((h, w, 3), 24, dtype=np.uint8)
    missing: list[tuple[int, int]] = []
    for ty in range(ty0, ty1 + 1):
        for tx in range(tx0, tx1 + 1):
            b = get_tile(tx, ty, z, cache, allow_net, stats)
            if b is None:
                missing.append((tx, ty))
                continue
            try:
                arr = np.asarray(Image.open(io.BytesIO(b)).convert("RGB"))
            except Exception:             # noqa: BLE001
                missing.append((tx, ty))
                continue
            if arr.shape != (TILE_PX, TILE_PX, 3):
                # 形状不对 ⇒ **量不到**，不是「对上了」。填进画布再比会让判据悄悄失明。
                missing.append((tx, ty))
                continue
            canvas[(ty - ty0) * TILE_PX:(ty - ty0 + 1) * TILE_PX,
                   (tx - tx0) * TILE_PX:(tx - tx0 + 1) * TILE_PX] = arr
    oy, ox = top - ty0 * TILE_PX, left - tx0 * TILE_PX
    return canvas[oy:oy + py, ox:ox + px], missing


def diff(a: np.ndarray, b: np.ndarray) -> dict:
    d = np.abs(a.astype(np.int16) - b.astype(np.int16))
    per = d.max(axis=2)
    return {"mad": round(float(d.mean()), 4), "max": int(per.max()),
            "exact_px": round(float((per == 0).mean()), 6)}


def _gcj_offset_m(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    """两点相距多少米（小范围平面近似；只用来判「量级对不对」）。"""
    dy = (lat2 - lat1) * 111320.0
    dx = (lon2 - lon1) * 111320.0 * math.cos(math.radians(lat1))
    return math.hypot(dx, dy)


# ── 判定本体 ────────────────────────────────────────────────────────────
#: 判定结果 = (检查编号后缀, 状态, 人话, 证据)
Outcome = tuple[str, Status, str, dict]

TITLES = {
    "img_vs_bbox": "比对大图：框说的那块地 == 图上那块地",
    "bbox_vs_center": "比对大图：bbox 与 center_gcj 互推一致",
    "center_conversion": "比对大图：中心做过 WGS→GCJ 换算",
}


def judge(man: dict, cache: Path, allow_net: bool = True) -> list[Outcome]:
    """判一份清单的校区大图。三层各出一条结论（没记的东西各自报 UNAVAILABLE）。"""
    out: list[Outcome] = []
    camp = man.get("campus") or {}
    bb = camp.get("bbox") or {}
    img = camp.get("img") or ""
    base = {"criterion_version": man.get("criterion_version"),
            "manifest_built": man.get("built"),
            "img": os.path.basename(img) if img else None}

    # ── P2：框 ↔ 图内容（决定性；只依赖 bbox） ────────────────────────────
    if not img or not bb:
        out.append(("img_vs_bbox", Status.UNAVAILABLE,
                    "清单里没有 campus.img 或 campus.bbox ⇒ 这一层量不了",
                    dict(base, why="缺字段")))
    elif not os.path.isfile(img):
        out.append(("img_vs_bbox", Status.GAP,
                    "清单说校区大图在 %s（%s 字节），盘上没有 ⇒ **产物丢了**。"
                    "注意这与「清单里没这一项」是两件事，补救动作相反"
                    % (os.path.basename(img), camp.get("bytes")),
                    dict(base, why="文件不在")))
    else:
        out.extend(_judge_content(base, camp, bb, img, cache, allow_net))

    # ── P1：bbox ↔ center_gcj ───────────────────────────────────────────
    cc = camp.get("center_gcj") or {}
    if not cc or not bb:
        out.append(("bbox_vs_center", Status.UNAVAILABLE,
                    "清单没记 `center_gcj`（criterion_version=%s）⇒ 框与中心**无法互推**。"
                    "这不是「没问题」，是**没记** —— 重建清单才量得了"
                    % man.get("criterion_version"),
                    dict(base, why="缺 center_gcj")))
    else:
        z, px, py, why = _frame(camp, bb)
        if why:
            out.append(("bbox_vs_center", Status.GAP, why,
                        dict(base, z=z, px=px, py=py, mismatch="图幅参数两处不一致")))
        elif z <= 0 or px <= 0 or py <= 0:
            out.append(("bbox_vs_center", Status.UNAVAILABLE,
                        "清单没记全图幅参数（新清单在 `campus` 层、旧清单在 `bbox` 层，"
                        "这次拿到 z=%d px=%d py=%d）⇒ 框与中心**无法互推**。"
                        "这不是「没问题」，是**没记** —— 重建清单才量得了" % (z, px, py),
                        dict(base, z=z, px=px, py=py, why="缺图幅参数")))
        else:
            x, y = lonlat_to_px(float(cc["lon"]), float(cc["lat"]), z)
            left, top = int(round(x - px / 2.0)), int(round(y - py / 2.0))
            want = bbox_from_origin(left, top, z, px, py)
            bad = {k: {"清单": bb.get(k), "由中心推出的": want[k]}
                   for k in ("west", "east", "north", "south")
                   if abs(float(bb.get(k, 1e30)) - want[k]) > 1e-9}
            ev = dict(base, z=z, px=px, py=py, center_gcj=cc,
                      origin=[left, top], mismatch=bad)
            if bad:
                dl = (float(bb.get("west", 0)) - want["west"]) * _npx(z) / 360.0
                ev["west_offset_px"] = round(dl, 1)
                out.append(("bbox_vs_center", Status.GAP,
                            "清单里的 bbox 与它自己记的 center_gcj 对不上（%d 个字段，"
                            "西边界差 %.1f px）⇒ 两处各算了一个值，而屏幕上"
                            "「摆对了」和「摆错了」长得一样" % (len(bad), dl), ev))
            else:
                out.append(("bbox_vs_center", Status.PASS,
                            "bbox 与 center_gcj 逐字段一致（容差 1e-9）", ev))

    # ── P3：center_gcj ↔ center_wgs84（换算有没有做） ──────────────────
    cw = camp.get("center_wgs84") or {}
    if not cc or not cw:
        out.append(("center_conversion", Status.UNAVAILABLE,
                    "清单没同时记 `center_gcj` 与 `center_wgs84` ⇒ 换算这一步量不了",
                    dict(base, why="缺中心")))
    else:
        off = _gcj_offset_m(float(cw["lon"]), float(cw["lat"]),
                            float(cc["lon"]), float(cc["lat"]))
        ev = dict(base, center_wgs84=cw, center_gcj=cc,
                  offset_m=round(off, 1), band_m=[GCJ_MIN_M, GCJ_MAX_M])
        if GCJ_MIN_M <= off <= GCJ_MAX_M:
            out.append(("center_conversion", Status.PASS,
                        "GCJ 与 WGS 中心相距 %.0f m，落在合理带 [%.0f, %.0f] 内 ⇒ "
                        "换算这一步是真的做了" % (off, GCJ_MIN_M, GCJ_MAX_M), ev))
        else:
            out.append(("center_conversion", Status.GAP,
                        "GCJ 与 WGS 中心相距 **%.1f m**，不在合理带 [%.0f, %.0f] 内。"
                        "≈0 m 通常意味着**拿 WGS 点直接当 GCJ 用了** —— "
                        "高德瓦片是 GCJ 网格，这样取图会偏出小半个街区，而图上完全看不出来"
                        % (off, GCJ_MIN_M, GCJ_MAX_M), ev))
    return out


def _judge_content(base: dict, camp: dict, bb: dict, img: str,
                   cache: Path, allow_net: bool) -> list[Outcome]:
    """P2：把 `bbox` 反推成像素原点，重拼，逐像素比。"""
    z, px, py, why = _frame(camp, bb)
    if why:
        return [("img_vs_bbox", Status.GAP, why,
                 dict(base, why="图幅参数两处不一致"))]
    if z <= 0:
        return [("img_vs_bbox", Status.UNAVAILABLE,
                 "清单没记图幅参数 `z`（新清单在 `campus` 层、旧清单在 `bbox` 层，"
                 "这次两处都没有）⇒ 反推不了原点，量不了",
                 dict(base, why="缺 z"))]
    real = np.asarray(Image.open(img).convert("RGB"))
    ih, iw = real.shape[:2]
    px, py = px or iw, py or ih
    ev = dict(base, z=z, image=[iw, ih], bbox_px=[px, py],
              bytes=os.path.getsize(img), bytes_field=camp.get("bytes"),
              sha12_field=camp.get("sha12"), bbox=bb)
    if (iw, ih) != (px, py):
        return [("img_vs_bbox", Status.GAP,
                 "清单说图是 %d×%d，盘上实际 %d×%d ⇒ 框和图不是同一批产物"
                 % (px, py, iw, ih), ev)]

    left, top = origin_from_bbox(bb, z)
    ev["origin_from_bbox"] = [left, top]
    stats: dict = {}
    mos, missing = stitch(left, top, px, py, z, cache, allow_net, stats)
    ev["tiles"] = {"net": stats.get("net", 0), "cache": stats.get("cache", 0),
                   "offline": stats.get("offline", 0), "fail": stats.get("fail", 0),
                   "missing": len(missing), "missing_sample": missing[:6]}
    if missing:
        return [("img_vs_bbox", Status.UNAVAILABLE,
                 "有 %d 块瓦片取不到（缓存没有、网也不通或取块失败）⇒ **这一层没量成**。"
                 "「这一带没影像」与「我没取到」在屏幕上是同一行字，所以不许报通过"
                 % len(missing), ev)]

    r = diff(real, mos)
    ev["diff"] = r
    # 阳性对照：已知平移的 MAD（尺子在这次运行里到底分不分得开）
    neg: dict[str, float] = {}
    half = NEG_REGION // 2
    if px >= NEG_REGION + 2 * NEG_SHIFT and py >= NEG_REGION + 2 * NEG_SHIFT:
        cx0, cy0 = px // 2 - half, py // 2 - half
        sub = real[cy0:cy0 + NEG_REGION, cx0:cx0 + NEG_REGION]
        for d in (-NEG_SHIFT, NEG_SHIFT):
            neg["dy%+d" % d] = diff(sub, mos[cy0 + d:cy0 + NEG_REGION + d,
                                             cx0:cx0 + NEG_REGION])["mad"]
            neg["dx%+d" % d] = diff(sub, mos[cy0:cy0 + NEG_REGION,
                                             cx0 + d:cx0 + NEG_REGION + d])["mad"]
    ev["discriminating_power"] = {"offset_px": NEG_SHIFT, "region_px": NEG_REGION,
                                  "mad_at_offset": neg, "pass_band": MAD_PASS}
    if not neg:
        return [("img_vs_bbox", Status.UNAVAILABLE,
                 "图只有 %d×%d，放不下 %d×%d 的阳性对照区 ⇒ **没量成**"
                 "（尺子没自证分辨力，结论不敢给）" % (px, py, NEG_REGION, NEG_REGION), ev)]
    if min(neg.values()) <= MAD_PASS:
        return [("img_vs_bbox", Status.UNAVAILABLE,
                 "阳性对照失败：平移 ±%d px 的 MAD 只有 %.2f（判据带 ≤ %.1f）⇒ "
                 "这次运行的尺子分不开「对」和「差一点」，**结论不可用**"
                 % (NEG_SHIFT, min(neg.values()), MAD_PASS), ev)]
    if r["mad"] <= MAD_PASS and r["exact_px"] >= EXACT_MIN:
        return [("img_vs_bbox", Status.PASS,
                 "按 bbox 重拼的图与盘上那张逐像素一致（MAD=%.4f，全等 %.4f%%）⇒ "
                 "图显示的**就是** bbox 说的那块地。阳性对照：平移 %d px 时 MAD=%.2f"
                 % (r["mad"], r["exact_px"] * 100, NEG_SHIFT, min(neg.values())), ev)]
    lat_c = (bb["north"] + bb["south"]) / 2.0
    return [("img_vs_bbox", Status.GAP,
             "**框与图不是同一块地**：按 bbox 重拼 vs 盘上那张，MAD=%.2f、全等仅 %.2f%%"
             "（应 ≈0 与 ≈100%%）⇒ 图上的点位会整体偏；而屏幕上「摆对了」和「摆错了」"
             "长得一模一样" % (r["mad"], r["exact_px"] * 100),
             dict(ev, m_per_px=round(m_per_px(lat_c, z), 3)))]


def load_manifest(data_dir: Path) -> tuple[dict | None, str]:
    p = Path(data_dir) / MANIFEST_REL
    if not p.is_file():
        return None, "还没有比对清单：%s（跑 _scratch/_compare/build_compare.py）" % p
    try:
        return json.loads(p.read_text(encoding="utf-8")), str(p)
    except (OSError, ValueError) as e:               # noqa: BLE001
        return None, "比对清单读不开：%s（%s）" % (p, e)


def check_c5(rep: Report, data_dir: Path, state: dict | None = None) -> None:
    """C5：卫星比对图的框与图对不对口。`state` 收下但不用（同 C4：签名一致优先）。"""
    man, why = load_manifest(data_dir)
    if man is None:
        rep.add(unavailable("C5", "卫星比对图「框 ↔ 图」对口", why))
        return
    allow_net = os.environ.get("GYM3D_COMPARE_NONET", "") not in ("1", "true", "yes")
    for suffix, st, detail, ev in judge(man, Path(data_dir) / CACHE_REL,
                                        allow_net=allow_net):
        rep.add(Finding(check="C5.%s" % suffix, title=TITLES[suffix], status=st,
                        detail=detail, measure=MEASURE, evidence=ev,
                        blocked_by=(detail if st == Status.UNAVAILABLE else "")))


# ── 自检：本地合成瓦片，不联网、确定性 ──────────────────────────────────
def _synthetic_tile(x: int, y: int) -> np.ndarray:
    """内容随 (x,y) **和像素位置**都变 —— 这样「整块平移」与「平移一个像素」都会让
    MAD 变化。若只随 (x,y) 变、块内是常量，偏 1 px 就量不出来（判据自己失明）。"""
    yy = (np.arange(TILE_PX, dtype=np.int32)[:, None] + y * 7)
    xx = (np.arange(TILE_PX, dtype=np.int32)[None, :] + x * 13)
    a = np.empty((TILE_PX, TILE_PX, 3), dtype=np.uint8)
    a[:, :, 0] = (xx * 3 + yy) % 256
    a[:, :, 1] = (xx + yy * 5) % 256
    a[:, :, 2] = ((xx ^ yy) * 7) % 256
    return a


FIX_CENTER = (104.146906537, 30.673169164)      # 真实量级：成都理工大学一带
FIX_Z, FIX_PX = 17, 1024
#: 仓里的真实数据目录 —— 只给「夹具形状 ⊆ 真产物形状」那条对照用（读不到就报没量）。
_REPO_DATA = Path(__file__).resolve().parents[2] / "data"


def _paths(obj, prefix: str = "") -> set[str]:
    """把一份清单摊成「点分键路径」集合 —— 用来**机械地**比对夹具形状与真产物形状。
    （只取形状，不取值；列表按元素展开但不编号，因为判据从不按下标读数。）"""
    out: set[str] = set()
    if isinstance(obj, dict):
        for k, v in obj.items():
            out.add(prefix + str(k))
            out |= _paths(v, prefix + str(k) + ".")
    elif isinstance(obj, list):
        for v in obj:
            out |= _paths(v, prefix)
    return out


def _mk_case(tmp: Path, legacy_shape: bool = False) -> tuple[dict, Path]:
    """造一个自洽的夹具：合成瓦片 → 按中心拼一张图 → 写出与它一致的 bbox。

    ★ `z`/`px`/`py` 写在 **`campus` 层** —— 这是 v3 产物的真形状
      （`_scratch/_compare/build_compare.py` 就是这么写的：它们描述那张**图**，不是那个框）。
      `legacy_shape=True` 造 v1/v2 的老形状（塞进 `bbox`），只用于「旧清单还量得了吗」那条对照。
    ★★ 这里**必须抄真产物**：2026-09-25 我改产物把 z 挪到了 campus 层，而夹具没跟着挪
      ⇒ 自检 12/12 全绿、真清单**一个字都量不出来**（P2「没记 z」、P1 拿 z=0 推了个半球大的框）。
      所以 selftest 里配了一条「夹具的每个键路径都得在真产物里存在」，专防这一类。
    """
    cache = tmp / "tiles"
    cache.mkdir(parents=True, exist_ok=True)
    clon, clat = FIX_CENTER
    x, y = lonlat_to_px(clon, clat, FIX_Z)
    left, top = int(round(x - FIX_PX / 2.0)), int(round(y - FIX_PX / 2.0))
    tx0, ty0 = left // TILE_PX, top // TILE_PX
    tx1, ty1 = (left + FIX_PX - 1) // TILE_PX, (top + FIX_PX - 1) // TILE_PX
    # ★ 夹具要**比窗口大一圈**（每边多 4 块）：下面那条「bbox 整体挪 2 块瓦片」的对照，
    #   挪完的窗口落在别的列上 —— 不备着那几列，判据只会报「取不到」（UNAVAILABLE），
    #   而那条对照就**永远证伪不了**（红不了也没错，等于没验）。这是夹具的缺陷，不是判据的。
    M = 4
    for ty in range(ty0 - M, ty1 + M + 1):
        for tx in range(tx0 - M, tx1 + M + 1):
            Image.fromarray(_synthetic_tile(tx, ty)).save(
                tile_cache_path(cache, FIX_Z, tx, ty), "PNG")
    img = tmp / "campus.png"
    mos, missing = stitch(left, top, FIX_PX, FIX_PX, FIX_Z, cache, False, {})
    assert not missing, "夹具自己拼不齐：%s" % missing
    Image.fromarray(mos).save(img, "PNG")
    bb = bbox_from_origin(left, top, FIX_Z, FIX_PX, FIX_PX)
    camp: dict = {"img": str(img), "bbox": bb, "bytes": os.path.getsize(img),
                  "sha12": "fixture",
                  "center_gcj": {"lon": clon, "lat": clat},
                  # 与 center_gcj 相距约 360 m（真实量级）⇒ P3 该过
                  "center_wgs84": {"lon": clon - 0.00393, "lat": clat - 0.00124}}
    if legacy_shape:
        camp["bbox"] = dict(bb, z=FIX_Z, px=FIX_PX, py=FIX_PX)
    else:
        camp.update(z=FIX_Z, px=FIX_PX, py=FIX_PX)
    man = {"criterion_version": 2 if legacy_shape else 3,
           "built": "夹具（合成瓦片）", "campus": camp}
    return man, cache


def _shape_parity(fixture_campus: dict, real_man: dict | None,
                  real_why: str = "") -> tuple[bool | None, str]:
    """夹具的键路径必须**都在真产物里存在** ⇒ `(True/False/None, 说明)`；`None` = 没量到。

    方向是**单向的**（夹具 ⊆ 真产物）：真产物比夹具多几个键是正常的（它记 `m_per_px`
    之类的额外统计），而**夹具多出一个真产物没有的键**就说明夹具在验一份不存在的形状 ——
    这正是 2026-09-25 那个坑：产物把 `z` 挪到了 `campus` 层，夹具还塞在 `bbox` 里，
    自检全绿、真产物一个字量不了。
    ★ 抽成函数是为了它能**被证伪**：拿一份老形状的夹具调它，它必须报不一致
      （不然这条对照自己也是个「永远绿」的摆设）。
    """
    if real_man is None:
        return None, "真清单读不到（%s）⇒ **没量**，不是「一致」" % real_why
    extra = sorted(_paths(fixture_campus) - _paths(real_man.get("campus") or {}))
    if extra:
        return False, ("夹具的键在真产物里**不存在**：%s ⇒ 夹具在验一份不存在的形状"
                       % extra)
    return True, "夹具的每个键路径在真产物里都存在"


def _shift_bbox_lon(man: dict, n_px: int) -> dict:
    """把 bbox 沿经度整体挪 n_px 像素（造「框与图各说各话」）。"""
    m = json.loads(json.dumps(man))
    bb = m["campus"]["bbox"]
    for k in ("west", "east"):
        bb[k] = px_to_lonlat(lonlat_to_px(bb[k], bb["north"], FIX_Z)[0] + n_px,
                             bb["north"], FIX_Z)[0]
    return m


def selftest() -> int:
    """每个结局各一条对照 ＋ 一组「拆掉那一层它必须红」的证伪。"""
    import shutil
    import tempfile
    tmp = Path(tempfile.mkdtemp(prefix="c5selftest_"))
    bad = 0

    def chk(label: str, want: Status, outs: list[Outcome], key: str = "img_vs_bbox"):
        nonlocal bad
        o = next((x for x in outs if x[0] == key), None)
        got = o[1] if o else None
        ok = got == want
        bad += 0 if ok else 1
        print("  [%s] %-44s 期望 %-11s 得到 %s"
              % ("✓" if ok else "✗", label, want.value, got.value if got else "缺"))
        if not ok and o:
            print("       detail=%s" % o[2][:170])
        return o

    try:
        man, cache = _mk_case(tmp)

        print("── 正例：三层每一层都该过")
        o = judge(man, cache, allow_net=False)
        for k in TITLES:
            chk("全绿 %s" % k, Status.PASS, o, k)
        d = next(x for x in o if x[0] == "img_vs_bbox")[3]["discriminating_power"]
        print("       分辨力：平移 %s px ⇒ MAD %s（判据带 ≤ %.1f）"
              % (d["offset_px"], d["mad_at_offset"], MAD_PASS))
        if min(d["mad_at_offset"].values()) <= MAD_PASS:
            print("  ✗ 阳性对照没分开 —— 这条尺子本身失效")
            bad += 1

        print("\n── 负例：bbox 沿经度偏 2 块（512 px）＝ **本次那个真缺陷的形状**")
        o = judge(_shift_bbox_lon(man, 2 * TILE_PX), cache, False)
        chk("内容层必须红", Status.GAP, o)
        chk("P1 框↔中心也必须红", Status.GAP, o, "bbox_vs_center")

        print("\n── 负例：bbox 只偏 8 px（亚块偏移，尺子对细偏也要敏感）")
        chk("内容层必须红", Status.GAP, judge(_shift_bbox_lon(man, 8), cache, False))

        print("\n── 负例：忘了 WGS→GCJ 换算（两个中心写成同一个点）")
        m4 = json.loads(json.dumps(man))
        m4["campus"]["center_wgs84"] = dict(m4["campus"]["center_gcj"])
        chk("中心偏移 ≈0 ⇒ P3 必须红", Status.GAP, judge(m4, cache, False),
            "center_conversion")

        print("\n── 量不到（不许读成「合格」）")
        m5 = json.loads(json.dumps(man))
        m5["campus"].pop("center_gcj")
        chk("没记 center_gcj ⇒ P1 报没量成", Status.UNAVAILABLE,
            judge(m5, cache, False), "bbox_vs_center")
        o6 = judge(man, tmp / "空缓存", allow_net=False)
        o6f = chk("瓦片一块都取不到 ⇒ 内容层报没量成", Status.UNAVAILABLE, o6)
        print("       缺块数 = %s" % o6f[3]["tiles"]["missing"])
        m7 = json.loads(json.dumps(man))
        m7["campus"]["img"] = str(tmp / "根本没这张.png")
        chk("清单说图在、盘上却没了 ⇒ GAP（不是 UNAVAILABLE）", Status.GAP,
            judge(m7, cache, False))
        m8 = json.loads(json.dumps(man))
        # ★ 只改 `campus.px/py`（图幅参数**现在在这儿**）。要是顺手去写 `bbox.px`，
        #   那就是**新造一个键**、同时让两处不一致 —— 断言照样绿，但验的已经是
        #   「两处不一致」那条分支了（铁律 36：同一条断言落在别的分支上，屏幕上分不开）。
        m8["campus"]["px"] = m8["campus"]["py"] = 512
        chk("清单的 px 与图的真实尺寸不符 ⇒ GAP", Status.GAP, judge(m8, cache, False))

        print("\n── 旧形状（z/px/py 在 `bbox` 里）**也必须量得了** —— "
              "偏 526 m 那份真清单就是这个形状，它是本判据唯一的实物阳性对照")
        m9, _ = _mk_case(tmp, legacy_shape=True)
        o9 = judge(m9, cache, False)
        chk("旧形状：内容层照样过", Status.PASS, o9)
        chk("旧形状：P1 照样过", Status.PASS, o9, "bbox_vs_center")
        o9b = chk("旧形状：偏 8 px 照样红（不是「量不了」冒充通过）", Status.GAP,
                  judge(_shift_bbox_lon(m9, 8), cache, False))

        print("\n── 同一个量记了两处、还不一致 ⇒ 不许挑一个用")
        m10 = json.loads(json.dumps(man))
        m10["campus"]["bbox"]["z"] = FIX_Z + 1
        chk("图幅参数两处不一致 ⇒ 内容层 GAP", Status.GAP, judge(m10, cache, False))
        chk("图幅参数两处不一致 ⇒ P1 也 GAP", Status.GAP, judge(m10, cache, False),
            "bbox_vs_center")
        # 「只重合一半」的形状（bbox 里只有 z、campus 里有三个）—— 第一版在这里
        # 直接 TypeError 崩了，而崩之前它已经在上面几条里全绿。判据必须能受住**混合形状**。
        m11 = json.loads(json.dumps(man))
        m11["campus"]["bbox"]["z"] = FIX_Z
        chk("两处只重合 z 且相等 ⇒ 照常过（不许崩）", Status.PASS, judge(m11, cache, False))

        print("\n── 夹具的形状**必须抄真产物**（这一条是本次那个坑的机器化）")
        real_man, real_why = load_manifest(_REPO_DATA)
        ok, why = _shape_parity(man["campus"], real_man, real_why)
        if ok is None:
            print("  [–] %s" % why)
        else:
            bad += 0 if ok else 1
            print("  [%s] %s" % ("✓" if ok else "✗", why))
        # 阳性对照：老形状的夹具**必须**被判成不一致 —— 不然这条对照自己是摆设。
        legacy_man, _ = _mk_case(tmp, legacy_shape=True)
        ok2, why2 = _shape_parity(legacy_man["campus"], real_man, real_why)
        if ok2 is None:
            print("  [–] 老形状对照：%s" % why2)
        else:
            good = ok2 is False
            bad += 0 if good else 1
            print("  [%s] 老形状夹具必须被判不一致：%s" % ("✓" if good else "✗", why2))

        print("\n── 阴性对照：夹具的**噪声地板**")
        same = bool((_synthetic_tile(103449, 53790) == _synthetic_tile(103449, 53790)).all())
        bad += 0 if same else 1
        print("  [%s] 同一坐标两次合成逐字节相同 ⇒ 判据不会被「噪声」骗"
              % ("✓" if same else "✗"))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("\n--selftest %s：%d 条对照没验成" % ("红" if bad else "绿", bad))
    return 1 if bad else 0


def main(argv: list[str]) -> int:
    if "--selftest" in argv:
        return selftest()
    for a in argv:
        if a.startswith("-"):
            # 本仓铁律 9：不认识的开关一律拒绝，绝不「忽略并按默认全量跑」
            print("不认识的参数：%s（只认 --selftest）" % a)
            return 2
    from backend.paths import DATA
    rep = Report(scope="system")
    check_c5(rep, DATA)
    for f in rep.findings:
        d = f.as_dict()
        print("[%s] %s\n     %s" % (d["status"].upper(), f.title, f.detail))
    return 1 if any(f.status == Status.GAP for f in rep.findings) else 0


if __name__ == "__main__":
    import sys
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(main(sys.argv[1:]))
