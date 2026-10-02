# -*- coding: utf-8 -*-
"""外业校核数据域的路由（无人机正射 ↔ 建好的模型）。

★ **本文件名不许叫 `site.py`**（2026-10-02 实测踩过一次，建 app 时当场炸）：

  `main.create_app()` 里有一行 `site = cfg.root / "frontend" / "site"`
  —— **一个局部变量**。它是函数局部名 ⇒ Python 把整个 `create_app` 里的 `site`
  都当成那个局部名，于是 `app.include_router(site.router, ...)` 报

      UnboundLocalError: cannot access local variable 'site'
      where it is not associated with a value

  症状是**建 app 时**炸（响的，好）；但它属于「别用全局构造器的名字给变量命名」
  那一族（铁律 011），而 `site` 更是 Python 的**内置模块名**。
  ⇒ 换个名字比加一句 alias 干净：alias 只是让这一处不再撞，别的函数再写一句
  `import site` 就又撞上了，而那时它是**静默拿到标准库的那个 site**。
  （本仓 memory `fracture-docset-pipeline` 里那条「模块名不许叫 `site.py`」同源。）

四条：两条 GET 只读（不挂 `ComputeDep`）、一条 GET 出图（只读）、一条 **POST 写锚点**
（挂 `ComputeDep` + `require_cap("manage")`，两条**叠加**：执行面闸答"这台进程许不许跑"，
权限面闸答"这个人许不许"）。

★ 出图为什么是**两条**路由（一条 JSON、一条 PNG），而不是一条带 header 的：

  `GET /site/{name}/check` 回 JSON —— 它回答「**这栋能不能校核**」这一个问题，
  三态（`ok` / `no_anchor` / `failed`）就在这个 JSON 里。
  `GET /site/{name}/ortho.png` 只回字节。

  这么分是为了让「无锚点」**结构上不可能**被画成一张空图：
  页面先拿 JSON，`state !== "ok"` 时它**根本不会去设 `<img src>`**，
  而不是"设了 src、图 404、`onerror` 里再补救" ——
  `frontend/admin/js/views/compare.js` 的文件头正好记着这一类坑：
  「404 与 409 在 `onerror` 下分不开」。**顺序就是正确性**，这里是它第二次出现。

★ 权限按域分派：这一域**不在** `deps.CAP_PLANE_PREFIXES` 里 ⇒ 写路由必须挂
  `ComputeDep`，否则 `deps.assert_writes_gated` 会在**启动时**拒绝启动（响的）。
  ⇒ 后果要写下来：`GYM3D_COMPUTE=0` 的只读服务器上，**写锚点会 403
  `compute_disabled`**。那是**对的**（服务器按设计只读；锚点由本机控制台写），
  但页面上必须把这句话原样显示，不许退回成"保存失败"。
"""
from __future__ import annotations

import json
import time

from fastapi import APIRouter, Depends, Query, Response

from ..authz import require_cap
from ..deps import BuildingName, ComputeDep, SettingsDep
from ..responses import ApiError, bad_request, not_found, ok
from ..services import annotations as ann
from ..services import artifacts, shapeaudit, sitecheck

router = APIRouter(tags=["site"], dependencies=[Depends(require_cap("view"))])

MANAGE = [Depends(require_cap("manage"))]

# 出图的内存缓存。★ 键里**必须**带锚点表的 mtime：锚点挪了 5 m 而进程还发着旧图，
# 屏幕上是一张「位置对得上」的图（铁律 022：配置只活在进程内存里 ⇒ 迟早丢且不报错）。
_PNG_CACHE: dict[tuple, tuple[float, bytes, dict]] = {}
_PNG_CACHE_MAX = 24


def _anc_mtime(cfg) -> float:
    p = sitecheck.anchors_path(cfg)
    return p.stat().st_mtime if p.is_file() else 0.0


