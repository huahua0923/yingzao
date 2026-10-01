# -*- coding: utf-8 -*-
"""外观图/航拍图数据域：**词的形状**（图片扩展名、屋顶受控词表、从文件名认楼号）。

★ 为什么这几行值一个独立模块 —— 它原先只长在 `_scratch/_ref_import.py` 里，
  而**那个文件没进 git**。`data/refs/README.md` 白纸黑字写着
  「认楼号的规则全库只此一份实现：`_ref_import.guess_building`，上传口也 import 它」。
  管理台（已进 git）现在要当那个"上传口"，于是那条"一份实现"就从
  「一个未入库文件里的函数」挪进已入库的树里 —— 否则就是本仓已犯三次的
  「已入库的 .py import 了存在但没入库的本地模块」（memory: untracked-module-imported-by-tracked）：
  在**这台机器上完全正常**，一 clone 就缺件，而缺件那一刻不报错，
  是"运行到上传那一步才死"。
  判据：`python _scratch/_import_graph_gap.py`（退出码进门禁）。

★ 分层：这里只有"名字怎么认、图放哪、词表是什么"，**没有 HTTP 形状** ——
  那是 `routers/workshop.py` 的事。
"""
import os
import re

#: 一张图入库时允许的 kind（`_ref_import.py --kind` 的 choices 与 facts 的字段同源）。
KINDS = ("aerial", "exterior", "facade", "roof", "roofplan", "cad", "other")

#: 哪些扩展名算"外观图/航拍图"。上传口按它决定图片进 `_inbox/refs/` 还是 `_inbox/`：
#: 图片不是 CAD，丢进 `_inbox/` 会被 `convert_dwg_to_dxf` 当图纸去啃。
IMG_EXT = (".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff")

# facts.json 里 `roof.type` 的受控词表 —— **判读与体检共用这一份**。
# 为什么要有它：模型侧 `style.roofType` 95 栋全是 "flat"，于是"照片说坡、模型说平"
# 本该报差异；但如果我判读时顺手写成 "坡屋顶"/"flat_roof"，体检同样报差异 ——
# 那条差异**是我造的**，不是模型的毛病。词表把这两种红分开：
# 不在词表里 = 判读写错了（去改 facts.json），在词表里且不等 = 模型真不符。
# "unknown" = 照片看不清，**不参与比较**（和没写一样），免得"看不出"被当成"不符"。
ROOF_TYPES = ("flat", "gable", "hip", "shed", "sawtooth", "vault", "dome", "mixed", "unknown")

#: 按扩展名给 Content-Type。`/refimg` 与 `/su` 两条出口共用，免得两处各写一份
#: 而漂成两套（`.tif` 在一处认得、在另一处退回 octet-stream，浏览器就直接下载）。
CT_BY_EXT = {
    "png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
    "webp": "image/webp", "bmp": "image/bmp", "tif": "image/tiff", "tiff": "image/tiff",
    "html": "text/html; charset=utf-8", "json": "application/json; charset=utf-8",
    "txt": "text/plain; charset=utf-8", "md": "text/plain; charset=utf-8",
}


def guess_building(filename):
    """从文件名认楼号：`c103_东立面.jpg` → `c103`；认不出返回空串。

    ★ 全库只此一份实现 —— 上传口（`routers/workshop.py`）与入库脚本
      （`_scratch/_ref_import.py`）都从这里 import，
      免得"上传时猜的楼号"和"入库时猜的楼号"哪天漂成两套。
    """
    m = re.search(r"c\s*0*(\d{2,3})(?!\d)", filename, re.I)
    if not m:
        m = re.search(r"(?<!\d)(\d{3})(?!\d)", filename)
    if not m:
        return ""
    return "c%03d" % int(m.group(1))


def known_building(name, buildings_dir):
    """楼号必须真的在库里 —— 猜错比猜不出更坏（会把图挂到别人家）。

    ★ `buildings_dir` 是**显式参数**，不走模块级常量：同一个进程里
      "库在哪"由 `Settings.resolved_data_dir` 说了算，而脚本侧由 `ROOT` 说了算。
      两边各有一个值没关系，**但必须由调用方交进来** ——
      写成模块级默认路径就成了"配置只活在某个文件里"，换个部署就悄悄指错地方
      （memory: config-in-memory-only-gets-lost）。
    """
    return bool(name) and os.path.isdir(os.path.join(str(buildings_dir), name))


def content_type_for(filename, fallback="application/octet-stream"):
    """按扩展名给 Content-Type。认不出给 fallback（不猜）。"""
    ext = os.path.splitext(filename)[1].lstrip(".").lower()
    return CT_BY_EXT.get(ext, fallback)
