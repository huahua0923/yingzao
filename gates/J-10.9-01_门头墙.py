# -*- coding: utf-8 -*-
"""J-10.9-01 · 门头墙（门上方那段墙）到底补上了没有，以及**没补上的那一批都归了因**。

★ 加这条闸的直接原因：用户 2026-10-15 报「**门上面的缺失**」。现在补出来了，
  但补出来的件**必须能说清自己还漏着谁** —— 本闸存在的意义就是让「漏 22 扇」
  永远出现在读数里，而不是被一次「账目闭合」抹成 0。

判据
 ① 参照件同趟：`构件库/对照.json` 的 `生成时刻` 与磁盘时刻都**不许**早于
    `06_su/contours/1层.json` 的磁盘时刻 − 600 s。
    —— 「上半链重跑了、下半链没重跑」在这栋楼里已经犯过一次（参照件停在 10-14，
       靠人眼在图上发现的）；这里把它变成一条会红的闸。
 ② 几何重算（**两个独立估计器**）：从 `06_su/contours/*层.json` 现算
    「门扇块数」与「与门头块(LINTEL)相交的门扇数」，**逐层**必须等于 `对照.json`
    里的 `门扇` / `有门头`。对不上的层**指名道姓**（铁律 194：两个同名的量按身份比，
    不许拿合计盖住某一层）。
 ③ 账目闭合：每层 `有门头 + 漏了 == 门扇`；全楼 `门扇` 合计 == 各层之和。
 ④ 归因闭合（**逐条**，不只核总数）：`漏_贴墙 + 漏_离墙 == 漏了`；
    明细行数 == `min(漏了, 20)`；`漏明细_截断 == (漏了 > 20)`；
    且每一条明细的 `距墙 ≤ 1.0 mm` ⇔ 它被算进 `漏_贴墙`。
    —— 明细在 `parts_lib` 里是 `miss[:20]`，总数却取自全量 `miss`；
       一旦漏超过 20 条，**分类会自己变少而总数不变**（同形状的错误已经犯过一次，
       铁律 183），所以这里逐条核对而不是只核两个总数。
 ⑤ 参数回抄：`对照.json` 每行回抄的 **9 个在用**门头墙参数（扫描半径 / 咬 / 离墙上限 /
    清边半径 / 墙厚上限 / 墙厚下限 / 洞口上限 / 洞口下限 / 最小块）必须**逐字等于**
    `参数.json` 的当前值。
    —— 「改了参数、没重跑件」只有这一条能抓（两个地方写同一个数，铁律 018）。
    （2026-10-16 换的：逐扇门构造上线后 `门头墙_闭环半径` / `门头墙_超出门扇` **已停用**
      ⇒ 它们不再进 `对照.json`，见 NO_ECHO；`门头墙_最小块` 反倒进得来，挪进了 ECHO。）
 ⑥ 判词不静默：本闸**任何一条出口**都要把 `漏 N（贴墙 a / 离墙 b）` 写进日志头与
    json 的 `漏` / `漏_贴墙` / `漏_离墙`；不存在「全绿且漏数看不见」的路。

量具
 几何侧：`shapely`，门扇环 `buffer(1.0, join_style=2)` 与门头环**相交**即算「有门头」
 （与 `parts_lib.lintel_module` 收口时那把尺子同容差：它也是 `buffer(1.0, join_style=2)`
  去碰面积 ≥ `门头墙_最小块` 的块 —— 定义**照抄交付件**，不另立一个）；
 账目侧：`构件库/对照.json` 的 `构件[12]`（逐层一行）；
 参数侧：`构件库/参数.json` 的 `构件.门`。

量具盲区（★先声明，再判）
 · 「有门头」的定义是**相交**，不是**覆盖**。门扇在这套图里是**开着、垂直于墙**的
   薄板（1 层 181 扇里 136 扇面积恒为 27422 mm² = 731.25 × 37.5），
   而门头块补在**墙的缺口**上 ⇒ 覆盖率对「有/没有」这件事**恒 ≈0.33、没有分辨力**。
   若改判「覆盖 ≥90%」就是**另一个定义**，得先由人裁定用哪个，本闸不偷偷换尺子
   （换过一次，读数 1 层 有门头 142 → 56，那不是「变坏了」是「量到别的东西了」）。
 · 只量**平面相交**，不量 z 向：门头块是不是真从 2.1 m 起、有没有长到层高，
   本闸不核（那是件自己声明的 `z=2100 h=1900`）。
 · 「贴墙 ⇔ 门洞未开 / 离墙 ⇔ 源图无墙」这个**因果**本闸不核，只核分类与明细自洽；
   要判因果得回 `01_cad/raw/*.dxf` 逐条看墙线。
 · 只认 `rebuild/06_su/contours/`：`packs/` 里那一份、以及页面 `demo/parts.html`
   上显示的数，本闸一概不核（那是 J-10.9-04 的事）。

正对照（每条必须**因该因**而红；`新增 N 条` 是相对 C1 基线的**差集**，不是违反总数）
 C1 真件          —— 基线，必须 0 条
 C2 抹掉一层的门头块 —— ② 红（几何与账目对不上，且指得出是**哪一层**）
 C3 账目 +1 不动明细 —— ②③④ 红（归因闭合断）
 C4 改一个回抄参数   —— ⑤ 红（参数表与件脱钩）
 C5 contours 不在    —— SKIP(rc=4)，**另起一个进程真跑一遍**验 rc
 C6 生成时刻改旧     —— ① 红（参照件停在上一趟）

三态：rc=0 PASS ／ rc=1 FAIL ／ rc=4 SKIP（contours 或 对照.json 不在 ⇒ 没量到）
"""
import glob
import json
import os
import subprocess
import sys
from datetime import datetime

