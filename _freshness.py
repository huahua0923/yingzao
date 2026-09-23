# -*- coding: utf-8 -*-
"""产物新鲜度门禁（**只读**，不写任何产物）。

为什么需要
----------
2026-09-14 实测：出图/交付产物与它们的输入之间**没有任何门禁**，而错法是静默的 ——

  · c006 第 7 层（内部 F6）：`dxf_plan/index.html` 与 `compare.html` 的 caption 写
    「门 86 / 楼梯井 2 / 房间 28」，同一栋的 `dxf_plan_recog/floor6.png` 图里画的却是
    「door=33 / stairwell=8 / rooms=6」—— **同一个对照页上，图是新的、字是旧的**，
    而这一页的用途恰恰是"对照真值找识别问题"。
  · 全库普查：A 页 40/49 过期（最久 4.6 天）、`compare.html` **49/49 全过期**、
    `rooms.json` 44/49、GLB 5/49（含 README 已知的 c103）。
  · 根因：计数是**烘焙进 HTML 的快照**，只有重跑出图脚本才更新；而 floors 天天在改。
    判据其实早就存在（`_dxf_compare_render.py` 的"缺或比 floor JSON 旧才重画"），
    只是散在各处、没有一处汇总，于是没人看得出"这一页该重跑了"。

判据（与出图脚本同一套口径，不另立新规）
----------------------------------------
**输入 = 该栋最新 `floors/floor*.json` 的 mtime**（无论改哪一层，都要求下游重出 ——
宁可多报，不可漏报；A 页的 PNG 也用 floors 的 outline 当裁切盒，见 `collect_floor`）。

  产物                                  依赖       等级
  <楼>/dxf_plan/index.html               floors     FAIL   计数快照
  <楼>/dxf_plan/floor*.png               floors     FAIL   裁切盒用的是 floors 的 outline
  <楼>/dxf_plan_recog/floor*.png         floors     FAIL   直接画 floors 的内容
  <楼>/dxf_plan_recog/index.html         floors     FAIL   计数快照
  <楼>/compare.html                      floors     FAIL   计数快照
  <楼>/<名>-building.glb                 floors     FAIL   交付模型
  <楼>/rooms.json                        floors     WARN   口径未定（见 README「rooms.json 侧
                                                             的自交环从未清洗过」），
                                                             只提醒不判死
  data/buildings/_dxf_index.html         全库 floors FAIL   A 页总目录
  data/buildings/_dxf_compare.html       全库 floors FAIL   对照总目录

★ WARN 不计入退出码：`rooms.json` 与 floors 本来就不同源（README 已记档），
  把它算成 FAIL 会天天红、红到没人看。

用法
----
    python -u _freshness.py                # 全库
    python -u _freshness.py c006 c009      # 只看指定楼
    python -u _freshness.py --quiet        # 只印过期项
退出码：有过期 FAIL 项 → 1；否则 0。
"""
import glob
import os
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

BASE = r"D:\gym3d\data\buildings"

#: (相对 <楼目录> 的路径模式, 等级, 说明)。模式按 sorted 展开，空 = 该产物缺失。
PRODUCTS = [
    ("dxf_plan/index.html", "FAIL", "A 页(计数快照)"),
    ("dxf_plan/floor*.png", "FAIL", "A 图(裁切盒取 floors 的 outline)"),
    ("dxf_plan_recog/floor*.png", "FAIL", "B 图(直接画 floors)"),
    ("dxf_plan_recog/index.html", "FAIL", "B 页(计数快照)"),
    ("compare.html", "FAIL", "A|B 对照页(计数快照)"),
    ("*-building.glb", "FAIL", "交付 GLB"),
    ("rooms.json", "WARN", "房间表(与 floors 不同源, 只提醒)"),
]

MASTERS = [
    ("_dxf_index.html", "FAIL", "源图纸总目录"),
    ("_dxf_compare.html", "FAIL", "对照总目录"),
]


def mt(path):
    try:
        return os.path.getmtime(path)
    except OSError:
        return None


def floor_input_time(bdir):
    """该栋的「输入时刻」= 最新 floor*.json 的 mtime；没有 floors 返回 None。"""
    fs = glob.glob(os.path.join(bdir, "floors", "floor*.json"))
    ts = [t for t in (mt(f) for f in fs) if t]
    return (max(ts), len(fs)) if ts else (None, 0)


def lag_str(sec):
    if sec < 90:
        return "%.0f 秒" % sec
    if sec < 5400:
        return "%.1f 分" % (sec / 60.0)
    if sec < 86400 * 2:
        return "%.1f 小时" % (sec / 3600.0)
    return "%.1f 天" % (sec / 86400.0)


