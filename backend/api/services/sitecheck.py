# -*- coding: utf-8 -*-
"""外业校核数据域：把「建好的模型」贴回「真实的正射影像」上，指出外形错误。

## 这一域回答什么

前面几域回答的都是「图上是这么画的」／「我们建成了什么」。
这一域回答的是**另一半**：「建成的这个，在真实场地上是不是长这样」。

## 尺子是现成的，而且**零落位成本**

`D:\\理工数据\\DOM\\原始DOM影像\\理工DOM.tif`
  · 15,573,061,529 B · 44452 × 58113 px · 3 波段 uint16
  · **EPSG:4544**（CGCS2000 / 3 度带 CM 105E）· 0.05 m/px
  · **金字塔已建** overviews [2,4,8,16,32,64,128,255]

它**本身就在校区坐标系里** ⇒ 与模型比对不需要任何落位数学。

★ 这条不是这里推出来的，是 `kb/src/09-component-details.md` 里已经写死的一条：
  「正射影像是**零落位成本**的尺子」。本条与它同源。

## 还缺的那一样：每栋楼的「落位锚点」

正射在 4544 里，模型在**它自己的 DXF 局部系**里（`floors/*.json` 的 `outline`
是米制局部坐标）。两者之间那个变换**盘上不存在** —— `_scratch/_c006_fly_vs_model.py`
的文件头把这件事写死了：「盘上没有任何锚点文件，所以配准只能自己算 ——
**这本来就是「外观检查」的第一道工序**」。

⇒ 本域的立场：**有锚点就算，没锚点就出声**。
   绝不拿一个手推的变换糊过去（`_anchor_match_probe.py` 的注释：「手推出来的变换
   不许直接进代码」）。

## 锚点存在哪

`data/_meta/site_anchors.json` —— **本域唯一会写的文件**。
一行一栋，**只增不改**（要改得显式带 `replace`）。

★ 每一行**必须**写清 `src` = 「这个点位是谁给的」。
  `_scratch/_c011_anchor.json` 的 `anchors.source` 原文是
  「用户给的 c011 点位（本会话原文）」——**那就只活在那一份脚本里**，
  换个人再来一次就得重新问一遍。存进表里，它才是资产。

## 朝向是个**假设**，不是个测量 —— 所以把它变成一条记录

`_scratch/_c011_ab.json` 自己写着这句 caveat：

    模型是按「自己的 XY 包围盒中心 = 用户给的点位」摆的 —— 这是假设不是测量；
    朝向（是否与北一致）本轮未验证，图上若出现 90°/镜像，先怀疑这一条。

⇒ 本域不消灭这个假设（消灭它要另一套测量），**把它变成一个可选的字段**：
   `rot_deg ∈ {0,90,180,270}`，由人在图上选定并**记进锚点表**。
   从此「朝向」从「没人验过的假设」变成「某人某时刻做的决定，写在盘上」。

## 三态，不许合并

`ok`（有锚点、出图成功）／ `no_anchor`（这栋没有落位锚点 ⇒ 做不了）／
`failed`（有锚点但出图失败，把服务端那句话原样带上）。
与 `services/compare.py` 的 `missing/stale/ok` 同一个理由：
三件事的下一步动作各不相同，屏幕上却是三句看着差不多的话。

## 只读纪律

`D:\\理工数据\\` 是**原始测绘成果**，本域**一个字节都不写**（只用 rasterio 读窗口）。
"""
from __future__ import annotations

import io
import json
import math
import os
from functools import lru_cache
from pathlib import Path
from typing import Any

# ★ 正射大图。默认写死，但允许环境变量覆盖 —— 部署到服务器上时那份图不一定在 D 盘。
#   找不到就**明说找的是哪个路径**（照抄 routers/campus.py 对 campus_dir 的处置）。
ORTHO_DEFAULT = r"D:\理工数据\DOM\原始DOM影像\理工DOM.tif"

# ── 三维那一侧：2024 飞的实景烘出来的**地表高程栅格（DSM）** ──────────
#
# ★ 为什么是 DSM 而不是点云：**本机盘上没有任何点云**（2026-10-02 普查：
#   D:\理工数据 与 D:\gym3d 上 .las/.laz/.ply/.e57/.xyz/.pts 全零命中）。
#   唯一的立体参照就是这个 DSM —— 它正是「飞的三维实景」被烘成的**高度场**。
#   所以「CloudCompare -C2M_DIST 逐点偏差」这条原定路子**没有可吃的输入**，
#   而 -ICP 会把我们正要量的那个偏差当作待配准量**配掉**（把整体抬高一并抹平）。
#   ⇒ 改用 DSM 内部**自己减自己**的量（地面与屋盖都取自同一张栅格）⇒ 基准自动抵消。
#
# ★ 这一份的出处（`_store/fly2024_dsm_025.json`）：
#     source = D:\理工数据\理工模型202408\Data（L21/L20/L19 网格）· EPSG:4544
#     origin = (416881, 3397504) · mpp = 0.25 · 9600×12800 · nodata = -9999
#   ★ 盘上有**三份**几乎同名的：`...025.tif`（权威，provenance 的 product）、
#     `...025.southup.tif`（**行序反的**那份）、`...025_v2.tif`（补洞版，
#     见 `fly2024_fill_report.json` 的 dsm_in→dsm_out）。挑哪一份**不按 mtime**，
#     按「取 c011 屋盖那一点是不是 ≈479 m」这个判据 —— 实测 southup 那一份在那个
#     窗口里**一格有效值都没有**，另两份给出逐位相同的 478.704。
#   ★ 它是 `_scratch/` 下的中间产物（`_bake_fly_store.py` 文件头自己写着
#     「不是 data/，不进交付，可随时重烤」）⇒ 不能当交付件读。所以这里
#     **允许环境变量覆盖**，且读不到时**明说路径**、不许退化成"没有偏差"。
DSM_DEFAULT = r"D:\gym3d\_scratch\c011_fly\_store\fly2024_dsm_025.tif"