from shapely.geometry import Polygon

sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = r"D:\项目\cdut3d"
CONTOURS = os.path.join(ROOT, "rebuild", "06_su", "contours")
PARAM = os.path.join(ROOT, "rebuild", "构件库", "参数.json")
DUIZHAO = os.path.join(ROOT, "rebuild", "构件库", "对照.json")
OUTD = os.path.join(HERE, "_out")
OUT = os.path.join(OUTD, "J-10.9-01.run.txt")

# ★ 本闸**已声明的盲区**（逐条抄自 docstring 的「量具盲区」，不新编）
BLIND = [
    "「有门头」= 门扇（外扩 1 mm）与门头块**相交**，不是覆盖：门扇是开着、垂直于墙的薄板"
    "（1 层 181 扇里 136 扇面积恒 27422 mm² = 731.25×37.5），门头在墙里只与它交 ≈240×37.5 "
    "⇒ 占比恒 ≈0.33；改判「覆盖 ≥90%」是**另一个定义**，得先由人裁定，本闸不偷偷换尺子",
    "那 1 mm 的容差就是 `parts_lib` 自己的取值，本闸照抄；但它落在**并集＋清边＋收边之后**的"
    "块上，而 `heal_short_edges` 最多能挪 16 mm 边 ⇒ 边线上那十几毫米的归属，两个读数可以不同",
    "只量平面相交、不量 z：门头块起止标高（声明 z=2100 h=1900）本闸不核",
    "「贴墙/离墙」的因果（门洞未开 / 源图无墙）本闸不核，只核分类与明细自洽",
    "只认 rebuild/06_su/contours/：packs/ 里那一份与页面显示的数本闸不核",
    "洞口是**两把尺子量出来的**（① 缺口法 ② 迈步法，见 parts_lib.lintel_module）：本闸只核"
    "「哪把尺子用了几扇」（`洞口靠削细料才量到`/`洞口靠迈步才量到`）在账上，不核量得对不对",
]

