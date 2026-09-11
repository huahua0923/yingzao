# -*- coding: utf-8 -*-
"""把每栋楼每层的平面图预渲染成静态 PNG（构建期跑，服务器只发文件）。

为什么要在构建期渲染
--------------------
老控制台的 `GET /floor/<F>.png` 是**请求期现算**的：读源 DXF → classify →
matplotlib 画图。这条路径要 ezdxf + matplotlib，而服务器「只服务」模式
刻意不装它们 —— 于是不预渲染，这个功能在服务器上就是 500。

顺带干掉两个老毛病：`_FLOOR_CACHE` 无界增长（进程内缓存，谁访问过谁留下），
以及每个请求 1.5 秒的 CPU 开销。

产物与既有文件的关系（重要）
----------------------------
    <楼>/plans/floor{F}.png        ← 诊断对比图，_scratch/render_floor_pngs.py 出
                                      （灰=原图墙 / 橙=门 / 蓝=识别墙 / 红=轮廓 + 覆盖率标题）
    <楼>/plans/recog_floor{F}.png  ← 本脚本出，**用户实际看到的那张**
                                      （黑=墙 / 红=门 / 蓝=柱 / 绿=楼梯）

两者内容不同、用途不同，所以刻意用不同文件名共存，互不覆盖。老控制台
`/floor/<F>.png` 服务的是后者（`vision.render_floor.render_floor_png`）。

用法
----
    python prerender_floor_png.py                 # 增量：只补缺的
    python prerender_floor_png.py --force         # 全部重渲
    python prerender_floor_png.py --only c108 c103   # 只跑指定楼
    python prerender_floor_png.py --dry-run       # 只列出要做什么
"""
import argparse
import os
import sys
import time

DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(DIR, "backend"))
sys.path.insert(0, os.path.join(DIR, "backend", "web"))
sys.path.insert(0, os.path.join(DIR, "backend", "vision"))
sys.path.insert(0, os.path.join(DIR, "backend", "modeling"))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from paths import BUILDINGS, DATA  # noqa: E402

PREFIX = "recog_floor"


def floor_numbers(out_dir):
    """某栋楼实际有哪些层 —— 只认磁盘上的 floor*.json，不假设 0..n-1 连续。"""
    if not os.path.isdir(out_dir):
        return []
    nums = []
    for name in os.listdir(out_dir):
        if not (name.startswith("floor") and name.endswith(".json")):
            continue
        try:
            nums.append(int(name[5:-5]))
        except ValueError:
            continue          # floor_plan.json 之类，不是层文件
    return sorted(nums)


def all_names():
    """楼栋清单：目录档案 + data/*-profile.json 覆盖 + 代码里注册的（lihua/j6）。

    代码注册楼从 `recognizer/profiles/*.py` 的文件名取，而不是读注册表 ——
    注册表是 `_PROFILES` 这个私有字典，伸手进去就等于把脚本焊在实现细节上；
    而「profiles 目录里一个模块 = 一个注册楼」正是 `profiles/__init__.py`
    自己的约定，跟着它走就不会错。
    """
    names = []
    if os.path.isdir(BUILDINGS):
        for d in sorted(os.listdir(BUILDINGS)):
            if os.path.exists(os.path.join(BUILDINGS, d, "profile.json")):
                names.append(d)
    for f in sorted(os.listdir(DATA)):
        if f.endswith("-profile.json"):
            names.append(f[: -len("-profile.json")])
    prof_dir = os.path.join(DIR, "backend", "recognizer", "profiles")
    if os.path.isdir(prof_dir):
        for f in sorted(os.listdir(prof_dir)):
            if f.endswith(".py") and not f.startswith("_"):
                names.append(f[:-3])
    seen, out = set(), []
    for n in names:
        if n not in seen:
            seen.add(n)
            out.append(n)
    return out


def plan_dir_for(name, out_dir, taken):
    """某栋楼的平面图目录 —— 并挡住「两栋楼写同一个目录」这种静默覆盖。

    常规楼是 `<楼目录>/plans`。但挂在 data/ 下的基线楼（lihua 的 `data/floors`、
    j6 的 `data/floors_j6`）父目录都是 `data/`，会被算成同一个 `data/plans/`
    —— 后跑的楼把先跑的图覆盖掉，而且**不报错**，只是图片悄悄换成了别人的楼。
    j6 目前没有 floors 目录、撞不上，但这是数据布局问题，不该靠脚本装看不见：
    真撞了就停下来报清楚是哪两栋。
    """
    plan_dir = os.path.join(os.path.dirname(out_dir), "plans")
    key = os.path.normcase(os.path.abspath(plan_dir))
    if key in taken:
        raise SystemExit(
            "预渲染中止：%s 与 %s 的平面图目录撞在一起（%s）。\n"
            "请给其中一栋单独的 out_dir，或改 plan_dir_for 的命名规则。"
            % (name, taken[key], plan_dir))
    taken[key] = name
    return plan_dir