# 高出本地地面这么多才算「不是地面」。3.0 m 与 `_fly_buildings.py` 的 h_min 同值
# —— 同一条判据在两个地方写同一个数时，**要把「同源」这件事写下来**（铁律 018：
# 两处一致证明不了它是对的；这里能证明的只是"我抄的是它"）。
DSM_H_MIN = 3.0
# 平屋盖占比的容差（米）。楼有平顶、树冠没有 —— 这是分「楼 / 树」的唯一判据，
# 也是 `_fly_buildings.py` 用的那个数。
DSM_FLAT_TOL = 0.5
# 交叉核对用的：那份已经按 1 m 网格分好栋的产物（它的地面也是分位估计，但窗口
# 与网格都与我这里不同 ⇒ 它是一条**真正独立**的第二条路，不只是换了个写法）。
DSM_FBB_REL = ("_scratch", "c011_fly", "_store", "fly_buildings.json")

ANCHORS_REL = ("data", "_meta", "site_anchors.json")
CRITERION_VERSION = 1

# ★ 单张出图的像素上限。校核看的是轮廓，1400 px 足够；
#   再大就只是把同一块正射插值得更糊（而读盘时间线性长）。
MAX_PX = 1400

# 默认窗口：以锚点为中心的一个正方形。160 m 能放下校区里绝大多数一栋楼。
DEFAULT_HALF_M = 80.0

NOTE = (
    "外业校核的落位锚点表。一行一栋，键是楼号。"
    "★ 每行的 src 必须写清「这个点位是谁给的」——"
    "出处不明的锚点，与「还没锚定」在屏幕上同形。"
)


class NoOrtho(RuntimeError):
    """正射影像不在盘上。★ 消息里**必须**带上找的是哪个路径。"""


class NoAnchor(KeyError):
    """这栋楼还没有落位锚点。"""


# ────────────────────────────────────────────────────────────────
# 锚点表
# ────────────────────────────────────────────────────────────────

def anchors_path(cfg) -> Path:
    return cfg.root.joinpath(*ANCHORS_REL)


def anchors_load(cfg) -> dict[str, Any]:
    """读锚点表。**文件不存在**返回一个空壳（不是异常）—— 空表是一个合法的状态。"""
    p = anchors_path(cfg)
    if not p.is_file():
        return {"criterion_version": CRITERION_VERSION, "note": NOTE, "items": {}}
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except Exception as exc:                       # noqa: BLE001
        # ★ 坏文件**不许**退化成空表：那会让「表里有人写的锚点全丢了」
        #   看起来像「还没人锚定过」，两件事的下一步动作完全相反。
        raise NoOrtho("锚点表读不出来（%s）：%s" % (p, type(exc).__name__)) from exc
    d.setdefault("items", {})
    return d


def anchor_one(cfg, name: str) -> dict[str, Any] | None:
    return (anchors_load(cfg).get("items") or {}).get(name)


def anchors_put(cfg, name: str, item: dict[str, Any], replace: bool = False) -> dict[str, Any]:
    """写一行。**只增不改**：键已存在且没带 `replace` ⇒ 拒（不静默覆盖）。

    ★ 原子写：临时文件 + `os.replace`（与 `services/console.py` 的 `_atomic_json`
      同一套路）。锚点表是人手工攒出来的，半截写等于全丢。
    """
    p = anchors_path(cfg)
    doc = anchors_load(cfg)
    items = doc.setdefault("items", {})
    if name in items and not replace:
        raise FileExistsError(name)

    rec = {
        "E": float(item["E"]),
        "N": float(item["N"]),
        "rot_deg": int(item.get("rot_deg") or 0) % 360,
        "src": str(item.get("src") or "").strip(),
        "by": str(item.get("by") or "").strip(),
        "ts": str(item.get("ts") or "").strip(),
    }
    # ★ 出处为空 = 这一行将来没人能核。宁可拒，也不留一个「像是量过的」数。
    if not rec["src"]:
        raise ValueError("锚点缺 src：出处不明的点位不许进表")
    if rec["rot_deg"] not in (0, 90, 180, 270):
        raise ValueError("rot_deg 只允许 0/90/180/270，收到 %r" % rec["rot_deg"])
    # 用户在正射上框出来的那个矩形（可选）。有它才能给出「长宽差/面积比」这类数。
    if item.get("trace"):
        t = item["trace"]
        rec["trace"] = {k: float(t[k]) for k in ("E0", "N0", "E1", "N1")}

    items[name] = rec
    doc["criterion_version"] = CRITERION_VERSION
    doc.setdefault("note", NOTE)

    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, p)
    return rec


# ────────────────────────────────────────────────────────────────
# 正射大图
# ────────────────────────────────────────────────────────────────

