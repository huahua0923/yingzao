# -*- coding: utf-8 -*-
"""把 kb/src/*.md 打包成单一 kb.json（供识别引擎/前端/LLM 检索）。

用法:
  python kb/build_kb.py              # 写 kb/kb.json
"""
import json
import os
import re
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

KB = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(KB, "src")
OUT = os.path.join(KB, "kb.json")

# 每个 md 的标题 → 稳定 slug（LLM 检索用）
def slug(title):
    t = re.sub(r"[^\w一-鿿]+", "-", title).strip("-").lower()
    return t or "untitled"


def title_of(text):
    for line in text.splitlines():
        m = re.match(r"^#\s+(.+)$", line)
        if m:
            return m.group(1).strip()
    return "untitled"


def main():
    manifest = json.load(open(os.path.join(SRC, "manifest.json"), encoding="utf-8"))
    sections = []
    for fname in manifest["order"]:
        path = os.path.join(SRC, fname)
        if not os.path.exists(path):
            print(f"跳过缺失 {fname}")
            continue
        text = open(path, encoding="utf-8").read()
        title = title_of(text)
        sections.append({
            "slug": slug(title),
            "title": title,
            "file": fname,
            "markdown": text,
        })
    out = {
        "title": manifest["title"],
        "description": manifest["description"],
        "version": manifest["version"],
        "sections": sections,
    }
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(f"已写 {OUT}：{len(sections)} 节，{sum(len(s['markdown']) for s in sections)} 字符")


if __name__ == "__main__":
    main()
