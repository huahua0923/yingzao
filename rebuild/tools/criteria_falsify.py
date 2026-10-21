# -*- coding: utf-8 -*-
r"""判据伪证器：把 `构件库/判据反例.json` 里每条「已知确有缺陷」的输入喂给判据，看它报不报。

为什么要有这个（铁律 183 / 用户 2026-10-20「判据有没有发挥它的作用」）：
  · 一条判据在别处报绿，**不能证明它对**；只有在一条已知坏的输入上报红过，那个绿才算数。
  · 判据改过以后（阈值/量具/逻辑三处任一），不重跑反例就不知道有没有把它改成永远绿。

跑法：
    python -X utf8 rebuild/tools/criteria_falsify.py            # 跑全部反例
    python -X utf8 rebuild/tools/criteria_falsify.py --id D-19  # 只跑一条

退出码：0 = 全部命中；1 = 有反例没报出来（判据失灵或阈值漂了）；2 = 反例文件读不出。
★ 不打印「全绿」当结论：没反例的判据单独点名（那条判据的绿没有依据）。
"""
import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
CDUT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
import defect_scan as DS                                                 # noqa: E402

CAT = os.path.join(CDUT, "rebuild", "构件库", "缺陷库.json")
CASES = os.path.join(CDUT, "rebuild", "构件库", "判据反例.json")


def detectors():
    """id → 检测器名（从缺陷库现读，不手抄）。"""
    with open(CAT, encoding="utf-8") as fh:
        return {e["id"]: e.get("检测器") for e in json.load(fh)["条"]}


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("--id", action="append", default=None)
    a = ap.parse_args(argv)
    try:
        with open(CASES, encoding="utf-8") as fh:
            j = json.load(fh)
    except Exception as ex:                                            # noqa: BLE001
        print("★ 反例文件读不出：%s" % ex)
        return 2
    cases = [c for c in j.get("cases") or [] if not a.id or c["id"] in a.id]
    det_of = detectors()
    DS.load_params()

    by_bid = {}
    for c in cases:
        by_bid.setdefault(c["bid"], []).append(c)

    bad = 0
    for bid, cs in sorted(by_bid.items()):
        ctx = DS.Ctx(bid)
        cache = {}
        for c in cs:
            det = det_of.get(c["id"])
            if not det or det not in DS.DETECTORS:
                print("[%s] %s %s：**没有检测器**（%s）—— 反例无从验证" %
                      ("缺", c["id"], bid, det))
                bad += 1
                continue
            if det not in cache:
                try:
                    cache[det] = DS.DETECTORS[det](ctx)
                except Exception as ex:                                # noqa: BLE001
                    cache[det] = "崩了：%s: %s" % (type(ex).__name__, ex)
            f = cache[det]
            if isinstance(f, str):
                print("[崩] %s %s：%s" % (c["id"], bid, f))
                bad += 1
                continue
            # ★ 层号一律按**字符串**比：D-24 那边层是整数 2，反例写的是 "2"，
            #   直接 `in` 比会永远不命中（2026-10-20 实测：反例明明报了红却判「失灵」）。
            want = None if c.get("层") is None else str(c.get("层"))
            hit = [x for x in f
                   if (want is None or want == str(x.get("层")))
                   and x.get("级别") == c.get("级别")]
            if hit:
                print("[中] %s %s %s → %s：%s" %
                      (c["id"], bid, c.get("层"), c["级别"],
                       str(hit[0].get("读数") or "")[:70]))
            else:
                got = sorted({(x.get("层"), x.get("级别")) for x in f})
                print("[★没报] %s %s %s 应报 %s，实际：%s" %
                      (c["id"], bid, c.get("层"), c["级别"], got or "0 条"))
                bad += 1

    no_case = j.get("还没有反例的判据") or []
    print("\n反例 %d 条 · 命中 %d · 失灵 %d" % (len(cases), len(cases) - bad, bad))
    if no_case:
        print("★ 没有反例的判据 %d 条（它们的绿没有依据，不许当结论）：%s"
              % (len(no_case), " ".join(no_case)))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
