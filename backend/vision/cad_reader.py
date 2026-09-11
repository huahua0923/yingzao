# -*- coding: utf-8 -*-
"""「看」智能体：把某层平面图渲染成图 → 视觉模型读图 → 结构化 JSON。

输出是「读图结论」，跟 recognizer 几何流水线的结果做交叉核对：视觉模型独立地读图，
两者在门数/楼梯数/柱数/外墙形状上不一致的地方就是流水线可疑点（对齐 SU「人眼看图」）。
注意视觉模型图里没有比例尺，不能精确量米数——米数仍以几何流水线为准，这里只出「形状、
外墙 vs 内墙、门/梯/柱数量与位置」这类定性结论。
"""
import json
import re

from .client import chat_vision
from .render_floor import render_floor_png

READER_PROMPT = (
    "这是一张建筑 CAD 平面图（黑色=墙、红色=门、蓝色=柱、绿色=楼梯，单位米）。"
    "请像建筑师读图一样，只基于图中实际看到的，输出严格 JSON（不要 markdown 代码块，不要解释）：\n"
    '{\n'
    '  "shape": "建筑外轮廓形状的简短描述（如 矩形/凸字形/凹字形/U形，有没有凹凸或翼楼）",\n'
    '  "facade_notes": "外墙是否闭合、沿外轮廓是否连续，有无缺口",\n'
    '  "door_external": <贴外轮廓的门大致数量，整数，粗略即可>,\n'
    '  "door_internal": <内部隔墙上的门大致数量，整数，粗略即可>,\n'
    '  "stairs": <楼梯间大致数量，整数>,\n'
    '  "columns": <结构柱大致数量，整数>,\n'
    '  "confidence": "高/中/低（图是否清晰可辨）"\n'
    '}\n'
    "数量给大致值即可（误差 ±几 没关系），不要逐项精确清点。只输出这一个 JSON 对象。"
)


def _extract_json(text):
    """从模型回答里抠出 JSON 对象（容错 markdown 代码块 / 前后杂字）。"""
    text = text.strip()
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        # 去掉 ```json ... ``` 再试
        clean = re.sub(r"^```[a-zA-Z]*\s*|\s*```$", "", text.strip())
        m = re.search(r"\{.*\}", clean, re.DOTALL)
        if not m:
            return None
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            return None


def read_floor(p, F, *, out_path=None):
    """渲染 F 层 → 视觉模型读图 → 返回 (dict, raw_text)。dict 解析失败时返回 (None, raw)。"""
    png = render_floor_png(p, F, out_path=out_path)
    raw = chat_vision(png, READER_PROMPT)
    return _extract_json(raw), raw
