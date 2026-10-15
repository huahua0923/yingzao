# -*- coding: utf-8 -*-
r"""判据 J-10.9-05：几何参数**只有一个源**（`rebuild/构件库/参数.json`），且件里记的数与它一致。

★ 为什么要单开一条（2026-10-15 #5A「参数单一源」）：`参数.json` 头注一直写着
  「本文件只此一份，build3d.py 里那些常数是**引用它的结果**」—— 但**那是承诺，不是事实**：
  代码里 `GOING_MM = 270.0` / `WELL_GAP_MM = 120.0` / `LANDING_T_M = 0.12` / `LIFT_T_MM = 150.0`
  各写了一份字面量，参数表里另有一份。两个地方写同一个数，**一致证明不了它是对的**
  （铁律 018）——而不一致时，症状要到 SU 的 `BBOX_mm` 才现形，**那时件已经出完了**。
  ★ 更坏的一种：原先 `main()` 里那段「代码值 vs 参数表值，不等就抛」的自查，比的是
    **自己跟自己**（代码那四个数就是手抄参数表的）⇒ 恒等、永远绿。看着像一道闸，
    其实一点分辨力都没有（铁律 137/158）。它已被删掉，改由本闸在**源头**上守。

判据
 ① **静态·RHS 必须是从参数表读**：`rebuild/tools/build3d.py` 里下面 `CONST` 那些名字的赋值，
    右值必须含 `PL.p(...)` / `PL.spec(...)` 调用；**名字缺一个也算红**（被删了也要说话 ——
    删掉一个常数会让某个下游 `NameError`，那要在 import 期就死，不是到 SU 才死）。
 ② **全仓不许有第二份字面量**：`rebuild/` `gates/` `demo/` 下的 `*.py` / `*.rb` / `*.js` 里，
    不许出现 `名字 = <数字>` 这种赋值（`GOING_MM = 270.0` 会被抓）。
    ★ 为什么连 `build3d.py` 自己也扫：① 只保证「有 PL 调用」，② 保证「没有裸数」——
      两条是**两把不同的尺子**（一条防抄回去、一条防写死），不是同一条写两遍。
 ③ **覆盖面**：`build.json::参数来源` 的键集合必须**恰好**等于 `CONST` 那些条（不多不少）。
    —— 少一条 = 某个参数没进对账；多一条 = 表里加了新常数而本闸的名单没跟着长。
 ④ **对账（两个独立读数）**：逐条比 `build.json::参数来源[名]` 与 `参数.json` **当场读**的值。
    · `值` 不等 ⇒ 红（件里记的数与表里的数不一致：要么有人又写死了一份、要么表改了没重出）
    · `标注` 不等 ⇒ 红（「件说自己是实测、表说是假设」这类脱钩，数字错看得见、**来源错看不见**）
    ★ 为什么要两个读数：光「代码从同一个文件读」**还是自证**。`build.json` 是**出件那一趟**
      留下的读数，`参数.json` 是**本闸当场**读的 —— 两者之间隔着一次完整的建件过程。

量具
 `rebuild/构件库/参数.json`（唯一真源，现读）；`rebuild/05_build/build.json::参数来源`
 （出件那趟留下的读数）；`rebuild/tools/build3d.py` 的**源码文本**（`ast` 解析，不 import）。

量具盲区（★先声明，再判）
 · ① 只认「右值里有 `PL.*` 调用」这一种形状。**换一种同样错的写法它看不见**，例如
   `GOING_MM = float(PL.p("楼梯","踏面")) if False else 270.0` 这类条件表达式 —— 本闸
   不做出个 Python 解释器，只做形状检查。
 · ② 只认 `名字 = <数字>` 这一种字面量形状。`名字 = 0.27*1000` 或 `名字 = 另一变量`
   抓不到。**「找不到」不等于「没有」**（铁律 158）。
 · ④ 比的是 `build.json` 与 `参数.json`，**不是**「件里的几何真按这个数长」。几何对不对是
   `J-10.9-02`（楼梯形制）/ `J-10.9-03`（竖井）的活；本闸只管**参数从哪来**。
 · 不断言这些数**对不对**：`女儿墙高 1200` 标着「假设」，本闸核的是「件与表都写着 1200 且都
   说是假设」，**不是**「1200 mm 是对的」。

正对照（每条必须**因该因**而红；铁律 137：判据要有分辨力，得喂过坏输入才转绿）
 C1 真件                          —— 基线
 C2 源码 `GOING_MM` 那行换回字面量 —— ② 红（源码文本里又出现裸数）
 C3 源码删掉 `PARAPET_T` 那一行     —— ① 红（「缺一个」也要说话）
 C4 `build.json::参数来源` 少一条   —— ③ 红
 C5 `build.json` 里女儿墙高改 1300  —— ④ 红（值）
 C6 `build.json` 里井壁厚标注改「实测」—— ④ 红（标注）
 C7 造一个含 `WELL_GAP_MM = 120.0` 的假源码 —— ② 红
 C8 `参数.json` 不在               —— SKIP(rc=4)，另起一个**真进程**验 rc

三态：rc=0 PASS ／ rc=1 FAIL ／ rc=4 SKIP（`参数.json` 或 `build.json` 不在）
"""
import ast
import io
import json
import os
import re
import shutil
import subprocess
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = r"D:\项目\cdut3d"
PARAM = os.path.join(ROOT, "rebuild", "构件库", "参数.json")
BUILD = os.path.join(ROOT, "rebuild", "05_build", "build.json")
B3D = os.path.join(ROOT, "rebuild", "tools", "build3d.py")
OUTD = os.path.join(HERE, "_out")
OUT = os.path.join(OUTD, "J-10.9-05.run.txt")

