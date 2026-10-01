# -*- coding: utf-8 -*-
"""影像比对数据域的路由（高德卫星 ↔ 本机照片）。

三条 GET，**全是只读** —— 所以都不挂 `ComputeDep`：
这一屏只是把已经算好的配对拿出来看，不写盘、不跑命令。
（本仓的规矩是「能不能写」只由 `deps.exec_denied_reason` 一处判；这里既然没有写口，
 就不该挂一个执行面闸门来装样子。）

★ 出图只认**清单里的键**：`/compare/img/p03`、`/compare/photo/p03`。
  键先在清单里查到条目、路径才从条目里出来 —— 请求方从头到尾给不出一个路径。
  这不是"顺手加的校验"，是这条读取面的全部边界（铁律 12）。
"""
from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse

from ..authz import require_cap
from ..deps import SettingsDep
from ..responses import ApiError, not_found, ok
from ..services import compare

# ★ 权限（2026-10-01 批次 2）：**全校区口径**，且这一次是**被迫**的，不是选的。
#   清单里的每一条是"无人机照片 ↔ 高德卫星裁切"的一对，靠 **WGS-84 经纬度**配对
#   （照片 EXIF 是 WGS-84、瓦片是 GCJ-02，差 ~360 m）—— 它**没有楼栋号**。
#   空间树只有 `楼/层/房号` 三级，配不上 ⇒ `visible(...)` 在这里没有可用的 key。
#   ★ 把"为什么没做逐栋过滤"写下来，而不是留白：下一个人看到这条没有范围过滤，
#     第一反应是"漏了"。真相是**这条数据不在那棵树里**；哪天照片带上楼号，
#     这一条就该跟着改细。
router = APIRouter(tags=["compare"], dependencies=[Depends(require_cap("view"))])


@router.get("/compare/list")
def compare_list(cfg: SettingsDep) -> dict:
    """清单：校区大图（含经纬度框）＋ 每一对（照片 · 卫星裁切）。

    ★ 「没有清单」必须是**一个说法**，不能是空数组：那两种情况在屏幕上
      一个是"还没建"，一个是"建了但一对都没有"。`absent` 就是那句话。
    """
    man = compare.load(cfg)
    items = [compare.brief(cfg, it) for it in (man.get("items") or [])]
    campus = man.get("campus") or None
    out = {
        "criterion_version": man.get("criterion_version"),
        "built": man.get("built"),
        "how": man.get("how"),
        "tile": man.get("tile"),
        "tiles": man.get("tiles"),
        "items": items,
        "campus": None if not campus else {
            "key": campus.get("key"),
            "title": campus.get("title"),
            "bbox": campus.get("bbox"),
            "bytes": campus.get("bytes"),
            "sha12": campus.get("sha12"),
        },
        # 局域网上不给本机绝对路径：来源只到"目录名"这一级（见 services/compare.brief）
        "counts": {"items": len(items)},
    }
    if man.get("absent"):
        out["absent"] = man["absent"]
    return ok(out)


def _serve(hit: tuple[str, object], key: str):
    """三态 → 响应。

    ★ `missing` ⇒ 404、`stale` ⇒ 409，**不许合并成一个码**：
      「你要的键我这没有」是调用方给错了（键写错、清单里没这一项），
      「键对，但它跟你当初建清单时不是同一份了」是**我们这边的产/数据漂了**（重建清单）。
      合并成 404 的话，屏幕上「照片被换过」长得像「键写错了」，
      而这两件事的下一步动作正相反。这也是这条读取面唯一会出现的两种失败。
    """
    st, val = hit
    if st == "missing":
        raise not_found(val, key=key)
    if st == "stale":
        raise ApiError(409, "pair_stale", str(val), {"key": key})
    path, ctype = val
    return FileResponse(str(path), media_type=ctype)


@router.get("/compare/img/{key}")
def compare_img(key: str, cfg: SettingsDep):
    """高德卫星图（校区大图 / 某一对的裁切）。"""
    return _serve(compare.aerial(cfg, key), key)


@router.get("/compare/photo/{key}")
def compare_photo(key: str, cfg: SettingsDep):
    """本机照片（**在原位**读，不复制进仓）。清单核不过就拒绝并说明。"""
    return _serve(compare.photo(cfg, key), key)
