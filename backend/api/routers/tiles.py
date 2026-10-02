# -*- coding: utf-8 -*-
"""2024 实景 3D Tiles 数据域：门户页那块"世界底"的静态读取面。

只有一条路由：`GET /api/tiles/{path}`。要看的东西分两类 ——
  · `tileset.json`          （10.4 MB，一次性，声明 124 个顶层瓦片与整棵树）
  · `Tile_+NNN_+NNN/*.glb`  （48,701 个，流式，每块一个）
两条走同一个处理函数：对 Cesium 来说它们都只是"这个 URL 给我字节"。

★ 这条面的全部边界（铁律 12）：**请求方给不出路径，只能给出一个相对键。**
  键先做一次 `PurePosixPath` 规范化（吃掉 `..` 与 `.`），再**必须**落在
  `tiles_dir` 里面 —— 核不过就 404。这不是"顺手加的一道校验"，是这条面
  唯一的实现：即使递进来 `../../etc/passwd`，规范化之后它也不在目录里。

★ 为什么**不用** `app.mount(..., StaticFiles(...))`（本仓别处都用挂载）：
  这里要的是两件挂载给不了的东西 ——
    ① 目录不在本机时，错误体里必须**印出找的是哪个目录**（服务器上
       `_scratch/_fly2024_tiles` 不存在，是"没跟着部署"，不是"瓦片坏了"；
       只回一句 404 会让这两种情况在屏幕上长得一模一样，铁律 16）；
    ② 扩展名白名单。那个目录里除了瓦片还躺着 `tileset.json.bak_bvfix`
       之类的备份件，挂载会把"此刻和以后"的一切都端出去。

★ 权限口径与 `routers/campus.py` **同一条**（那边写得很长，这里只记结论）：
  实景瓦片 = 校区外形，是给所有人看的；要挡的是**进到楼里面**之后的每层功能与
  使用单位（那些走 `/api/buildings/{name}*` 与 `/api/rooms*`）。所以这一条
  只要 `view`，**不做逐栋过滤** —— 瓦片是一整棵树，切开就画不出来了。
"""
from pathlib import Path, PurePosixPath

from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse

# ★ 直接 `python backend/api/routers/tiles.py` 跑末尾那段自检入口时，`__package__`
#   是空的 ⇒ 下面那句 `from ..authz import …` 抛「attempted relative import with no
#   known parent package」。屏幕上像"这个文件坏了"，而它是好的（铁律 168 同族）。
#   这里把直接运行**转成** `-m`，两条跑法都通。守卫在 `authz.py` / `deps.py` /
#   `routers/portal.py` 里各有一份。
if __package__ in (None, ""):
    import os as _os
    import subprocess as _sp
    import sys as _sys

    _root = _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
    _mod = (_os.path.relpath(_os.path.abspath(__file__), _root)[:-3]
            .replace(_os.sep, ".").replace("/", "."))
    _sys.exit(_sp.call([_sys.executable, "-m", _mod, *_sys.argv[1:]], cwd=_root))

from ..authz import require_cap
from ..deps import SettingsDep
from ..responses import not_found

router = APIRouter(tags=["tiles"], dependencies=[Depends(require_cap("view"))])

# 只放这几种出去（与 `serve_campus_view.py` / `campus.py::_ALLOWED_EXT` 同一取舍）。
# ★ 不放 `.bak*`：目录里有 `tileset.json.bak_bvfix`，它是"修包围盒之前"的那一份，
#   端出去只会让人拿旧树去对新的瓦片。
_ALLOWED_EXT = {".json", ".glb", ".jpg", ".png"}

# MIME 按扩展名写死，不靠 mimetypes 猜：`.glb` 在本仓多台机器上被猜成
# `application/octet-stream`（Windows 注册表里没登记），Cesium 收下照解码、
# 但浏览器 devtools 里那条 `Content-Type` 是错的，排查时会带偏方向。
_MIME = {
    ".json": "application/json",
    ".glb": "model/gltf-binary",
    ".jpg": "image/jpeg",
    ".png": "image/png",
}


def _safe_join(root: Path, key: str) -> Path | None:
    """把 URL 里的相对键接到 root 下；越界或不合规就回 None。

    ★ 用 `PurePosixPath` 而不是 `Path`：URL 里的分隔符**恒是** `/`，
      而在 Windows 上 `Path("a/b")` 会被 `\\` 的语义重新解释一遍
      （本仓铁律 013：路径一旦被当成模式用，反斜杠就变成转义符）。
    ★ `..` 在这条路上不必单独拦 —— 规范化会把 `a/../../b` 折成 `b`，
      折不出去（`../..` 折成 `..`）的那些，`relative_to` 一道就把它挡了。
    """
    p = PurePosixPath(key)
    if p.is_absolute() or ".." in p.parts:
        return None
    if p.suffix.lower() not in _ALLOWED_EXT:
        return None
    root = root.resolve()
    full = (root / Path(*p.parts)).resolve()
    try:
        full.relative_to(root)
    except ValueError:
        return None
    return full