def ortho_path(cfg) -> Path:
    return Path(os.environ.get("GYM3D_ORTHO_TIF") or ORTHO_DEFAULT)


@lru_cache(maxsize=4)
def _meta_cached(path_str: str, mtime: int, size: int) -> dict[str, Any]:
    """把 header 读一次缓存起来。

    ★ 缓存键里带上 `(mtime, size)`：正射被换过一份而进程还记着旧 bounds，
      屏幕上给的就是**另一张图上的坐标**，且完全看不出来（铁律 022 同族）。
    """
    import rasterio                          # 延迟 import：没装也不用整个服务起不来
    with rasterio.open(path_str) as ds:
        b = ds.bounds
        # ★ `to_epsg()` **默认置信度**在**这一份**图上返回 None，而 `to_epsg(0)` 返回 4544
        #   （2026-10-02 实测：`crs.to_epsg() -> None`、`crs.to_epsg(0) -> 4544`、
        #   `to_authority() -> None`，而 crs 的 WKT 末尾明明写着 AUTHORITY["EPSG","4544"]）。
        #   代价：如果照默认写法，页面上会印出 **「EPSG: None」**，而本域整套「零落位成本」
        #   的论证就架在这个系上 —— 一个 None 会让那张图看起来像"坐标系没认出来"。
        #   ⇒ 用 `to_epsg(0)`（只信 WKT 里作者自己声明的那个 authority），
        #     并把**默认口径的结果一起发出去** —— 两个数不一致时，读的人得看得见这件事，
        #     而不是等我下次再踩一遍（铁律 182：判据的口径是量具的一部分）。
        epsg = None
        epsg_default = None
        try:
            epsg = ds.crs.to_epsg(0) if ds.crs else None
            epsg_default = ds.crs.to_epsg() if ds.crs else None
        except Exception:                    # noqa: BLE001
            pass
        return {
            "path": path_str,
            "crs": str(ds.crs),
            "epsg": epsg,
            # ★ 这一项存在的唯一理由是「让口径差可见」。它**不是**给判据用的。
            "epsg_default_confidence": epsg_default,
            "epsg_caliber": "to_epsg(0)：只信 WKT 里的 AUTHORITY（默认置信度在这一份图上给 None）",
            "count": ds.count,
            "dtype": ds.dtypes[0],
            # ★ 0.05 在浮点上落成 0.049999999999998164 —— 判据要按**误差**比，
            #   不许按 `== 0.05`（本仓铁律 182②「舍入是量具的一部分」的同一族）。
            "res": [abs(ds.transform.a), abs(ds.transform.e)],
            "width": ds.width,
            "height": ds.height,
            "bounds": [b.left, b.bottom, b.right, b.top],
            "overviews": sorted(ds.overviews(1) or []),
        }


def ortho_meta(cfg) -> dict[str, Any]:
    p = ortho_path(cfg)
    if not p.is_file():
        # ★ 必须说出**找的是哪个路径**：否则「图不在」与「路径写错了」同形。
        raise NoOrtho("正射影像不在盘上，找的是：%s" % p)
    st = p.stat()
    return _meta_cached(str(p), int(st.st_mtime), st.st_size)


def _stretch(a, lo_q: float = 2.0, hi_q: float = 98.0):
    """uint16 → uint8。按**本块自己的**分位数拉伸。

    ★ 用本块分位数而不是全图分位数：全图分位数得把 15.6 GB 扫一遍。
      代价是**同一栋楼在不同窗口下灰度会变** —— 所以出图时把 lo/hi 一并返回，
      让「颜色看起来不一样」这件事有出处可查。
    """
    import numpy as np
    f = a.astype("float32")
    lo, hi = float(np.percentile(f, lo_q)), float(np.percentile(f, hi_q))
    if not math.isfinite(lo) or not math.isfinite(hi) or hi - lo < 1e-6:
        lo, hi = float(f.min()), float(max(f.max(), f.min() + 1.0))
    return np.clip((f - lo) * (255.0 / (hi - lo)), 0, 255).astype("uint8"), lo, hi