def check_building(name, quiet=False):
    """返回 (fail 行 list, warn 行 list)。每行 = (楼, 产物, 等级, 落后秒, 说明)。"""
    bdir = os.path.join(BASE, name)
    t_in, n = floor_input_time(bdir)
    if t_in is None:
        return [], []
    fails, warns = [], []
    for pat, level, note in PRODUCTS:
        hits = sorted(glob.glob(os.path.join(bdir, pat)))
        if not hits:
            # 缺失不算"过期"，但也要说一声（否则"没有产物"会被当成"全绿"）
            row = (name, pat, "MISS", 0.0, note + " · **产物不存在**")
            (fails if level == "FAIL" else warns).append(row)
            continue
        t_out = min(t for t in (mt(h) for h in hits) if t)
        if t_out < t_in:
            row = (name, os.path.basename(pat), level, t_in - t_out, note)
            (fails if level == "FAIL" else warns).append(row)
    return fails, warns


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    quiet = "--quiet" in sys.argv
    names = args or sorted(d for d in os.listdir(BASE)
                           if os.path.isdir(os.path.join(BASE, d, "floors")))
    t0 = time.time()
    all_fails, all_warns, no_input = [], [], []
    fleet_in = 0.0
    for nm in names:
        t_in, _ = floor_input_time(os.path.join(BASE, nm))
        if t_in is None:
            no_input.append(nm)
            continue
        fleet_in = max(fleet_in, t_in)
        f, w = check_building(nm, quiet)
        all_fails += f
        all_warns += w
    # 全库总目录：依赖**全库**最新 floors。指定楼名单时跳过 —— 那时 fleet_in 只由
    # 这几栋算出来，拿它判总目录会得出"总目录过期"的假结论（总目录本来就不该为
    # 一次单栋调试重排）。
    if not args:
        for pat, level, note in MASTERS:
            p = os.path.join(BASE, pat)
            t_out = mt(p)
            if t_out is None:
                all_fails.append(("-", pat, "MISS", 0.0, note + " · **产物不存在**"))
            elif t_out < fleet_in:
                all_fails.append(("-", pat, level, fleet_in - t_out, note))

    print("=" * 78)
    print("产物新鲜度门禁 · 基准 = 各栋最新 floors/floor*.json 的 mtime")
    print("=" * 78)
    if all_fails:
        all_fails.sort(key=lambda r: -r[3])
        # 先给"按产物类型"的汇总 —— 135 行明细没人看得完，先看哪一类病最多
        by_prod = {}
        for row in all_fails:
            key = row[1]
            cur = by_prod.setdefault(key, [0, 0.0, 0])
            cur[0] += 1
            cur[1] = max(cur[1], row[3])
            cur[2] += 1 if row[2] == "MISS" else 0
        print("汇总（按产物）：")
        for k, (n, worst, miss) in sorted(by_prod.items(), key=lambda kv: -kv[1][0]):
            print("  %-34s %2d 栋过期%s  最久 %s"
                  % (k, n, ("（含 %d 栋缺失）" % miss) if miss else "", lag_str(worst)))
        print("\n明细：")
        print("【FAIL】过期/缺失 %d 项 —— 下游产物没跟上 floors：" % len(all_fails))
        for nm, prod, level, lag, note in all_fails[:40]:
            tail = "缺失" if level == "MISS" else "落后 " + lag_str(lag)
            print("  %-8s %-34s %-8s %s" % (nm, prod, tail, note))
        if len(all_fails) > 40:
            print("  …… 另有 %d 项" % (len(all_fails) - 40))
    else:
        print("【PASS】所有 FAIL 级产物都不比 floors 旧。")
    if not quiet and all_warns:
        all_warns.sort(key=lambda r: -r[3])
        print("\n【WARN】只提醒、不计退出码（%d 项）：" % len(all_warns))
        for nm, prod, level, lag, note in all_warns[:12]:
            tail = "缺失" if level == "MISS" else "落后 " + lag_str(lag)
            print("  %-8s %-34s %-8s %s" % (nm, prod, tail, note))
        if len(all_warns) > 12:
            print("  …… 另有 %d 项" % (len(all_warns) - 12))
    if no_input:
        print("\n（无 floors 输入、未判：%s）" % ", ".join(no_input))
    print("\n检查 %d 栋 / %.1f s。重出命令见 README「标准命令序列」"
          "（出图只跑对应 owner 脚本；批量只走 _par_batch.py）。"
          % (len(names), time.time() - t0))
    return 1 if all_fails else 0


if __name__ == "__main__":
    sys.exit(main())