def _state_error(res: dict):
    """三态 → HTTP。★ 三件事的下一步动作不同，所以**不许合成一个码**：

    · `no_anchor` ⇒ **404**：调用方要的那栋没有锚点 —— 下一步是**去点一个锚点**。
    · `no_floors` ⇒ **404**：这栋楼盘上就没有 `floors/floor*.json` —— 下一步是查数据。
    · `no_ortho` / `crop_failed` ⇒ **500**：**我们的**管道坏了 —— 下一步是修服务端。
    """
    st = res.get("state")
    why = res.get("why") or ""
    detail = {"state": st, "reason": res.get("reason"),
              "anchors_file": res.get("anchors_path")}
    if st == "no_anchor":
        # 404：调用方要的那栋没有锚点。detail 里带上**锚点表在哪**，
        # 否则读的人只知道"做不了"，不知道去哪把它补上（铁律 166④）。
        raise ApiError(404, "no_anchor", why, detail)
    if res.get("reason") == "no_floors":
        raise not_found(why, **detail)
    raise ApiError(500, "site_broken", why, detail)


@router.get("/site/manifest")
def site_manifest(cfg: SettingsDep) -> dict:
    """全校区：**逐栋三态** + 三档分开的计数。

    ★ 楼栋名单**只从 `artifacts.list_buildings()` 取一处**，不自己 glob 第二遍。
      两处名单迟早会不一样，而"哪一处漏了一栋"在屏幕上只是一个数（铁律 18/084）。

    ★ 三档分开计数、**不合成一个**「可校核 N 栋」：`no_anchor`（要人去点）与
      `failed`（我们的管道坏了）下一步动作相反，加起来就看不出来了。
    """
    # ★ 必须是 `resolved_data_dir`，不是 `data_dir`：后者是 `Path | None`，
    #   默认值是 **None**（真实值由 computed 属性补出来，见 settings.py:149）。
    #   传 None 进去不会当场报错 —— 它一路走到 `None / "buildings"` 才炸，
    #   而那已经是**请求处理里面**了（本仓另一处也是这么写的：buildings.py:66）。
    rows = artifacts.list_buildings(cfg.resolved_data_dir)
    names = [r["name"] for r in rows]
    man = sitecheck.manifest(cfg, names)
    title = {r["name"]: r.get("title") for r in rows}
    for it in man["items"]:
        it["title"] = title.get(it["name"]) or it["name"]
    man["anchors_file"] = str(sitecheck.anchors_path(cfg))
    return ok(man)


def _buildings_signature(cfg) -> tuple:
    """`data/buildings/` 下每一栋的目录 mtime，作为稽核结果的**失效指纹**。

    ★ 为什么用目录 mtime 而不是「进程启动时刻」或一个 TTL：铁律 022 ——
      配置只活在进程内存里 ⇒ 迟早丢、而且丢了不报错。
      GLB 被重出 ⇒ `data/buildings/<n>/` 的 mtime 变；`floors/*.json` 被就地改写
      ⇒ `floors/` 的 mtime 变。两个都在指纹里，所以**重出模型之后这一页立刻跟着变**。
      （已知盲区：只改文件内容而不改目录 mtime 的写法抓不到 —— 本仓的写盘都是
       建/删/改名，不是就地改写。）
    """
    bdir = cfg.resolved_data_dir / "buildings"
    if not bdir.is_dir():
        return ()
    out = []
    for p in sorted(bdir.iterdir()):
        if not p.is_dir():
            continue
        try:
            fl = (p / "floors").stat().st_mtime
        except OSError:
            fl = 0.0
        try:
            out.append((p.name, int(p.stat().st_mtime), int(fl)))
        except OSError:
            out.append((p.name, 0, int(fl)))
    return tuple(out)


_SHAPE_CACHE: dict[tuple, dict] = {}