# ★ 名单就是「几何参数里哪些是常数」这件事本身 —— 加一条要**同时**改这里与 `build3d.py` 的
#   `_PARAM_SRC`，本闸的 ③ 会拿两边的键集合对，对不上就红（名单漏长也是红，不是绿）。
CONST = {
    # ★ 2026-10-15 补漏：这条**早就该在名单里**。`共用/层高` 一直是参数表上的一句话，
    #   而 `build3d.py:58` 写着字面量 `STOREY_M = 4.0` —— 名单里没有它 ⇒ 本闸 ② 扫不到，
    #   闸全绿而真源根本没被读。这是「判据名单漏掉主体则永远绿」的原样重演（铁律 137/183）：
    #   **名单本身就是判据的一部分**，漏一条不是少查一条，是那一块永远绿。
    "STOREY_M":       ("共用", "层高"),
    "RISER_TARGET_M": ("楼梯", "踢面_目标"),
    "GOING_MM":       ("楼梯", "踏面"),
    "WELL_GAP_MM":    ("楼梯", "梯井宽"),
    "LANDING_T_M":    ("楼梯", "平台厚"),
    "PARAPET_H":      ("顶部", "女儿墙高"),
    "PARAPET_T":      ("顶部", "女儿墙厚"),
    "ROOF_STAIR_H":   ("顶部", "楼梯房高"),
    "LIFT_T_MM":      ("竖井", "井壁厚"),
    # ★ 2026-10-15 补：第三条路（「扇线＋开启弧」型单扇门）的两个参数。
    "DOOR_ARC_ON":    ("门", "门扇_线弧_补建"),
    "DOOR_ARC_T_MM":  ("门", "门扇_线弧_名义厚"),
}
WANT = sorted("%s/%s" % v for v in CONST.values())
# ② 扫哪些源码。★ 只扫**源码**，不扫 md/json —— 文档与对照页里印着 270 是**对的**
#   （那正是它们该干的事），扫了会满屏假红。
SCAN_EXT = (".py", ".rb", ".js")
SCAN_DIRS = ("rebuild", "gates", "demo")

BLIND = [
    "① 只认「右值里有 PL.* 调用」这一种形状：换一种同样错的写法（如条件表达式里塞字面量）看不见",
    "② 只认「名字 = <数字>」这一种字面量形状：名字 = 0.27*1000 或名字 = 另一变量，抓不到 —— "
    "「找不到」不等于「没有」（铁律 158）",
    "④ 比的是 build.json 与 参数.json 两个读数，不是「件里的几何真按这个数长」——几何是 "
    "J-10.9-02/J-10.9-03 的活",
    "不断言这些数对不对：女儿墙高 1200 标着「假设」，本闸核「件与表都写着它、都说是假设」，"
    "不是「1200 mm 是对的」",
    "不核 06_su 那半条链：本闸读的是参照件 build.json，正式件（SU 出的）不在本闸",
]

_LOG = []


def log(s):
    _LOG.append(s)
    print(s)


