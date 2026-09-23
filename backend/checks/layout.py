# -*- coding: utf-8 -*-
"""产物在磁盘上的摆法 —— **全包唯一一份**。

★ 为什么值得单独一个模块：这里曾经有**两个同名、契约不同**的 `_floor_files`
—— builtin 的那个收「楼目录」（内部再拼 `floors/`），heavy 的那个收
「floors 目录」。两个都能 import、都能跑，给错参数**不报错，返回空列表**，
于是屏幕上显示"没有楼层文件"，看起来像**数据缺失**，实际是调用方传错了路径
（CLAUDE.md 铁律 16：量具坏了和被测量对象是空的，在屏幕上长得一样；
memory: dual-representation-shadowed-control 同族的坑）。

出路不是"记得传对"，是**让签名本身没有歧义**：统一收 `(data_dir, 楼名)`，
调用方手里根本没有"某个目录"可以传错。契约写在名字里，不写在注释里。
"""
from __future__ import annotations

import re
from pathlib import Path

# 交付楼层的文件名：floor0.json、floor1.json ...
FLOOR_RE = re.compile(r"^floor(\d+)\.json$")
FLOOR_GLOB = "floor*.json"


def buildings_dir(data_dir) -> Path:
    return Path(data_dir) / "buildings"


def building_dir(data_dir, name: str) -> Path:
    """某栋楼的产物目录：`<data>/buildings/<楼号>/`。"""
    return buildings_dir(data_dir) / name


def floors_dir(data_dir, name: str) -> Path:
    return building_dir(data_dir, name) / "floors"


def floor_files(data_dir, name: str) -> list[tuple[int, Path]]:
    """该栋楼的逐层 JSON，按层号升序：[(0, path0), (1, path1), ...]。

    只认 `floor<数字>.json`。**不连续也照收**：这里不做"是不是从 0 开始连续"
    的判断，那是各条检查自己的判据（有的楼首层就是 F1）。
    """
    d = floors_dir(data_dir, name)
    if not d.is_dir():
        return []
    out = []
    for p in d.iterdir():
        m = FLOOR_RE.match(p.name)
        if m:
            out.append((int(m.group(1)), p))
    return sorted(out)
