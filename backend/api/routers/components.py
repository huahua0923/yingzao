# -*- coding: utf-8 -*-
"""构件分析数据域：把 `backend/recognizer/component_library.py` 摊给前端看。

这是"识别到底按什么规则认构件"的那一屏 —— 11 个构件的签名、参数、踩过的坑，
外加 3 件外部量具（图纸自带面积表 / 填充 / 房间数）。

**为什么直接 import 构件库而不是抄一份到前端**：抄一份就又多了一处
"同一事实两种写法"，改了一边另一边静默过期（memory: dual-representation-shadowed-control）。
`component_library` 模块级只 import math，在只服务模式下也能安全 import ——
所以这里可以直接用它，不必走 JSON 中转。
"""
import math
import sys
from pathlib import Path

from fastapi import APIRouter

from ..responses import ok

router = APIRouter(tags=["components"])

# `recognizer` 是 `backend/` 下的顶层包（不是 `backend.recognizer`），
# 而 run_api.py 只把**仓库根**塞进 sys.path —— 所以 `from recognizer import …`
# 会 ModuleNotFoundError，整个 /api/components 回 500。
# 这里补一次 `backend/`，与 backend/db/rooms_registry.py 的做法一致（它同样要
# import 顶层 `paths`）。只在模块导入时补，且幂等。
_BACKEND_DIR = str(Path(__file__).resolve().parents[2])
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)


def _consts() -> dict:
    """命名常量：识别代码从这里取值，改一处全楼生效。

    白名单式列举，不用 `dir(module)` 反射 —— 反射会把 import 进来的
    `math` 也一起回出去，而且以后新增的模块级变量会**悄悄**出现在 API 里。
    要暴露新常量就得来这加一行，这是特意的。
    """
    from recognizer import component_library as C
    names = ("SLAB_RATIO", "DOOR_LEAF_MIN", "DOOR_LEAF_MAX", "DOOR_SPAN_MAX",
             "JAMB_LEN", "JAMB_W", "WALL_T_OUTER", "WALL_T_INNER",
             "INNER_WALL_CENTROID_FACTOR", "FLOOR_CLUSTER_GAP")
    return {n: getattr(C, n) for n in names if hasattr(C, n)}


@router.get("/components")
def components() -> dict:
    from recognizer import component_library as C
    comps = C.COMPONENTS
    # 只回可 JSON 化的那几栏，并按签名表自己的顺序排列（Python 3.7+ 保序）。
    items = [{"name": k, "signature": v.get("signature"),
              "params": v.get("params") or {}, "pitfalls": v.get("pitfalls") or []}
             for k, v in comps.items()]
    gauges = [{"name": k, "where": v.get("在哪"), "usage": v.get("用法"),
               "why": v.get("为什么"), "pitfall": v.get("坑")}
              for k, v in C.GAUGES.items()]
    return ok({
        "components": items,
        "gauges": gauges,
        "constants": _consts(),
        "floor_cluster_gap_mm": getattr(C, "FLOOR_CLUSTER_GAP", None),
    }, meta={"components": len(items), "gauges": len(gauges),
             "source": "backend/recognizer/component_library.py"})