def crop(cfg, bounds_en: tuple[float, float, float, float], max_px: int = MAX_PX):
    """按 **EPSG:4544 的 (E0,N0,E1,N1)** 从正射里裁一块，回 (PIL.Image, meta)。

    ★★ `out_shape` **必须给** —— 给了它 rasterio 才会去走已建好的 overviews
       （[2,4,8,16,32,64,128,255]），否则就是按 0.05 m/px 把那一块的
       `w/0.05 × h/0.05` 个像素全读进来。160 m 见方 = 3200×3200×3×2 B ≈ 61 MB，
       而走 overview 读的是同一块的 1/16。**这是本函数唯一一处「顺序就是正确性」**。

    ★ 窗口越界时**裁到图内**并把 `clipped` 标出来，不静默补零：
      补零出来的那一半在屏幕上是一条黑边，看起来像「这儿没东西」。
    """
    import numpy as np
    import rasterio
    from PIL import Image
    from rasterio.windows import Window, from_bounds

    meta = ortho_meta(cfg)
    e0, n0, e1, n1 = (float(v) for v in bounds_en)
    if e1 < e0:
        e0, e1 = e1, e0
    if n1 < n0:
        n0, n1 = n1, n0
    if e1 - e0 <= 0 or n1 - n0 <= 0:
        raise ValueError("窗口的宽或高是 0：(%r,%r,%r,%r)" % (e0, n0, e1, n1))

    bl, bb, br, bt = meta["bounds"]
    ce0, cn0 = max(e0, bl), max(n0, bb)
    ce1, cn1 = min(e1, br), min(n1, bt)
    clipped = (ce0, cn0, ce1, cn1) != (e0, n0, e1, n1)
    if ce1 <= ce0 or cn1 <= cn0:
        raise ValueError(
            "窗口整个落在正射范围外：要 (%0.1f,%0.1f)-(%0.1f,%0.1f)，"
            "正射只有 (%0.1f,%0.1f)-(%0.1f,%0.1f)" % (e0, n0, e1, n1, bl, bb, br, bt))

    with rasterio.open(meta["path"]) as ds:
        win = from_bounds(ce0, cn0, ce1, cn1, ds.transform)
        wan = abs(win.width) * (ds.transform.a ** 2) ** 0.5      # 米
        han = abs(win.height) * abs(ds.transform.e)
        scale = max(wan, han) / float(max_px)
        if scale <= 0:
            scale = 1.0
        w = max(1, int(round(wan / scale)))
        h = max(1, int(round(han / scale)))
        arr = ds.read(window=win, out_shape=(ds.count, h, w),
                      resampling=rasterio.enums.Resampling.average, boundless=False)

    mpp_out = (ce1 - ce0) / w
    rgb = arr[:3] if arr.shape[0] >= 3 else np.repeat(arr[:1], 3, axis=0)
    chans, lo, hi = [], None, None
    for i in range(3):
        u8, lo, hi = _stretch(rgb[i])
        chans.append(u8)
    img = Image.fromarray(np.dstack(chans), "RGB")
    return img, {
        "window_en": [ce0, cn0, ce1, cn1],
        "asked_en": [e0, n0, e1, n1],
        "clipped": bool(clipped),
        "px": [w, h],
        "mpp": mpp_out,
        "stretch": [lo, hi],
        "overviews": meta["overviews"],
    }


def png_bytes(img) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=False)
    return buf.getvalue()


# ────────────────────────────────────────────────────────────────
# 模型足迹（局部米制）
# ────────────────────────────────────────────────────────────────

def _poly_area(poly) -> float:
    s = 0.0
    n = len(poly)
    for i in range(n):
        x0, y0 = poly[i]
        x1, y1 = poly[(i + 1) % n]
        s += x0 * y1 - x1 * y0
    return abs(s) / 2.0


def footprint(cfg, name: str) -> dict[str, Any] | None:
    """从 `floors/floor*.json` 取这栋楼的**平面轮廓**（米，局部系）。

    ★ 为什么不用 GLB：`data/buildings/<n>/<n>-building.glb` 最大 105 MB，
      为了拿一个外接框去解一份三角网不划算；而 `outline` 正是**建这份 GLB 的输入**，
      口径上还更靠上游一格。

    ★ 报**两个**东西，别混：
      · `plan`   —— 取**面积最大**的那一层轮廓（塔楼各层同形，取最大的那个不漏挑檐）
      · `envelope` —— **跨全部楼层**的外接框（= 模型在平面上的真实占位）
      只用其中一个都会给出一个像结论的数：只用 plan 会漏掉某层外挑，
      只用 envelope 会把一个 L 形楼说成一个矩形。
    """
    base = cfg.root / "data" / "buildings" / name / "floors"
    if not base.is_dir():
        return None
    files = sorted(base.glob("floor*.json"))
    if not files:
        return None

    best, best_area, floors_used = None, -1.0, []
    xs: list[float] = []
    ys: list[float] = []
    for f in files:
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except Exception:                       # noqa: BLE001
            continue
        o = d.get("outline")
        if not (isinstance(o, list) and len(o) >= 3):
            continue
        poly = [(float(p[0]), float(p[1])) for p in o if isinstance(p, (list, tuple)) and len(p) >= 2]
        if len(poly) < 3:
            continue
        floors_used.append(str(d.get("floor")))
        xs.extend(p[0] for p in poly)
        ys.extend(p[1] for p in poly)
        a = _poly_area(poly)
        if a > best_area:
            best, best_area = poly, a

    if best is None or not floors_used:
        return None

    bx0, bx1 = min(xs), max(xs)
    by0, by1 = min(ys), max(ys)
    return {
        "name": name,
        "plan": best,
        "plan_area_m2": best_area,
        "plan_bbox": [bx0, by0, bx1, by1],
        "envelope": {"w_m": bx1 - bx0, "d_m": by1 - by0,
                     "bbox": [bx0, by0, bx1, by1]},
        "n_floors": len(floors_used),
        "floors": floors_used,
        "caliber": "取自 floors/floor*.json 的 outline（米，DXF 局部系）",
    }


def _rot(p, deg: int):
    """绕原点把点转 `deg` 度（逆时针）。只做 90 的整数倍 —— 见文件头「朝向」。"""
    import math as _m
    r = _m.radians(deg)
    c, s = round(_m.cos(r), 12), round(_m.sin(r), 12)
    x, y = p
    return (x * c - y * s, x * s + y * c)


def _draw_poly(px_draw, ploy_xy, color, width=2):
    px_draw.line(list(ploy_xy) + [ploy_xy[0]], fill=color, width=width)


# ────────────────────────────────────────────────────────────────
# 三维那一侧：DSM 上的外形量测
# ────────────────────────────────────────────────────────────────