def write(path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as fh:
        fh.write(("\n".join(_LOG) + "\n").encode("utf-8").replace(b"\r\n", b"\n"))


def json_path(out_txt):
    if out_txt == OUT:
        return os.path.join(OUTD, "J-10.9-05.json")
    if out_txt.endswith(".run.txt"):
        return out_txt[:-len(".run.txt")] + ".json"
    return os.path.splitext(out_txt)[0] + ".json"


def finish(rc, out, readings):
    p = json_path(out)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as fh:
        json.dump({"pass": rc == 0, "rc": rc, **readings, "blind": BLIND},
                  fh, ensure_ascii=False, indent=1)
    log("  rc=%d" % rc)
    log("  写出: %s" % p)
    write(out)
    return rc


# --------------------------------------------------------------- ① 静态：RHS 是不是从参数表读
def scan_rhs(src):
    r"""→ `{名字: 右值源码}`。只收**模块级**（`tree.body`）的赋值。

    ★ 为什么只收模块级：函数里的同名局部变量与「常数」是两件事，混进来就是另一个量了
      （铁律 174：两个同名的量必须死掉一个）。
    """
    got = {}
    tree = ast.parse(src)
    for node in tree.body:
        tgts, val = [], None
        if isinstance(node, ast.Assign):
            tgts, val = node.targets, node.value
        elif isinstance(node, ast.AnnAssign):
            tgts, val = [node.target], node.value
        if val is None:
            continue
        for t in tgts:
            if isinstance(t, ast.Name) and t.id in CONST:
                got[t.id] = ast.get_source_segment(src, val) or "<取不到源码>"
    return got


def rhs_reads_param(rhs_src):
    """右值里有没有 `PL.p(...)` / `PL.spec(...)` / `PL._mm(...)` 调用。

    ★ 为什么用文本取源码、又用 AST 判：文本那一份是**印给人看的**（要看那行长什么样），
      AST 那一份是**判的** —— 避免 `PLp` 这类同形名字误判。
    """
    try:
        v = ast.parse(rhs_src, mode="eval").body
    except SyntaxError:
        return False
    for n in ast.walk(v):
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute):
            if isinstance(n.func.value, ast.Name) and n.func.value.id == "PL":
                return n.func.attr in ("p", "spec", "_mm")
    return False


# --------------------------------------------------------------- ② 全仓第二份字面量
def scan_literals(dirs, exts):
    r"""→ `[(相对路径, 行号, 行文本)]`：形如 `<名字> = <数字>` 的赋值。"""
    hits = []
    for d in dirs:
        base = os.path.join(ROOT, d)
        for cur, _sub, files in os.walk(base):
            if os.sep + "_out" in cur or os.sep + "__pycache__" in cur:
                continue
            for fn in files:
                if not fn.endswith(exts):
                    continue
                fp = os.path.join(cur, fn)
                try:
                    with io.open(fp, encoding="utf-8", errors="replace") as fh:
                        lines = fh.readlines()
                except OSError:
                    continue
                for i, ln in enumerate(lines, 1):
                    for name in CONST:
                        # ★ 行首（含缩进）就是 `名字 = 数字`。行中间的不算：
                        #   `"PARAPET": int(round(B3.PARAPET_H*1000))` 是**引用**不是第二份。
                        if re.match(r"^\s*%s\s*=\s*[-+]?\d" % re.escape(name), ln):
                            hits.append((os.path.relpath(fp, ROOT), i, ln.strip()))
    return hits


# --------------------------------------------------------------- ③④ 对账
def read_json(path):
    with io.open(path, encoding="utf-8") as fh:
        return json.load(fh)


def write_text(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with io.open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)


