# -*- coding: utf-8 -*-
"""视觉模块：把某层平面图渲染成 PNG（墙黑/门红/柱蓝/楼梯绿）。

★ 2026-09-14 清理：这里原先还 import `client`（DeepSeek 视觉模型）与 `cad_reader`
（「看」智能体读图）。那两条链**全仓零消费者**，副作用却是 `import vision` 必须
装齐 ezdxf + matplotlib + requests —— `backend/web/control.py` 之所以把 import
塞进函数体里，根因就是这个包级副作用。现在只留真正被用的 `render_floor`。
被移走的 5 个文件在 `_scratch/legacy/2026-09-14-cleanup/`。
"""
from .render_floor import render_floor_png

__all__ = ["render_floor_png"]