def prune_stale(plan_dir, floors, dry_run):
    """删掉「本楼已经没有对应层」的旧 recog_ 图。

    只动 recog_ 前缀：同目录的 floor{F}.png 是诊断图，有自己的生命周期，
    不归本脚本管 —— 删错就是把别人的产物当垃圾清了。
    """
    removed = []
    if not os.path.isdir(plan_dir):
        return removed
    for f in os.listdir(plan_dir):
        if not (f.startswith(PREFIX) and f.endswith(".png")):
            continue
        try:
            F = int(f[len(PREFIX):-4])
        except ValueError:
            continue
        if F not in floors:
            removed.append(f)
            if not dry_run:
                os.remove(os.path.join(plan_dir, f))
    return removed


def main():
    ap = argparse.ArgumentParser(description="预渲染每层平面图为静态 PNG")
    ap.add_argument("--only", nargs="*", metavar="NAME", help="只处理指定楼栋")
    ap.add_argument("--force", action="store_true", help="已存在的也重渲")
    ap.add_argument("--dry-run", action="store_true", help="只列出计划，不写文件")
    args = ap.parse_args()

    from run_step import load_profile
    from vision.render_floor import render_floor_png

    names = args.only or all_names()
    t_start = time.time()
    done, skipped, planned, failed, pruned = 0, 0, 0, [], []
    taken_plan_dirs = {}

    for name in names:
        try:
            p = load_profile(name)
        except Exception as exc:  # noqa: BLE001
            print("[%s] 跳过：读档案失败 %s: %s" % (name, type(exc).__name__, exc))
            continue

        floors = floor_numbers(p.out_dir)
        if not floors:
            print("[%s] 跳过：%s 下没有 floor*.json" % (name, p.out_dir))
            continue

        plan_dir = plan_dir_for(name, p.out_dir, taken_plan_dirs)
        gone = prune_stale(plan_dir, floors, args.dry_run)
        if gone:
            pruned.extend((name, f) for f in gone)
            print("[%s] 清理过期图 %d 张：%s" % (name, len(gone), ", ".join(sorted(gone))))

        if not os.path.isdir(plan_dir) and not args.dry_run:
            os.makedirs(plan_dir, exist_ok=True)

        made = []
        for F in floors:
            out = os.path.join(plan_dir, "%s%d.png" % (PREFIX, F))
            if os.path.exists(out) and not args.force:
                skipped += 1
                continue
            if args.dry_run:
                made.append(F)
                continue
            t0 = time.time()
            try:
                render_floor_png(p, F, out_path=out)
            except Exception as exc:  # noqa: BLE001 — 单层失败不该中断整批
                failed.append((name, F, "%s: %s" % (type(exc).__name__, exc)))
                print("[%s] F%d 渲染失败：%s: %s" % (name, F, type(exc).__name__, exc))
                continue
            done += 1
            made.append(F)
            size = os.path.getsize(out) // 1024
            # flush：301 层要跑十几分钟，stdout 重定向到文件时是块缓冲的，
            # 不 flush 就全程看不到进度、只能靠数文件数 —— 日志等于没有。
            print("[%s] F%-2d -> %s  %4d KB  %.1fs"
                  % (name, F, os.path.basename(out), size, time.time() - t0),
                  flush=True)

        if made:
            planned += len(made)
            print("[%s] %s %d 层 -> %s"
                  % (name, "待渲染" if args.dry_run else "已渲染", len(made), plan_dir))

    elapsed = time.time() - t_start
    print("\n" + "=" * 60)
    print("预渲染%s：%s %d 层 / 跳过（已存在） %d 层 / 清理过期 %d 张 / 失败 %d 层 / 耗时 %.1f 分钟"
          % ("（试运行，未写文件）" if args.dry_run else "完成",
             "待渲" if args.dry_run else "新渲", planned,
             skipped, len(pruned), len(failed), elapsed / 60))
    if failed:
        print("失败明细：")
        for name, F, msg in failed:
            print("  %s F%d: %s" % (name, F, msg))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