@router.get("/site/shape-audit")
def site_shape_audit(cfg: SettingsDep) -> dict:
    """全库「模型竖向自洽」稽核 —— **逐栋一条可判的差**，给首页第三模式用。

    ★ 这一条**只读**，所以不挂 `ComputeDep`：它不写盘、不依赖执行面，
      `GYM3D_COMPUTE=0` 的只读服务器上照样该能看。

    ★ 楼栋名单**仍然只从 `artifacts.list_buildings()` 取那一处**（与 `/site/manifest`
      同源）—— 两处名单迟早会不一样，而"哪一处漏了一栋"在屏幕上只是一个数。

    ★ 这一层量的是**模型自己自洽不自洽**，不是模型对不对：两边一起错它照样全绿。
      这句话在 `caveat` 里原样回给页面，必须显示出来。
    """
    rows = artifacts.list_buildings(cfg.resolved_data_dir)
    names = [r["name"] for r in rows]
    sig = _buildings_signature(cfg)
    key = (sig, tuple(names))
    hit = _SHAPE_CACHE.get(key)
    # ★ `cached` 必须是**这一趟真的发生了什么**，不许写成常数：
    #   `bool(x and False) or False` 这种式子恒为 False，而它印出来像一个读数
    #   （铁律 146：判词写成常量字符串 ⇒ 被测对象改好之后那张「已坏」还在屏幕上）。
    cached = hit is not None
    if hit is None:
        title = {r["name"]: r.get("title") for r in rows}
        hit = shapeaudit.audit(cfg, names, title)
        _SHAPE_CACHE.clear()          # 只留最新一份：这是一张全库快照，留旧的没有意义
        _SHAPE_CACHE[key] = hit
    return ok(hit, meta={"cached": cached, "signature_n": len(sig)})


def _site_result(cfg, name: str, half: float, px: int, overlay: bool) -> dict:
    # ★ 键里**两个 mtime 都要有**：锚点表挪了 5 m、或高程栅格被重烤过，
    #   而进程还在发上一趟的偏差 —— 屏幕上是一组「像结论」的数（铁律 022）。
    key = (name, round(float(half), 3), int(px), bool(overlay),
           _anc_mtime(cfg), sitecheck.dsm_mtime(cfg))
    hit = _PNG_CACHE.get(key)
    if hit is not None:
        res = dict(hit[2])
        res["png"] = hit[1]
        res["_ms"] = 0.0
        res["_cached"] = True
        return res

    t0 = time.perf_counter()
    res = sitecheck.site_image(cfg, name, half_m=half, max_px=px, overlay=overlay)
    res["_ms"] = round((time.perf_counter() - t0) * 1000.0, 1)
    res["_cached"] = False
    if res.get("state") == "ok":
        if len(_PNG_CACHE) >= _PNG_CACHE_MAX:
            _PNG_CACHE.pop(next(iter(_PNG_CACHE)))
        _PNG_CACHE[key] = (time.time(), res["png"], {k: v for k, v in res.items() if k != "png"})
    return res


@router.get("/site/{name}/check")
def site_check(name: BuildingName, cfg: SettingsDep,
               half: float = Query(80.0, ge=10.0, le=400.0),
               px: int = Query(sitecheck.MAX_PX, ge=256, le=2048),
               overlay: bool = Query(True)) -> dict:
    """「这栋能不能校核」—— **三态都在这个 JSON 里**，图另外取。"""
    res = _site_result(cfg, name, half, px, overlay)
    if res.get("state") != "ok":
        _state_error({**res, "anchors_path": str(sitecheck.anchors_path(cfg))})
    out = {k: v for k, v in res.items() if k not in ("png",)}
    out["png_url"] = "/api/site/%s/ortho.png?half=%g&px=%d&overlay=%d" % (
        name, half, px, 1 if overlay else 0)
    return ok(out)


@router.get("/site/{name}/ortho.png")
def site_ortho(name: BuildingName, cfg: SettingsDep,
               half: float = Query(80.0, ge=10.0, le=400.0),
               px: int = Query(sitecheck.MAX_PX, ge=256, le=2048),
               overlay: bool = Query(True)):
    """正射裁切 ⊕ 模型足迹。像素尺寸/比例尺回在**响应头**，便于当场核。"""
    res = _site_result(cfg, name, half, px, overlay)
    if res.get("state") != "ok":
        _state_error({**res, "anchors_path": str(sitecheck.anchors_path(cfg))})
    h = {
        # ★ 这三个头是给**核**用的，不是给页面用的（页面读 JSON）。
        #   判据：拿 Content-Length 与 X-Gym3d-Px 反推出的 m/px，必须与请求的 half 对得上。
        "X-Gym3d-Px": "%dx%d" % tuple(res["px"]),
        "X-Gym3d-Mpp": "%.6f" % res["mpp"],
        "X-Gym3d-Window": ",".join("%.2f" % v for v in res["window_en"]),
        "X-Gym3d-Ms": "%.1f" % res["_ms"],
        "X-Gym3d-Clip": "1" if res["clipped"] else "0",
        "Cache-Control": "no-store",
    }
    return Response(content=res["png"], media_type="image/png", headers=h)


