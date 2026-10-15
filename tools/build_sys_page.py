# -*- coding: utf-8 -*-
"""cdut3d 系统总览页生成器 —— 字段与流程全摊在一页上（用户 2026-10-12 明令）。

「后面做所有系统，就要有页面，所有的字段，流程都在上面，这样也方便修改。」

★ 页面上的每一个数都**现场从盘上读**：判据脚本的 docstring、判据产物 json 的
  字段名与类型、run.txt 的 rc 与判词、文件大小与时刻。**一个都不手打** ——
  手打的会静默过期，那这页就成了第二种真相（铁律 103/174）。

★ 每条判据给**三个互相独立的读数**，并排摆着（json 的 `pass` ／ run.txt 的 `rc=` ／
  run.txt 的判词行）。**不许拿一个去冒充另一个**：本仓有三条判据的判词只活在
  stdout 里（`J-09.2-A0` / `J-10.2-01` / `J-10.6-01`），只读 json 会把它们的 PASS
  印成「没量到」；反过来，只读 stdout 会把「产出物与退出码互相打脸」那种病盖住。
  两路读数不一致时，状态记**「不一致」**，不替谁圆场（铁律 174/196/199）。

用法: python tools/build_sys_page.py
"""
import ast
import glob
import io
import json
import os
import re
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
GATES = os.path.join(ROOT, "gates")
GOUT = os.path.join(GATES, "_out")
A1 = os.path.join(ROOT, "a1")
TOOLS = os.path.join(ROOT, "tools")
DEMO = os.path.join(ROOT, "demo")
OUT = os.path.join(DEMO, "sys.html")

# ---- 档位与实测耗时：**唯一来源**是 `tools/gate_tiers.py` + `gates/_out/_ledger.json` ----
# ★ 本页**不许**再抄一份档位表（那是同一个量的第二份副本，铁律 174）。run_gates.py 也 import 同一个。
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import gate_tiers as GT                                              # noqa: E402


def load_ledger():
    """run_gates.py 每趟落的**逐条实测耗时**。读不到就返回空 —— 空 ≠ 0 秒（铁律 197）。"""
    p = os.path.join(GOUT, "_ledger.json")
    if not os.path.exists(p):
        return {"rows": {}, "runs": [], "missing": True}
    try:
        d = json.load(open(p, encoding="utf-8"))
    except Exception as e:                                           # noqa: BLE001
        return {"rows": {}, "runs": [], "missing": True, "err": str(e)}
    # ★ `rows` 必须是**按判据编号索引的 dict**。旧版台账把它落成 list（一次跑一份），
    #   这里必须**显式挡住**：`setdefault` 挡不住「键在但是错的类型」，
    #   下一步 `.get()` 就会 AttributeError —— 页面整个不生成，而根因在格式不在数据。
    if not isinstance(d.get("rows"), dict):
        return {"rows": {}, "runs": d.get("runs") or [],
                "missing": True,
                "err": "台账 rows 是 %s，不是按编号索引的 dict ⇒ 按「没跑过」处理"
                       % type(d.get("rows")).__name__}
    d.setdefault("runs", [])
    d["missing"] = not d["rows"]
    return d


LEDGER = load_ledger()

# 链的次序：**结构声明**（不是读数）—— 每一步都能顺着文件名回盘核对。
CHAIN = [
    ("① 源数据", "D:\\gym3d\\材料\\dxf_output\\*.dxf", "只读 · 字节未动",
     ["a1/probe_layers.py", "a1/batch_grid.py"]),
    ("② CAD 实体化", "a1/stage2_prepare_dxf.py", "墙层多段线闭合 → out.dxf",
     ["gates/J-07.9.4-01_wallclose.py", "gates/J-07.9.4-02_wallclose_downstream.py",
      "gates/J-07.9.4-03_residual_to_model.py"]),
    ("③ 图幅定位", "a1/sheet_grid.py", "从 DXF 自动发现平面图图幅排布",
     ["gates/J-09.2-A1_wallchain.py"]),
    ("④ 构件", "a1/generic_wall.py", "墙链（墙/柱/洞口/房间/踏步各一个入口）",
     ["gates/J-09.2-A1b_openings.py", "gates/J-09.2-A1c_rooms.py",
      "gates/J-09.2-A1d_treads.py"]),
    ("⑤ 交付包", "tools/modelpack.py ＋ demo/build_pack.py",
     "两个平台之间唯一的接缝。★ 2026-10-14 换链：模型那一段**不建几何** —— 只把重建链的"
     "**正式件** `rebuild/06_su/c006_su.glb` 原样搬进包。这一格原先印的是 "
     "`tools/modelpack.py ＋ tools/floors_from_libs3d.py ＋ tools/pack_d1.py`，"
     "后两个已随 libs3d 链一起退场（代价写在包内 `meta/layering.json` 的 `supersedes`）。",
     ["gates/J-10.2-01_modelpack.py", "gates/J-10.2-02_floorshift.py",
      "gates/J-09.2-A1e_wallclosed.py"]),
    ("⑤a 模型真源（重建链）",
     "rebuild/tools/export_sheet.py → recognize.py → redraw.py → review_index.py"
     " → build3d.py → render3d.py → export_contours.py ＋ rebuild/06_su/su_step2_build.rb"
     " → rebuild/tools/su_obj_to_glb.py",
     "★ 2026-10-14 换链后，包内件的真源是**这一条**：DXF 图幅 → SU 正式件 `06_su`"
     "（c006_su.skp/.obj）→ `c006_su.glb`（只转格式、不动顶点）。它与 ①–④ 那条 a1 链"
     "**各走各的**，两条链各有自己的判据。这一格原先印的是 `tools/slab_into_floor.py`"
     "（一层楼板换 AutoCAD 描回来的那块），已随 libs3d 链退场。",
     ["gates/J-10.8-01_build3d.py", "gates/J-10.8-02_su.py", "gates/J-10.8-03_views.py"]),
    ("⑥ 交付文档", "tools/md2docx.py", "方案 md → docx", ["gates/J-10.0-01-docx_sync.py"]),
]