@router.get("/tiles/{path:path}", include_in_schema=False)
def tiles_asset(cfg: SettingsDep, path: str) -> FileResponse:
    """实景瓦片的一块。`path` 是相对 `tiles_dir` 的键，例如 `Tile_+003_+005/x.glb`。

    ★ `FileResponse`（不是自己 `read_bytes`）—— 10.4 MB 的 `tileset.json` 与
      几千个 2~200 KB 的 `.glb`，重复访问全都该走 Starlette 自带的
      etag/last-modified ⇒ 304。自己读进内存再回等于把缓存也一起扔掉。
    """
    d = cfg.resolved_tiles_dir
    if not d.is_dir():
        raise not_found(
            "实景瓦片目录不在本机",
            dir=str(d),
            hint=("要用实景底就把 GYM3D_TILES_DIR 指到瓦片所在地"
                  "（本机默认 _scratch/_fly2024_tiles，服务器上是 /opt/gym3d/fly2024-tiles）"),
        )
    full = _safe_join(d, path)
    if full is None:
        raise not_found("这个键不在实景瓦片目录里", key=path)
    if not full.is_file():
        raise not_found("实景瓦片目录里没有这个文件", dir=str(d), key=path)
    return FileResponse(str(full), media_type=_MIME.get(full.suffix.lower()))


if __name__ == "__main__":
    # 自检：`_safe_join` 是这条面上**唯一**的边界，所以它必须带自己的伪证。
    # ★ 关键是**两边都要有**：光跑一堆"应该拒"的例子全过，证明不了"应该放的放得过去" ——
    #   一个**永远拒**的闸能通过全部阴性对照，它和正确的闸在屏幕上一模一样
    #   （本仓铁律 153，2026-09-29 在棱镜下过单通路上亲身踩过）。
    #   所以下面同时有 ON（必须放行）和 OFF（必须拒）两组。
    import json
    import sys
    from pathlib import Path

    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    root = Path(r"D:\gym3d\_scratch\_fly2024_tiles")

    # ★★ ON 组里那条"真瓦片"的键**必须从盘上读回来**，不许手打。
    #   这里我先前栽过一次：写的是 `Tile_+003_+005/L17_0.glb` —— 前缀少一层
    #   `Data/`、文件名也是我**编的**。`_safe_join` 只做拼接、不问盘上有没有，
    #   于是它照样印 ✓，一看是"路径切得对"，读起来却是"这个瓦片取得出来"。
    #   （本仓铁律 105：对照的输入要由程序从实测数里算出来，不是手打一个像的。）
    #   真布局：`Data/Tile_+NNN_+NNN/Tile_+NNN_+NNN.glb`。
    ts = json.loads((root / "tileset.json").read_text(encoding="utf-8"))
    kids = ts["root"]["children"]
    uri = kids[0]["content"]["uri"]            # 例如 Data/Tile_+003_+005/Tile_+003_+005.glb

    on = [                                     # 必须**放行**
        "tileset.json",                        # 盘上有
        uri,                                   # 盘上有（下面会真的去核）
        "./tileset.json",
        uri.replace("/", "/./", 1),            # Data/./Tile_…/….glb —— 规范化要吃掉这个 `./`
    ]
    off = [                                    # 必须**拒**
        "../tileset.json",
        "a/../../b.json",
        "/etc/passwd",
        "C:/Windows/win.ini",
        "tileset.json.bak_bvfix",              # 备份件：扩展名不在白名单
        "tileset.json.bad_inflated",           # 另一份备份，同上
        "x.exe",
        "x.py",
        "",                                    # 空键
    ]
    n, bad = 0, 0

    # ★ 先核一件事：ON 组**声称**是盘上真文件的那些键，盘上是不是真有。
    #   核不过就当场红 —— 否则下面那排 ✓ 说的是"拼得对"，不是"取得出"。
    for k in [k for k in on if k in ("tileset.json", uri)]:
        n += 1
        ok = (root / Path(*PurePosixPath(k).parts)).is_file()
        bad += 0 if ok else 1
        print("  %s 存在 %-52r → %s" % ("✓" if ok else "✗", k, ok))

    for k in on:
        n += 1
        got = _safe_join(root, k)
        ok = got is not None
        bad += 0 if ok else 1
        print("  %s ON  %-52r → %s" % ("✓" if ok else "✗", k, got))
    for k in off:
        n += 1
        got = _safe_join(root, k)
        ok = got is None
        bad += 0 if ok else 1
        print("  %s OFF %-52r → %s" % ("✓" if ok else "✗", k, got))
    print("  顶层瓦片 %d 个；本趟用的样本键 %r" % (len(kids), uri))
    print("  %d 支，%d 不合格" % (n, bad))
    raise SystemExit(1 if bad else 0)

