# -*- coding: utf-8 -*-
"""影像比对数据域：高德卫星 ↔ 本机照片 —— 配对是**算出来的**，不是人工摆的。

照片的 EXIF GPS 是 WGS-84，高德瓦片是 GCJ-02 网格（两者在本仓实测差约 360 m）。
配对由 `_scratch/_compare/build_compare.py` 用 `wgs84_to_gcj02 → lonlat_to_tile`
算出来，连同每张图的字节数/修改时间一起写进清单。

★ **只按清单里的键出图，请求方永远不给路径。**
  清单 = `data/compare/manifest.json`。为什么不写成 `?path=`：那等于开一条
  「按任意路径读盘」的读取面（本仓记过「响应多带字段 = 开新读取面」，
  这里更直接 —— 参数本身就是路径）。
  键是 `p03` / `campus` 这种定长串，先在清单里查到条目，路径才出现。

★ 照片**在原位**服务，不复制进 `data/refs/_images/`：那是相机原片，一张几 MB，
  复制一份只是多一份要同步的副本。代价是清单记的绝对路径必须仍然成立 ——
  所以清单里存了 `bytes` + `mtime`，**下发前核一遍**：对不上就拒绝并说明。
  理由不是洁癖：照片被换过之后，清单里那串 GPS 就不再属于它了，
  而屏幕上「配上了」和「配错了」长得一模一样。

★ 尺子的边界（免得被当成更强的保证）：`bytes` + `mtime` 只能认出
  「换过/截断过」这类改动，**认不出"内容换了但长度与时间戳都碰巧一样"**。
  它是防手滑的量具，不是内容指纹。要内容指纹得存 sha256 并在下发时读全文件 ——
  一张 4 MB 的图每请求多读一遍，换不来多少确定性。

★ 照片侧与卫星侧**共用同一个 `_stale()`**（三态、三句理由都只此一份）。
  两侧的差别只有一处：**清单给这一侧记了多少字段，闸门就有多强** ——
  记了 `bytes`/`mtime` 才核得出来，没记就只剩"在不在盘上"。
  这条边界要写在能看见的地方，因为它让两侧**看起来**不一样，
  而实际上它们是同一把尺子、只是量到的东西不同（本仓记过：量具的覆盖差异
  在汇总里是看不见的）。另注：`{key: campus}` 走的是顶层 `campus`，
  它有 `img` 没有 `photo` —— 拿 `/photo/campus` 问是**端点用错了**，回 404 而不是 409。
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from ..settings import Settings
from . import refs

MANIFEST = "manifest.json"


def store_dir(cfg: Settings) -> Path:
    """比对产物目录 `data/compare/`（`data/*` 在 `.gitignore` 里，不进仓）。"""
    return Path(cfg.resolved_data_dir) / "compare"


def manifest_path(cfg: Settings) -> Path:
    return store_dir(cfg) / MANIFEST


def load(cfg: Settings) -> dict:
    """读清单。**每次现读**（改了清单不必重启进程）。"""
    p = manifest_path(cfg)
    if not p.is_file():
        return {"items": [], "campus": None,
                "absent": "还没有比对清单：%s（跑 _scratch/_compare/build_compare.py）" % p}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:            # noqa: BLE001
        return {"items": [], "campus": None,
                "absent": "比对清单读不开：%s（%s）" % (p, e)}


def _stale(path: str, want_bytes: int | None, want_mtime: float | None,
           what: str = "这张照片") -> str:
    """`bytes` + `mtime` 对不上 ⇒ 回一句人话。对得上回空串。

    ★ 分开报三种情况（都不许合并成一句「有问题」）：文件没了 / 长度变了 / 时间变了。
      补救办法不同：前两种要重建清单，第三种可能只是被重新导出过。

    ★ `what` 由调用方给（照片 / 卫星图）。照片侧与卫星侧**共用这一份实现**，
      名词跟着调用方走 —— 否则卫星图丢了会报出「这张**照片**不在原位了」。
      两条读取面各写一份同类判据，是本仓栽过的那种"一个判断多份实现"。
    """
    if not os.path.isfile(path):
        return "%s不在原位了：%s" % (what, path)
    if want_bytes is not None and os.path.getsize(path) != want_bytes:
        # 后果句写成**两侧都成立**的说法：照片那份是"EXIF 坐标不一定还属于它"，
        # 裁切那份是"这个点不一定还落在这张图的中心"。别照照片的口吻写死 ——
        # 同一份实现被两处调用，句子就得对两处都为真。
        return ("%s的字节数变了（清单 %s，现在 %s）⇒ 建清单之后被改过，"
                "清单里记的坐标不一定还对着它" % (what, want_bytes, os.path.getsize(path)))
    if want_mtime is not None and abs(os.path.getmtime(path) - want_mtime) > 1.0:
        return ("%s的修改时间变了（清单 %s，现在 %s）⇒ 被重新导出或替换过，"
                "需要重建清单再比" % (what, want_mtime, os.path.getmtime(path)))
    return ""


def _entry(cfg: Settings, key: str) -> dict | None:
    man = load(cfg)
    if key == "campus":
        return man.get("campus") or None
    for it in man.get("items") or []:
        if it.get("key") == key:
            return it
    return None


def photo(cfg: Settings, key: str) -> tuple[str, object]:
    """本机照片。

    回 `("ok", (Path, media_type))` / `("missing", 说明)` / `("stale", 说明)`。
    ★ **三态不能合并成一句**：`missing` 是"你要的键我这没有"（调用方给错了），
      `stale` 是"键对，但你那份文件跟建清单时不是同一份了"（补救是重建清单）。
      两种都回 404 的话，"照片被换过"在屏幕上就长得像"键写错了"，
      而这两件事的下一步动作是相反的。
    """
    it = _entry(cfg, key)
    if it is None:
        return ("missing", "清单里没有这一项：%s" % key)
    ph = it.get("photo") or {}
    path = ph.get("abs") or ""
    if not path:
        # 键**在**清单里，但它不是一对照片（`campus` 就是这种：顶层有 `img`、没有 `photo`）。
        # ★ 这里必须是 `missing`，不是 `stale`：409 的语义是"键对、我们这边数据漂了 ⇒ 重建清单"，
        #   而对着这个键重建清单**一万次也变不出一个 `photo` 段** —— 两个补救方向正相反。
        #   不拦的话会走到 `_stale("")`，其中 `not isfile("")` 命中"不在原位"那条，
        #   屏幕上印成「这张照片不在原位了：」＋**一个空路径**（冒号后面什么都没有），
        #   看着像我们的产物丢了，其实是端点用错了。
        return ("missing", "清单里这一项不是照片：%s" % key)
    why = _stale(path, ph.get("bytes"), ph.get("mtime"))
    if why:
        return ("stale", why)
    return ("ok", (Path(path), refs.content_type_for(path, fallback="image/jpeg")))


def aerial(cfg: Settings, key: str) -> tuple[str, object]:
    """高德裁切（校区大图 / 某一对）。同样三态：见 `photo()` 的理由。

    裁切图是我们自己的产物 ⇒ 它不在盘上属于 `stale`（清单与产物对不上，
    要重建），不是"你要的键没有"。

    ★ 闸门**跟着清单里记了什么走**：记了 `bytes`/`mtime` 就核，没记就只核"在不在盘上"。
      此刻 `campus` 记了 `bytes`（核得上）、11 条 `aerial` 一个都没记 ⇒ 那 11 条仍只一道闸。
      ★ 但这不是"两条读取面强度不同"的挡箭牌：`build_compare.py` 已改成给裁切**也**记
        `bytes`+`mtime`，下次重建清单时这 11 条自动升到与照片同级 —— **改数据不改代码**，
        正因为判据只有这一份实现。
      ★ 校区大图那道 `bytes` 不是可有可无：清单里的 `bbox` 就是**用来把点位摆上这张图**的
        （见 `compare.js` 按 `campus.bbox` 算百分比）。图换了、bbox 没换 ⇒ 点位会摆在
        一张不属于它的图上，而屏幕上"摆对了"和"摆错了"长得一样。
    """
    if key == "campus":
        it = _entry(cfg, "campus") or {}
        rec, path = it, (it.get("img") or "")
    else:
        it = _entry(cfg, key)
        if it is None:
            return ("missing", "清单里没有这一项：%s" % key)
        rec = it.get("aerial") or {}
        path = rec.get("crop") or ""
    if not path:
        return ("missing", "清单里没有这一项的卫星图：%s" % key)
    why = _stale(path, rec.get("bytes"), rec.get("mtime"), what="这张卫星图")
    if why:
        return ("stale", why)
    return ("ok", (Path(path), "image/png"))


def brief(cfg: Settings, it: dict) -> dict:
    """给界面的一条：**不带任何本机绝对路径**（来源只给目录名）。

    ★ 只回目录名不回全路径，是有意的：全路径里带着用户名与盘上结构，
      而这一屏在局域网上可读。要看是哪张图，界面已经能显示图本身。
    """
    aer = it.get("aerial") or {}
    ph = it.get("photo") or {}
    return {
        "key": it.get("key"),
        "title": it.get("title"),
        "dt": it.get("dt"),
        "km": it.get("km"),
        "wgs84": it.get("wgs84"),
        "gcj02": it.get("gcj02"),
        "in_campus_image": bool(it.get("in_campus_image")),
        "photo": {"base": ph.get("base"), "dir_head": (ph.get("dir") or "").split(os.sep)[-1],
                  "bytes": ph.get("bytes"), "sha12": ph.get("sha12")},
        "aerial": {"z": aer.get("z"), "px": aer.get("px"),
                   "m_per_px": aer.get("m_per_px"),
                   "tiles": aer.get("tiles"),
                   "placeholder_tiles": aer.get("placeholder_tiles"),
                   "bbox": aer.get("bbox")},
    }
