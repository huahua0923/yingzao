# -*- coding: utf-8 -*-
"""为 c108 网安楼生成 profile.json（第 49 栋）。

值全部来自实测，不是抄模板：
  offset 63600   —— 四块平面的 Y 间距实测 64300/63600/63600，取标准值；房号标注
                    间距也是 63600（35080→98680→162280→225880），逐层吻合
  cy     31400   —— 首层墙块 Y 26080~36720 的中心。floor = round((y-cy)/offset)，
                    四层墙块与四条房号带都落在各自楼层的 ±0.084 内，不贴 0.5 边界
  cx     1198645 —— **列0** 墙块 X 1169575~1227715 的中心。
                    注意 detect_params 自动给的是 1535735，那是整张图(含列1)的中点，
                    对这栋是错的：列1 在 X 1.84e6 外另有 123 面墙，不隔离会混进每一层
  x_range        —— 隔离列0，排除列1。
                    判据：列1 有 123 面墙、58.1m 宽，但**一条房号都没有**
                    （房号 32 条全在列0），面积图层只有 1 条游离数字
                    → 是屋顶/详图平面，不是可入住层。层数由房号前缀定死：01/02/03/04 共 4 层
  column_layer   —— 图层存在但 0 实体。按 c116 先例显式写图层名；识别出 0 柱是忠实结果
"""
import json
import os

sys_dir = r"D:\gym3d\data\buildings\c108"
os.makedirs(os.path.join(sys_dir, "floors"), exist_ok=True)

profile = {
    "name": "c108",
    "title": "网安楼",
    "dxf": r"D:\dxf_output\C108-网安楼.dxf",
    "wall_layer": "4.2墙体",
    "column_layer": "4.1结构柱",
    "x_range": [1169575, 1227715],
    "offset": 63600,
    "cx": 1198645.0,
    "cy": 31400.0,
    "rooms": os.path.join(sys_dir, "rooms.json"),
    "out_dir": os.path.join(sys_dir, "floors"),
    # 算法默认值：与 backend/recognizer/detect_params.py 的 ALGO_DEFAULTS 一致
    "door_min_points": 10,
    "stair_points": 5,
    "wall_min": 0.08,
    "wall_max": 0.35,
    "wall_extend": 0.15,
    "wall_fallback": 0.15,
    "door_w_single": 1.1,
    "door_w_double": 2.4,
    "door_depth": 0.5,
    "outline_buf": 0.15,
    "open_r": 0.35,
    "parapet_margin": 0.5,
    "layer_height": 4.2,
    "slab": 0.2,
    "style": {
        "facade": "#a4533d",
        "inner": "#cfc9bd",
        "roof": "#6b5a4a",
        "roofType": "flat",
        "parapet": "#6a4a40",
        "glass": "#789cb8",
        "door": "#8a5a38",
    },
    "outline_unify": True,
    "pair_curved": True,
}

with open(os.path.join(sys_dir, "profile.json"), "w", encoding="utf-8") as f:
    json.dump(profile, f, ensure_ascii=False, indent=1)
print("已写:", os.path.join(sys_dir, "profile.json"))
print("层数预期: 4（房号前缀 01/02/03/04）")
print("floor_of 自查（各层墙块中心 → 应得 0/1/2/3）:")
for f, yc in enumerate([31400, 95000, 158600, 222200]):
    print("   y=%6d → floor %d" % (yc, round((yc - profile["cy"]) / profile["offset"])))