def dsm_path(cfg) -> Path:
    return Path(os.environ.get("GYM3D_DSM_TIF") or DSM_DEFAULT)


@lru_cache(maxsize=4)
def _dsm_meta_cached(path_str: str, mtime: int, size: int) -> dict[str, Any]:
    """DSM 的 header。★ 缓存键里带 `(mtime, size)`，理由与 `_meta_cached` 逐字相同。"""
    import rasterio
    with rasterio.open(path_str) as ds:
        b = ds.bounds
        epsg = None
        try:
            epsg = ds.crs.to_epsg(0) if ds.crs else None
        except Exception:                       # noqa: BLE001
            pass
        return {
            "path": path_str,
            "crs": str(ds.crs),
            "epsg": epsg,
            "res": [abs(ds.transform.a), abs(ds.transform.e)],
            "width": ds.width,
            "height": ds.height,
            "bounds": [b.left, b.bottom, b.right, b.top],
            "nodata": ds.nodata,
            "overviews": sorted(ds.overviews(1) or []),
        }


def dsm_meta(cfg) -> dict[str, Any]:
    p = dsm_path(cfg)
    if not p.is_file():
        raise NoOrtho("实景高程栅格（DSM）不在盘上，找的是：%s" % p)
    st = p.stat()
    return _dsm_meta_cached(str(p), int(st.st_mtime), st.st_size)


def dsm_mtime(cfg) -> float:
    """给路由的缓存键用 —— 栅格被重烤过而进程还发着旧的偏差，屏幕上看不出来（铁律 022）。"""
    p = dsm_path(cfg)
    return p.stat().st_mtime if p.is_file() else 0.0


def _cross_check(cfg, E: float, N: float) -> dict[str, Any]:
    """第二条路：读 `fly_buildings.json` 里离锚点最近的那一栋，与本次现量对一遍。

    ★ 为什么非要有这一条：铁律 182 —— **每条判据旁边要有一条独立算同一个量的路**。
      那一条的口径与这里**确实不同**（它的地面是 100 m 方块的 5 分位、网格 1 m、
      还先做了连通分块），所以两条对得上才算数；对不上时第一个嫌疑人是**我这把尺子**。

    ★ 而且它**不许**只用「最近」认亲：最近质心离得再近，也可能认的是隔壁那一栋。
      所以这里把「锚点是不是真落在那栋自己的外接框里」一起算出来并**印出去** ——
      认亲的凭据要摆在屏幕上，不能只留在我的脑子里（铁律 140/141）。
    """
    p = cfg.root.joinpath(*DSM_FBB_REL)
    if not p.is_file():
        return {"state": "absent", "why": "盘上没有分栋产物：%s" % p}
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
        b = d.get("buildings") or []
    except Exception as exc:                    # noqa: BLE001
        return {"state": "unreadable", "why": "%s: %s" % (type(exc).__name__, exc)}
    if not b:
        return {"state": "empty", "why": "产物里没有 buildings 数组"}

    # ★ 键名不是 E/N —— 实测过：我按 `x.get("E")` 取，全返回 None，
    #   于是「最近的那一栋」算出来距离 3 420 830 m（地球另一头）。
    #   dict 不抛异常，那个数还长得像结论（铁律 141：字段的名字不是它的定义）。
    def _d(x):
        return math.hypot(float(x.get("cen_e") or 0.0) - E, float(x.get("cen_n") or 0.0) - N)

    best = min(b, key=_d)
    ee, nn = float(best.get("ext_e") or 0.0), float(best.get("ext_n") or 0.0)
    dE = float(best.get("cen_e") or 0.0) - E
    dN = float(best.get("cen_n") or 0.0) - N
    inside = abs(dE) <= ee / 2.0 and abs(dN) <= nn / 2.0
    return {
        "state": "ok",
        "source": str(p),
        "at": {"d_m": round(_d(best), 2), "dE_m": round(dE, 2), "dN_m": round(dN, 2)},
        "anchor_inside": bool(inside),
        "anchor_inside_note": ("锚点落在这栋自己的外接框里（认亲的凭据，不是只按『最近』）"
                               if inside else
                               "★ 锚点**不在**这栋的外接框里 —— 这一条很可能认的是隔壁那一栋，"
                               "两个数对不上时先看这一句"),
        "area_m2": best.get("area_m2"),
        "ext_e_m": ee, "ext_n_m": nn,
        "roof_z": best.get("roof_z"), "gnd_z": best.get("gnd_z"), "h_m": best.get("h"),
        "flat": best.get("flat"), "lab": best.get("lab"),
    }


