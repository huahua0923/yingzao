# -*- coding: utf-8 -*-
"""GLB 逐字节基线：改代码前先存证，改完必须一字不差。

为什么要 sha256 而不是「看起来一样」
------------------------------------
GLB 的字节完全由 verts / faces 两个列表的**顺序**和**每个浮点数的位模式**决定。
优化「顶点发射方式」这类改动，最容易出的错不是崩溃，而是悄悄换了顶点顺序或
让某个 `math.cos` 变成 `np.cos`（末位差 1 ulp）—— 渲染上看不出来，但已经是
另一份产物了。所以判据只能是字节。

先验证确定性
------------
如果同一份代码跑两次 sha256 就不一样（比如 GLB 头里带时间戳），那 sha256
比对本身没意义。所以本脚本先对同一栋楼连跑两次做自检，不通过就直接退出。

用法
----
    python _scratch/_glb_baseline.py            # 存基线到 _scratch/_glb_baseline/
    python _scratch/_glb_baseline.py --check _scratch/_glb_after
        # 用 after 目录里的产物与基线逐字节比对
"""
import hashlib
import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for sub in ("backend", "backend/web", "backend/modeling"):
    sys.path.insert(0, os.path.join(ROOT, sub))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

DEFAULT = ["c019", "c055", "c006", "c114", "c018"]
ALLLIST = os.path.join(ROOT, "_scratch", "_glb_baseline_all.json")
TMP = os.path.join(ROOT, "_scratch", "_glb_tmp")


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def build(name, outdir):
    """用当前代码把一栋楼装配到 outdir，返回 (路径, 三角形数, 顶点数)。"""
    import importlib
    import build_standard_glb as bsg
    importlib.reload(bsg)                      # 每栋重置模块级累加器
    from run_step import load_profile

    p = load_profile(name)
    bsg.DATA = os.path.dirname(p.out_dir)
    os.makedirs(outdir, exist_ok=True)
    bsg.OUT = os.path.join(outdir, "%s-building.glb" % name)
    bsg.INCLUDE_SYNTHETIC_WINDOWS = True
    bsg.main()
    return bsg.OUT


def all_building_names():
    """全部交付楼栋 —— 判据与 run_batch.py:29-31 完全一致，不另立门户。

    刻意不抄 prerender_floor_png.py 那套「目录 + data/*-profile.json + profiles/*.py」
    的三合一枚举：那套是为了覆盖 lihua / j6 这两个 out_dir 挂在 data/ 下的基线楼，
    而这次要核的是交付件，正好就是 data/buildings 下有 profile.json 的那些。
    """
    from paths import BUILDINGS
    return sorted(d for d in os.listdir(BUILDINGS)
                  if os.path.isdir(os.path.join(BUILDINGS, d))
                  and os.path.exists(os.path.join(BUILDINGS, d, "profile.json")))


def sweep(names, manifest_path, write):
    """逐栋建到**同一个**临时路径、算 sha256、立刻删文件。

    为什么不把 49 份 GLB 都留着：合计 2.3 GB，而比对只需要哈希。建成一个删一个，
    磁盘峰值 = 一个 GLB（c055 的 153 MB），代价是要重跑一遍——可接受。

    write=True  建基线；write=False 与已有基线比对。
    """
    os.makedirs(TMP, exist_ok=True)
    old = {}
    if not write:
        if not os.path.exists(manifest_path):
            print("没有基线文件 %s，先跑一次 --all。" % manifest_path)
            return 1
        with open(manifest_path, encoding="utf-8") as f:
            old = json.load(f)

    rec, bad, failed = {}, [], []
    t_all = time.time()
    for i, name in enumerate(names, 1):
        path = os.path.join(TMP, "%s-building.glb" % name)
        t0 = time.time()
        h = size = None
        try:
            build(name, TMP)
            h, size = sha256(path), os.path.getsize(path)
        except Exception as exc:                     # noqa: BLE001 — 单栋失败不该中断整批
            failed.append((name, "%s: %s" % (type(exc).__name__, exc)))
            print("[%2d/%d] %-6s ✗ 构建失败 %s: %s"
                  % (i, len(names), name, type(exc).__name__, exc), flush=True)
        if os.path.exists(path):
            os.remove(path)                          # 成功失败都删，别攒 153MB 的残骸
        if h is None:
            continue

        rec[name] = {"sha256": h, "bytes": size}
        if write:
            print("[%2d/%d] %-6s %s  %7.2f MB  %5.1fs"
                  % (i, len(names), name, h[:16], size / 1e6, time.time() - t0),
                  flush=True)
        elif name not in old:
            bad.append(name)
            print("[%2d/%d] %-6s ✗ 基线里没有这一栋" % (i, len(names), name), flush=True)
        elif old[name]["sha256"] == h:
            print("[%2d/%d] %-6s ✓ %s" % (i, len(names), name, h[:16]), flush=True)
        else:
            bad.append(name)
            print("[%2d/%d] %-6s ✗ 不一致\n          基线 %s  %d 字节\n"
                  "          现在 %s  %d 字节  (差 %+d)"
                  % (i, len(names), name, old[name]["sha256"][:16], old[name]["bytes"],
                     h[:16], size, size - old[name]["bytes"]), flush=True)

    print("\n" + "=" * 60)
    if write:
        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump(rec, f, indent=2, ensure_ascii=False)
        print("基线已写 %s：%d 栋，耗时 %.1f 分钟"
              % (manifest_path, len(rec), (time.time() - t_all) / 60))
    else:
        print("比对完成：%d 栋" % len(rec))
    if failed:
        print("构建失败 %d 栋：" % len(failed))
        for n, m in failed:
            print("  %s: %s" % (n, m))
    if bad:
        print("逐字节不一致 %d 栋：%s" % (len(bad), ", ".join(bad)))
    if failed or bad:
        return 1
    print("全部通过。" if not write else "")
    return 0


