# -*- coding: utf-8 -*-
"""理化楼（C005）——识别引擎基线档案（已跑通）。

绘图约定：
  - 墙/门/台阶同图层「4.2墙体」，按 LWPOLYLINE 点数区分
    （门 ≥10 点、台阶 ==5 点、其余为墙）
  - 结构柱在「4.1结构柱」图层（0.5×0.5m，仅首层）
  - 墙 = 双线墙皮配对；门 = 16/23 点多段线；台阶 = 5 点 ⊓

⚠️ dxf 是本机专属的外部资源（不在仓库里），服务器上不参与任何计算；
   rooms / out_dir 走 backend/paths.py，换机器不用改。
"""
import os
import sys

sys.path.insert(0, os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")))    # backend/
from paths import DATA  # noqa: E402

from ..profile import BuildingProfile, register

LIHUA = register(BuildingProfile(
    name="lihua",
    title="理化楼（C005）",
    dxf=r"D:\校庆\校庆材料\C005-理化楼2.dxf",
    rooms=str(DATA / "rooms.json"),
    out_dir=str(DATA / "floors"),

    # offset = 图纸上相邻两层平面的真实 Y 间距（98900mm，非 99000）。各层墙点中点实测
    # 逐层 -100mm 漂移（99000 时 floor0 -15 → floor4 -415mm），改成 98900 后各层统一 -15mm，
    # 消除「Z 轴（南北）逐层错位」。
    offset=98900.0,
    cx=707300.0,
    cy=28100.0,

    wall_layer="4.2墙体",
    column_layer="4.1结构柱",

    door_min_points=10,
    stair_points=5,
    door_by_points=True,

    wall_min=0.08,
    wall_max=0.35,
    wall_extend=0.15,
    wall_fallback=0.15,
    # 外墙真实墙厚 = 门垛实测 240mm。8 点周边折线是「单线外皮」（无内皮线），
    # 不能和内墙皮线配对读厚，改为往建筑内侧单向 buffer outer_wall_t 成实体墙。
    outer_wall_t=0.24,
    # 内墙真实墙厚 snap：0.12 薄隔墙（楼梯井/设备边）、0.24 隔墙、0.30 承重。
    wall_thicknesses=[0.12, 0.24, 0.30],

    door_w_single=1.1,
    door_w_double=2.4,
    door_depth=0.5,

    outline_buf=0.15,
    open_r=0.35,
    parapet_margin=0.5,

    layer_height=4.2,
    slab=0.2,

    # 阶梯楼（中间高两侧低）：5 层为中央塔楼（门/房间 x∈[-26.7,26.7]），两侧是 4 层翼楼屋面。
    # 顶层墙里，翼楼屋面女儿墙与塔楼外墙是「同一条跨满全宽的连续折线」（n=8，x∈[-51.9,51.9]），
    # 按质心过滤（wall_x）会误杀塔楼外墙。改用 wall_x_clip 把墙折线裁到塔楼 X 区间：
    # 塔楼那半保留、翼楼那半切掉，顶层轮廓自然收缩为中央块（926㎡），翼楼屋面 = floor3 满
    # footprint − 塔楼 outline（recognize 自动写 roof.wingRoof，~940㎡）。
    # 否则 5 层墙 union 含翼楼女儿墙 → outline 撑成全 footprint（1877㎡），屋顶/女儿墙
    # 悬挑盖住翼楼、翼楼屋面只剩 13㎡ 碎屑、翼楼女儿墙被当 4.2m 全高墙（「第五层不对」根因）。
    transition={4: {"wall_x_clip": [-26.73, 26.73]}},

    # 外观：红砖平顶（与 c006 等老教学楼同款），roofType 必须 flat——
    # 否则 emit_spec 会落到 STYLE_DEFAULT 的 "gable"，给理化楼盖 11m 坡顶、总高错到 32m。
    style={
        "facade": "#a4533d", "inner": "#cfc9bd", "roof": "#6b5a4a",
        "roofType": "flat", "parapet": "#6a4a40", "glass": "#789cb8", "door": "#5c3a1e",
    },
))
