# -*- coding: utf-8 -*-
"""标准楼参数单点定义。

profile = 怎么读 DXF（检测参数：图层名 / 点数阈值 / 墙皮配对 / 坐标变换）
standard = 标准楼长什么样（目标参数：墙厚 / 层高 / 门窗 / 女儿墙 / 屋顶）

前端 JS 无法 import Python，故 recognize.py 末尾 emit_spec("data/spec.json")，
building.html 启动时 fetch 这份 spec，失败则回退内置常量，两条渲染路径同源防漂移。
"""
import json

# 所有目标尺寸统一单位：米
STANDARD = {
    # 层高 / 楼板 / 墙高
    "floor_h": 4.2,
    "slab_t": 0.2,
    "wall_h": 4.0,               # wall_h = floor_h - slab_t

    # 墙厚归一化（外墙 / 内墙）
    "outer_wall_t": 0.30,
    "inner_wall_t": 0.24,

    # 门（门宽由检测决定，见 profile.door_w_single/door_w_double；此处只定门高与门板厚）
    "door_h": 2.4,
    "door_panel_t": 0.05,

    # 结构柱
    "column_w": 0.5,
    "column_d": 0.5,

    # 窗（DXF 无窗数据，合成布点）
    "win_sill": 0.9,
    "win_h": 1.5,
    "win_w": 2.0,
    "win_spacing": 6.5,
    "win_in_depth": 0.40,        # 窗洞口向内吃进的深度
    "win_out": 0.06,             # 窗框向外突出量
    "glass_t": 0.04,             # 玻璃厚度
    "win_margin": 1.5,           # 墙段两端各留 1.5m 不布窗
    "win_min_seg": 3.5,          # 外墙直段长度下限才布窗
    "win_min_run": 2.0,          # 减去 margin 后剩余长度下限

    # 屋顶 / 女儿墙
    "roof_t": 0.2,
    "parapet_h": 0.9,
    "parapet_t": 0.5,            # 女儿墙厚（生成环宽度）

    # 楼梯（类型由 detect_stairwells 按跑数自动判定：1=直跑 2=双跑 3=双分式，无需配置）
    "stair_landing": 0.15,       # 顶层楼梯终止于屋顶下方的预留
}


# 外观样式默认（被各楼 profile.style 覆盖；facade=外墙色 roof=屋顶色 roofType=flat|gable）
STYLE_DEFAULT = {
    "facade": "#a4533d",    # 红砖（老校区主色）
    "inner": "#cfc9bd",     # 内墙浅米灰
    "roof": "#434b4a",      # 黛瓦深灰
    "roofType": "gable",    # 苏式坡顶；现代楼覆盖为 flat
    "parapet": "#5a4a40",   # 女儿墙/檐口
    "glass": "#789cb8",     # 窗玻璃
    "door": "#8a5a38",      # 门板
}


def emit_spec(path, style=None, overrides=None):
    """把 STANDARD + style + 每栋楼 overrides 写为 JSON，供前端 fetch（数据驱动查看器与 GLB 同源）。"""
    data = dict(STANDARD)
    if overrides:
        data.update(overrides)
    data["style"] = dict(style or STYLE_DEFAULT)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
