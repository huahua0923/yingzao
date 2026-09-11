# -*- coding: utf-8 -*-
"""临时：近景门渲染图 → 视觉模型检查门洞/过梁/门扇。"""
import os
import sys

sys.path.insert(0, os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")))    # backend/
from paths import DATA  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))          # backend/vision
from client import chat_vision

img = open(DATA / "lihua-door-closeup.png", "rb").read()

prompt = (
    "这是教学楼南立面一扇门（门洞+门上方墙体）的近景渲染图。请精确回答：\n"
    "1. 门洞里有没有「门扇/门板」？门扇是什么颜色？是嵌在门洞中间，还是空的？\n"
    "2. 门洞上方（门顶到墙顶之间）有没有墙（门头过梁）？过梁和左右墙体是不是一样厚、一样平？\n"
    "3. 门洞左右两侧的墙厚度看起来正常吗？有没有门洞比墙宽很多、或者墙被挖穿漏光的情况？\n"
    "4. 总体：这扇门的建模对不对？哪里还需要改？"
)

print(chat_vision(img, prompt))
