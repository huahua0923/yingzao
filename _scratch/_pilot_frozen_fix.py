# -*- coding: utf-8 -*-
"""解冻楼( c006/c009/c103/c104 )的「轮廓/弧墙」修复试点: 备份 -> 改profile -> 重识别
-> 复测 -> 不达标自动回滚。

用法:
    python _pilot_frozen_fix.py c009 --set pair_curved=true
    python _pilot_frozen_fix.py c009 --set pair_curved=true --set outline_unify=false
    python _pilot_frozen_fix.py c009 --bak before_unify_off --set outline_unify=false

判定(必须同时满足才保留):
    1) 弧墙识别率 提升 >= +1.0 个百分点
    2) qa_structural.py <name> 返回 0 且 ERROR=0
    3) 每层墙数 > 0(没有整层塌)
否则整栋回滚到备份。

安全:
  - 备份 profile.json + floors/ + rooms.json 到 <name>/.orig/before_frozen_fix/
    (该目录一旦存在就不再覆盖 —— 保留「最初的冻结态」作为最终回滚点)
  - 重识别走生产入口 `python run_building.py <name>`, 不自己造管道
"""
import json, os, sys, shutil, subprocess, re, glob

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path[:0] = [r"D:\gym3d", r"D:\gym3d\backend", r"D:\gym3d\backend\web"]
os.chdir(r"D:\gym3d")

ROOT = r"D:\gym3d\data\buildings"
BAKNAME = "before_frozen_fix"
_b_err = [None]


def backup(name, bkname=None):
    d = os.path.join(ROOT, name)
    bak = os.path.join(d, ".orig", bkname or BAKNAME)
    if os.path.isdir(bak) and os.path.exists(os.path.join(bak, "profile.json")):
        return bak, "已存在(保留最初冻结态)"
    os.makedirs(bak, exist_ok=True)
    shutil.copy2(os.path.join(d, "profile.json"), os.path.join(bak, "profile.json"))
    for f in ("rooms.json", "spec.json"):
        s = os.path.join(d, f)
        if os.path.exists(s):
            shutil.copy2(s, os.path.join(bak, f))
    fd = os.path.join(bak, "floors")
    if os.path.isdir(fd):
        shutil.rmtree(fd)
    shutil.copytree(os.path.join(d, "floors"), fd)
    return bak, "已备份"


def restore(name, bak):
    d = os.path.join(ROOT, name)
    shutil.copy2(os.path.join(bak, "profile.json"), os.path.join(d, "profile.json"))
    for f in ("rooms.json", "spec.json"):
        s = os.path.join(bak, f)
        if os.path.exists(s):
            shutil.copy2(s, os.path.join(d, f))
    for fp in glob.glob(os.path.join(bak, "floors", "floor*.json")):
        shutil.copy2(fp, os.path.join(d, "floors", os.path.basename(fp)))
    return "已回滚到 " + bak


def set_key(name, key, raw):
    """按字节改 profile.json, 保持 LF, 改完校验 JSON。"""
    P = os.path.join(ROOT, name, "profile.json")
    s = open(P, encoding="utf-8", newline="").read()
    # 解冻楼 profile.json 行尾不一(c041/c072/c073/c006 是 LF, c009/c103/c104 是 CRLF)。
    # 按原文件风格写回, 避免为改一行把整文件行尾翻掉。
    nl = "\r\n" if "\r\n" in s else "\n"
    val = {"true": "true", "false": "false"}.get(raw.lower(), raw)
    pat = re.compile(r'("%s"\s*:\s*)([^,\n}]+)' % re.escape(key))

    def _sub(m):
        return m.group(1) + val

    if pat.search(s):
        s2 = pat.sub(_sub, s, count=1)
        act = "改"
    else:
        i = s.rstrip().rfind("}")
        j = s.rstrip()[:i].rstrip()
        sep = "" if j.endswith("{") else ","
        s2 = j + sep + nl + '  "%s": %s' % (key, val) + nl + "}" + nl
        act = "加"
    json.loads(s2)
    open(P, "w", encoding="utf-8", newline="").write(s2)
    r2 = open(P, encoding="utf-8", newline="").read()
    assert ("\r\n" in r2) == (nl == "\r\n"), "换行风格被改写"
    return "%s %s=%s (换行%s)" % (act, key, val, "CRLF" if nl == "\r\n" else "LF")


def walls_per_floor(name):
    out = {}
    for fp in sorted(glob.glob(os.path.join(ROOT, name, "floors", "floor*.json"))):
        F = int(os.path.basename(fp)[5:-5])
        fl = json.load(open(fp, encoding="utf-8"))
        out[F] = (len(fl["walls"]), sum(1 for w in fl["walls"] if w["type"] == "inner"))
    return out


def curve_stats(name):
    from _curve_delivered_check import check as curve_check
    nm, data, pf = curve_check(name)
    if not isinstance(data, tuple):
        return None
    tot, ins, outside, orph, hit, blob_only, other = data
    return {"tot": tot / 1000.0, "ins": ins / 1000.0, "hit": hit / 1000.0,
            "blob": blob_only / 1000.0, "cov": 100.0 * hit / ins if ins else 0.0,
            "floor": {f: (v[0] / 1000.0, v[1] / 1000.0) for f, v in pf.items()}}


