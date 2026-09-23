# -*- coding: utf-8 -*-
"""建模产物索引 —— 「哪些楼、每栋有什么、在磁盘哪儿」。

**硬约束：本模块只 import 标准库。**

不是洁癖：只服务模式（服务器上 GYM3D_COMPUTE=0）的第一道防线是
「服务器 venv 里根本没有 ezdxf/shapely/trimesh」。如果读一栋楼的楼层摘要
需要 import ezdxf，那道防线就废了 —— 服务器为了「能看」被迫装全套重依赖，
于是它也就「能算」了。所以这里只做文件系统与 JSON：
磁盘上有什么就报什么，缺什么就说缺（`exists: false`），绝不临场重算。

磁盘布局（一栋楼一个目录，`data/buildings/<name>/`）：

    profile.json            识别参数（本楼的"配方"）
    spec.json               建模规格（墙厚/层高/门窗尺寸）
    rooms.json              房间台账（全局 id 段）
    floors/floor{F}.json     逐层交付几何 ← 前端看的就是它
    dxf_plan_fast/floor{F}.png   CAD 忠实渲染（原图长什么样）
    dxf_plan_recog/floor{F}.png  识别结果叠加图（认成了什么样，49 栋有）
    plans/floor{F}.png           另一套渲染（49 栋有）
    <name>-building.glb      三维模型
"""
from __future__ import annotations

import json
import os
import re
import threading
from pathlib import Path
from typing import Any, Iterable

from ..responses import ApiError, not_found

# ── 可寻址的楼号 ──────────────────────────────────────────────────
# 与 deps.BuildingName 的 pattern 保持一致；这里是第二道（也是最后一道）：
# 任何拼路径之前都要过 _safe_name，哪怕调用方已经过 FastAPI 校验。
_NAME_RE = re.compile(r"^[A-Za-z0-9_-]{1,32}$")

# profile.json 里**不回给前端**的键：
#   dxf —— 绝对路径（D:\dxf_output\C113-艺术楼.dxf）。回它等于把本机目录结构
#          写到响应里；前端要的只是"有没有、叫什么名字"，那是 dxf_name 的事。
#          这是本条模块唯一的"select"：不回整个对象，回白名单。
_PROFILE_OMIT = frozenset({"dxf", "out_dir"})

# 逐层图三种来源，按可信度排序（前者没有就退后者，并在 meta 里说明用的是哪套）。
PLAN_SOURCES = (
    ("dxf_plan_recog", "识别结果图"),
    ("plans", "平面图"),
    ("dxf_plan", "平面图(旧)"),
)
CAD_DIR, CAD_LABEL = "dxf_plan_fast", "CAD 原图"

# ★「逐层图纸文件叫什么名」只能有**一处**写法。
#   盘上找文件、URL 里拼路径、路由校验允许的名字 —— 这三处必须同源。
#   它们原来是三份各写各的（盘上 `floor%d.png`、URL 里 `%d.png`、
#   路由正则 `floor(\d{1,2})\.png`），于是 `/api/buildings/<楼>/floors` 回的
#   `cad.url` / `plan.url` 拿去请求**永远是 400**：字段长得对，路径是错的。
#   这个洞不报错，只会让"照着接口字段写"的前端静默拿不到图
#   （memory: one-judgement-many-implementations）。
FLOOR_PNG_RE = r"^floor(\d{1,2})\.png$"


def floor_png_name(F: int) -> str:
    """逐层图在盘上和在 URL 里的同一个文件名。两边都从这一处取。"""
    return "floor%d.png" % F

# 缓存：文件 mtime 变了就重读。95 栋 × 逐层读 JSON 不做缓存的话，
# 一次 /api/buildings 要开上千个文件。
_CACHE: dict[str, tuple[Any, Any]] = {}
_CACHE_LOCK = threading.Lock()


def _cached(key: str, sig: Any, make) -> Any:
    """sig 是"这份缓存代表的磁盘状态"（mtime_ns + size）。变了就重算。

    为什么带 mtime 而不是永久缓存：本项目交付件会被重跑覆盖
    （改了 rooms.json 就要 backfill floors），永久缓存会让后台显示上一版，
    而且这种陈旧**没有报错**——正是本项目吃过多次的坑（见 memory:
    delivery-glb-content-staleness）。mtime 变化是最便宜的失效信号。
    """
    with _CACHE_LOCK:
        hit = _CACHE.get(key)
        if hit is not None and hit[0] == sig:
            return hit[1]
    val = make()
    with _CACHE_LOCK:
        _CACHE[key] = (sig, val)
    return val