def judge(rhs, literals, prov, par):
    """→ (violations, readings)。`par` = 参数表（顶层，含 `构件`）。"""
    fs = []
    rd = {}

    # ①
    for name in sorted(CONST):
        cat, pname = CONST[name]
        if name not in rhs:
            fs.append("① `build3d.py` 里**找不到**模块级赋值 `%s` —— 常数被删了或被挪进函数里。"
                      "缺一个也要说话：删掉它会在下游变成 `NameError`" % name)
            continue
        ok = rhs_reads_param(rhs[name])
        rd[name] = rhs[name]
        log("    %-15s ← %s  %s" % (name, rhs[name], "✔" if ok else "✘ 不是从参数表读"))
        if not ok:
            fs.append("① `%s` 的右值不是从参数表读：`%s` —— 必须是 `PL.p(\"%s\",\"%s\")` 这种形状"
                      % (name, rhs[name], cat, pname))

    # ②
    for rel, i, txt in literals:
        fs.append("② `%s:%d` 有第二份字面量：`%s`" % (rel, i, txt))
    rd["第二份字面量"] = len(literals)

    # ③
    got = sorted(prov.keys())
    rd["参数来源键数"] = len(got)
    if got != WANT:
        for k in sorted(set(WANT) - set(got)):
            fs.append("③ `build.json::参数来源` 少了 `%s` —— 这一条没进对账" % k)
        for k in sorted(set(got) - set(WANT)):
            fs.append("③ `build.json::参数来源` 多了 `%s` —— 表里加了新常数，`build3d.py` 的 "
                      "`_PARAM_SRC` 与本闸的 `CONST` 没跟着长" % k)

    # ④
    for k in sorted(set(WANT) & set(got)):
        cat, pname = k.split("/", 1)
        lib = ((par.get("构件") or {}).get(cat) or {}).get(pname)
        if lib is None:
            fs.append("④ 参数表里没有 `%s`，而件里记着它" % k)
            continue
        for field in ("值", "标注"):
            a, b = prov[k].get(field), lib.get(field)
            if a != b:
                fs.append("④ `%s.%s` 对不上：件里记的=%r ≠ 参数表现读的=%r"
                          % (k, field, a, b))
        rd[k] = {"件": prov[k].get("值"), "表": lib.get("值"),
                 "标注": lib.get("标注")}
    return fs, rd