RC_RE = re.compile(r"rc=(-?\d+)")
ZONG_RE = re.compile(r"总判\s*[:：]?\s*(PASS|FAIL)")
# ★ 2026-10-15 加 `NO-GAUGE` / `SKIP`：判据把「没量到」也写在行首（例：`J-09.1.1-viewer`
#   印的 `  NO-GAUGE  rc=4  本判据…没量到`）。原先只认 PASS/FAIL ⇒ 那一行的判词列印成
#    **「—（run.txt 里没有判词行）」** —— 把「我不认识这个判词」说成了「它没有判词」。
#    与 FAIL 同形与否要分开写（铁律 199）；这里只是**让那一格如实显示**，
#    归类的判断仍由 `judge()` 里 `rc==4` 那一支与 `got` 决定（vr 进不了 got 的 PASS/FAIL 集合）。
VERD_RE = re.compile(r"(?m)^[ \t]*(PASS|FAIL|NO-GAUGE|SKIP)\b")


def doc_first_line(path):
    """模块 docstring 第一行 —— 解析失败就明说，不许拿文件名冒充。"""
    try:
        tree = ast.parse(io.open(path, encoding="utf-8", errors="replace").read())
    except SyntaxError as e:
        return "（解析失败：%s）" % e
    doc = ast.get_docstring(tree) or ""
    for line in doc.strip().splitlines():
        if line.strip():
            return line.strip()
    return "（无 docstring）"


def core_candidates(stem):
    """产物名的候选：① 与脚本同名 ② 在第一个 `_` 处截断 ③ 再逐个去掉尾部 `-段`。

    实测三种都要用：`J-09.2-A1b_openings`→②；`J-10.0-01-docx_sync`→③（落 `J-10.0-01`）；
    `J-09.1.1-viewer`→①（它的产物**就是**带 `-viewer` 的）。**按盘上实际存在的文件判**，
    不靠猜 —— 用了第几条规则会印在页上。
    """
    cands = [stem]
    if "_" in stem:
        cands.append(stem.split("_")[0])
    while "-" in cands[-1]:
        nxt = cands[-1].rsplit("-", 1)[0]
        if len(nxt) < 4:
            break
        cands.append(nxt)
    return [c for i, c in enumerate(cands) if c not in cands[:i]]


def resolve(stem, suffixes, present):
    """在 _out/ 里找产物：返回 (文件名 or None, 用了第几条候选规则 or None)。"""
    for i, c in enumerate(core_candidates(stem)):
        for suf in suffixes:
            if c + suf in present:
                return c + suf, i
    return None, None


SUFFIXES = (".json", ".run.txt", ".log", ".console.txt")


def gid_of(stem, jn, rn):
    """判据编号 —— 从**产物名**反推，产物名与脚本名不同名时以产物为准。

    ★ 不许用 `os.path.splitext`：编号里带点（`J-07.9.4-01`），splitext 会在**最后一个点**
      处切，把 `J-09.2-A0_chain` 切成 `J-09` —— 台账上一排编号会全变成 `J-09`/`J-10`，
      看着还挺整齐（铁律 174：像结论的数）。
    """
    n = jn or rn or (stem + ".json")
    for suf in SUFFIXES:
        if n.endswith(suf):
            n = n[:-len(suf)]
            break
    return n.split("_")[0]


def kind_of(v):
    if isinstance(v, dict):
        return "dict(%d)" % len(v)
    if isinstance(v, list):
        return "list(%d)" % len(v)
    if isinstance(v, bool):
        return "bool"
    if v is None:
        return "null"
    if isinstance(v, (int, float)):
        return "num"
    return "str(%d)" % len(str(v))


def ctl_count(j):
    """json 里 `controls` 那个 dict 的 bool 叶子 —— 全真才算「全触发」。"""
    c = j.get("controls") if isinstance(j, dict) else None
    if not isinstance(c, dict):
        return None
    flags = [x for x in c.values() if isinstance(x, bool)]
    if not flags:
        return None
    return sum(1 for x in flags if x), len(flags)


def out_writes(src):
    """扫判据源码里**点到的** `_out/` 下的名字。

    ★ 它分不出**读还是写**、也分不出**文件还是目录** —— 这是把「它写的东西」当标签会
      说假话的地方（实测 `J-07.9.4-03` 那条里就点着一个**读**别人的 json、还有两个是
      工作目录）。所以页上的标签写的是「源码里点到的 _out/ 名字」，并逐条标出盘上是
      文件、目录还是缺 —— 只当线索，不当结论。
    ★ 也**会漏**：路径靠变量拼起来的名字扫不到（铁律 158：判词要声明量具对什么盲）。
    """
    txt = io.open(src, encoding="utf-8", errors="replace").read()
    names = set(re.findall(r'"_out"\s*,\s*"([^"\\/]+)"', txt))
    names |= set(re.findall(r'_out[/\\]([A-Za-z0-9._\u4e00-\u9fff-]+)', txt))
    names = set(n for n in names if not n.startswith("_out"))
    return sorted(names)