def verify_determinism(name, tmpdir):
    """同一栋楼连跑两次，sha256 必须相同 —— 否则后续比对无意义。"""
    print("\n[自检] 确定性：%s 连跑两次……" % name, flush=True)
    a = build(name, os.path.join(tmpdir, "det_a"))
    b = build(name, os.path.join(tmpdir, "det_b"))
    ha, hb = sha256(a), sha256(b)
    if ha != hb:
        print("  ✗ 不确定！两次 sha256 不同，说明 GLB 里含时间戳/随机量。")
        print("    %s\n    %s" % (ha, hb))
        print("  改用结构比对（verts/faces 数组逐元素）才能验证，不能用 sha256。")
        return False
    print("  ✓ 确定性成立：%s" % ha[:16])
    return True


def main():
    args = sys.argv[1:]
    if args and args[0] == "--check":
        return do_check(args[1])
    if args and args[0] == "--all":
        names = all_building_names()
        print("全量逐字节扫：%d 栋（逐个建、算哈希、删文件）" % len(names), flush=True)
        return sweep(names, ALLLIST, write=True)
    if args and args[0] == "--check-all":
        names = all_building_names()
        print("全量逐字节核：%d 栋\n" % len(names), flush=True)
        return sweep(names, ALLLIST, write=False)

    names = [a for a in args if not a.startswith("--")] or DEFAULT
    base = os.path.join(ROOT, "_scratch", "_glb_baseline")
    os.makedirs(base, exist_ok=True)

    if not verify_determinism(names[0], base):
        return 2

    manifest = {}
    for name in names:
        t0 = time.time()
        path = build(name, base)
        h = sha256(path)
        size = os.path.getsize(path)
        manifest[name] = {"sha256": h, "bytes": size}
        print("[%s] %s  %.2f MB  %.1fs" % (name, h[:16], size / 1e6, time.time() - t0),
              flush=True)

    with open(os.path.join(base, "baseline.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)
    print("\n基线已写入 %s/baseline.json（%d 栋）" % (base, len(manifest)))
    return 0


def do_check(after_dir):
    base = os.path.join(ROOT, "_scratch", "_glb_baseline")
    with open(os.path.join(base, "baseline.json"), encoding="utf-8") as f:
        manifest = json.load(f)

    print("逐字节比对：%s\n" % after_dir)
    bad = []
    for name, rec in sorted(manifest.items()):
        path = os.path.join(after_dir, "%s-building.glb" % name)
        if not os.path.exists(path):
            print("  %-6s ✗ 缺产物" % name)
            bad.append(name)
            continue
        h = sha256(path)
        if h == rec["sha256"]:
            print("  %-6s ✓ 一致  %s" % (name, h[:16]))
        else:
            size = os.path.getsize(path)
            print("  %-6s ✗ 不一致" % name)
            print("        基线 %s  %d 字节" % (rec["sha256"][:16], rec["bytes"]))
            print("        现在 %s  %d 字节  (差 %+d)" % (h[:16], size, size - rec["bytes"]))
            bad.append(name)

    print()
    if bad:
        print("未通过：%s —— 产物已经变了，必须查清原因再继续。" % ", ".join(bad))
        return 1
    print("全部通过：%d 栋 GLB 逐字节一致。" % len(manifest))
    return 0


if __name__ == "__main__":
    sys.exit(main())