# 门头墙那 9 个**在用、且被回抄的**参数：对照.json 的键名 → 参数.json 的键名
# （键名两套是实测如此，不是笔误：对照.json 是 `parts_lib` 的 diag 盒子，键名短）
ECHO = {"扫描半径": "门头墙_扫描半径", "咬": "门头墙_缝合",
        "离墙上限": "门头墙_离墙上限", "清边半径": "门头墙_清边半径",
        "墙厚上限": "门头墙_墙厚上限", "墙厚下限": "门头墙_墙厚下限",
        "洞口上限": "门头墙_洞口上限", "洞口下限": "门头墙_洞口下限",
        "最小块": "门头墙_最小块"}
# ★ 两个**已停用**的参数：`门头墙_闭环半径` / `门头墙_超出门扇`。
#   逐扇门构造（2026-10-16）之后不做闭运算、板的沿墙长度由洞口自量 ⇒ 这两个数**不参与任何几何**，
#   `parts_lib` 也不再把它们回抄进 `对照.json`（只在 `停用参数` 名单里点名）。
#   本闸**核不到**它们 —— 声明出来，不当过（铁律 158：找不到的判词要写明尺子对什么盲）。
NO_ECHO = ("门头墙_闭环半径", "门头墙_超出门扇")
MILE = 1.0                       # 「贴墙」的门槛（mm）—— parts_lib 的定义，抄来核它自洽
FRESH_SLACK_S = 600              # 对照.json 允许比 contours 早这么多秒（同一趟里的写盘次序）
DETAIL_CAP = 20                  # parts_lib 的 miss[:20]

_LOG = []


def log(s):
    _LOG.append(s)
    print(s)


