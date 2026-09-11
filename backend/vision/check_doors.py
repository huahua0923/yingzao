# -*- coding: utf-8 -*-
"""临时：把渲染图发给视觉模型，检查门的建模对不对（门洞/过梁/门扇）。"""
import os
import sys

sys.path.insert(0, os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")))    # backend/
from paths import DATA  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))          # backend/vision
from client import chat_vision_multi

front = open(DATA / "lihua-front.png", "rb").read()
iso = open(DATA / "lihua-iso.png", "rb").read()

prompt = (
    "这是同一栋砖红色教学楼（理化楼）的正立面和轴测渲染图。"
    "请重点检查「门」的建模是否正确，只回答以下几点，简洁：\n"
    "1. 每个门洞上方是否有一段「门头过梁」（门洞只到门高、其上是墙），还是门洞一直开到墙顶/被挖穿？\n"
    "2. 门洞两侧和过梁是否和墙体一样厚（过梁有没有明显比墙宽、凸出墙外一大块）？\n"
    "3. 有没有门洞明显比门扇宽很多、或者门扇浮在墙外/没嵌进墙里的情况？\n"
    "4. 总体上「门」看起来对不对，还有没有明显别扭的地方？"
)

print(chat_vision_multi([(front, "image/png"), (iso, "image/png")], prompt))