# --------------------------------------------------------------- 主
def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    param_p = PARAM
    build_p = BUILD
    out = OUT
    for i, a in enumerate(argv):
        if a == "--param" and i + 1 < len(argv):
            param_p = argv[i + 1]
        elif a == "--build" and i + 1 < len(argv):
            build_p = argv[i + 1]
        elif a == "--out" and i + 1 < len(argv):
            out = argv[i + 1]

    log("#" * 78)
    log("J-10.9-05 参数单一源 —— 几何参数只有一个源（`rebuild/构件库/参数.json`）")
    log("  参数表 %s" % param_p)
    log("  件读数 %s" % build_p)
    log("#" * 78)

    # ★ SKIP 与 FAIL 必须分开（铁律 199：「没量到」与「崩了/错了」不同形）
    if not os.path.isfile(param_p):
        log("SKIP(4) 参数表不在：%s —— 这是**没量到**，不是判红" % param_p)
        return finish(4, out, {"skip": "参数.json 不在", "path": param_p})
    if not os.path.isfile(build_p):
        log("SKIP(4) 件读数不在：%s —— 先跑 `python rebuild/tools/build3d.py`" % build_p)
        return finish(4, out, {"skip": "build.json 不在", "path": build_p})

    par = read_json(param_p)
    build = read_json(build_p)
    prov = build.get("参数来源")
    if not isinstance(prov, dict):
        log("FAIL(1) `build.json::参数来源` 不存在或不是对象（%r）—— 这一趟件是**旧版**出的"
            % type(prov).__name__)
        return finish(1, out, {"n_violations": 1})

    log("-" * 78)
    log("① 静态：CONST 名单里这些常数的右值必须从参数表读")
    with io.open(B3D, encoding="utf-8") as fh:
        src = fh.read()
    rhs = scan_rhs(src)
    lits = scan_literals(SCAN_DIRS, SCAN_EXT)
    fs, rd = judge(rhs, lits, prov, par)

    log("-" * 78)
    log("④ 对账（件里记的 vs 参数表现读的）")
    for k in sorted(rd):
        v = rd[k]
        if isinstance(v, dict) and "件" in v:
            log("    %-18s 件=%-8s 表=%-8s 标注=%s" % (k, v["件"], v["表"], v["标注"]))

    # ---- 正对照：每条都必须**因该因**而红（铁律 137）
    log("-" * 78)
    log("正对照（每条只该因它点名的那一条而红）")
    bad = list(fs)

    def ctl(tag, got, want):
        nonlocal bad
        ok = sorted(set(got)) == sorted(set(want))
        log("  %-30s → %s（红在 %s，要 %s）"
            % (tag, "✔" if ok else "✘", sorted(set(got)) or "无", sorted(want)))
        if not ok:
            bad.append("对照 %s 没按预期红（得到 %s，要 %s）" % (tag, sorted(set(got)), sorted(want)))

    def tags(fs_):
        out_ = set()
        for f in fs_:
            m = re.match(r"([①②③④])", f)
            if m:
                out_.add(m.group(1))
        return sorted(out_)

    # C1 基线
    ctl("C1 真件", tags(fs), [])
    # ★ 对照用的假源文件**必须放在 `SCAN_DIRS` 之外**：放 `_out/` 下会被
    #   `scan_literals` 自己的 `_out` 跳过规则吃掉（我第一次就写在那儿，C7 没红 ——
    #   自己给自己设了盲区）；放 `rebuild/` 下则会被**下一次**的真扫（C1）捡到而假红。
    #   ⇒ 单开一个根目录下的临时目录，跑完删掉。
    probe = os.path.join(ROOT, "_probe_j100905")
    probe_rel = os.path.relpath(probe, ROOT)
    try:
        # C2 源码 GOING_MM 换回字面量：**把改坏的源码真的写到盘上再扫**。
        #    只把 `literals=[]` 喂进去，② 就没被喂到 —— 对照只验了一半（第一版就是这么写的，
        #    当场被 C2 自己抓出来：红在 ①、要 ②）。
        s2 = src.replace('GOING_MM       = float(PL.p("楼梯", "踏面"))', "GOING_MM = 270.0")
        assert s2 != src, "C2 的锚点没命中 —— 对照自己失效了"
        write_text(os.path.join(probe, "build3d_probe.py"), s2)
        lits2 = scan_literals([probe_rel], SCAN_EXT)
        ctl("C2 源码 GOING_MM 写字面量",
            tags(judge(scan_rhs(s2), lits2, prov, par)[0]), ["①", "②"])
        # C3 源码删掉 PARAPET_T（源码文本不落盘也行：① 读的是文本）
        s3 = "\n".join(ln for ln in src.splitlines() if not ln.startswith("PARAPET_T"))
        ctl("C3 源码删 PARAPET_T", tags(judge(scan_rhs(s3), [], prov, par)[0]), ["①"])
        # C4 件读数少一条
        p4 = {k: v for k, v in prov.items() if k != "顶部/女儿墙厚"}
        ctl("C4 件读数少一条", tags(judge(rhs, [], p4, par)[0]), ["③"])
        # C5 件读数改值
        p5 = json.loads(json.dumps(prov))
        p5["顶部/女儿墙高"]["值"] = 1300
        ctl("C5 件读数值改 1300", tags(judge(rhs, [], p5, par)[0]), ["④"])
        # C6 件读数改标注
        p6 = json.loads(json.dumps(prov))
        p6["竖井/井壁厚"]["标注"] = "实测"
        ctl("C6 件读数标注改实测", tags(judge(rhs, [], p6, par)[0]), ["④"])
        # C7 造一个含第二份字面量的假源码
        write_text(os.path.join(probe, "fake_gate.py"), "WELL_GAP_MM = 120.0\n")
        hits = scan_literals([probe_rel], SCAN_EXT)
        ctl("C7 假源码里的字面量", tags(judge(rhs, hits, prov, par)[0]), ["②"])
    finally:
        shutil.rmtree(probe, ignore_errors=True)
    # C8 参数表不在 ⇒ 真进程验 rc=4
    tmp = os.path.join(OUTD, "_param_missing.run.txt")
    env = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    r = subprocess.run([sys.executable, os.path.abspath(__file__),
                        "--param", os.path.join(ROOT, "rebuild", "构件库", "_no_such.json"),
                        "--out", tmp], cwd=ROOT, capture_output=True, env=env)
    log("  %-30s → %s（rc=%d，要 4）"
        % ("C8 参数表不在", "✔" if r.returncode == 4 else "✘", r.returncode))
    if r.returncode != 4:
        bad.append("对照 C8 参数表不在时没 SKIP（rc=%d，要 4）" % r.returncode)

    log("-" * 78)
    log("J-10.9-05 总判 : %s" % ("PASS" if not bad else "FAIL（%d 条）" % len(bad)))
    for x in bad:
        log("  ✗ " + x)

    readings = {"n_violations": len(bad), "参数": rd,
                "第二份字面量": [[a, b] for a, b, _ in lits]}
    return finish(0 if not bad else 1, out, readings)


if __name__ == "__main__":
    sys.exit(main())
