# -*- coding: utf-8 -*-
"""检查用的**外部数据源** —— 引擎自己产出、自己读回的产物。

## 为什么要有这一层

A 层（builtin）不许 import ezdxf，所以它读不到图纸；但"逐层房间数/建筑面积"
这两个数**只有图纸里有**。出路不是让 A 层去猜，也不是让它回一个空的通过，
而是：**让引擎把图纸里的数取出来，落成一份产物，A 层再去读那份产物。**

这一层就是这个"取出来"的工序。产物落在 `data/_meta/area_audit_detail.json`，
每栋楼逐层记 {图纸建筑面积, 图纸房间数, 模型楼板面积, 差值}。

## 现成的一把手（不重造）

`backend/checks/_area_audit.py` 已经能干这件事，且**它是"调试好的代码"，不许改**
（CLAUDE.md 铁律：调试好的代码禁止再修改）。所以这里只做两件事：
  ① 调它（带楼名列表 = 它会多打一段逐层明细）；
  ② 把它的文本输出解析成 JSON —— 解析失败就报"量不到"，绝不编。

★ 2026-09-24 路径变更：这个脚本原在 `_scratch/`，随「中间产物移出仓库」收编进
  `backend/checks/`。**内容一字未动**（搬前搬后 sha256 相同），只换了位置 ——
  所以"不许改"这条仍然成立。凡引用它的地方都要跟着换：那是**路径字符串**，
  不是 import，写错了不会报错，只会在跑的时候说"找不到脚本"。
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

DETAIL_REL = os.path.join("data", "_meta", "area_audit_detail.json")
SCRIPT_REL = os.path.join("backend", "checks", "_area_audit.py")

# `   1层 图纸  6751.30  模型  3892.70  差  -2858.6   房间数 21`
_FLOOR_RE = re.compile(
    r"^\s*(?P<k>\d+)层\s+图纸\s*(?P<a>-?[\d.]+)\s+模型\s*(?P<m>-?[\d.]+)\s+"
    r"差\s*(?P<d>[-+]?[\d.]+)\s+房间数\s*(?P<rooms>\S*)\s*$")
_TITLE_RE = re.compile(r"^---\s+(?P<name>[A-Za-z0-9_-]+)\s+逐层")


def repo_root(data_dir) -> Path:
    return Path(data_dir).resolve().parent


def detail_path(data_dir) -> Path:
    return repo_root(data_dir) / DETAIL_REL


def load_detail(data_dir) -> dict | None:
    """读引擎自己产出的逐层明细。没有就 None（调用方报 UNAVAILABLE）。"""
    p = detail_path(data_dir)
    if not p.is_file():
        return None
    try:
        with open(p, encoding="utf-8") as fh:
            d = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return None
    return d.get("buildings") if isinstance(d, dict) else None


def parse_detail(text: str) -> dict:
    """把 `_area_audit.py <楼...>` 的文本输出解析成 {楼号: [逐层, ...]}。"""
    out: dict[str, list] = {}
    cur = None
    for line in text.splitlines():
        m = _TITLE_RE.match(line)
        if m:
            cur = m.group("name")
            out.setdefault(cur, [])
            continue
        m = _FLOOR_RE.match(line)
        if m and cur:
            rooms = m.group("rooms")
            out[cur].append({
                "drawing_floor": int(m.group("k")),
                "model_floor": int(m.group("k")) - 1,
                "drawing_m2": float(m.group("a")),
                "model_m2": float(m.group("m")),
                "delta_m2": float(m.group("d")),
                # 图纸「房间数」列。空/非数字 → None，不补 0
                # （补 0 会让"没写"看起来像"0 间房"）。
                "drawing_rooms": _int_or_none(rooms),
            })
    return out


def _int_or_none(s) -> int | None:
    """把 `21.0` / `21` 都读成 21；空串、`None`、非数字 → None。

    ★ 这里踩过一个"永远量不到"的坑：原来写的是 `int(s) if s.isdigit() else None`，
    而 `_area_audit.py` 打印的是 `房间数 %s` ← `num()` 出来的 **float**，
    所以屏幕上永远是 `房间数 21.0`，`"21.0".isdigit()` = **False**，
    于是全库 93 栋的 `drawing_rooms` **无一例外都是 null** ——
    不是图纸没这一列（它有，实测 `房间数 = '23'`），是这把量具**永远量不到它自己的被测对象**。
    更坏的是下游 A2 拿着 null 报"没量到，去跑 --audit-all"，
    把人支去重跑一个**结构上不可能产生结果**的作业（memory:
    gauge-coverage-invisible-in-summary：量不到和全对在汇总里长得一样）。
    """
    if s is None:
        return None
    t = str(s).strip()
    if not t or t.lower() in ("none", "nan", "-", "—", "/"):
        return None
    try:
        v = float(t)
    except ValueError:
        return None
    return int(v) if abs(v - round(v)) < 1e-9 else None


def refresh_detail(data_dir, names: list[str], timeout_s: int = 3600) -> dict:
    """现算逐层明细并落盘（原子写）。

    用 `subprocess.run(capture_output=True)` 而不是 PIPE+poll：
    后者在本仓踩过一次死锁（CLAUDE.md 铁律 14，白等 11 分钟）。
    """
    root = repo_root(data_dir)
    script = root / SCRIPT_REL
    if not script.is_file():
        raise FileNotFoundError("对账脚本不在：%s" % SCRIPT_REL)
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    p = subprocess.run([sys.executable, "-u", str(script), *names],
                       cwd=str(root), env=env, timeout=timeout_s,
                       capture_output=True, encoding="utf-8", errors="replace")
    if p.returncode != 0:
        raise RuntimeError("对账脚本退出码 %d：%s"
                           % (p.returncode, (p.stderr or "")[-2000:]))
    buildings = parse_detail(p.stdout or "")
    if not buildings:
        # 解析出 0 栋 ⇒ **多半是量具/格式变了**，不是"全库都没数据"。
        # 这两种在屏幕上一样，所以这里要抛出来（memory: gbk-mangled-log-units 同族）。
        raise RuntimeError("对账脚本跑完了，但一栋楼都没解析出来 —— "
                           "多半是输出格式变了，别当成『全库无数据』")
    payload = {"buildings": buildings, "names": names,
               "count": len(buildings)}
    _atomic_json(detail_path(data_dir), payload)
    return payload


def _atomic_json(path: Path, payload: dict) -> None:
    """tmp + os.replace。直写会截成 0 字节（memory: atomic-artifact-write）。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=1)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
