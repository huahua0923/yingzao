# -*- coding: utf-8 -*-
"""检查结果的词汇表 —— 系统自带检查的输出类型。

**为什么"没量成"必须是一个独立状态**：这是本项目反复栽的坑。
汇总表里「没量过」和「全对」长得一模一样（memory: gauge-coverage-invisible-in-summary），
于是 45 栋交付 0 间房能安安静静地待在库里没人发现。

所以这里把结局分成四种，且**在类型层面就不允许合并**：

    PASS         量过，合规
    WATCH        量过，可疑（接近门槛，或有已知合理解释，需人拍板）
    GAP          量过，确定不合规
    UNAVAILABLE  **没量成**（缺依赖 / 缺输入 / 量具自己崩了）
    NOT_APPLICABLE  本来就不该量（单层楼没有"上下贯通"这回事）

汇总规则（`rollup`）只有一条需要记住：
**UNAVAILABLE 会污染整组结论，让它变成 INCOMPLETE 而不是 PASS。**
"有一项没量成"整体就不算通过 —— 否则子系统会用沉默换绿灯。
"""
from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Any


class Status(str, enum.Enum):
    PASS = "pass"
    WATCH = "watch"
    GAP = "gap"
    UNAVAILABLE = "unavailable"
    NOT_APPLICABLE = "na"


class Verdict(str, enum.Enum):
    PASS = "pass"
    INCOMPLETE = "incomplete"      # 有项目没量成 —— 不等于通过
    WATCH = "watch"
    FAIL = "fail"


# 汇总时的优先级：数值越大越"该被看见"。
# GAP 压过 WATCH，WATCH 压过 UNAVAILABLE —— 但 UNAVAILABLE 压过 PASS。
_ORDER = {Status.PASS: 0, Status.NOT_APPLICABLE: 0,
          Status.UNAVAILABLE: 1, Status.WATCH: 2, Status.GAP: 3}


@dataclass
class Finding:
    """一条检查结论。"""
    check: str                      # 检查编号，如 "A1.rooms_vs_drawing"
    title: str                      # 人话标题
    status: Status
    detail: str = ""                # 一句话说明（会显示给用户）
    floor: int | None = None        # 属于哪层；None = 整栋级
    evidence: dict[str, Any] = field(default_factory=dict)   # 数值证据，供逐位核对
    # 计量口径：这道判据量的到底是什么。★ 必须写 ——
    # 本项目的"面积"至少有四个口径（楼板足迹 / 建筑面积 / 使用面积 / 房间面积和），
    # 混用一次就得出过一个错结论（memory: lihua-standardization-done ★面积四口径绝不许混用）。
    measure: str = ""
    # 量不成的原因（只有 UNAVAILABLE 用）
    blocked_by: str = ""

    def as_dict(self) -> dict:
        d = {"check": self.check, "title": self.title, "status": self.status.value,
             "detail": self.detail, "floor": self.floor, "measure": self.measure,
             "evidence": self.evidence}
        if self.blocked_by:
            d["blocked_by"] = self.blocked_by
        return d


@dataclass
class Report:
    """一栋楼（或一次全库）的检查报告。"""
    scope: str                      # "building:c113" / "fleet"
    findings: list[Finding] = field(default_factory=list)
    meta: dict[str, Any] = field(default_factory=dict)

    def add(self, f: Finding) -> Finding:
        self.findings.append(f)
        return f

    def counts(self) -> dict[str, int]:
        c: dict[str, int] = {}
        for f in self.findings:
            c[f.status.value] = c.get(f.status.value, 0) + 1
        return c

    def rollup(self) -> str:
        """整组结论。

        ★ 顺序不是"取最严重的那个"：**只要有 UNAVAILABLE 且没有 GAP**，
        结论是 INCOMPLETE 而不是 PASS —— 「没量成」必须能压掉绿灯。
        但 GAP 更该被看见（确定的缺陷比"没量"更紧急），所以 GAP 在上。
        """
        st = {f.status for f in self.findings if f.status != Status.NOT_APPLICABLE}
        if not st:
            return Verdict.PASS.value if self.findings else Verdict.INCOMPLETE.value
        if Status.GAP in st:
            return Verdict.FAIL.value
        if Status.WATCH in st:
            # WATCH 与 UNAVAILABLE 同时存在时，回 INCOMPLETE：
            # 连没量成的东西都可能藏着一个 WATCH，别急着给结论。
            return (Verdict.INCOMPLETE.value if Status.UNAVAILABLE in st
                    else Verdict.WATCH.value)
        if Status.UNAVAILABLE in st:
            return Verdict.INCOMPLETE.value
        return Verdict.PASS.value

    def blockers(self) -> list[dict]:
        """拦交付的项。只有 GAP 拦；WATCH/UNAVAILABLE 只提示。"""
        return [f.as_dict() for f in self.findings if f.status == Status.GAP]

    def by_floor(self) -> dict[str, list[dict]]:
        out: dict[str, list[dict]] = {}
        for f in self.findings:
            out.setdefault("F%d" % f.floor if f.floor is not None else "整栋",
                           []).append(f.as_dict())
        return out

    def as_dict(self) -> dict:
        return {
            "scope": self.scope,
            "verdict": self.rollup(),
            "counts": self.counts(),
            "deliverable": not self.blockers(),
            "blockers": self.blockers(),
            "findings": [f.as_dict() for f in self.findings],
            "by_floor": self.by_floor(),
            "meta": self.meta,
        }


def unavailable(check: str, title: str, why: str, **kw) -> Finding:
    """没量成的标准写法。**特意做成函数** —— 让"量不到"好写，
    这样就没有人会图省事直接 return PASS 把它糊过去。"""
    return Finding(check=check, title=title, status=Status.UNAVAILABLE,
                   detail=why, blocked_by=why, **kw)
