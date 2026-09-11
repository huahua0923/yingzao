# -*- coding: utf-8 -*-
"""第六教学楼（C006）——档案占位（待修）。

当前六教建模有误，待「逐模块改算法」阶段修正。与理化楼的差异不是改参数能解决，
需要为 classify 提供六教专属分类器：

  - 墙 = LINE + ARC 双线（非 LWPOLYLINE 单图层）
  - 门 = 4 点矩形（非 16/23 点多段线）
  - 柱 = INSERT(_FZHK) 块引用（非独立图层的 LWPOLYLINE）
  - 12 层阶梯状结构（裙楼 1~6 + 过渡 7 + 塔楼 8~11 + 屋顶 12），
    TOWER_SHIFT = -469675（塔楼相对裙楼的 Y 偏移）

下方数值均为占位，路径/坐标/图层待六教图纸确认后再填。
"""
from ..profile import BuildingProfile, register

J6 = register(BuildingProfile(
    name="j6",
    title="第六教学楼（逸夫楼 C006）",
    dxf=r"D:\校庆\校庆材料\C006-六教.dxf",   # 待确认实际路径
    rooms=r"D:\gym3d\data\rooms_j6.json",      # 待生成
    out_dir=r"D:\gym3d\data\floors_j6",        # 待生成

    offset=99000.0,          # 占位，待确认六教实际偏移
    cx=0.0,
    cy=0.0,

    wall_layer="",           # 六教墙是 LINE+ARC，非单图层 LWPOLYLINE
    column_layer="",

    door_min_points=10,
    stair_points=5,

    wall_min=0.08,
    wall_max=0.35,
    wall_extend=0.15,
    wall_fallback=0.15,

    door_w_single=1.1,
    door_w_double=2.4,
    door_depth=0.5,

    outline_buf=0.15,
    open_r=0.35,
    parapet_margin=0.5,

    layer_height=4.2,
    slab=0.2,
))
