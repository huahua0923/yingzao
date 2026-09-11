# -*- coding: utf-8 -*-
"""视觉模块：把 DXF 平面图渲染成图 + 调 DeepSeek 视觉模型读图。

「看/画/检查」三智能体的「看」依赖这里：
- render_floor 把某层平面图渲染成 PNG（墙黑/门红/柱蓝/楼梯绿）；
- client 把图喂给 deepseek-v4-flash-vision-exp 拿回结构化读图结论。
"""
from .client import chat_vision, chat_vision_multi
from .render_floor import render_floor_png
from .cad_reader import read_floor

__all__ = ["chat_vision", "chat_vision_multi", "render_floor_png", "read_floor"]
