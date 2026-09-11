# -*- coding: utf-8 -*-
"""给各楼 profile.json 加外观 style（红砖坡顶 / 现代面砖平顶 / 红砖平顶）。"""
import json
import os

BASE = r"D:\gym3d\data\buildings"

# 苏式红砖黛瓦坡顶（1956 苏式建筑群）
SU_SHI = {
    "facade": "#a4533d", "inner": "#cfc9bd", "roof": "#434b4a",
    "roofType": "gable", "parapet": "#6a4a40", "glass": "#789cb8", "door": "#8a5a38",
}
# 现代浅色面砖平顶（2015 东区新楼：浅色面砖 + 灰/黄体量 + 蓝玻璃楼梯间）
MODERN = {
    "facade": "#d3ccc2", "inner": "#cfc9bd", "roof": "#6b7078",
    "roofType": "flat", "parapet": "#8a8f96", "glass": "#3d6b8f", "door": "#6b7078",
}
# 红砖平顶（其余老教学楼）
BRICK_FLAT = {
    "facade": "#a4533d", "inner": "#cfc9bd", "roof": "#6b5a4a",
    "roofType": "flat", "parapet": "#6a4a40", "glass": "#789cb8", "door": "#8a5a38",
}

STYLE = {
    "c025": SU_SHI, "c028": SU_SHI, "c027": SU_SHI,   # 第一/二/三教学楼
    "c103": MODERN, "c104": MODERN,                    # 东1/东2教
    "c009": BRICK_FLAT, "c022": BRICK_FLAT, "c026": BRICK_FLAT,
    "c041": BRICK_FLAT, "c114": BRICK_FLAT, "c006": BRICK_FLAT,
}

for name, style in STYLE.items():
    path = os.path.join(BASE, name, "profile.json")
    with open(path, encoding="utf-8") as f:
        cfg = json.load(f)
    cfg["style"] = style
    with open(path, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=1)
    print(f"[{name}] {cfg['title']}  roofType={style['roofType']}  facade={style['facade']}")
print("done")
