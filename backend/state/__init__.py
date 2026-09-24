# -*- coding: utf-8 -*-
"""系统状态层 —— 「现在是什么状态」，只许从这里取数。

与 `backend/checks/` 的分工，一条线划清：

    checks/   「**应该**是什么样」 —— 判据、门槛、红/绿。它**质询**。
    state/    「**现在**是什么样」 —— 口径、计数、账。它**只陈述，不判**。

为什么非要分开：`census.py` 量出 `floors_delivered=456`，
而 C1 判据负责说「这个数跟另一个来源对不上」。**量的人和判的人不是同一个**，
否则「量具坏了」和「被测对象坏了」永远分不开（本仓 memory 记过这一族坑）。

目前只有一个模块：

    census.py   全库口径的唯一计算者 → data/_meta/state.json
                CLI: 无参=现算并落盘 / --print / --compare <基线> / --selftest
"""
from __future__ import annotations