def _sig(*paths: Path) -> tuple:
    out = []
    for p in paths:
        try:
            st = p.stat()
            out.append((p.name, st.st_mtime_ns, st.st_size))
        except OSError:
            out.append((p.name, None, None))
    return tuple(out)


def _dir_sig(d: Path, pattern: str) -> tuple:
    """一个目录里所有匹配文件的指纹。

    ★ 必须让缓存键**覆盖被缓存的值真正读到的每一份文件**。
    `_building_row` 除 profile/rooms 外还读 floors/*.json 算面积；
    只把 profile+rooms 放进键，就会出现「改了 floors、后台还显示旧面积」
    而且**不报错**。本项目栽过同类（memory: cache-key-must-cover-the-judge）。
    """
    if not d.is_dir():
        return ()
    return tuple(sorted((p.name, p.stat().st_mtime_ns, p.stat().st_size)
                        for p in d.glob(pattern) if p.is_file()))


# ── 基本路径 ──────────────────────────────────────────────────────

def buildings_dir(data_dir: Path) -> Path:
    return data_dir / "buildings"


def _safe_name(name: str) -> str:
    if not _NAME_RE.match(name or ""):
        # 走到这里说明调用方绕过了 FastAPI 的 Path(pattern=...) 校验。
        # 明确地拒绝，而不是让 "/" 之后的部分悄悄拼进路径。
        raise ApiError(400, "bad_building_name",
                       "楼号只允许字母/数字/下划线/短横线：%r" % (name,))
    return name


def building_dir(data_dir: Path, name: str) -> Path:
    return buildings_dir(data_dir) / _safe_name(name)


def require_building(data_dir: Path, name: str) -> Path:
    d = building_dir(data_dir, name)
    if not (d / "profile.json").is_file():
        raise not_found("没有这栋楼：%s" % name, building=name)
    return d


def read_json(path: Path) -> Any:
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except FileNotFoundError:
        raise not_found("产物不存在：%s" % path.name, file=path.name) from None
    except json.JSONDecodeError as ex:
        # 空/截断的 JSON 是本项目真实发生过的故障（原子写之前的 json.dump
        # 直写会留 0 字节文件）。这里把"文件在但读不了"与"文件不在"分开报，
        # 否则又变成"量具坏了和对象是空的长得一样"。
        raise ApiError(500, "artifact_corrupt",
                       "产物损坏（JSON 解析失败）：%s" % path.name,
                       {"file": path.name, "error": str(ex)}) from ex


def _exists_url(d: Path, url: str, label: str) -> dict:
    p = d
    ok = p.is_file()
    return {"label": label, "url": url if ok else None, "exists": ok,
            "bytes": (p.stat().st_size if ok else 0)}


# ── 楼栋列表 ──────────────────────────────────────────────────────

def list_buildings(data_dir: Path) -> list[dict]:
    """全部楼栋 + 一句摘要。按楼号排序（c001…c115、ny27…）。"""
    root = buildings_dir(data_dir)
    if not root.is_dir():
        return []
    names = sorted(d.name for d in root.iterdir()
                   if d.is_dir() and (d / "profile.json").is_file())
    return [_cached("bld:" + n,
                    _sig(root / n / "profile.json", root / n / "rooms.json")
                    + _dir_sig(root / n / "floors", "floor*.json"),
                    lambda n=n: _building_row(root / n)) for n in names]


def _building_row(d: Path) -> dict:
    name = d.name
    cfg = read_json(d / "profile.json")
    floors = _floor_indices(d)
    rooms = read_json(d / "rooms.json") if (d / "rooms.json").is_file() else []
    glb = d / ("%s-building.glb" % name)
    return {
        "name": name,
        "title": cfg.get("title") or name,
        "floors": floors,
        "floor_count": len(floors),
        "rooms": len(rooms) if isinstance(rooms, list) else 0,
        # 交付楼板面积（各层 outline 面积之和，单位㎡）—— 与图纸面积表是两个口径，
        # 前端要并排显示时必须各自标名，别混成一个数（见 component_library.GAUGES）。
        "outline_area_m2": _outline_total(d, floors),
        "has_model": glb.is_file(),
        "has_cad": (d / CAD_DIR).is_dir(),
        "plan_source": _plan_source(d)[0],
        "classifier": cfg.get("classifier") or "(默认 lwpolyline)",
        "layer_height": cfg.get("layer_height"),
        "style": cfg.get("style") or {},
        "notes": sorted(k for k in cfg if k.startswith("_note")),
    }


def _outline_total(d: Path, floors: Iterable[int]) -> float:
    tot = 0.0
    for F in floors:
        try:
            g = read_json(d / "floors" / ("floor%d.json" % F))
        except ApiError:
            continue
        tot += _shoelace(g.get("outline") or [])
    return round(tot, 1)


