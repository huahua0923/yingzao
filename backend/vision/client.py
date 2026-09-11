# -*- coding: utf-8 -*-
"""DeepSeek 视觉模型客户端：图（PNG bytes）→ 文本。

走 DeepSeek OpenAI 兼容端点，模型 deepseek-v4-flash-vision-exp（本机唯一能收图的模型，
见 memory/deepseek-claude-code-gateway）。主会话模型 deepseek-v4-pro 是纯文本、收图静默
失效，所以「看」必须经这里直连视觉模型，不能靠 Claude Code 会话内贴图。
"""
import os
import json
import base64
import urllib.request

VISION_MODEL = "deepseek-v4-flash-vision-exp"
ENDPOINT = "https://api.deepseek.com/chat/completions"
# 该模型会先输出英文 CoT（reasoning_content）再写 answer（content）。max_tokens 太小会
# 把预算全烧在推理上、content 为空、finish_reason="length"。实测「数门/数柱」类提示词
# 推理会逐项枚举、单层能吃掉 6000+ token，故默认给足 16000，保证拿到 content。
DEFAULT_MAX_TOKENS = 16000


def _api_key(key):
    key = key or os.environ.get("DEEPSEEK_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")
    if not key:
        raise RuntimeError("缺少 DEEPSEEK_API_KEY 环境变量（视觉模型调用需要）")
    return key


def _post(payload, key, timeout):
    req = urllib.request.Request(
        ENDPOINT,
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def _image_content(image_bytes, mime="image/png"):
    b64 = base64.b64encode(image_bytes).decode()
    return {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}}


def chat_vision(image_bytes, prompt, *, model=VISION_MODEL, max_tokens=DEFAULT_MAX_TOKENS,
                key=None, timeout=180, mime="image/png"):
    """单图 + 提示词 → 文本。image_bytes 为 PNG/JPEG 原始字节。"""
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": [
            {"type": "text", "text": prompt},
            _image_content(image_bytes, mime),
        ]}],
        "max_tokens": max_tokens,
    }
    d = _post(payload, _api_key(key), timeout)
    return d["choices"][0]["message"]["content"]


def chat_vision_multi(images, prompt, *, model=VISION_MODEL, max_tokens=DEFAULT_MAX_TOKENS,
                      key=None, timeout=180):
    """多图 + 提示词 → 文本。images = [(bytes, mime), ...]（如 GLB 渲染图 + 原始平面图比对）。"""
    content = [{"type": "text", "text": prompt}]
    for img in images:
        if isinstance(img, (bytes, bytearray)):
            content.append(_image_content(img))
        else:
            content.append(_image_content(img[0], img[1] if len(img) > 1 else "image/png"))
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": content}],
        "max_tokens": max_tokens,
    }
    d = _post(payload, _api_key(key), timeout)
    return d["choices"][0]["message"]["content"]