def tag_at(name):
    """这个名字在盘上是什么 —— 两个目录都找：`gates/_out/` 和仓库根的 `_out/`。

    ★ 第三档**不许写成「缺」**：扫描把源码里**任何** `_out` 路径下的名字都收进来了，
      而 `J-07.9.4-01`（工作目录）住在仓库根的 `_out/`、`chain_run.json` 住在
      `chain/_out/` —— 都不是 `gates/_out/`。写成「缺」= 拿本页的尺子去量别人的目录，
      会把「不在我这个目录里」印成「不存在」（铁律 158：判词要声明量具对什么盲）。
    """
    for base, where in ((GOUT, ""), (os.path.join(ROOT, "_out"), "（在仓库根的 `_out/` 下）")):
        p = os.path.join(base, name)
        if os.path.isdir(p):
            return " <span class='dir'>目录</span><span class='w2'>%s</span>" % where
        if os.path.isfile(p):
            return " <span class='pass'>文件</span><span class='w2'>%s</span>" % where
    return " <span class='w2'>（这两个 _out 下都没有这个名字）</span>"


def esc(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def mdb(s):
    """把 docstring 里的 `**粗**` 与 `` `代码` `` 变成 HTML —— 先转义再换，顺序不能反。

    ★ 只认这两种记号：docstring 是没人替我们管格式的自由文本，多认几种就会把
      普通字符吃进去（例如落单的 `*`）。认不出的一律原样印。
    """
    s = re.sub(r"\*\*([^*\n]+)\*\*", r"<b>\1</b>", esc(s))
    return re.sub(r"`([^`\n]+)`", r"<code>\1</code>", s)


def brief(v):
    s = esc(json.dumps(v, ensure_ascii=False))
    return s if len(s) <= 110 else s[:110] + " …"


def stamp(path):
    # ★ path 可能是 None（那份判据两样产物都没有）—— 必须自己挡，
    #   否则 os.path.isfile(None) 抛 TypeError，整页一条都不出。
    if not path or not os.path.isfile(path):
        return "—"
    return time.strftime("%m-%d %H:%M", time.localtime(os.path.getmtime(path)))


def kb(path):
    return "%.1f KB" % (os.path.getsize(path) / 1024.0) if path and os.path.isfile(path) else "—"


def read_text(path):
    if not path or not os.path.isfile(path):
        return ""
    return io.open(path, encoding="utf-8", errors="replace").read()


def collect_gates():
    present = set(os.listdir(GOUT)) if os.path.isdir(GOUT) else set()
    rows = []
    for p in sorted(glob.glob(os.path.join(GATES, "*.py"))):
        stem = os.path.basename(p)[:-3]
        jn, jrule = resolve(stem, [".json"], present)
        rn, rrule = resolve(stem, [".run.txt", ".log", ".console.txt"], present)
        jp = os.path.join(GOUT, jn) if jn else None
        rp = os.path.join(GOUT, rn) if rn else None
        j = None
        if jp:
            try:
                j = json.load(io.open(jp, encoding="utf-8"))
            except ValueError as e:
                j = {"__bad__": str(e)}
        rt = read_text(rp)
        rows.append({
            "gid": gid_of(stem, jn, rn),
            "stem": stem, "py": "gates/" + os.path.basename(p),
            "doc": doc_first_line(p), "jp": jp, "rp": rp, "j": j,
            "jn": jn, "rn": rn, "jrule": jrule, "rrule": rrule,
            "rcs": sorted(set(int(x) for x in RC_RE.findall(rt))),
            "zong": sorted(set(ZONG_RE.findall(rt))),
            "verd": sorted(set(VERD_RE.findall(rt))),
            "writes": out_writes(p), "crash": "Traceback" in rt,
        })
    return rows


def judge(g):
    """三个读数各自是什么 + 合起来是什么。**先各自记录，再判一致性**，不合并成一句「绿」。"""
    jr = "—（没产物）"
    if g["jp"]:
        if "__bad__" in g["j"]:
            jr = "坏 json"
        elif "pass" not in g["j"]:
            jr = "无 pass 字段"
        else:
            # ★ 2026-10-15 修：`rc=4` 是**没量到 / SKIP**（仓里约定 OK 0 / FAIL 1 / SKIP 4），
            #   而这类判据的 json 常常**同时**写着 `pass: false` ⇒ 这里只读 `pass` 的话，
            #   就把「没量到」印成了「判红」—— 正是本文件 :640 承诺**分开写**的那两件事。
            #   实测（23 条判据的 json 逐条扫）只有 `J-09.1.1-viewer` 走这一支：
            #   `pass:false, rc:4, unmeasured:['H 的刺激像素落在模型外']`
            #   ⇒ 汇总页曾把「FAIL 2 + 没量到 1」印成「FAIL 3」（铁律 199）。
            #   给 `jr` 一个**非 PASS/FAIL** 的串：下面 `got` 认不出它 ⇒ 这一格由 `vr` 那一路说了算。
            jr = "没量到" if g["j"].get("rc") == 4 else ("PASS" if g["j"]["pass"] else "FAIL")
    rr = "—（run.txt 里没有 rc=）"
    if g["rcs"]:
        # ★ 一个 run.txt 里常有**好几个** rc（判词那行一个、正对照那几行各一个）——
        #   都印出来，别挑一个当代表（铁律 174：同名的两个量必须都露脸）。
        rr = "rc=" + ",".join(str(x) for x in g["rcs"])
    vr = "—（run.txt 里没有判词行）"
    if g["zong"]:
        vr = g["zong"][0] + ("（多值）" if len(g["zong"]) > 1 else "")
    elif g["verd"]:
        vr = g["verd"][0] + ("（多值）" if len(g["verd"]) > 1 else "")

    got = set(x for x in (jr, vr) if x in ("PASS", "FAIL"))
    if len(got) > 1:
        st = "不一致"
    elif got:
        st = got.pop()
    else:
        st = "没量到"

    flags = []
    if st == "不一致":
        flags.append("★ 两路读数打架：json 说 <b>%s</b>、run.txt 判词说 <b>%s</b>"
                     " —— 谁都不许替谁圆场，去查是谁写的、什么时候写的" % (jr, vr))
    if jr == "PASS" and g["rcs"] and 0 not in g["rcs"]:
        flags.append("★ rc 非 0 而产物说 PASS（产出物与退出码互相打脸）")
    if jr == "FAIL" and g["rcs"] == [0]:
        flags.append("★ rc=0 而产物说 FAIL（同上，反方向）")
    # ★ 2026-10-15：`rc=4` 的格子要点名说清它**不是判红**，并把「没量到哪一条」摆出来 ——
    #   否则上面那条 `jr="没量到"` 只是把标签换了，读的人仍旧看不到它为什么没量到。
    #   （这条 flag 只在 json 同时写了 `pass:false` 时出现，正是最容易被读成判红的那种形状。）
    if g["jp"] and isinstance(g["j"], dict) and g["j"].get("rc") == 4 \
            and g["j"].get("pass") is False:
        _un = g["j"].get("unmeasured") or []
        flags.append("★ json 写 <b>pass=false</b>、同一条 json 又写 <b>rc=4</b> ⇒ 这是"
                     "<b>没量到</b>，不是判红（铁律 199：同形不同因）。它没量到的是：<code>%s</code>"
                     % esc("；".join(str(x) for x in _un) if _un else "（json 里没写是哪一条）"))
    if g["crash"]:
        flags.append("★ run.txt 里出现过 Traceback —— 「崩了」与「没量到」不是一回事")
    # ★ 只有在「去过尾段」才点名：那是唯一可能**挑错兄弟产物**的找法（例如 A1b 的产物
    #   与 A1 的只差一个字母）。同名或按第一个 `_` 截断的都是确定的一对一，不必刷屏。
    if g["jrule"] is not None and g["jrule"] >= 2:
        flags.append("产物名比脚本名短（去过尾段 `<code>%s</code>` —— 找法可能撞上兄弟判据的产物）"
                     % esc(g["jn"]))
    if g["rrule"] is not None and g["rrule"] >= 2:
        flags.append("判词名比脚本名短（去过尾段 `<code>%s</code>`）" % esc(g["rn"]))
    if not g["jp"]:
        flags.append("★ 本判据<b>不落 json</b> —— 判词只活在 run.txt／控制台里")
    if not g["rp"]:
        flags.append("★ <b>连 run.txt 也没有</b> —— 它的判词没留在盘上")
    return st, jr, rr, vr, flags


def fields_rows(j):
    out = []
    if not isinstance(j, dict):
        return out
    for k, v in j.items():
        out.append("<tr><td class='k'>%s</td><td>%s</td><td class='v'>%s</td></tr>"
                   % (esc(str(k)), kind_of(v), brief(v)))
    return out


def build(inject=None):
    gaps = collect_gates()
    if not gaps:
        print("★ 没量到：gates/ 下一个 .py 都没有")
        return 4

    trows, det, warns = [], [], []
    tally = {"PASS": 0, "FAIL": 0, "没量到": 0, "不一致": 0}
    for g in gaps:
        st, jr, rr, vr, flags = judge(g)
        tally[st] = tally.get(st, 0) + 1
        cc = ctl_count(g["j"]) if g["jp"] else None
        ctl = "%d/%d" % cc if cc else "—"
        nf = len(g["j"]) if isinstance(g["j"], dict) and "__bad__" not in g["j"] else 0
        when = stamp(g["jp"] or g["rp"])

        wr = "　".join("%s%s" % (esc(n), tag_at(n)) for n in g["writes"]) or "—"
        stars = [f for f in flags if f.startswith("★")]
        if stars and st != "PASS":
            warns.append((g["gid"], stars))

        # 档 + 该条**最近一次实跑的秒数**（来自 run_gates 落的台账）。没跑过就写「没跑过」——
        # ★ 与「跑了 0.0s」分开写（铁律 197：量具必须分得开「正好 N」与「被截断」）。
        _t = GT.tier_for(g["gid"], is_viewer="viewer" in g["py"].lower())
        _lr = LEDGER["rows"].get(g["gid"])
        _sec = ("%.1f s" % _lr["secs"]) if isinstance(_lr, dict) and "secs" in _lr else "没跑过"
        tcell = ("<span class='tier t-%s'>%s</span><br><span class='w2'>%s</span>"
                 % (esc(_t), esc(_t), esc(_sec)))

        trows.append(
            "<tr><td class='id'>%s</td><td><code>%s</code></td><td>%s</td><td class='%s'>%s</td>"
            "<td class='rd'>%s</td><td class='rd'>%s</td><td class='rd'>%s</td>"
            "<td>%s</td><td>%s</td><td>%s</td></tr>"
            "<tr class='sub'><td></td><td colspan='9' class='doc'>%s"
            "<br><span class='w2'>源码里点到的 _out/ 名字（分不出读写、也分不出文件与目录）：%s</span>%s</td></tr>"
            % (esc(g["gid"]), g["py"], tcell, {"PASS": "pass", "FAIL": "fail"}.get(st, "miss"), st,
               esc(jr), esc(rr), esc(vr), ctl, nf, when, mdb(g["doc"]), wr,
               ("<br><span class='w2'>" + "；".join(flags) + "</span>")
               if flags else ""))
        if isinstance(g["j"], dict) and "__bad__" not in g["j"]:
            det.append("<details><summary><b>" + esc(g["gid"]) + "</b> · "
                       + mdb(g["doc"]) + " · 产物 " + esc(os.path.basename(g["jp"]))
                       + "（" + kb(g["jp"]) + "，" + stamp(g["jp"]) + "）· "
                       + str(nf) + " 顶层字段</summary>"
                       + "<table class='f'><thead><tr><th>字段</th><th>类型</th>"
                         "<th>值</th></tr></thead><tbody>"
                       + "".join(fields_rows(g["j"])) + "</tbody></table></details>")

    csteps = []
    for name, main, what, gs in CHAIN:
        cell = ""
        for x in gs:
            if x.startswith("gates/"):
                st = next((judge(g)[0] for g in gaps if g["py"] == x), "—（gates/ 里没这个脚本）")
                cell += "<span class='gt'><code>%s</code><span class='%s'>%s</span></span>" % (
                    esc(x), {"PASS": "pass", "FAIL": "fail"}.get(st, "miss"), esc(st))
            else:  # 链上的**脚本**不是判据，就别给它安一个判据状态
                cell += "<span class='gt'><code>%s</code></span>" % esc(x)
        csteps.append("<li><b>%s</b> <code>%s</code><span class='w'>%s</span>"
                      "<span class='g'>%s</span></li>"
                      % (name, esc(main), esc(what),
                         ("判据：" if all(x.startswith("gates/") for x in gs) else "脚本／判据：")
                         + cell))

    def script_rows(folder):
        """返回 (行 HTML, 条数) —— 条数由页面自己印，别让谁在正文里手打一个数。"""
        rows = []
        for p in sorted(glob.glob(os.path.join(folder, "*.py"))):
            rel = os.path.relpath(p, ROOT).replace("\\", "/")
            rows.append("<tr><td><code>%s</code></td><td class='doc'>%s</td>"
                        "<td>%s</td><td>%s</td></tr>"
                        % (esc(rel), mdb(doc_first_line(p)), kb(p), stamp(p)))
        return "".join(rows), len(rows)

    a1_html, a1_rows = script_rows(A1)
    tk_html, tk_rows = script_rows(TOOLS)

    # ★ 落盘件体检：**用同一把尺子**（直接 import `tools/lint_json_strict.py`），
    #   不在这页里另写一份判断 —— 两个同名的量必须死掉一个（铁律 174）。
    #   为什么值得占一页版面：坏 JSON 的症状是**浏览器白屏**，而本页的字段表读的
    #   正是这些 json；Python 自己 `json.loads` 默认吃 `NaN` ⇒ **写的人和读的人都在
    #   Python 里，谁也量不出这是坏件**（铁律 123，2026-10-12 实测 J-09.2-A1 命中）。
    def json_health():
        sys.path.insert(0, TOOLS)
        import lint_json_strict as LJS
        files = LJS.gather([ROOT], keep_all=False)
        bad = []
        for p in files:
            st, msg = LJS.scan_file(p)
            if st != "ok":
                bad.append((os.path.relpath(p, ROOT).replace("\\", "/"), st, msg))
        return len(files), bad, set(LJS.SKIP_DIRS)

    n_json, j_bad, j_skip = json_health()
    if j_bad:
        jhealth = ("<table class='w'><thead><tr><th>文件</th><th>判</th><th>说明</th></tr></thead>"
                   "<tbody>"
                   + "".join("<tr><td><code>%s</code></td><td class='fail'>%s</td><td>%s</td></tr>"
                             % (esc(p), esc(st), mdb(msg)) for p, st, msg in j_bad)
                   + "</tbody></table>"
                   # ★ 修法必须**按状态分叉**：linter 早就把 `nan` / `syntax` / `read` 分开了
                   #   （`scan_file` 的三态），可上一版这里只印一条 NaN 的修法 ⇒ 对着一个
                   #   `syntax` 件**指错了因**（2026-10-14 实测命中：`obs_footprint_c006.json`
                   #   是 `np.float32` 抛 TypeError 留下的**半截件**，与 NaN 毫无关系）。
                   #   同形不同因 ⇒ 一个症状类给多个因（铁律 199：崩了 ≠ 没量到）。
                   + "<p class='lead'>★ 它们的共同症状是 <b>Python 读得回、浏览器 "
                   "<code>JSON.parse</code> 抛错</b>（白屏），但<b>因不同，修法也不同</b>，"
                   "照 <b>判</b>那一列分叉：</p>"
                   "<ul class='lead'>"
                   "<li><b>nan</b> —— 裸 <code>NaN</code>/<code>Infinity</code>。落盘改走 "
                   "<code>tools/jsonstrict.py</code> 的 <code>dump()</code>，把「没量到」写成 "
                   "<code>null</code>。</li>"
                   "<li><b>syntax</b> —— ★ 先分清是<b>语法写错</b>还是<b>写到一半断了</b>："
                   "<code>json.dump</code> 是<b>先写后抛</b>，序列化到一半抛异常（实测："
                   "<code>np.float32</code> <b>不是</b> <code>float</code> 子类 ⇒ 抛 "
                   "<code>TypeError</code>）就会在盘上留个<b>断头件</b>，而两种因的读数同形。"
                   "修法两条一起上：显式 <code>float()</code> 转换 ＋ <b>先写 <code>.tmp</code> "
                   "再 <code>os.replace</code></b>（同盘原子）。</li>"
                   "<li><b>read</b> —— 编码 / UTF-8 BOM，浏览器同样抛。</li>"
                   "</ul>")
    else:
        # ★ 空集合不许恒绿：说清「扫了几件、都没触发」，而不是只印一个「无异常」。
        jhealth = ("<p class='lead'>扫了 <b>%d</b> 件 json（跳过 <code>%s</code>），"
                   "<b>0</b> 件不是严格 JSON。</p>"
                   % (n_json, "、".join(sorted(j_skip))))
    jchip = ("<chip class='fail'>坏 JSON %d</chip>" % len(j_bad)) if j_bad \
        else ("<chip>严格 JSON %d 件全绿</chip>" % n_json)

    deliv = []
    for pat in ["demo/*.html", "建设方案V3.8*.docx", "建设方案V3*.md", "规范/*.md"]:
        for p in sorted(glob.glob(os.path.join(ROOT, pat))):
            deliv.append("<tr><td><code>%s</code></td><td>%s</td><td>%s</td></tr>"
                         % (esc(os.path.relpath(p, ROOT).replace("\\", "/")), kb(p), stamp(p)))

    if warns:
        wbox = ("<h2>要点名的格子 <span>上面台账里带 ★ 的那些，都在这儿</span></h2>"
                "<table class='w'><thead><tr><th>编号</th><th>要说的</th></tr></thead><tbody>"
                + "".join("<tr><td class='id'>%s</td><td>%s</td></tr>"
                          % (esc(a), "；".join(bs)) for a, bs in warns)
                + "</tbody></table>")
    else:
        # ★ 空集合不许恒绿：说清「扫了几条、都没触发」，而不是只印一个「无异常」。
        wbox = ("<h2>要点名的格子</h2><p class='lead'>本趟扫了 <b>%d</b> 条判据，"
                "带 ★ 的告警 <b>0</b> 条。</p>" % len(gaps))

    njson = sum(1 for g in gaps if g["jp"])
    subs = {
        "{{NGATE}}": str(len(gaps)), "{{NPASS}}": str(tally["PASS"]),
        "{{NFAIL}}": str(tally["FAIL"]), "{{NMISS}}": str(tally["没量到"]),
        "{{NCONF}}": str(tally["不一致"]),
        "{{NJSON}}": str(njson), "{{NNOJSON}}": str(len(gaps) - njson),
        "{{NOW}}": time.strftime("%Y-%m-%d %H:%M"),
        "{{CHAIN}}": "".join(csteps), "{{TROWS}}": "".join(trows),
        "{{DET}}": "".join(det), "{{WARN}}": wbox,
        "{{A1ROWS}}": a1_html, "{{TKROWS}}": tk_html,
        "{{NA1}}": str(a1_rows), "{{NTK}}": str(tk_rows),
        "{{DELIV}}": "".join(deliv), "{{OUTDIR}}": GOUT.replace("\\", "/"),
        "{{JHEALTH}}": jhealth, "{{JCHIP}}": jchip,
    }
    body = BODY + (inject or "")   # inject 只给正对照用，正常跑是 None
    for k, v in subs.items():
        body = body.replace(k, v)
    # ★ 残留占位符必须**在渲染完的正文里**扫，不许拿 `subs` 的键去扫 ——
    #   第一版就是拿键扫的：`{{A1ROWS}}` 因为**根本不在 subs 里**而整段没被替换，
    #   守卫照样报「没有残留」并 rc=0（铁律 137：名单漏掉主体则永远绿）。
    #   这趟是页面**字节数掉了 9 KB**才露的马脚，不是守卫报的。
    left = sorted(set(re.findall(r"\{\{[A-Z0-9_]+\}\}", body)))
    if left:
        print("★ 还有没替换的占位符:", left)
        return 1

    html = ('<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            '<link rel="icon" href="data:,">'  # 免得控制台留一条 favicon 404
            '<title>cdut3d · 系统总览（字段与流程）</title><style>' + CSS
            + '</style></head><body>' + body + '</body></html>')
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    # ★ 字节层写盘：文本模式在 Windows 上会把 LF 翻成 CRLF，+1 字节/行
    #   （铁律 79）。同一批交付件里 `demo/index.html` 是 LF，别让这页自成一格。
    with open(OUT, "wb") as f:
        f.write(html.encode("utf-8"))
    print("写出 %s（%.1f KB）" % (OUT, os.path.getsize(OUT) / 1024.0))
    print("  判据 %d 条：PASS %d ／ FAIL %d ／ 没量到 %d ／ 不一致 %d（落 json 的 %d 条）"
          % (len(gaps), tally["PASS"], tally["FAIL"], tally["没量到"],
             tally["不一致"], njson))
    print("  要点名的格子 %d 条" % len(warns))
    return 0


CSS = """
 :root{--ink:#e9e6e0;--dim:#8f8b83;--line:#2b2825;--bg:#0f0e0d;--panel:#161513;
   --hi:#c9a227;--ok:#7fd39a;--bad:#e8776d;--warn:#e0b341;
   --mono:ui-monospace,"Cascadia Mono",Consolas,monospace}
 *{box-sizing:border-box}
 body{margin:0;background:var(--bg);color:var(--ink);
   font:14.5px/1.75 "Segoe UI",-apple-system,"Microsoft YaHei",sans-serif;
   background-image:radial-gradient(120% 70% at 84% -12%,#1c1b18,#0f0e0d 62%)}
 header{display:flex;align-items:baseline;gap:12px;flex-wrap:wrap;
   padding:20px 30px 16px;border-bottom:1px solid var(--line);background:#131211}
 header h1{margin:0 12px 0 0;font-size:21px;letter-spacing:.4px}
 header .sub{color:var(--dim);font-size:13px;margin-right:auto}
 chip{display:inline-block;padding:3px 10px;border:1px solid var(--line);border-radius:999px;
   font:12.5px var(--mono);color:var(--dim);white-space:nowrap}
 main{padding:26px 30px 60px;max-width:1560px}
 h2{font-size:16px;margin:34px 0 12px;padding-left:10px;border-left:3px solid var(--hi);
   letter-spacing:.3px}
 h2 span{color:var(--dim);font-weight:400;font-size:13px;margin-left:8px}
 p.lead{color:#cbc7bf;margin:0 0 8px}
 p.lead b{color:var(--hi)}
 code{font:12.5px var(--mono);background:#1e1c19;border:1px solid var(--line);
   border-radius:5px;padding:1px 6px;color:#dcd6cb}
 table{width:100%;border-collapse:collapse;background:var(--panel);
   border:1px solid var(--line);border-radius:10px;overflow:hidden}
 th,td{padding:8px 11px;border-bottom:1px solid var(--line);vertical-align:top;text-align:left}
 th{background:#1b1917;color:var(--dim);font-weight:600;font-size:12.5px;letter-spacing:.4px}
 tr:last-child td{border-bottom:0}
 tr.sub td{background:#131211;border-bottom:1px solid var(--line);padding-top:2px}
 td.id{font:12.5px var(--mono);color:var(--hi);white-space:nowrap}
 td.doc{color:#c7c3bb}
 td.rd{font:12px var(--mono);color:#d5d0c7;white-space:nowrap}
 td.k{font:12.5px var(--mono);color:#dcd6cb;width:190px}
 td.v{font:12px var(--mono);color:var(--dim);word-break:break-all;max-width:620px}
 .pass{color:var(--ok);font-weight:600}
 .fail{color:var(--bad);font-weight:600}
 .miss{color:var(--warn);font-weight:600}
 .dir{color:#8fb8d3;font-weight:600}
 .w2{color:#a9a49b}
 /* 档位徽标：颜色只用来分档，不表示好坏（每档都有留下的理由） */
 .tier{display:inline-block;padding:1px 7px;border-radius:9px;font:11.5px var(--mono);
   border:1px solid #3a3f47;color:#cfc8bd;background:#20242b}
 .t-quick{border-color:#3f6b4f;color:#a8d8b8;background:#18251d}
 .t-dxf{border-color:#3d5a76;color:#a9c8e4;background:#18222c}
 .t-cad{border-color:#7a5a2e;color:#e0be86;background:#2a2318}
 .t-viewer{border-color:#5b4a72;color:#c9b3e2;background:#231d2b}
 .t-other{border-color:#4a4a4a;color:#b9b3a9;background:#1e1e1e}
 ol.chain{list-style:none;margin:0;padding:0}
 ol.chain li{position:relative;padding:12px 14px 12px 18px;margin:0 0 8px;
   border:1px solid var(--line);border-left:3px solid var(--hi);border-radius:8px;background:#161513}
 ol.chain li b{color:var(--hi);margin-right:8px}
 ol.chain li .w{display:block;color:#c7c3bb;margin:4px 0}
 ol.chain li .g{display:block;color:var(--dim);font-size:12.5px;line-height:2.4}
 ol.chain li .g .gt{display:inline-block;margin:0 16px 4px 0;white-space:nowrap}
 ol.chain li .g .gt code{margin-right:6px;font-size:12px}
 details{margin:8px 0;border:1px solid var(--line);border-radius:9px;background:#141311}
 details>summary{cursor:pointer;padding:10px 13px;color:#cbc7bf}
 details>summary b{color:var(--hi)}
 table.f{margin:0}
 table.w td{font-size:13px}
 footer{margin-top:36px;padding-top:16px;border-top:1px solid var(--line);color:var(--dim);
   font-size:12.5px;line-height:1.9}
"""

BODY = """
<header>
  <h1>cdut3d · 系统总览</h1>
  <span class="sub">字段与流程都在这一页上 —— 改哪儿就从这儿点回去</span>
  <chip>{{NGATE}} 条判据</chip><chip class="pass">PASS {{NPASS}}</chip>
  <chip class="fail">FAIL {{NFAIL}}</chip><chip class="miss">没量到 {{NMISS}}</chip>
  <chip class="miss">读数不一致 {{NCONF}}</chip>
  <chip>落 json {{NJSON}} / 不落 {{NNOJSON}}</chip>
  {{JCHIP}}
  <chip>生成于 {{NOW}}</chip>
</header>
<main>

<p class="lead">本页由 <code>tools/build_sys_page.py</code> 现场生成：判据的作用抄自各自
的 docstring、字段名与类型从 <code>gates/_out/*.json</code> 现读、rc 与判词从 run.txt 现读、
大小与时刻取盘上文件。<b>一个数都不手打</b> —— 手打的会静默过期，这页就成了第二种真相。</p>

<h2>流程 · 数据到交付 <span>每一步都给了文件，判据状态也是现读的</span></h2>
<ol class="chain">{{CHAIN}}</ol>
<p class="lead">★ 次序是结构声明，不是读数；每一步的<em>作用</em>抄自该脚本自己的 docstring。</p>

<h2>判据台账 <span>三路读数并排摆着，谁也不替谁说话</span></h2>
<p class="lead">★ <b>「档」＝改哪一块才需要重跑这一条</b>（表在 <code>tools/gate_tiers.py</code>，
<code>run_gates.py</code> 与本页都 import 同一份，不许各写一份）。徽标后面的秒数是<b>该条最近一次实跑</b>的耗时，
取自 <code>gates/_out/_ledger.json</code>（<code>run_gates.py</code> 每趟落一次）；<b>「没跑过」与「0.0 s」是两回事</b>。<br>
★★ <b>2026-10-12 决定：CAD 档不进默认套件</b>。依据是实测不是估计 —— 判据 <code>J-07.9.4-03</code> 的
<b>定向臂在最终模型上 Δ足迹 = 0.000 m²</b>（那 300 mm 残段整个落在既有墙足迹里），而 CAD 三条占全量墙钟
<b>六成以上</b>、每趟冷启 <b>6 次 AutoCAD</b>；且外墙缝已由 <code>tools/wall_close.py</code>（纯几何、
判据 <code>J-09.2-A1e</code>，留在 quick 档）以 <b>1412 根 / 补后残留 0</b> 补上，不需要 AutoCAD。
⇒ 默认只跑 <code>quick + dxf</code>；要 CAD 跑 <code>--cad</code> 或 <code>--full</code>。
<b>代价写在旁边</b>：CAD 链与 <code>out.dxf</code> 若断，默认这趟<b>不会报</b>，发版前须跑一次 <code>--full</code>。</p>
<table><thead><tr><th>编号</th><th>脚本</th><th>档 / 最近实测</th><th>状态</th><th>json 的 pass</th>
<th>rc</th><th>run.txt 判词</th><th>正对照</th><th>顶层字段</th><th>产物时刻</th></tr></thead>
<tbody>{{TROWS}}</tbody></table>
<p class="lead">★ <b>读数分三路</b>：① 产物 json 的 <code>pass</code> ② run.txt 里的
<code>rc=</code> ③ run.txt 里的判词行（<code>PASS</code>／<code>FAIL</code>／<code>总判</code>）。
<b>哪一路没有就写「没有」</b>，不许拿另一路冒充 —— 本仓有 <b>{{NNOJSON}}</b> 条判据
<b>不落 json</b>，只读 json 会把它们的 PASS 印成「没量到」。<br>
★「没量到」与「FAIL」<b>分开写</b>；run.txt 里出现过 <code>Traceback</code> 的单独点名
（崩了 ≠ 没量到）。<br>
★「正对照」只数 json 里 <code>controls</code> 的 bool 叶子（全真才算全触发）；那格记 — 的，
<b>不代表它没有对照</b>，去读它的 run.txt。<br>
★「源码里点到的 _out/ 名字」是正则扫出来的（<b>会漏</b>：路径靠变量拼的扫不到），
<b>分不出读还是写、也分不出文件还是目录</b>，而且<b>凡是源码里带 `_out` 的路径都收</b>
—— 所以名字先在 `gates/_out/` 找、再到仓库根的 `_out/` 找，<b>两个都没有</b>才写
「这两个 _out 下都没有」（例如 `chain/_out/chain_run.json` 住在链那边）——
<b>「不在我找的这两个目录里」不等于「不存在」</b>。只当线索，不当结论。</p>

{{WARN}}

<h2>落盘件体检 · 交付面上的 json <span>尺子 <code>tools/lint_json_strict.py</code>，读数现算</span></h2>
{{JHEALTH}}
<p class="lead">★ <b>为什么单列一格</b>：坏 JSON 的症状是<b>浏览器白屏</b>，而下面那张字段表读的正是这些
json。Python 的 <code>json.loads</code> <b>默认吃</b> <code>NaN</code> ⇒ <b>写的人和读的人都在 Python 里，
谁也量不出这是坏件</b>（铁律 123）。⇒ 「没量到」一格一律写 <code>null</code>，不写裸 <code>NaN</code>；
落盘走 <code>tools/jsonstrict.py</code>。本格的数与那条命令的读数<b>同源</b>（页面直接 import 那把尺子）。</p>

<h2>字段 · 每个判据产物的顶层字段 <span>点开看值</span></h2>
{{DET}}

<h2>链上的脚本（a1/）<span>{{NA1}} 个 · 作用抄自各自 docstring 首行</span></h2>
<table><thead><tr><th>文件</th><th>作用</th><th>大小</th><th>时刻</th></tr></thead>
<tbody>{{A1ROWS}}</tbody></table>

<h2>工具（tools/）<span>{{NTK}} 个</span></h2>
<table><thead><tr><th>文件</th><th>作用</th><th>大小</th><th>时刻</th></tr></thead>
<tbody>{{TKROWS}}</tbody></table>

<h2>交付面 <span>页面 · 文档 · 规范</span></h2>
<table><thead><tr><th>文件</th><th>大小</th><th>时刻</th></tr></thead><tbody>{{DELIV}}</tbody></table>

<footer>生成器 <code>tools/build_sys_page.py</code>。判据的产物在
<code>{{OUTDIR}}</code>；判据本身在 <code>gates/</code>。★ 只报不判的格子在页上写明了；
★ 这页只负责<em>看得见</em>，判的仍是各判据自己的读数。<br>
演示页：<code>demo/index.html</code>（模型包查看器）· <code>demo/wallclose.html</code>（墙层闭合接进链）。</footer>
</main>
"""

if __name__ == "__main__":
    # ★ 守卫要有**分辨力**：塞一个没人替换的占位符，它必须 rc=1。
    #   不喂这一口，就分不清「真的没有残留」与「守卫根本看不见残留」（铁律 137）。
    if "--selftest-placeholder" in sys.argv:
        rc = build(inject="\n{{ZZZ_SELFTEST}}\n")
        print("正对照（塞一个没人替换的占位符）rc=%d ⇒ %s"
              % (rc, "✓ 守卫活着（按预期 rc=1）" if rc == 1 else "★ 守卫死了"))
        sys.exit(0 if rc == 1 else 3)
    sys.exit(build())