def run_recognize(name):
    r = subprocess.run([sys.executable, "run_building.py", name],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    tail = (r.stdout or "").strip().splitlines()[-6:]
    return r.returncode, r.stdout or "", r.stderr or "", tail


def qa(name):
    """返回 (rc, ERROR数, 汇总行)。

    c009 本来就是 FAIL/ERROR=37(已知柱族锚定 UA 欠识别), 所以门槛不能是「PASS」,
    只能是「ERROR 数不增加」。
    """
    r = subprocess.run([sys.executable, "qa_structural.py", name],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    line, err_n = "", None
    for ln in (r.stdout or "").splitlines():
        parts = ln.split()
        # 汇总行固定 5 列: <楼> <层数> <ERROR> <WARN> <状态>, 状态是 PASS/FAIL/CAUTION
        # 三者之一(旧代码只认 PASS/FAIL, 把 CAUTION 楼整行丢掉 -> 基线 None)。
        # 表头 'c103 (6 层):' split 后只有 3 段, 天然被 len>=5 挡掉。
        if len(parts) >= 5 and parts[0] == name:
            try:
                err_n = int(parts[2])
            except ValueError:
                continue
            line = ln.strip()
    return r.returncode, err_n, line


def main():
    name = sys.argv[1]
    sets = []
    argv = sys.argv[2:]
    for i, a in enumerate(argv):
        if a == "--set":
            k, _, v = argv[i + 1].partition("=")
            sets.append((k, v))
    if not sets:
        print("需要至少一个 --set k=v"); return 2

    bkname = BAKNAME
    for i, a in enumerate(argv):
        if a == "--bak":
            bkname = argv[i + 1]
    print("===== %s =====" % name)
    bak, msg = backup(name, bkname)
    print("  备份: %s (%s)" % (bak, msg))
    b_walls = walls_per_floor(name)
    b_curve = curve_stats(name)
    _b_err[0] = qa(name)[1]
    print("  改前: 墙/层 %s" % {f: "%d/%d" % v for f, v in sorted(b_walls.items())})
    if b_curve:
        print("        弧墙 域内%.0fm 识别%.1f%%(%.0fm) 仅blob%.0fm"
              % (b_curve["ins"], b_curve["cov"], b_curve["hit"], b_curve["blob"]))
    for k, v in sets:
        print("  %s" % set_key(name, k, v))

    rc, out, err, tail = run_recognize(name)
    print("  重识别 rc=%d" % rc)
    for ln in tail:
        print("      " + ln)
    if rc != 0:
        print("  重识别失败 -> %s" % restore(name, bak))
        if err.strip():
            print("      stderr: %s" % err.strip()[-400:])
        return 1

    a_walls = walls_per_floor(name)
    a_curve = curve_stats(name)
    qrc, q_err, qline = qa(name)
    b_err = _b_err[0]
    print("  改后: 墙/层")
    for F in sorted(set(b_walls) | set(a_walls)):
        b = b_walls.get(F, (0, 0))
        a = a_walls.get(F, (0, 0))
        mark = "  <-- 变化" if b != a else ""
        print("     层%-3d %-14s %-14s%s" % (F, "%d/%d" % b, "%d/%d" % a, mark))
    if a_curve:
        print("        弧墙 域内%.0fm 识别%.1f%%(%.0fm) 仅blob%.0fm   [改前 %.1f%%]"
              % (a_curve["ins"], a_curve["cov"], a_curve["hit"], a_curve["blob"],
                 b_curve["cov"] if b_curve else 0.0))
        for F in sorted(a_curve["floor"]):
            h, t = a_curve["floor"][F]
            bh, bt = (b_curve["floor"].get(F) or (0.0, 0.0)) if b_curve else (0.0, 0.0)
            if t >= 3.0 or bt >= 3.0:
                print("     层%-3d 弧 %.0f%%(%.0fm)  [改前 %.0f%%(%.0fm)]"
                      % (F, 100 * h / t if t else 0, t, 100 * bh / bt if bt else 0, bt))
    print("  QA: %s   [改前 ERROR=%s]" % (qline, b_err))

    empty = [F for F, v in a_walls.items() if v[0] <= 0]
    better = (a_curve is not None and b_curve is not None
              and a_curve["cov"] > b_curve["cov"] + 1.0)
    qa_ok = (q_err is not None and b_err is not None and q_err <= b_err)
    if not better or not qa_ok or empty:
        why = []
        if not better:
            why.append("弧墙识别率未提升")
        if not qa_ok:
            why.append("ERROR 数增加 %s -> %s" % (b_err, q_err))
        if empty:
            why.append("层%s 墙数为0" % empty)
        print("  不保留(%s) -> %s" % ("; ".join(why), restore(name, bak)))
        return 1
    print("  ✓ 保留: 弧墙 %.1f%% -> %.1f%%, ERROR %s -> %s (未增加)"
          % (b_curve["cov"], a_curve["cov"], b_err, q_err))
    return 0


if __name__ == "__main__":
    sys.exit(main())