def relief(cfg, name: str, rec: dict[str, Any], fp: dict[str, Any],
           half_m: float = DEFAULT_HALF_M) -> dict[str, Any]:
    """在实景高程栅格上量这栋楼的**外形**：地面标高 / 屋盖标高 / 屋盖外接。

    ── 为什么这三个数是**能信**的（基准自动抵消）────────────────────
    地面取这张栅格里本窗的 5 分位、屋盖取同一窗里那一块的 95 分位 ——
    **两个数来自同一张栅格、同一套高程基准**，所以「椭球高 / 正常高差多少」
    这件事**根本不用知道**：相减时抵消掉了。
    （本仓记过：DSM 存的是椭球高 —— `memory/geo-dsm-datum-and-survey-registration`。
      正因为存在这一条，才不许拿 DSM 的绝对标高去与模型的局部 Z 直接比。）

    ── 屋盖外接是**檐口**，不是墙 ────────────────────────────────
    总账 §5.2 已结案：DSM 记的是**顶面**。有挑檐的楼，檐下那一圈地面上读到的
    **不是地面，是挑檐的顶** ⇒ 「屋盖外接」永远 = 屋顶含檐口。c011 实测：
    模型 61.8 m（墙）vs 实景 74.8 m（檐口），差的 6.5 m/侧就是挑檐，
    用户 2026-09-29 已确认「是有挑檐的」。
    ⇒ 所以本函数把「实景外接 − 模型足迹 = 挑檐」**当真**，而不是当缺陷；
      真正的缺陷是**模型里根本没有这一圈**。这句话必须跟着数一起回去。

    ── 三态（与出图那三态同一套理由：下一步动作相反）──────────────
    `ok` 量到了 / `no_dsm` 栅格不在 / `outside` 锚点落在栅格外 /
    `no_blob` 窗内没有足够的地物 / `failed` 我们的管道坏了（原样带出异常）
    """
    import numpy as np
    from scipy import ndimage

    try:
        meta = dsm_meta(cfg)
    except NoOrtho as exc:
        return {"state": "no_dsm", "why": str(exc), "path": str(dsm_path(cfg))}

    E, N = float(rec["E"]), float(rec["N"])
    env = fp["envelope"]
    # 窗口半径：包住模型足迹再留 30 m 余量（留给挑檐与地面参考）。
    R = max(60.0, max(env["w_m"], env["d_m"]) / 2.0 + 30.0)

    bl, bb, br, bt = meta["bounds"]
    if not (bl <= E <= br and bb <= N <= bt):
        return {"state": "outside", "path": meta["path"],
                "why": ("锚点 (%0.1f, %0.1f) 落在这份高程栅格的范围之外："
                        "(%0.1f,%0.1f)-(%0.1f,%0.1f) ⇒ 这一栋量不了，"
                        "不是「它没有外形问题」" % (E, N, bl, bb, br, bt))}

    try:
        import rasterio
        from rasterio.windows import from_bounds
        with rasterio.open(meta["path"]) as ds:
            win = from_bounds(E - R, N - R, E + R, N + R, ds.transform)
            a = ds.read(1, window=win, boundless=True,
                        fill_value=float(meta["nodata"] if meta["nodata"] is not None else -9999.0))
            tr = ds.transform
            # 每个格中心的 4544 坐标（要用来量外接，不能拿格号当米）
            rr, cc = np.mgrid[0:a.shape[0], 0:a.shape[1]]
            ee = tr.c + (cc + 0.5) * tr.a
            nn = tr.f + (rr + 0.5) * tr.e
    except Exception as exc:                    # noqa: BLE001
        return {"state": "failed", "path": meta["path"],
                "why": "%s: %s" % (type(exc).__name__, exc)}

    nod = float(meta["nodata"] if meta["nodata"] is not None else -9999.0)
    good = a > (nod + 1.0)
    frac = float(good.mean()) if a.size else 0.0
    if frac < 0.5:
        return {"state": "no_blob", "path": meta["path"], "valid_frac": round(frac, 4),
                "why": ("这个窗口里只有 %.1f%% 的格有高程 —— 空得太厉害，"
                        "量出来的「地面/屋盖」会是噪声" % (frac * 100.0))}

    ground = float(np.percentile(a[good], 5.0))
    mask = good & (a > ground + DSM_H_MIN)

    # ── 只留锚点所在的那一块，不把邻居与树算进来 ────────────────────
    #    ★ 不隔离的话，±R 里任何一栋楼都会把「屋盖外接」撑大，
    #      而屏幕上只是一个**偏大的数**，看不出来混进了别人。
    lab, n_lab = ndimage.label(mask)
    if n_lab == 0:
        return {"state": "no_blob", "path": meta["path"], "ground_m": round(ground, 3),
                "why": ("地面 +%.1f m 以上一个格都没有 ⇒ 这个窗口里没有可量的地物"
                        % DSM_H_MIN)}
    cy, cx = a.shape[0] // 2, a.shape[1] // 2
    mine = int(lab[cy, cx])
    anchor_pin = bool(mine)
    if not mine:
        # 锚点那一格不在任何一块上：退而取**质心离锚点最近**的那一块，
        # 但把这件事**说出来** —— 静默退成一个"最近"会让认亲无从核对。
        cents = ndimage.center_of_mass(mask, lab, range(1, n_lab + 1))
        dd = [math.hypot(cx - c[1], cy - c[0]) for c in cents]
        mine = int(np.argmin(dd)) + 1
        pin_d_m = float(min(dd)) * abs(meta["res"][0])
    else:
        pin_d_m = 0.0

    sel = lab == mine
    zc = a[sel]
    ec, nc = ee[sel], nn[sel]
    if zc.size < 8:
        return {"state": "no_blob", "path": meta["path"], "ground_m": round(ground, 3),
                "why": "锚点落在的那一块只有 %d 格，太小，量不出外形" % zc.size}

    med_z = float(np.median(zc))
    roof_z = float(np.percentile(zc, 95.0))
    flat = float((np.abs(zc - med_z) <= DSM_FLAT_TOL).mean())
    ext_e = float(ec.max() - ec.min())
    ext_n = float(nc.max() - nc.min())

    w_m, d_m = float(env["w_m"]), float(env["d_m"])
    cross = _cross_check(cfg, E, N)

    out: dict[str, Any] = {
        "state": "ok",
        "source": {
            "path": meta["path"], "epsg": meta["epsg"], "crs": meta["crs"],
            "res_m": round(abs(meta["res"][0]), 4),
            "bounds": [round(v, 1) for v in meta["bounds"]],
            "caliber": "2024 飞的实景烘出的地表高程栅格（DSM），EPSG:4544，取**顶面**",
        },
        "window_en": [round(E - R, 2), round(N - R, 2), round(E + R, 2), round(N + R, 2)],
        "radius_m": round(R, 1),
        "ground_m": round(ground, 3),
        "roof_m": round(roof_z, 3),
        "roof_med_m": round(med_z, 3),
        "h_m": round(roof_z - ground, 2),
        "flat": round(flat, 4),
        "n_cells": int(zc.size),
        "ext_e_m": round(ext_e, 2),
        "ext_n_m": round(ext_n, 2),
        "anchor_pin": anchor_pin,
        "anchor_pin_d_m": round(pin_d_m, 2),
        "model": {"w_m": round(w_m, 2), "d_m": round(d_m, 2),
                  "caliber": fp["caliber"]},
        "vs_model": {
            "over_e_m": round((ext_e - w_m) / 2.0, 2),
            "over_n_m": round((ext_n - d_m) / 2.0, 2),
        },
        "cross": cross,
        # ★ 这一句**必须**跟着数一起到页面上：它就是「这个差是不是缺陷」的判据。
        "caveat": (
            "实景外接量的是**檐口**不是墙（DSM 记顶面）⇒ 「实景 − 模型」这个差"
            "在**有挑檐**的楼上等于挑檐宽度，**不是**模型错了。"
            "总账 §5.2 已结案（2026-09-29 用户确认 c011 有挑檐）：c011 模型 61.8 m 是墙、"
            "实景 74.8 m 是檐口 —— 所以真正的缺陷是**模型里缺这一圈檐**，"
            "而这件事图纸上看不出来。地面与屋盖都取自同一张栅格，"
            "**高程基准自动抵消**，不必知道它存的是椭球高还是正常高。"),
    }
    return out


