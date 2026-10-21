# -*- coding: utf-8 -*-
r"""把 D-19/20/21 的阈值**由账本现算**，写进 `参数.json::缺陷扫描`（不手抄）。

为什么要有它（铁律 103/174）：
  2026-10-20 第一版阈值我在注释里手写了「p95 0.41% / p99 1.98%」—— 那是错的
  （实测 p95 1.06%）。结果 64 栋里 62 栋都有一层黄：**一个谁都黄的东西等于没报**。
  手打的数会把「阈值声明错了」报成「模型有缺陷」，所以阈值只能由程序从实测分布算。

标定口径（每层一个比值，按层取分位，不是按点）：
  · 黄 = p95   —— 全仓最差的 5% 的层，进「值得看一眼」清单
  · 红 = p99.5 —— 全仓最差的 0.5% 的层
为什么不用「按点」：点是采样密度，层才是人修的单位；按点算会被大楼层的点数吃掉小层。

⚠ 这是**相对**标定：它排序，不判对错。红的层是「比全仓 99.5% 的层都差」，
  不等于「一定错」；判据的用处是**把注意力按坏的程度排好**，再由人裁。

用法：
    python -X utf8 rebuild/tools/calibrate_cov_thresholds.py            # 只打印
    python -X utf8 rebuild/tools/calibrate_cov_thresholds.py --apply    # 写参数.json（LF 写盘）
"""
import argparse
import io
import json
import os
import sys

import numpy as np

CDUT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
LEDGER = os.path.join(CDUT, "过程", "_ledger", "cov-why.jsonl")
PARAMS = os.path.join(CDUT, "rebuild", "构件库", "参数.json")

# 参数名 → (账本字段, 分母字段, 说明)。★ 账本 `类` 里是**全名**，不是简称：
#   写简称取不到值 ⇒ 分位数算出来是空的（2026-10-20 实测踩过，静默跳过）。
# 第三项 = 计数住在哪儿：`类` 里（归因分账）还是顶层（直接量的）。
# ★ 2026-10-20 踩过：无件/偏了住在 `类` 里，我按顶层 `r.get(num)` 取 ⇒ 359 行全 None
#   ⇒ 阈值算成 0.0，还「看起来像算出来了」。同名的键在两个位置（铁律 018/174）。
SPEC = {
    "dxf_漏墙": ("那里没有件（>1 m）", "源点", "类", "源图上有、件里 1 m 内什么都没有"),
    "dxf_多墙": ("多墙点", "生成点", "顶层", "件里有、源图 300 mm 内没有"),
    "dxf_偏了": ("有件但偏了（300–1000 mm）", "源点", "类", "件在，但离源线 0.3~1 m"),
}
Q_黄, Q_红 = 95.0, 99.5


def rates(rows, num, den, where):
    """逐层比值。`num` 只从 `where` 指的那一处取（铁律 018：同名两处必须死掉一个）。

    账本里**没有这个类**的键，只有在「分账闭合」时才算 0。
    为什么不能一律当 0（铁律 199：没量到 ≠ 0）：
      账本的 `类` 只写观察到的类。假如某次普查漏记了一类，缺键会被当成 0，
      分位数就往低里算 —— 阈值越松，判据越绿，错得越静默。
    为什么可以当 0（2026-10-20 实测）：
      五类互斥且穷尽，359 层**逐层**满足 sum(类) == 漏点（0 层不闭合）；
      所以缺键 = 这一类一个点都没有，是**量出来的 0**，不是没量。
    闭合不了的那层直接跳过（记 `n_skip`），不参与分位。
    """
    v = []
    n_skip = 0
    for r in rows:
        if "err" in r:
            continue
        d = r.get(den) or 0
        n = (r.get("类") or {}).get(num) if where == "类" else r.get(num)
        if n is None:
            cat = r.get("类") or {}
            if where != "类" or sum(cat.values()) != r.get("漏点"):
                n_skip += 1
                continue
            n = 0
        if n < 0 or not d:                   # -1 = 没量到，不是 0
            continue
        v.append(n / d)
    if n_skip:
        print("  ★ %s：%d 层缺这个数且分账不闭合（缺键不能当 0），已跳过" % (num, n_skip))
    return np.asarray(v, dtype=float)


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args(argv)
    try:
        rows = [json.loads(ln) for ln in io.open(LEDGER, encoding="utf-8") if ln.strip()]
    except Exception as ex:                                            # noqa: BLE001
        print("★ 账本读不出：%s" % ex)
        return 2
    ok = [r for r in rows if "err" not in r]
    print("账本 %s：%d 层（失败 %d）" % (LEDGER, len(ok), len(rows) - len(ok)))
    out = {}
    for key, (num, den, where, why) in SPEC.items():
        v = rates(rows, num, den, where)
        if not len(v):
            print("★ %s：一层都量不到 ⇒ 不写阈值（没量到不是 0）" % key)
            continue
        y, r = float(np.percentile(v, Q_黄)), float(np.percentile(v, Q_红))
        out[key + "_黄"] = round(y, 4)
        out[key + "_红"] = round(r, 4)
        print("  %-8s %-22s n=%3d  黄 p95 %.4f  红 p99.5 %.4f  最大 %.4f"
              % (key, why, len(v), y, r, float(v.max())))
    if not a.apply:
        print("\n（预演，没写盘；加 --apply 写 参数.json）")
        return 0
    with io.open(PARAMS, encoding="utf-8") as fh:
        p = json.load(fh)
    ps = p.setdefault("缺陷扫描", {})
    ps.update(out)
    with io.open(PARAMS, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(p, fh, ensure_ascii=False, indent=1)
        fh.write("\n")
    print("\n已写 %s（LF 写盘）：%s" % (PARAMS, json.dumps(out, ensure_ascii=False)))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
