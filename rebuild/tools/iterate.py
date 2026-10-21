# -*- coding: utf-8 -*-
r"""判据迭代账：**每量一次就和上一比**，把「改了以后到底好没好」记成账。

为什么要有它（用户 2026-10-20）：
  「你一定要确保整个的判据和识别修改都能生成一个迭代，不能每次识别出来都不改，
   或者改了以后还是错的。」
  过去判据只在跑的时候打一行读数，没人把它们连成时间线 ⇒
    · 「识别出来不改」看不出来：没人知道同一个红是不是已经红了三周；
    · 「改了以后还是错的」也看不出来：改完又跑一次，红还在，但那一次红和上一次红
      在屏幕上长得一模一样。
  这个工具把每次读数落进 `过程/_ledger/iterate.jsonl`，并与**同一条判据、同一栋楼**
  的上一条对比，直接给判词：修好 / 改善 / 没变 / 变差 / 新出现。

跑法：
    python -X utf8 rebuild/tools/iterate.py --id D-24 --bid c085 --说明 "改 _leak_split 后重建包"
    python -X utf8 rebuild/tools/iterate.py --id D-24 --all          # 全仓逐栋量一遍再比
    python -X utf8 rebuild/tools/iterate.py --id D-24 --bid c085 --看   # 只看，不记账

退出码：0 = 全部修好/改善；1 = 还有红或变差（这就是「改了以后还是错的」）；2 = 读不出。
★ 判定只认**级别计数**，不认读数文字：文字会随阈值变，计数是同一把尺子。
★ 一条判据没有反例、或没有修法，本工具照记，但会在表里点名 —— 那两样缺一，
  这个「绿」就只是一次读数，不是结论。
"""
import argparse
import datetime
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
CDUT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

import defect_scan as DS                                                 # noqa: E402

CAT = os.path.join(CDUT, "rebuild", "构件库", "缺陷库.json")
CASES = os.path.join(CDUT, "rebuild", "构件库", "判据反例.json")
FIXES = os.path.join(CDUT, "rebuild", "构件库", "修正注册表.json")
LEDGER = os.path.join(CDUT, "过程", "_ledger", "iterate.jsonl")
PACK = os.path.join(CDUT, "packs", "cdut-main")


def _load(p, default):
    try:
        with open(p, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:                                                    # noqa: BLE001
        return default


def _det_of(cid):
    for e in _load(CAT, {}).get("条") or []:
        if e.get("id") == cid:
            return e.get("检测器")
    return None


def _history():
    out = []
    try:
        with open(LEDGER, encoding="utf-8") as fh:
            for ln in fh:
                ln = ln.strip()
                if ln:
                    out.append(json.loads(ln))
    except FileNotFoundError:
        pass
    return out


def _count(fs):
    c = {"红": 0, "黄": 0, "提示": 0}
    for f in fs or []:
        lv = f.get("级别")
        if lv in c:
            c[lv] += 1
    return c


def _verdict(now, prev):
    if prev is None:
        return "首次"
    if now["红"] < prev["红"] or (now["红"] == prev["红"] and now["黄"] < prev["黄"]):
        return "改善" if (now["红"] or now["黄"]) else "修好"
    if now["红"] == prev["红"] and now["黄"] == prev["黄"]:
        return "没变"
    return "变差"


def measure(bid, det):
    ctx = DS.Ctx(bid)
    try:
        fs = DS.DETECTORS[det](ctx)
    except Exception as ex:                                              # noqa: BLE001
        return None, "崩了：%s: %s" % (type(ex).__name__, ex)
    if fs is None:
        return None, "未量到（检测器没有可量对象）"
    return fs, "已量"


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("--id", required=True)
    ap.add_argument("--bid")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--说明", default="")
    ap.add_argument("--看", action="store_true", help="只看，不写账")
    a = ap.parse_args(argv)
    det = _det_of(a.id)
    if not det or det not in DS.DETECTORS:
        print("★ %s 没有检测器（%r）—— 迭代无从谈起" % (a.id, det))
        return 2
    DS.load_params()
    bids = ([a.bid] if a.bid else
            sorted(d for d in os.listdir(PACK) if os.path.isdir(os.path.join(PACK, d))))
    if not a.bid and not a.all:
        print("要给 --bid 或 --all")
        return 2

    hist = _history()
    prev_of = {}
    for r in hist:
        if r.get("id") == a.id:
            prev_of[r["bid"]] = r          # 后来的覆盖前面的 ⇒ 拿到最近一条

    rows, recs = [], []
    for bid in bids:
        fs, st = measure(bid, det)
        now = _count(fs)
        prev = prev_of.get(bid)
        v = "未量到" if fs is None else _verdict(now, prev and prev.get("计数"))
        rows.append((bid, st, now, prev, v))
        if not a.看:
            recs.append({"ts": datetime.datetime.now().isoformat(timespec="seconds"),
                         "id": a.id, "bid": bid, "状态": st, "计数": now,
                         "判定": v, "说明": a.说明,
                         "上次ts": (prev or {}).get("ts")})
    print("%-8s %-26s %-22s %-22s %s" % ("栋", "状态", "这一次（红/黄/提示）", "上一次", "判定"))
    for bid, st, now, prev, v in rows:
        p = "%d/%d/%d" % (prev["计数"]["红"], prev["计数"]["黄"], prev["计数"]["提示"]) \
            if prev else "（没有上一条）"
        print("%-8s %-26s %-22s %-22s %s"
              % (bid, st, "%d/%d/%d" % (now["红"], now["黄"], now["提示"]), p, v))

    bad = [r for r in rows if r[2]["红"] > 0 or r[4] in ("变差", "未量到")]
    print("\n%d 栋：红 %d · 改善 %d · 没变 %d · 变差 %d · 未量到 %d"
          % (len(rows), sum(1 for r in rows if r[2]["红"]),
             sum(1 for r in rows if r[4] in ("改善", "修好")),
             sum(1 for r in rows if r[4] == "没变"),
             sum(1 for r in rows if r[4] == "变差"),
             sum(1 for r in rows if r[4] == "未量到")))
    # 缺「反例 / 修法」的判据：读数照样记，但结论不算
    have_case = a.id in {c.get("id") for c in _load(CASES, {}).get("cases") or []}
    fix = (_load(FIXES, {}).get("条") or {}).get(a.id) or {}
    print("这一条的凭据：反例 %s · 修法 %s · 量具 %s"
          % ("有" if have_case else "★没有（绿不算结论）",
             fix.get("修法") or "★没登记（改完也不知道改哪）",
             fix.get("改哪里") or "未登记"))
    if not a.看 and recs:
        os.makedirs(os.path.dirname(LEDGER), exist_ok=True)
        with open(LEDGER, "a", encoding="utf-8", newline="\n") as fh:
            for r in recs:
                fh.write(json.dumps(r, ensure_ascii=False) + "\n")
        print("已记账 %d 行 → %s" % (len(recs), LEDGER))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