def _shoelace(ring: list) -> float:
    """鞋带公式取**绝对**面积。不扣洞 —— 这是"足迹"，不是"净面积"。

    刻意不做 buffer(0) 清洗：那要 import shapely，本模块的硬约束就是不要它。
    自交环在这里会偏，但只用它排序/量级，判缺陷请用面积对账页（图纸自带表）。
    """
    n = len(ring)
    if n < 3:
        return 0.0
    s = 0.0
    for i in range(n):
        x1, y1 = ring[i][0], ring[i][1]
        x2, y2 = ring[(i + 1) % n][0], ring[(i + 1) % n][1]
        s += x1 * y2 - x2 * y1
    return abs(s) / 2.0


# ── 单栋详情 ──────────────────────────────────────────────────────

def profile_public(data_dir: Path, name: str) -> dict:
    d = require_building(data_dir, name)
    raw = read_json(d / "profile.json")
    out = {k: v for k, v in raw.items() if k not in _PROFILE_OMIT}
    dxf = raw.get("dxf")
    # 只回文件名，不回路径：前端要显示的是"C113-艺术楼.dxf"，
    # 不是"这台机器把它放在哪个盘"。
    out["dxf_name"] = Path(dxf).name if dxf else None
    out["dxf_present"] = bool(dxf and os.path.isfile(dxf))
    return out


def floors_summary(data_dir: Path, name: str) -> list[dict]:
    d = require_building(data_dir, name)
    out = []
    for F in _floor_indices(d):
        g = read_json(d / "floors" / ("floor%d.json" % F))
        rooms = g.get("rooms") or []
        out.append({
            "floor": F,
            "layer_height": g.get("layer_height"),
            "outline_area_m2": round(_shoelace(g.get("outline") or []), 1),
            "rooms": len(rooms),
            # ★ 房间面积从 `poly` **现算**。原来读的是 `r["area_m2"]` —— 全库 9768 条
            #   房间条目（95 栋每一层）**一条都没有这个键**：产物写的是 `poly`。
            #   于是这个数在**全库每一层都是 0.0**，前台显示成"房间面积 0 ㎡"，
            #   看着像"这栋楼没量到面积"。一个永远为 0 的显示值比不显示更坏。
            #   `area_m2` 若存在就先用它（别的生产者可能会写），否则按 poly 算。
            #   注意这是**足迹**不是净面积（不扣洞），跟 outline_area_m2 同口径。
            "rooms_area_m2": round(sum(float(r.get("area_m2")
                                             or _shoelace(r.get("poly") or []))
                                       for r in rooms), 1),
            "counts": {k: len(g.get(k) or []) for k in
                       ("walls", "windows", "columns", "doors",
                        "elevators", "stairs", "stairwells", "outline_parts")},
            "cad": _exists_url(d / CAD_DIR / floor_png_name(F),
                               _url(name, "cad", F), CAD_LABEL),
            "plan": _plan_entry(d, name, F),
            "json": _url(name, "floor-json", F),
        })
    return out


def floor_full(data_dir: Path, name: str, F: int) -> dict:
    d = require_building(data_dir, name)
    return read_json(_floor_path(d, name, F))


def rooms(data_dir: Path, name: str) -> list:
    require_building(data_dir, name)
    p = building_dir(data_dir, name) / "rooms.json"
    if not p.is_file():
        return []
    r = read_json(p)
    return r if isinstance(r, list) else []


def spec(data_dir: Path, name: str) -> dict:
    d = require_building(data_dir, name)
    return read_json(d / "spec.json") if (d / "spec.json").is_file() else {}


def _floor_indices(d: Path) -> list[int]:
    fd = d / "floors"
    if not fd.is_dir():
        return []
    return sorted(int(m.group(1)) for m in
                  (re.match(r"floor(\d+)\.json$", p.name) for p in fd.iterdir())
                  if m)


def _floor_path(d: Path, name: str, F: int) -> Path:
    p = d / "floors" / ("floor%d.json" % F)
    if not p.is_file():
        raise not_found("%s 没有 F%d 这一层" % (name, F),
                        building=name, floor=F)
    return p


def _plan_source(d: Path) -> tuple[str, str]:
    for sub, label in PLAN_SOURCES:
        if (d / sub).is_dir() and any((d / sub).glob("floor*.png")):
            return sub, label
    return "", ""


def _plan_entry(d: Path, name: str, F: int) -> dict:
    sub, label = _plan_source(d)
    if not sub:
        return {"label": "无", "url": None, "exists": False, "bytes": 0,
                "source": None}
    e = _exists_url(d / sub / floor_png_name(F), _url(name, "plan", F), label)
    e["source"] = sub
    return e