@router.get("/components/selfcheck")
def selfcheck() -> dict:
    """构件库的**自检**：判据函数的边界落在它该落的那一侧吗。

    为什么要有这一屏：本项目栽过「量程把待检对象滤掉了 —— 边界值本身写错时
    断言也不会红」（memory: vacuous-test-assertions / criterion 系列）。
    这里不重跑识别，只对**纯函数判据**喂探针。

    ★ 这个自检能抓什么、抓不到什么，写清楚了才敢看绿灯：
      · 能抓：**比较运算符写错**（`<` 写成 `<=`、区间开闭反了）、
              前置条件被改掉（`n < 3` 变成 `n < 5` 会让真门被判不是门）、
              常量被改到荒谬值（DOOR_LEAF_MIN 设成 5m 会当场红）。
      · 抓不到：常量"错得自洽"。探针里的边界值是用 `C.DOOR_LEAF_MAX`
                **符号**写的 —— 所以它测的是"边界两侧谁算谁不算"，不是
                "0.6/3.0 这两个数对不对"。后者只能靠外部量具（图纸里门的实际宽度）。
                两处一致证明不了它对（memory: 一个判断四份实现 一类）。
      · 量不到：`is_slab` 内部 import shapely —— 只服务模式（服务器 venv 没装）
                时这一条会报 unavailable，**verdict 就不是 pass**。
                "没量过"和"全过"必须长得不一样（memory: gauge-coverage-invisible-in-summary）。
    """
    from recognizer import component_library as C

    def seg(L, n=3):
        """一条长 L 的开口折线（n>=3 才进 is_door 的分支）。"""
        pts = [(0.0, 0.0), (L, 0.0)]
        for i in range(2, n):
            pts.append((L, 0.0001 * i))
        return pts

    def box(s):
        return [(0.0, 0.0), (s, 0.0), (s, s), (0.0, s), (0.0, 0.0)]

    probes = [
        # 楼板判据：面积/周长 > SLAB_RATIO（严格大于）
        ("is_slab", box(5.0), True, "5×5 方：25/20=1.25 > 1.0 → 填充/楼板"),
        ("is_slab", box(4.0), False, "4×4 方：16/16 恰=1.0 → 阈值是严格大于，不算楼板"),
        ("is_slab", [(0.0, 0.0), (0.2, 0.0), (0.2, 3.0), (0.0, 3.0)],
         False, "0.2×3 墙皮：0.6/6.4=0.09 → 墙，不是楼板"),
        # 门判据：不闭合 + 最长段 ∈ [DOOR_LEAF_MIN, DOOR_LEAF_MAX)
        ("is_door", seg(1.0), True, "门扇线 1.0m → 门"),
        ("is_door", seg(C.DOOR_LEAF_MIN), True, "恰在下界：区间左闭，0.6 算门"),
        ("is_door", seg(C.DOOR_LEAF_MIN - 1e-9), False, "下界内侧一点点 → 不算门"),
        ("is_door", seg(C.DOOR_LEAF_MAX), False, "恰在上界：区间右开，3.0 不算门"),
        ("is_door", seg(C.DOOR_LEAF_MAX - 1e-9), True, "上界内侧一点点 → 算门"),
        ("is_door", seg(0.34), False, "门垛最长段 0.34m → 不是门"),
        ("is_door", [(0.0, 0.0), (1.0, 0.0)], False,
         "★前置条件：只有 2 点时不进判据（n<3 直接 False）—— 它测的是"
         "「点数门槛还在不在」，不是门宽"),
        ("is_door", box(1.0), False, "闭合环 → 不是门（is_door 只管开口折线）"),
        # 纯几何工具
        ("is_closed", box(1.0), True, "首尾点重合 → 闭合"),
        ("is_closed", seg(1.0), False, "开口折线 → 不闭合"),
    ]
    results = []
    for fn, arg, expect, note in probes:
        row = {"fn": fn, "expected": expect, "note": note, "status": None,
               "got": None}
        f = getattr(C, fn, None)
        if f is None:
            row["status"] = "unavailable"
            row["note"] += " ｜构件库里没有这个函数（可能改名了）"
        else:
            try:
                row["got"] = bool(f(arg))
                row["status"] = "pass" if row["got"] == expect else "fail"
            except ImportError as ex:
                # 依赖没装 ≠ 判据错。分开报，别混进 fail 也别混进 pass。
                row["status"] = "unavailable"
                row["note"] += " ｜缺依赖：%s" % ex
            except Exception as ex:                   # noqa: BLE001
                row["status"] = "fail"
                row["note"] += " ｜抛 %s: %s" % (type(ex).__name__, ex)
        results.append(row)
    counts: dict[str, int] = {}
    for r in results:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    verdict = ("fail" if counts.get("fail")
               else "partial" if counts.get("unavailable") else "pass")
    return ok({"probes": results, "counts": counts, "total": len(results)},
              meta={"verdict": verdict,
                    "hint": "探针不过 ⇒ 先怀疑构件库判据，别改这里的期望值"
                            "（期望值照着「它该干什么」写，不是照着现况抄的）"})