def site_image(cfg, name: str, half_m: float = DEFAULT_HALF_M,
               max_px: int = MAX_PX, overlay: bool = True) -> dict[str, Any]:
    """出「正射裁切 ⊕ 模型足迹」那一张图。

    返回 `{"state": ..., "png": bytes|None, ...}`。**三态**：
      · `ok`        —— 有锚点、出图成功
      · `no_anchor` —— 这栋没有落位锚点（`campus_outlines.json` 的 341 条 `poly_en`
                       也没有楼号，341 条里 `c\\d\\d\\d` 零命中 ⇒ 从那里也拿不到）
      · `failed`    —— 有锚点但出图失败，`why` 里带**服务端原话**
    """
    from PIL import ImageDraw

    fp = footprint(cfg, name)
    if fp is None:
        return {"state": "failed", "png": None, "reason": "no_floors",
                "why": "这栋楼没有 floors/floor*.json，取不到轮廓"}

    rec = anchor_one(cfg, name)
    if not rec:
        return {"state": "no_anchor", "png": None, "footprint": _fp_brief(fp),
                "why": ("这栋楼还没有落位锚点（%s 里没有 %s 这一行）。"
                        "配准是「外观检查」的第一道工序，没有它就算不出来 —— "
                        "不许拿一个手推的变换糊过去。" % (anchors_path(cfg).name, name))}

    E, N = float(rec["E"]), float(rec["N"])
    half = float(half_m)
    box = (E - half, N - half, E + half, N + half)

    try:
        img, meta = crop(cfg, box, max_px=max_px)
    except NoOrtho as exc:
        return {"state": "failed", "png": None, "reason": "no_ortho", "why": str(exc)}
    except Exception as exc:                    # noqa: BLE001
        return {"state": "failed", "png": None, "reason": "crop_failed",
                "why": "%s: %s" % (type(exc).__name__, exc)}

    # ── 把模型足迹按「自己的 bbox 中心 → 锚点」摆上去 ───────────────
    # ★ 这一步是**假设**（`_c011_ab.json` 自己写着「这是假设不是测量」），
    #   所以 `caveat` 一定要跟着数据一起回去，让页面上必须印它。
    b = fp["plan_bbox"]
    cx, cy = (b[0] + b[2]) / 2.0, (b[1] + b[3]) / 2.0
    rot = int(rec.get("rot_deg") or 0)
    mpp = meta["mpp"]
    wpx, hpx = meta["px"]

    def to_px(p):
        x, y = _rot((p[0] - cx, p[1] - cy), rot)
        return (wpx / 2.0 + x / mpp, hpx / 2.0 - y / mpp)     # 图上 y 向下

    if overlay:
        dr = ImageDraw.Draw(img)
        _draw_poly(dr, [to_px(p) for p in fp["plan"]], (255, 40, 40), width=2)
        # 锚点本身：一个小十字。它是「我们假设的那个中心」，不是测出来的物件。
        dr.line([(wpx / 2 - 9, hpx / 2), (wpx / 2 + 9, hpx / 2)], fill=(255, 235, 0), width=1)
        dr.line([(wpx / 2, hpx / 2 - 9), (wpx / 2, hpx / 2 + 9)], fill=(255, 235, 0), width=1)

    tr = rec.get("trace")
    metrics = None
    if tr:
        # 用户在正射上亲手框的那一栋（米）—— 有它才能给出「长宽差 / 面积比」。
        tw = abs(tr["E1"] - tr["E0"])
        td = abs(tr["N1"] - tr["N0"])
        metrics = {
            "trace": {"w_m": tw, "d_m": td, "area_m2": tw * td},
            "model": {"w_m": fp["envelope"]["w_m"], "d_m": fp["envelope"]["d_m"],
                      "area_m2": fp["envelope"]["w_m"] * fp["envelope"]["d_m"]},
            "why_no_iou": ("只有外接矩形能比。真 IoU 要拿正射上提取的**多边形**，"
                           "而阈值法在这个场景不稳（研究结论：只在高对比场景可靠）"),
        }
        if metrics["trace"]["area_m2"] > 0:
            metrics["ratio"] = round(
                metrics["model"]["area_m2"] / metrics["trace"]["area_m2"], 4)

    return {
        "state": "ok",
        "png": png_bytes(img),
        "window_en": meta["window_en"],
        "clipped": meta["clipped"],
        "px": meta["px"],
        "mpp": mpp,
        "stretch": meta["stretch"],
        "anchor": rec,
        "footprint": _fp_brief(fp),
        "metrics": metrics,
        # ★ 三维那一侧。它**不参与**出图（图是正射的二维叠合），
        #   所以它是**加法**：出图失败与否与它无关，它失败也不该把图带塌。
        #   两件事各自有三态，不许合并成一个「校核失败」。
        "relief": relief(cfg, name, rec, fp, half_m=half_m),
        "caveat": ("模型是按「自己的轮廓 bbox 中心 = 锚点」摆的 —— 这是**假设不是测量**"
                   "（原文见 _scratch/_c011_ab.json 的 caveat）。"
                   "朝向由锚点的 rot_deg 决定，它是某人某时刻选定的，不是量出来的。"
                   "图上若出现 90°/镜像，先怀疑这一条。"),
    }