# ── 二进制产物（PNG / GLB / DXF）────────────────────────────────────

def resolve_binary(data_dir: Path, name: str, kind: str, F: int | None = None
                   ) -> tuple[Path, str]:
    """把 (kind, F) 解析成一个真实文件 + 响应用的 media type。

    只认这张白名单表 —— 前端传什么都不可能读到白名单外的文件。
    返回 FileResponse 的那个 handler 负责流式发送（GLB 有 2.3GB，
    绝不能 read_bytes 进内存）。
    """
    d = require_building(data_dir, name)
    if kind == "cad":
        sub, label, mt = CAD_DIR, CAD_LABEL, "image/png"
    elif kind == "plan":
        sub, label, mt = _plan_source(d), None, "image/png"
        sub = sub[0]
        if not sub:
            raise not_found("%s 没有识别结果图" % name, building=name, kind=kind)
    elif kind == "model":
        p = d / ("%s-building.glb" % name)
        if not p.is_file():
            raise not_found("%s 没有三维模型" % name, building=name)
        return p, "model/gltf-binary"
    elif kind == "dxf":
        cfg = read_json(d / "profile.json")
        raw = cfg.get("dxf")
        p = Path(raw) if raw else None
        # 服务器上源 DXF 目录留空（GYM3D_DXF_DIR 不配）⇒ 这里明确说"本机没有"，
        # 而不是回一个 0 字节下载（那看起来像文件坏了）。
        if not p or not p.is_file():
            raise not_found("本进程拿不到源 DXF（源图目录可能未配置在所部署的机器上）",
                            building=name)
        return p, "application/dxf"
    else:
        raise ApiError(400, "bad_artifact_kind", "未知产物类型：%r" % kind)

    if F is None:
        raise ApiError(400, "floor_required", "%s 需要指定楼层" % kind)
    p = d / sub / ("floor%d.png" % F)
    if not p.is_file():
        raise not_found("%s 的 %s 缺 F%d" % (name, label or sub, F),
                        building=name, floor=F, kind=kind, source=sub)
    return p, mt


def inventory(data_dir: Path, name: str) -> list[dict]:
    """一栋楼的产物清单 —— 后台"这条链走到哪一步了"那一屏。"""
    d = require_building(data_dir, name)
    sub, plan_label = _plan_source(d)
    glb = d / ("%s-building.glb" % name)
    rows = [
        {"key": "profile", "label": "识别参数 profile.json", "exists": True,
         "bytes": (d / "profile.json").stat().st_size,
         "url": _url(name, "profile")},
        {"key": "spec", "label": "建模规格 spec.json",
         "exists": (d / "spec.json").is_file(),
         "bytes": ((d / "spec.json").stat().st_size
                   if (d / "spec.json").is_file() else 0),
         "url": _url(name, "spec")},
        {"key": "rooms", "label": "房间台账 rooms.json",
         "exists": (d / "rooms.json").is_file(),
         "bytes": ((d / "rooms.json").stat().st_size
                   if (d / "rooms.json").is_file() else 0),
         "url": _url(name, "rooms")},
        {"key": "floors", "label": "逐层交付几何 floors/", "exists": True,
         "count": len(_floor_indices(d)), "url": _url(name, "floors")},
        {"key": "cad", "label": "CAD 原图（逐层）",
         "exists": (d / CAD_DIR).is_dir(),
         "count": len(list((d / CAD_DIR).glob("floor*.png")))
         if (d / CAD_DIR).is_dir() else 0,
         "url": _url(name, "cad", 0) if (d / CAD_DIR).is_dir() else None},
        {"key": "plan", "label": plan_label or "识别结果图", "exists": bool(sub),
         "count": len(list((d / sub).glob("floor*.png"))) if sub else 0,
         "url": _url(name, "plan", 0) if sub else None, "source": sub or None},
        {"key": "model", "label": "三维模型 GLB", "exists": glb.is_file(),
         "bytes": glb.stat().st_size if glb.is_file() else 0,
         "url": _url(name, "model") if glb.is_file() else None},
    ]
    return rows


def _url(name: str, kind: str, F: int | None = None) -> str:
    base = "/api/buildings/%s" % name
    if kind == "cad":
        return "%s/cad/%s" % (base, floor_png_name(F))
    if kind == "plan":
        return "%s/plan/%s" % (base, floor_png_name(F))
    if kind == "model":
        return "%s/model.glb" % base
    if kind == "dxf":
        return "%s/source.dxf" % base
    if kind == "floor-json":
        return "%s/floors/%d" % (base, F)
    return "%s/%s" % (base, kind)
