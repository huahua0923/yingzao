# -*- coding: utf-8 -*-
"""楼层层序自检(全楼): 用图纸自带的房间号 XX-FF-NN 反查模型层号是否对得上。

依据: 每张图纸的房间号前缀第二段 FF 就是真实层号(1-based)。把每条房间号按
floor_of(profile) 归到模型层 k, 统计该层里出现的 FF 众数:
  众数 == k+1          -> OK      (模型层序与图纸一致)
  众数 == N-k          -> 倒置!!  (图纸层号与 Y 升序相反, 需加降序 floor_ys)
  其他                 -> 异常?   (分层噪声/多翼楼/标注错位, 需人工看)
只读诊断, 不改任何数据。用法: python _floor_order_check.py [name ...]
"""
import os, sys, re, glob, json, collections

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path[:0] = [r"D:\gym3d", r"D:\gym3d\backend", r"D:\gym3d\backend\web"]
import ezdxf
from run_building import load_profile
from backend.recognizer.profile import floor_of

ROOT = r"D:\gym3d\data\buildings"


def plain(s):
    return re.sub(r"\\[A-Za-z][^;]*;", "", s or "").strip()


def parse_ff(t):
    """从房间号标注解析真实层号 FF(1-based)。覆盖三种图面写法:
      41-01-00      3 段 XX-FF-NN        -> 中段
      6-A-01-00     4 段 XX-翼-FF-NN     -> 第 3 段(翼楼字母在 2 段)
      NY27-111      人才公寓 <楼>-<F><NN> -> 数字后缀首位
    """
    m = re.match(r"^\s*\d+\s*-\s*[A-Za-z]{1,2}\s*-\s*(\d+)", t)   # 4 段
    if m:
        return int(m.group(1))
    m = re.match(r"^\s*[A-Za-z]{1,4}\d*\s*-\s*(\d{2,})\s*$", t)   # 人才公寓式
    if m:
        return int(m.group(1)[0])
    m = re.match(r"^\s*\d+\s*-\s*(\d+)", t)                       # 3 段
    if m:
        return int(m.group(1))
    return None


def check(name):
    try:
        p = load_profile(name)
        doc = ezdxf.readfile(p.dxf)
    except Exception as e:  # noqa: BLE001
        return name, "SKIP", "读失败 %s" % str(e)[:50], None
    msp = doc.modelspace()
    bands = collections.defaultdict(list)
    for e in msp:
        if e.dxftype() not in ("MTEXT", "TEXT"):
            continue
        if "房间号" not in e.dxf.layer:
            continue
        ff = parse_ff(plain(e.text))
        if ff is None:
            continue
        x, y = e.dxf.insert[0], e.dxf.insert[1]
        try:
            k = int(round(floor_of(p, x, y)))
        except Exception:  # noqa: BLE001
            continue
        bands[k].append(ff)

    if not bands:
        return name, "无号码", "该图无房间号标注(或层名不同)", None
    # 只用有足够标注的层做主判(剔除孤立噪声带, 如 c034 的 F-2 单条)
    keep = {k: v for k, v in bands.items() if len(v) >= 3} or bands
    ks = sorted(keep)
    N = len(ks)
    rows, ident, inv, off1 = [], 0, 0, 0
    for k in ks:
        c = collections.Counter(keep[k])
        ff, cnt = c.most_common(1)[0]
        agree = sum(1 for v in keep[k] if v == k + 1)
        rev = sum(1 for v in keep[k] if v == N - 1 - (k - ks[0]))
        same = sum(1 for v in keep[k] if v == k)
        if agree >= max(rev, same) and agree:
            tag, ident = "OK", ident + 1
        elif rev > agree:
            tag, inv = "倒置", inv + 1
        elif same > agree:
            tag, off1 = "偏1", off1 + 1
        else:
            tag = "?"
        rows.append((k, ff, cnt, len(keep[k]), tag))
    tags = collections.Counter(t for _, _, _, _, t in rows)
    if ident == len(rows):
        verdict = "正常"
    elif inv >= max(ident, off1) and inv >= len(rows) - 1:
        verdict = "倒置!!"
    elif off1 >= max(ident, inv):
        verdict = "底部多层!!"
    elif ident >= max(inv, off1):
        verdict = "基本正常"
    else:
        verdict = "异常?"
    noisy = [k for k in bands if k not in keep]
    detail = " ".join("F%d=%d(%s)" % (k, ff, t) for k, ff, _, _, t in rows)
    if noisy:
        detail += "  [稀疏带 %s 忽略]" % noisy
    return name, verdict, detail, rows


names = sys.argv[1:] or sorted(
    os.path.basename(d) for d in glob.glob(os.path.join(ROOT, "*")) if os.path.isdir(d))

print("== 楼层层序自检(按图纸房间号) ==")
summary = collections.Counter()
bad = []
for nm in names:
    name, verdict, detail, rows = check(nm)
    summary[verdict] += 1
    if verdict in ("倒置!!", "异常?"):
        bad.append(name)
    print("%-7s %-6s %s" % (name, verdict, detail))
print("\n== 汇总 ==")
for k, v in summary.most_common():
    print("  %-6s %d" % (k, v))
if bad:
    print("需人工/可修:", ", ".join(bad))
