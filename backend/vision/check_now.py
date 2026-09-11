# -*- coding: utf-8 -*-
"""临时：视觉模型检查当前 GLB 的墙/门（front 立面 + top 平面）。"""
import os
import sys

sys.path.insert(0, os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")))    # backend/
from paths import DATA  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))          # backend/vision
from client import chat_vision_multi

front = open(DATA / "_now_front.png", "rb").read()
top = open(DATA / "_now_top.png", "rb").read()

prompt = (
    "两张图是同一栋教学楼（理化楼）的 3D 建模渲染：第一张是南立面正视图，第二张是顶视平面图。\n"
    "请对照「SketchUp 读图成图」的标准，逐条精确定位墙和门的错误：\n"
    "1. 【门】每扇门：门洞是否真的挖穿了墙（能看到门洞内侧空间）？门洞里有没有门扇/门板？"
    "门扇颜色能不能和墙面区分开？门扇是嵌在墙里，还是浮在墙外/悬空？\n"
    "2. 【门头过梁】门洞上方的墙（门顶到墙顶）和左右墙体是不是一样厚、一样平？有没有门上方鼓出来一块/比墙宽？\n"
    "3. 【墙】外墙/内墙的厚度看起来正常吗（外墙约 0.3m、内墙约 0.24m）？有没有墙被门洞挖断后两侧漏缝、"
    "或者墙角缺一块、或者墙明显过厚/过薄？\n"
    "4. 【平面图】从顶视图看，外墙轮廓是否闭合？门洞是否把外墙整段切开？\n"
    "请具体到「第几层的哪个位置、什么问题、应该改成什么样」，不要笼统说「看起来还行」。"
)

print(chat_vision_multi([front, top], prompt))
