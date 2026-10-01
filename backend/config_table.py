# -*- coding: utf-8 -*-
"""按楼配置表 `config/buildings.json` 的读取口 —— 「单独流程」的落点。

## 为什么要有这一层

`ID_BASE` / `LAYER_ROLE_OVERRIDE` / `PURPOSE_DROP_AREA_LIKE` 原来是**硬编码**在
`extract/extract_rooms_generic.py` 里的三张 Python 字典。后果实测过：

    目录数 95 / ID_BASE 键数 77 / 不在表里的 18 栋
    ⇒ 那 18 栋的 rooms.json **18/18 全是空数组**

它们不是识别不出来，是**代码里没给它们留位置** —— 而「没留位置」在屏幕上跟
「这栋楼没有房间」长得一模一样。把名单搬进配置，是为了让它成为一个**可以改的输入**，
而不是一个只能由改代码来改的事实。

## 生效方式（先配置、后旧表）

读得到 `config/buildings.json` 就用它；缺键的楼**回落**到代码里的旧表。
⇒ 引入本模块**不改变任何现有行为**（配置是照旧表逐条生成的）。
⇒ 想让某栋楼生效，改 JSON 即可，不用碰 .py。

## ★ 段基址缺了不许兜底

旧代码写的是 `ID_BASE.get(name, 1000000)` —— 而 **`1000000` 已经被 `c104` 占用**。
所以那个兜底不是「安全的默认值」，是**一次静默的主键相撞**：
谁要是靠它跑通了，跑出来的 18 栋楼会和 c104 的房间 id 重叠。
⇒ 本模块返回 `None` 表示「没给」，由调用方决定怎么办（现在是跳过并出声），
   **不许**在这里发明一个默认值。
"""
import json
import os

from paths import ROOT

CONFIG = os.path.join(str(ROOT), "config", "buildings.json")

# 代码里的旧表（回落用）。延迟导入，避免本模块在没装 ezdxf 的环境里也炸。
_LEGACY = None


def _legacy():
    global _LEGACY
    if _LEGACY is None:
        import ast
        import io
        p = os.path.join(str(ROOT), "backend", "extract", "extract_rooms_generic.py")
        try:
            tree = ast.parse(io.open(p, encoding="utf-8").read())
            d = {}
            for n in ast.walk(tree):
                if isinstance(n, ast.Assign):
                    for x in n.targets:
                        if getattr(x, "id", None) in (
                                "ID_BASE", "LAYER_ROLE_OVERRIDE", "PURPOSE_DROP_AREA_LIKE"):
                            d[x.id] = ast.literal_eval(n.value)
            _LEGACY = d
        except Exception:  # noqa: BLE001
            _LEGACY = {}
    return _LEGACY


_CFG = None


def _cfg():
    global _CFG
    if _CFG is None:
        try:
            with open(CONFIG, encoding="utf-8") as f:
                _CFG = json.load(f)
        except Exception:  # noqa: BLE001
            _CFG = {}
    return _CFG


def reload():
    """改了 config/buildings.json 之后强制重读（长驻进程用；命令行每次跑都是新进程，不用管）。"""
    global _CFG
    _CFG = None
    return _cfg()


def entry(name):
    """该楼的配置条目（dict）。读不到返回 {}。"""
    return (_cfg().get("buildings") or {}).get(name) or {}


def layer_role():
    """全局层角色默认（不按楼）：{"5":"area","6":"number","7":"purpose","8":"dept"}。"""
    return _cfg().get("layer_role") or _legacy().get("LAYER_ROLE", {})


def room_id_base(name):
    """房间 id 段基址。

    ★ 返回 None = 「这栋楼没给段基址」，**不是 0、也不是 1000000**。
      调用方必须显式处理 —— 兜底值会和 c104 撞主键（见模块 docstring）。
    """
    v = entry(name).get("room_id_base")
    if v is not None:
        return int(v)
    v = _legacy().get("ID_BASE", {}).get(name)
    return int(v) if v is not None else None


def layer_role_override(name):
    """该楼的层角色覆盖。键可为数字前缀("7")或精确层名("7使用单位")；值 None = 剔除该层。"""
    v = entry(name).get("layer_role_override")
    if v is not None:
        return v
    return _legacy().get("LAYER_ROLE_OVERRIDE", {}).get(name, {})


def purpose_drop_area_like(name):
    """该楼「层里混装用途与面积串」的层名集合；没有则 None（与旧代码口径一致）。"""
    v = entry(name).get("purpose_drop_area_like")
    if v is not None:
        return set(v)
    s = _legacy().get("PURPOSE_DROP_AREA_LIKE", {}).get(name)
    return set(s) if s else None


def named_buildings():
    """本配置表覆盖到的楼（按 段基址 是否存在排序：有段基址的在前）。

    `--all` 用这个而不是 `sorted(ID_BASE)` —— 名单从代码里搬到了配置里。
    """
    b = _cfg().get("buildings") or {}
    if not b:
        return sorted(_legacy().get("ID_BASE", {}))
    return sorted(b, key=lambda n: (room_id_base(n) is None, n))


def with_base():
    """有段基址的楼（= 抽得出房间的那些）。"""
    return [n for n in named_buildings() if room_id_base(n) is not None]


def without_base():
    """★ 没有段基址的楼 —— 这些楼的 rooms.json 会是空数组。**要出声，不许静默跳过。**"""
    return [n for n in named_buildings() if room_id_base(n) is None]


__all__ = ["CONFIG", "reload", "entry", "layer_role", "room_id_base",
           "layer_role_override", "purpose_drop_area_like",
           "named_buildings", "with_base", "without_base"]
