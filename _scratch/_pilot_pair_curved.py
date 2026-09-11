# -*- coding: utf-8 -*-
"""弧墙配对试点: 开 pair_curved -> 重建楼层 -> 复测「弧墙识别率」, 不达标自动回滚。

用法: python _pilot_pair_curved.py c072 [c073 c041]

安全:
  - 改 profile 前把 profile.json + floors/ 整目录备份到 .orig/before_paircurved/
    (force 脚本自己的 .orig/floors.before_force_stairtread 可能已被旧内容占用, 不可依赖)
  - 逐层仍由 verify_floor 把关(不达标不写该层)
  - 全部完成后用同一套指标复测; 若「弧墙识别率」没变好, 自动回滚到备份并报告
"""
import json, os, sys, shutil, glob, importlib

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path[:0] = [r"D:\gym3d", r"D:\gym3d\backend", r"D:\gym3d\backend\web"]

ROOT = r"D:\gym3d\data\buildings"


def backup(name):
    d = os.path.join(ROOT, name)
    bak = os.path.join(d, ".orig", "before_paircurved")
    os.makedirs(bak, exist_ok=True)
    for f in ["profile.json"]:
        if not os.path.exists(os.path.join(bak, f)):
            shutil.copy2(os.path.join(d, f), os.path.join(bak, f))
    fd = os.path.join(bak, "floors")
    if not os.path.isdir(fd):
        shutil.copytree(os.path.join(d, "floors"), fd)
    return bak


def rollback(name, bak):
    d = os.path.join(ROOT, name)
    shutil.copy2(os.path.join(bak, "profile.json"), os.path.join(d, "profile.json"))
    fd = os.path.join(bak, "floors")
    for fp in glob.glob(os.path.join(fd, "floor*.json")):
        shutil.copy2(fp, os.path.join(d, "floors", os.path.basename(fp)))
    return "已回滚"


def set_flag(name, value):
    P = os.path.join(ROOT, name, "profile.json")
    s = open(P, encoding="utf-8").read()
    assert "\r" not in s, "%s 含 CRLF" % P
    if value:
        if '"pair_curved"' in s:
            return "已有"
        i = s.rstrip().rfind("}")
        j = s.rstrip()[:i].rstrip()
        sep = "" if j.endswith("{") else ","
        s = j + sep + '\n  "pair_curved": true\n}\n'
    else:
        import re
        s2 = re.sub(r',?\s*"pair_curved"\s*:\s*(true|false)\s*', "", s)
        s = s2
    open(P, "w", encoding="utf-8", newline="").write(s)
    return "已设" if value else "已清"


# 复用交付体检的指标(只读)
from _curve_delivered_check import check as curve_check, FROZEN  # noqa: E402


def walls_per_floor(name):
    out = {}
    for fp in sorted(glob.glob(os.path.join(ROOT, name, "floors", "floor*.json"))):
        F = int(os.path.basename(fp)[5:-5])
        fl = json.load(open(fp, encoding="utf-8"))
        inn = sum(1 for w in fl["walls"] if w["type"] == "inner")
        out[F] = (len(fl["walls"]), inn)
    return out


def report_curve(name):
    nm, data, pf = curve_check(name)
    if not isinstance(data, tuple):
        return None
    tot, ins, outside, orph, hit, blob_only, other = data
    return {"tot": tot / 1000.0, "ins": ins / 1000.0, "hit": hit / 1000.0,
            "blob": blob_only / 1000.0, "cov": 100.0 * hit / ins if ins else 0.0}


for nm in sys.argv[1:]:
    nm = nm.strip()
    if nm in FROZEN:
        print("%-6s 冻结楼, 跳过" % nm)
        continue
    print("\n===== %s =====" % nm)
    bak = backup(nm)
    before = walls_per_floor(nm)
    c_before = report_curve(nm)
    print("  备份: %s" % bak)
    print("  改前: %s" % ("弧长%.0fm 域内%.0fm 识别%.1f%%(%.0fm) 仅blob%.0fm"
                        % (c_before["tot"], c_before["ins"], c_before["cov"],
                           c_before["hit"], c_before["blob"]) if c_before else "无曲墙"))
    print("  %s" % set_flag(nm, True))

    import _wall_thin_force as FORCE
    res = FORCE.run(nm)
    print("  重建: %s" % res[1])
    if len(res) > 3 and res[3]:
        print("        FAIL: %s" % res[3][:5])

    after = walls_per_floor(nm)
    c_after = report_curve(nm)
    print("  %-5s %-16s %-16s %s" % ("层", "改前(墙/内墙)", "改后(墙/内墙)", "弧墙识别率"))
    ok = True
    if c_after is None:
        print("  复测无曲墙数据, 回滚")
        ok = False
    else:
        print("  弧墙: 域内%.0fm 识别%.1f%%(%.0fm) 仅blob%.0fm  [改前 %.1f%%]"
              % (c_after["ins"], c_after["cov"], c_after["hit"], c_after["blob"], c_before["cov"]))
        for F in sorted(after):
            b = before.get(F, (0, 0))
            a = after[F]
            print("  %-5d %-16s %-16s" % (F, "%d/%d" % b, "%d/%d" % a))
        if c_after["cov"] <= c_before["cov"] + 1.0:
            print("  弧墙识别率未变好(%.1f%% -> %.1f%%), 回滚"
                  % (c_before["cov"], c_after["cov"]))
            ok = False
    if not ok:
        print("  %s" % rollback(nm, bak))