@router.post("/site/anchors/{name}", dependencies=MANAGE)
def site_put_anchor(name: BuildingName, obj: dict, cfg: ComputeDep,
                    replace: bool = Query(False)) -> dict:
    """写一条落位锚点（**写操作**：挂 `ComputeDep`，只写 `data/_meta/site_anchors.json`）。

    ★ 只增不改：同名已存在且没带 `?replace=1` ⇒ **409 并点名**（不静默覆盖）。
      锚点是人一处一处攒出来的，静默覆盖等于把别人的工作抹了，而屏幕上写着"成功"。
    """
    for k in ("E", "N"):
        if k not in obj:
            raise bad_request("锚点必须有 %s（EPSG:4544，米）" % k)
    try:
        rec = sitecheck.anchors_put(cfg, name, obj, replace=bool(replace))
    except FileExistsError:
        raise ApiError(409, "anchor_exists",
                       "%s 已经有锚点了。要改得显式带 ?replace=1 —— "
                       "静默覆盖会让「我改了」和「我什么也没做」在屏幕上一样。"
                       % name, {"name": name})
    except (ValueError, TypeError) as exc:
        raise bad_request(str(exc), name=name)
    return ok(rec, meta={"file": str(sitecheck.anchors_path(cfg))})


# ────────────────────────────────────────────────────────────────
# 人工标注（左屏圈问题）
# ────────────────────────────────────────────────────────────────

@router.get("/annotations")
def ann_list(cfg: SettingsDep, building: str = "", f: str = "") -> dict:
    """读标注。**沿用 `_qa/annotations.json` 的既有形状**，一个字段都不加。"""
    try:
        items = ann.load(cfg)
    except ann.BadStore as exc:
        # ★ 坏文件**不回空数组**：那会让「30 条全丢了」看起来像「还没人标过」。
        raise ApiError(500, "annotations_unreadable", str(exc))
    if building:
        items = [r for r in items if str(r.get("building")) == building]
    if f != "":
        items = [r for r in items if str(r.get("f")) == str(f)]
    return ok({"items": items, "n": len(items),
               "types": [{"key": k, "label": v} for k, v in ann.TYPES],
               "kinds": list(ann.KINDS)},
              meta={"file": str(ann.store_path(cfg))})


@router.post("/annotations", dependencies=MANAGE)
def ann_add(rec: dict, cfg: ComputeDep) -> dict:
    """加一条人工标注（**写操作**，故挂 `ComputeDep`）。

    ★ 落到**同一个** `_qa/annotations.json`、**同一套**原子写、**同一个** `indent=2`。
      另开一个新库会让「我这页看到的」和「8150 标注台看到的」不是同一批 ——
      而那种分叉在屏幕上只表现为"那边少标了几条"，看着像人偷懒。
    """
    try:
        item = ann.append(cfg, rec)
    except ann.BadStore as exc:
        raise ApiError(500, "annotations_unreadable", str(exc))
    except ValueError as exc:
        raise bad_request(str(exc))
    return ok(item, meta={"file": str(ann.store_path(cfg))})


@router.get("/annotations/summary")
def ann_summary(cfg: SettingsDep) -> dict:
    """「是不是通用问题」—— **两个轴各自聚合、并排摆、绝不相加**（见 §why_not_merged）。"""
    try:
        return ok(ann.summary(cfg))
    except ann.BadStore as exc:
        raise ApiError(500, "annotations_unreadable", str(exc))