def _fp_brief(fp: dict[str, Any]) -> dict[str, Any]:
    return {
        "n_pts": len(fp["plan"]),
        "n_floors": fp["n_floors"],
        "plan_area_m2": round(fp["plan_area_m2"], 1),
        "w_m": round(fp["envelope"]["w_m"], 2),
        "d_m": round(fp["envelope"]["d_m"], 2),
        "caliber": fp["caliber"],
    }


# ────────────────────────────────────────────────────────────────
# 全库清单（哪些楼能校核、哪些不能、为什么）
# ────────────────────────────────────────────────────────────────

def manifest(cfg, names: list[str]) -> dict[str, Any]:
    """逐栋三态。★ **三档分开计数**，不许合成一个「可校核 N 栋」了事。

    先把 `no_anchor` 与 `failed` 分开，是因为它们的下一步动作相反：
      前者要人去点一个锚点，后者是**我们的**管道坏了。
    """
    items, n_ok, n_no, n_fail = [], 0, 0, 0
    ortho_ok, ortho_why = True, None
    try:
        om = ortho_meta(cfg)
    except NoOrtho as exc:
        ortho_ok, ortho_why = False, str(exc)
        om = None

    for n in names:
        rec = anchor_one(cfg, n)
        has_fp = (cfg.root / "data" / "buildings" / n / "floors").is_dir()
        if not ortho_ok:
            st, why = "failed", ortho_why
        elif not has_fp:
            st, why = "failed", "没有 floors/floor*.json"
        elif not rec:
            st, why = "no_anchor", "还没有落位锚点"
        else:
            st, why = "ok", None
        if st == "ok":
            n_ok += 1
        elif st == "no_anchor":
            n_no += 1
        else:
            n_fail += 1
        items.append({"name": n, "state": st, "why": why,
                      "E": (rec or {}).get("E"), "N": (rec or {}).get("N"),
                      "src": (rec or {}).get("src"), "rot_deg": (rec or {}).get("rot_deg")})

    return {
        "criterion_version": CRITERION_VERSION,
        "ortho": om,
        "ortho_ok": ortho_ok,
        "items": items,
        "counts": {"total": len(names), "ok": n_ok, "no_anchor": n_no, "failed": n_fail},
        "campus_box": None if not om else _campus_box(cfg),
    }


def _campus_box(cfg) -> dict[str, Any]:
    """校区的 4544 范围 —— 首页用来出那张「整校区鸟瞰」底图（还没锚定时点位置用）。

    ★ 这里**不**用正射自己的 bounds（它 2222 × 2906 m，是整个航摄区），
      而是用 `campus_outlines.json` 里 341 条实测轮廓的 bbox 再外扩一点 ——
      那张图才是「我们要看的那片校区」。两者差多少，页面上会印出来。
    """
    p = cfg.root / "_scratch" / "_campus3d" / "campus-terrain" / "campus_outlines.json"
    if not p.is_file():
        return {}
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
        b = d.get("bbox_en") or {}
        return {"e0": b.get("e0"), "n0": b.get("n0"), "e1": b.get("e1"), "n1": b.get("n1"),
                "n_outlines": (d.get("counts") or {}).get("outlines"),
                "source": str(p)}
    except Exception:                           # noqa: BLE001
        return {}