def write(path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as fh:
        fh.write(("\n".join(_LOG) + "\n").encode("utf-8").replace(b"\r\n", b"\n"))


def json_path(out_txt):
    """★ 产物 json 与 run.txt 同编号、同目录（C5 的子进程换 --out 时不污染正牌路径）。"""
    if out_txt == OUT:
        return os.path.join(OUTD, "J-10.9-01.json")
    if out_txt.endswith(".run.txt"):
        return out_txt[:-len(".run.txt")] + ".json"
    return os.path.splitext(out_txt)[0] + ".json"


def finish(rc, out, readings):
    """★ 三路读数的**唯一出口**（产物 json 的 pass / rc ／ run.txt 的 rc= ／ 判词行）。"""
    p = json_path(out)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as fh:
        json.dump({"pass": rc == 0, "rc": rc, **readings, "blind": BLIND},
                  fh, ensure_ascii=False, indent=1)
    log("  rc=%d" % rc)
    log("  写出: %s" % p)
    write(out)
    return rc


# ---------------- 量具 ----------------
def rings(path):
    """读一层 contours ⇒ {层: {"door": [ring], "lint": [ring]}}。"""
    d = json.load(open(path, "r", encoding="utf-8"))
    lay = os.path.basename(path)[:-5]
    out = {"door": [], "lint": []}
    for p in d["polys"]:
        L = p.get("layer")
        if L == "DOOR":
            out["door"].append(p["ring"])
        elif L == "LINTEL":
            out["lint"].append(p["ring"])
    return lay, out


def polys(rs):
    """环 → 有效多边形；自交/零面积的那几个**单独数出来**（不与「没门头」同形，铁律 199）。"""
    gs, bad = [], 0
    for r in rs:
        try:
            g = Polygon(r)
        except Exception:
            bad += 1
            continue
        if (not g.is_valid) or g.is_empty or g.area <= 0:
            bad += 1
            continue
        gs.append(g)
    return gs, bad


def fresh(dz, c_path):
    """① 参照件同趟：返回 (是否新, 读数 dict)。"""
    ts = str(dz.get("生成时刻") or "")
    t_dz = os.path.getmtime(DUIZHAO)
    t_c = os.path.getmtime(c_path)
    return bool(ts) and (t_dz + FRESH_SLACK_S) >= t_c, {
        "对照生成时刻": ts,
        "对照_mtime": datetime.fromtimestamp(t_dz).strftime("%Y-%m-%d %H:%M:%S"),
        "contours_mtime": datetime.fromtimestamp(t_c).strftime("%Y-%m-%d %H:%M:%S"),
        "slack_s": FRESH_SLACK_S,
    }


def geo_counts(cs):
    """② 从几何现算：逐层 门扇数 / 与门头块相交的门扇数。"""
    res, degen = {}, 0
    for lay in sorted(cs):
        dg, b1 = polys(cs[lay]["door"])
        lg, b2 = polys(cs[lay]["lint"])
        degen += b1 + b2
        if not dg:
            res[lay] = (0, 0)
            continue
        hit = 0
        for g in dg:
            gb = g.buffer(1.0, join_style=2)
            if any(gb.intersects(h) for h in lg):
                hit += 1
        res[lay] = (len(dg), hit)
    return res, degen


# ---------------- 判据 ----------------
def judge(cs, dz, par, fr):
    """cs: 层→{"door":[ring],"lint":[ring]}；dz: 对照.json；par: 参数.json；fr: ① 的读数。"""
    fs = []
    door_p = par["构件"]["门"]

    # ① 参照件同趟
    if not fr["是否新"]:
        fs.append("① 对照.json（%s，mtime %s）比 contours（%s）旧 —— 参照件停在上一趟"
                  % (fr["对照生成时刻"], fr["对照_mtime"], fr["contours_mtime"]))

    # ② 几何重算 vs 账目（按层比，不按合计比）
    gc, degen = geo_counts(cs)
    rows = {c["层"]: c for c in dz["构件"]}
    for lay in sorted(set(rows) | set(gc)):
        if lay not in gc or lay not in rows:
            fs.append("② %s 只在%s里有 ⇒ 两个估计器**量的不是同一批层**"
                      % (lay, "几何" if lay in gc else "账目"))
            continue
        gd, gl = gc[lay]
        if (gd, gl) != (rows[lay]["门扇"], rows[lay]["有门头"]):
            fs.append("② %s 几何现算「门扇 %d / 有门头 %d」≠ 账目「门扇 %d / 有门头 %d」"
                      " —— 对照.json 与导出件脱钩（差 %d 扇门 / %d 扇门头）"
                      % (lay, gd, gl, rows[lay]["门扇"], rows[lay]["有门头"],
                         gd - rows[lay]["门扇"], gl - rows[lay]["有门头"]))

    # ③ 账目闭合
    for lay in sorted(rows):
        c = rows[lay]
        if c["有门头"] + c["漏了"] != c["门扇"]:
            fs.append("③ %s 有门头 %d + 漏了 %d ≠ 门扇 %d"
                      % (lay, c["有门头"], c["漏了"], c["门扇"]))
    tot_leaf = sum(c["门扇"] for c in rows.values())
    tot_have = sum(c["有门头"] for c in rows.values())
    tot_miss = sum(c["漏了"] for c in rows.values())

    # ④ 归因闭合（逐条）
    for lay in sorted(rows):
        c = rows[lay]
        detail = c.get("漏明细_距墙_距块_面积") or []
        n_wall, n_far = c["漏_贴墙"], c["漏_离墙"]
        if n_wall + n_far != c["漏了"]:
            fs.append("④ %s 贴墙 %d + 离墙 %d ≠ 漏了 %d" % (lay, n_wall, n_far, c["漏了"]))
        want_rows = min(c["漏了"], DETAIL_CAP)
        if len(detail) != want_rows:
            fs.append("④ %s 明细 %d 行 ≠ min(漏了 %d, %d)"
                      % (lay, len(detail), c["漏了"], DETAIL_CAP))
        if bool(c.get("漏明细_截断")) != (c["漏了"] > DETAIL_CAP):
            fs.append("④ %s 漏明细_截断=%s 与 漏了 %d 对不上"
                      % (lay, c.get("漏明细_截断"), c["漏了"]))
        # 逐条：距墙 ≤ 1.0 mm ⇔ 算进「贴墙」
        near = sum(1 for m in detail if m[0] <= MILE)
        if c["漏了"] <= DETAIL_CAP and near != n_wall:
            fs.append("④ %s 明细里 距墙≤%.1fmm 的有 %d 条，账上写 贴墙 %d 条 —— "
                      "分类与明细不是同一批（明细被截断时总数会自己变绿）"
                      % (lay, MILE, near, n_wall))

    # ⑤ 参数回抄
    confirmed = 0
    for lay in sorted(rows):
        c = rows[lay]
        for k_dz, k_par in ECHO.items():
            confirmed += 1
            v_par = door_p[k_par]["值"]
            if abs(float(c[k_dz]) - float(v_par)) > 1e-9:
                fs.append("⑤ %s 回抄 %s=%s ≠ 参数.json 的 %s —— 改了参数没重跑件"
                          % (lay, k_dz, c[k_dz], v_par))
    head = {
        "门扇": tot_leaf, "有门头": tot_have, "漏": tot_miss,
        "漏_贴墙": sum(c["漏_贴墙"] for c in rows.values()),
        "漏_离墙": sum(c["漏_离墙"] for c in rows.values()),
        "漏明细_截断层": sorted([l for l in rows if rows[l].get("漏明细_截断")]),
        "回抄核对": confirmed, "未回抄参数": list(NO_ECHO),
    }
    return fs, {"几何": gc, "退化环": degen}, head


def main():
    global CONTOURS, DUIZHAO
    argv = sys.argv[1:]
    out = argv[argv.index("--out") + 1] if "--out" in argv else OUT
    if "--contours" in argv:
        CONTOURS = argv[argv.index("--contours") + 1]
    if "--duizhao" in argv:
        DUIZHAO = argv[argv.index("--duizhao") + 1]

    _LOG.clear()
    log("J-10.9-01 · 门头墙补上了没有 + 没补上的都归了因（contours %s）" % CONTOURS)

    files = sorted(glob.glob(os.path.join(CONTOURS, "*层.json")))
    lack = [p for p in (DUIZHAO, PARAM) if not os.path.exists(p)] + ([] if files else [CONTOURS])
    if lack:
        log("★ 没量到：缺 %d 件 —— %s ⇒ SKIP(rc=4)"
            % (len(lack), [os.path.basename(m) for m in lack]))
        return finish(4, out, {"n_files": len(files), "n_missing": len(lack),
                               "missing": [os.path.basename(m) for m in lack]})

    dz = json.load(open(DUIZHAO, "r", encoding="utf-8"))
    par = json.load(open(PARAM, "r", encoding="utf-8"))
    cs = {}
    for p in files:
        lay, r = rings(p)
        cs[lay] = r
    log("  读入 %d 层 contours ｜ 参数.json「门」%d 条" % (len(cs), len(par["构件"]["门"])))

    is_new, fr = fresh(dz, os.path.join(CONTOURS, "1层.json"))
    fr["是否新"] = is_new
    log("  ① 对照生成时刻 %s ｜ 对照 mtime %s ｜ contours mtime %s ⇒ %s"
        % (fr["对照生成时刻"], fr["对照_mtime"], fr["contours_mtime"],
           "同趟" if is_new else "★参照件停在上一趟"))
    log("-" * 78)

    base, g, head = judge(cs, dz, par, fr)
    log("  ⑥ 判词 : 门扇 %d ｜ 有门头 %d ｜ **漏 %d（贴墙 %d / 离墙 %d）**"
        % (head["门扇"], head["有门头"], head["漏"], head["漏_贴墙"], head["漏_离墙"]))
    log("  ② 几何现算 vs 账目 : 逐层 %d 层" % len(g["几何"]))
    bylay = {x["层"]: x for x in dz["构件"]}
    for lay in sorted(g["几何"]):
        gd, gl = g["几何"][lay]
        c = bylay[lay]
        log("     %-6s 几何 门扇%4d/有门头%4d ｜ 账目 门扇%4d/有门头%4d  %s"
            % (lay, gd, gl, c["门扇"], c["有门头"],
               "✔" if (gd, gl) == (c["门扇"], c["有门头"]) else "✘"))
    if g["退化环"]:
        log("  ★ 退化环 %d 个（读不成多边形）⇒ 这几扇按**没量到**处理，不与「没门头」同形"
            % g["退化环"])
    log("  ⑤ 参数回抄：核了 %d 格（%d 层 × %d 条）｜★ 未回抄、本闸核不到的：%s"
        % (head["回抄核对"], len(bylay), len(ECHO), "、".join(NO_ECHO)))
    log("C1 真件 ⇒ 违反 %d 条%s" % (len(base), " ⇒ 放行" if not base else ""))
    for x in base:
        log("    " + x)
    bad = list(base)

    def ctl(name, fs_, want):
        new = [x for x in fs_ if x not in base]
        got = sorted({x[0] for x in new})
        ok = bool(new) and got == sorted(want)
        log("  对照 %-22s → %s（新增 %d 条，要 %s，实得 %s）"
            % (name, "✔红" if ok else "✘没红/红错因", len(new), "".join(want), "".join(got) or "—"))
        if not ok:
            bad.append("对照 %s 没按预期红（要 %s，实得 %s，新增 %d 条）"
                       % (name, "".join(want), "".join(got) or "无", len(new)))

    # C2 抹掉一层的门头块
    which = sorted(cs)[0]
    cs2 = {k: {"door": v["door"], "lint": list(v["lint"])} for k, v in cs.items()}
    cs2[which]["lint"] = []
    ctl("C2 抹掉%s门头块" % which, judge(cs2, dz, par, fr)[0], ["②"])
    # C3 账目 +1 不动明细
    dz3 = json.loads(json.dumps(dz))
    dz3["构件"][0]["漏了"] += 1
    ctl("C3 账目+1不动明细", judge(cs, dz3, par, fr)[0], ["③", "④"])
    # C4 改一个回抄参数
    dz4 = json.loads(json.dumps(dz))
    dz4["构件"][0]["离墙上限"] = float(dz4["构件"][0]["离墙上限"]) + 7.0
    ctl("C4 改回抄参数", judge(cs, dz4, par, fr)[0], ["⑤"])
    # C6 生成时刻改旧
    fr6 = dict(fr)
    fr6["是否新"] = False
    ctl("C6 参照件改旧", judge(cs, dz, par, fr6)[0], ["①"])

    # C5 件不在 ⇒ SKIP：**另起一个进程真跑**（判词必须把「没做」与「坏了」分开）
    tmp = os.path.join(OUTD, "_doorhead_skip_probe.txt")
    env = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    r = subprocess.run([sys.executable, os.path.abspath(__file__),
                        "--contours", os.path.join(CONTOURS, "_no_such_dir"), "--out", tmp],
                       cwd=ROOT, capture_output=True, env=env)
    log("  对照 %-22s → %s（rc=%d，要 4）"
        % ("C5 contours 不在", "✔" if r.returncode == 4 else "✘", r.returncode))
    if r.returncode != 4:
        bad.append("对照 C5 contours 不在时没 SKIP（rc=%d，要 4）" % r.returncode)

    log("-" * 78)
    log("J-10.9-01 总判 : %s" % ("PASS" if not bad else "FAIL（%d 条）" % len(bad)))
    for x in bad:
        log("  ✗ " + x)

    readings = dict(head)
    readings.update(fr)
    readings["层数"] = len(cs)
    readings["退化环"] = g["退化环"]
    readings["n_violations"] = len(bad)
    return finish(0 if not bad else 1, out, readings)


if __name__ == "__main__":
    sys.exit(main())
