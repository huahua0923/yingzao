# -*- coding: utf-8 -*-
r"""判据 J-10.9-04：构件库对照页（`demo/parts.html`）**屏幕上的数**，必须就是两份 json 里的数。

★ 用户原话是「**你能不能建一个构件库，可以比对**」⇒ 交付物里有这一页。
  页面自己在页脚声明「本页不写死任何数字」（`parts.html:484-490`）—— 本闸就核这句话是不是真的：
  用**真浏览器**打开、读**渲染后的 DOM**，把屏幕上的每个数与 `参数.json` / `对照.json` 现算的结果逐字比。

判据
 ① 页脚两个时刻各自对上源件：`（更新 <参数.json::更新>）` 与 `（生成于 <对照.json::生成时刻>）`
    必须**连标签带值逐字**出现在 `#foot`。★ 不许只找裸值 —— `更新` 只有年月日，
    同一段页脚里还印着 `生成于 2026-10-15 …`，裸子串会被另一个时刻喂饱（对照 C3 首轮就这么假绿过）。
 ② 顶栏七格逐字对上（都从两份 json 现算）：参数条数 ／ 实测·假设 ／ 规范·旧规范 ／ 待坐实 ／
    对照数据时刻 ／ 门扇·梯间·竖井行 ／ 门头墙漏。
 ③ 门面板的**逐层表**：层序 + 每层 8 列（层/门扇/有门头/漏/贴墙/离墙/块/m²）+ 合计行，逐字比。
 ④ 楼梯面板的「读数」表：7 个读数行的「值 × 个数」串、两跑/单跑，逐字比；表里**不许有**现算之外的行走。
 ⑤ 竖井面板的净空表：每行 dims/次数/面积/层数 逐字比；且 `参数.json::竖井/判定.值`
    **原句必须印在页面上**（判词是数据、必须在脸上）。
 ⑥ 三栏都在，且三栏标题里带着**用户报的三条症状原话**（「门上面的缺失」「楼梯样式不对」
    「电梯生成的也不是不对」）—— 这一页是为这三条建的，不许悄悄丢掉其中一条。
 ⑦ 页面上出现**读不到数据文件**的报错块 ⇒ 红（这不是「量不到」：那个错误块本身是被量到的读数）。

量具
 `demo/parts.html` 在本机 `127.0.0.1:<临时端口>` 下用 **python playwright（chromium）** 打开，
 读渲染后的 DOM（`gates/J-09.1.1-viewer.py` 的先例）。★ **不另起常驻服务器**：端口写 0 由内核分配，
 用完即关；也**不碰**已在跑的 8451。两份 json 是唯一真源，页面里每个数都由本闸**独立现算**再逐字比
 ⇒ 「页面抄死了一份旧数」这件事，会以「比不过」的形式现形（对照用的合成件顺带证明这一点）。

量具盲区（★先声明，再判）
 · 只核**读数**，不核**版面**：颜色、红字/绿字/字重、`<span class="bad">` 的落点，本闸一概看不见
   （那是像素的活，做成了也脆）。
 · 只核落进上面 7 条口径的那几格：页面上还有散文、注释、链接与 `title` 上的出处，本闸不逐句核
   ⇒ 「页面上某句话数字写错了」只有在它落进 7 条口径时才拦得住。
 · 三张构件特写图（`closeup_{door,stair,shaft}_{iso,front,top}.png` 等）只作**读数**记「在不在」，
   **本闸不判**（判了会把「图还没出」记成「对照页错了」，两件事不该混）。
 · `参数.json` 里没进页面的字段（例如只进 `title` 的 `出处`）核不到。
 · 只核 `demo/parts.html`；`demo/index.html` / `slab.html` 的读数不在本闸内（另有 `J-09.1.1`）。
 · ★ 「页面取不到」与「页面画出来了但报错」**分开**（铁律 199）：`parts.html` 取不到 / 浏览器没装 /
   20 s 内没画出来 ⇒ **SKIP(rc=4)「没量到」**；页面画出来了却报「读不到数据文件」⇒ **FAIL(rc=1)**，
   因为那个错误块是**量到的读数**，不是量不到。
   （与方案里「缺 json ⇒ rc=4」的写法不同：缺 json 时页面**照样能画**、且画出了确定的错 ⇒ 按「错误」算；
   真进 rc=4 的是页面本身取不到，见 C5。）

正对照（每条必须**因该因**而红；`新增 N 条` 是相对 C1 基线的**差集**，铁律 183）
 ★ 对照件落在 `gates/_out/_page_probe_<tag>/`（`parts.html` 字节拷贝 + 改过的 json）；
   **被改过的那版 json 只喂给页面**，期望值一律取原版 ⇒ 对照证明的是
   「json 一变、页面就跟着变」（页面若把数抄死在 HTML 里，对照不会红）。
 C1 真件                —— 基线
 C2 对照.json 一层门扇 +1 —— ② 与 ③ 红（顶栏合计 + 该层逐行）
 C3 参数.json 更新时刻改 —— ① 红（② 不动：`更新` 不进顶栏）
 C4 对照.json 生成时刻改 —— ① 与 ② 红（页脚 + 顶栏的「对照数据时刻」）
 C5 页面不存在           —— SKIP(rc=4)（真进 rc=4 的那条路）

三态：rc=0 PASS ／ rc=1 FAIL（含页面报错块）／ rc=4 SKIP（页面取不到、浏览器没装、没画出来）
"""
import functools
import http.server
import json
import math
import os
import shutil
import socketserver
import sys
import threading

sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = r"D:\项目\cdut3d"
PAGE = "demo/parts.html"
REL_PARAM = os.path.join("rebuild", "构件库", "参数.json")
REL_DZ = os.path.join("rebuild", "构件库", "对照.json")
PARAM = os.path.join(ROOT, REL_PARAM)
DUIZHAO = os.path.join(ROOT, REL_DZ)
OUTD = os.path.join(HERE, "_out")
OUT = os.path.join(OUTD, "J-10.9-04.run.txt")

SYMPTOMS = ("门上面的缺失", "楼梯样式不对", "电梯生成的也不是不对")
BLIND = [
    "只核读数不核版面：颜色/红绿/字重/<span class=bad> 的落点全部看不见",
    "只核落进 7 条口径的那几格：页面上的散文/注释/链接与 title 上的出处不逐句核",
    "构件特写图只作读数记「在不在」，本闸不判（图还没出不该记成对照页错了）",
    "参数.json 里没进页面的字段（如只作 title 的 出处）核不到",
    "只核 demo/parts.html；index.html / slab.html 的读数不在本闸内",
    "★ 页面取不到/没画出来 ⇒ rc=4；页面画出来了但报「读不到数据文件」⇒ rc=1（那个错误块是被量到的读数）",
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
        return os.path.join(OUTD, "J-10.9-04.json")
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


# ---------- 与页面 `parts.html:121-124` 逐字对齐的三个格式器 ----------
def jsnum(x):
    """JS 的 String(number)：整数值不带小数点（1853.0 → '1853'）。"""
    if isinstance(x, float) and x.is_integer():
        return str(int(x))
    return repr(x) if isinstance(x, float) else str(x)


def nfmt(x):
    """页面 `const n = x => …`：整值印整数，否则 `+x.toFixed(3)`（去尾零）。"""
    if not isinstance(x, (int, float)) or isinstance(x, bool):
        return str(x)
    if abs(x - round(x)) < 1e-9:
        return str(int(round(x)))
    return ("%.3f" % x).rstrip("0").rstrip(".")


def jsround(x):
    """页面用 `Math.round`（.5 一律向上），Python 的 round 是银行家舍入 ⇒ 不一致会假红。"""
    return int(math.floor(x + 0.5))


def ws(s):
    return " ".join(str(s).split())


# ---------- 页面侧：临时端口 + 真浏览器读 DOM ----------
class _Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass


class _Srv(socketserver.ThreadingTCPServer):
    daemon_threads = True

    def handle_error(self, request, client_address):
        # 浏览器读完就掐连接 ⇒ 每次都吐一屏 ConnectionResetError，把判词淹掉。
        # 只静音这三类「对端先走」的；别的照旧往上抛，不把真错也吞了。
        e = sys.exc_info()[1]
        if isinstance(e, (ConnectionResetError, ConnectionAbortedError, BrokenPipeError)):
            return
        socketserver.ThreadingTCPServer.handle_error(self, request, client_address)


def serve(root):
    srv = _Srv(("127.0.0.1", 0), functools.partial(_Quiet, directory=root))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, srv.server_address[1]


DOM_JS = r"""() => {
  const t = e => e ? e.textContent.replace(/\s+/g,' ').trim() : null;
  const out = {err:null, bar:[], panels:[], band:[], bandtext:[], foot:null, imgs:[]};
  out.err  = t(document.querySelector('#cols .err'));
  out.foot = t(document.querySelector('#foot'));
  document.querySelectorAll('#bar > div').forEach(d=>{
    out.bar.push([t(d.querySelector('.k')), t(d.querySelector('.v'))]);});
  document.querySelectorAll('#cols > .comp').forEach(p=>{
    out.panels.push({
      h2: t(p.querySelector('h2')),
      text: t(p),
      tables: Array.from(p.querySelectorAll('table')).map(tb=>Array.from(tb.querySelectorAll('tr'))
        .map(tr=>Array.from(tr.querySelectorAll('th,td')).map(c=>t(c))))});});
  document.querySelectorAll('.diffs > .comp > h2').forEach(h=>out.band.push(t(h)));
  // ★ 「差在哪」那三块不在 #cols 里（`parts.html:115` 把 s3 推给 DIFFS 单独铺一行），
  //   竖井的判词原句就印在这里 ⇒ 判词查找必须带上它的**全文**，不能只取 h2。
  document.querySelectorAll('.diffs > .comp').forEach(d=>out.bandtext.push(t(d)));
  document.querySelectorAll('#cols img, .diffs img').forEach(i=>out.imgs.push(i.getAttribute('src')));
  return out;
}"""


def probe_url(url, timeout_ms=20000):
    """打开页面、等它画出来、读 DOM。返回 (dom, err_kind)；err_kind 非空 ⇒ 没量到。"""
    try:
        from playwright.sync_api import sync_playwright
    except Exception as e:                                        # noqa: BLE001
        return None, "没装 playwright（%s）" % e
    try:
        with sync_playwright() as pw:
            b = pw.chromium.launch()
            try:
                pg = b.new_page()
                try:
                    r = pg.goto(url, timeout=timeout_ms)
                    code = r.status if r else 0
                    if code >= 400:
                        return None, "HTTP %d（%s）" % (code, url)
                    pg.wait_for_function(
                        "() => {const c=document.querySelector('#cols');"
                        "return c && c.children.length>0;}", timeout=timeout_ms)
                except Exception as e:                            # noqa: BLE001
                    return None, "%d ms 内 #cols 一个孩子都没有（没画出来：%s）%s" % (
                        timeout_ms, url, e)
                return pg.evaluate(DOM_JS), ""
            finally:
                b.close()
    except Exception as e:                                        # noqa: BLE001
        return None, "浏览器起不来/打不开（%s）" % e


def probe_at(root, page_rel):
    srv, port = serve(root)
    try:
        log("  临时端口 %d（127.0.0.1，用完即关；不用 8451）→ %s" % (port, page_rel))
        return probe_url("http://127.0.0.1:%d/%s" % (port, page_rel))
    finally:
        srv.shutdown()


# ---------- 现算期望值 ----------
def bar_expected(P, D):
    allp = [P["构件"][c][k] for c in P["构件"] for k in P["构件"][c]]
    mk = lambda m: len([x for x in allp if x["标注"] == m])
    return [["参数条数", "%d" % len(allp)],
            ["实测 / 假设", "%d / %d" % (mk("实测"), mk("假设"))],
            ["规范 / 旧规范", "%d / %d" % (mk("规范"), mk("旧规范"))],
            ["待坐实（无值）", "%d" % mk("待坐实")],
            ["对照数据时刻", D.get("生成时刻") or "—"],
            ["门扇 / 梯间 / 竖井行", "%d / %d / %d" % (sum(r["门扇"] for r in D["构件"]),
                                                     len(D["楼梯形制"]), len(D["竖井"]))],
            ["门头墙漏", "%d" % sum(r["漏了"] for r in D["构件"])]]


def stair_expected(F):
    out = {}
    for k, label in (("踏面_mm", "踏面 mm"), ("踢面_mm", "踢面 mm"), ("级数_每跑", "每跑级数"),
                     ("梯段宽_mm", "梯段宽 mm"), ("梯井宽_mm", "梯井宽 mm"),
                     ("平台厚_mm", "平台厚 mm"), ("半层高_mm", "半层高 mm")):
        m = {}
        for r in F:
            m[r[k]] = m.get(r[k], 0) + 1
        out[label] = "、".join(nfmt(v) + (" ×%d" % m[v] if m[v] > 1 else "")
                              for v in sorted(m))
    one = [r for r in F if not r["两跑"]]
    out["两跑 / 单跑"] = "%d / %d" % (len(F) - len(one), len(one)) + (
        " （" + "；".join("%s@(%d, %d)" % (r["层"], jsround(r["中点_xy"][0]), jsround(r["中点_xy"][1]))
                         for r in one) + "）" if one else "")
    out["栏杆 条 / 贴墙跳过 / 块"] = "%d / %d / %d" % (
        sum(r["栏杆_侧"] for r in F), sum(r["栏杆_贴墙"] for r in F), sum(r["栏杆_块"] for r in F))
    return out


def shaft_expected(S):
    m = {}
    for r in S:
        m.setdefault("%s×%s" % (jsnum(r["净宽_mm"]), jsnum(r["净高_mm"])), []).append(r)
    rows = []
    for k in sorted(m, key=lambda k: -len(m[k])):
        hit = m[k]
        rows.append([k + " mm", "%d" % len(hit), nfmt(hit[0]["净面积_m2"]),
                     "%d 层" % len({r["层"] for r in hit})])
    return rows


# ---------- 判 ----------
def judge(dom, P, D):
    fs = []
    lay = D["构件"]

    # ① 页脚两个时刻
    # ★ 必须**贴着页脚的标签取**（`（更新 …）` / `（生成于 …）`），不能只找裸值：
    #   `更新` 只是年月日，而同一段页脚里还有 `生成于 2026-10-15 14:37:49` ——
    #   裸子串会被另一个时刻喂饱，把「更新错了」判成绿（今天 C3 就是这么假绿的）。
    foot = dom["foot"] or ""
    for tag, want in (("（更新 %s）", P.get("更新") or "—"),
                      ("（生成于 %s）", D.get("生成时刻") or "—")):
        if (tag % want) not in foot:
            fs.append("① 页脚里找不到 %r（页脚：%s）" % (tag % want, foot[:160]))

    # ② 顶栏七格
    bar = dom["bar"]
    want = bar_expected(P, D)
    if len(bar) != len(want):
        fs.append("② 顶栏 %d 格，应为 %d 格" % (len(bar), len(want)))
    for i, (k, v) in enumerate(want):
        if i >= len(bar):
            break
        if ws(bar[i][0]) != k:
            fs.append("② 顶栏第 %d 格的标签是 %r，应为 %r" % (i + 1, ws(bar[i][0]), k))
        if ws(bar[i][1]) != v:
            fs.append("② 顶栏「%s」＝%r，现算应为 %r" % (k, ws(bar[i][1]), v))

    # ③ 门逐层表
    door = None
    for p in dom["panels"]:
        for tb in p["tables"]:
            if tb and tb[0] and ws(tb[0][0]) == "层":
                door = tb
    if not door:
        fs.append("③ 门面板里找不到表头首格为「层」的表 ⇒ 逐层表没画出来")
    else:
        if len(door) != len(lay) + 2:
            fs.append("③ 门逐层表 %d 行（含表头/合计），应为 %d 行" % (len(door), len(lay) + 2))
        for i, r in enumerate(lay):
            if i + 1 >= len(door):
                break
            exp = [r["层"], "%d" % r["门扇"], "%d" % r["有门头"], "%d" % r["漏了"],
                   "%d" % r["漏_贴墙"], "%d" % r["漏_离墙"], "%d" % r["块"],
                   nfmt(r["面积合计_m2"])]
            got = [ws(x) for x in door[i + 1]]
            if got != exp:
                fs.append("③ 门逐层表第 %d 行＝%s，现算应为 %s" % (i + 1, got, exp))
        T = lambda k: sum(r[k] for r in lay)
        exp = ["合计", "%d" % T("门扇"), "%d" % T("有门头"), "%d" % T("漏了"),
               "%d" % T("漏_贴墙"), "%d" % T("漏_离墙"), "%d" % T("块")]
        got = [x for x in (ws(c) for c in door[-1]) if x]
        if got != exp:
            fs.append("③ 门逐层表合计行＝%s，现算应为 %s" % (got, exp))

    # ④ 楼梯读数表
    stair = None
    for p in dom["panels"]:
        for tb in p["tables"]:
            if tb and tb[0] and ws(tb[0][0]) == "读数":
                stair = tb
    if not stair:
        fs.append("④ 楼梯面板里找不到表头首格为「读数」的表")
    else:
        exp = stair_expected(D["楼梯形制"])
        got = {ws(r[0]): ws(r[1]) for r in stair[1:] if len(r) >= 2}
        for k, v in exp.items():
            if k not in got:
                fs.append("④ 楼梯读数表缺「%s」这一行" % k)
            elif got[k] != v:
                fs.append("④ 楼梯读数「%s」＝%r，现算应为 %r" % (k, got[k], v))
        for k in got:
            if k not in exp:
                fs.append("④ 楼梯读数表多出一行「%s」（＝%r），本闸现算里没有这一项" % (k, got[k]))
        if len(stair) != len(exp) + 1:
            fs.append("④ 楼梯读数表 %d 行（含表头），现算应有 %d 行" % (len(stair), len(exp) + 1))

    # ⑤ 竖井净空表 + 判词原句
    sh = None
    for p in dom["panels"]:
        for tb in p["tables"]:
            if tb and tb[0] and "井道内空" in ws(tb[0][0]):
                sh = tb
    if not sh:
        fs.append("⑤ 竖井面板里找不到表头含「井道内空」的表")
    else:
        exp = shaft_expected(D["竖井"])
        got = [[ws(x) for x in r] for r in sh[1:]]
        if got != exp:
            fs.append("⑤ 竖井净空表＝%s，现算应为 %s" % (got, exp))
    verdict = P["构件"]["竖井"]["判定"]["值"]
    body = " ".join([foot] + [p["text"] or "" for p in dom["panels"]]
                    + dom["bandtext"] + dom["band"])
    if verdict not in body:
        fs.append("⑤ 竖井判词原句 %r 没印在页面上（判词是数据，必须在脸上）" % verdict)

    # ⑥ 三栏 + 三条症状原话
    if len(dom["panels"]) != 3:
        fs.append("⑥ 面板 %d 栏，应为 3 栏（门/楼梯/竖井）" % len(dom["panels"]))
    for s in SYMPTOMS:
        if not any(s in (p["h2"] or "") for p in dom["panels"]):
            fs.append("⑥ 三栏标题里找不到用户报的症状原话 %r" % s)

    # ⑦ 页面报错块
    if dom["err"]:
        fs.append("⑦ 页面上报出「读不到数据文件」：%s" % ws(dom["err"])[:200])

    miss = []
    for s in sorted(set(x for x in dom["imgs"] if x)):
        p = os.path.normpath(os.path.join(ROOT, "demo", s))
        if not os.path.isfile(p):
            miss.append(s)
    return fs, {
        "顶栏": [[ws(k), ws(v)] for k, v in bar],
        "三栏": [ws(p["h2"]) for p in dom["panels"]],
        "差在哪": dom["band"],
        "页脚": foot[:200],
        "参数条数": len([1 for c in P["构件"] for _ in P["构件"][c]]),
        "门扇合计": sum(r["门扇"] for r in lay),
        "梯间行": len(D["楼梯形制"]), "竖井行": len(D["竖井"]),
        "件里判词": verdict,
        "页上图片": len(dom["imgs"]), "找不到的图": miss,
    }


def load(pfile, dfile):
    P = json.load(open(pfile, "r", encoding="utf-8"))
    D = json.load(open(dfile, "r", encoding="utf-8"))
    lack = [k for k in ("构件", "更新") if k not in P] + \
           [k for k in ("生成时刻", "构件", "楼梯形制", "竖井") if k not in D]
    if lack:
        raise ValueError("件形状不对：缺 %s" % lack)
    return P, D


def main():
    argv = sys.argv[1:]
    out = argv[argv.index("--out") + 1] if "--out" in argv else OUT
    page_rel = argv[argv.index("--page") + 1] if "--page" in argv else PAGE

    _LOG.clear()
    log("J-10.9-04 · 构件库对照页上的数，是不是 json 里的数（%s）" % page_rel)
    log("  真源：%s ／ %s" % (REL_PARAM, REL_DZ))

    lack = [p for p in (os.path.join(ROOT, PAGE), PARAM, DUIZHAO) if not os.path.isfile(p)]
    if lack:
        log("★ 没量到：缺 %s ⇒ SKIP(rc=4)" % [os.path.relpath(p, ROOT) for p in lack])
        return finish(4, out, {"n_missing": len(lack),
                               "missing": [os.path.relpath(p, ROOT) for p in lack]})

    dom, ek = probe_at(ROOT, page_rel)
    if ek:
        log("  ★ 没量到：%s ⇒ SKIP(rc=4)" % ek)
        return finish(4, out, {"probe_error": ek})

    try:
        P, D = load(PARAM, DUIZHAO)
    except Exception as e:                                        # noqa: BLE001
        log("  ★ 没量到：%s ⇒ SKIP(rc=4)" % e)
        return finish(4, out, {"probe_error": str(e)})

    base, head = judge(dom, P, D)
    log("  ① 页脚 %s" % head["页脚"])
    for i, (k, v) in enumerate(head["顶栏"]):
        log("  ② 顶栏 %d. %-18s = %s" % (i + 1, k, v))
    log("  ⑥ 三栏 %s" % "｜".join(head["三栏"]))
    log("  读数 参数 %d 条 ｜ 门扇合计 %d ｜ 梯间 %d 行 ｜ 竖井 %d 行 ｜ 件里判词 %r"
        % (head["参数条数"], head["门扇合计"], head["梯间行"], head["竖井行"], head["件里判词"]))
    log("  页上 %d 张图（读不到 %d 张：%s）—— 只作读数，本闸不判"
        % (head["页上图片"], len(head["找不到的图"]), head["找不到的图"] or "—"))
    log("-" * 78)
    log("C1 真件 ⇒ 违反 %d 条" % len(base))
    for x in base:
        log("    " + x)
    bad = list(base)

    def ctl(name, fs_, want):
        new = [x for x in fs_ if x not in base]
        got = sorted({ws(x).split(" ")[0] for x in new})     # ★ 标签可能带 ③a/⑤b，不许只取 x[0]
        ok = bool(new) and got == sorted(want)
        log("  对照 %-20s → %s（新增 %d 条，要 %s，实得 %s）"
            % (name, "✔红" if ok else "✘没红/红错因", len(new), "".join(want), "".join(got) or "—"))
        for x in new:
            log("      · " + x)
        if not ok:
            bad.append("对照 %s 没按预期红（要 %s，实得 %s，新增 %d 条）"
                       % (name, "".join(want), "".join(got) or "无", len(new)))

    def probe_tampered(tag, mutate_p=None, mutate_d=None):
        """把 json 改一版放进合成根，**另外起一个端口**再读一次真页面。

        ★ 期望值必须取**原版** json（`P0/D0`），被改过的那版**只喂给页面**：
          页面本就从 json 现算 ⇒ 两边都用改过的数会「一起动、比得过」，对照就永远不红（今天踩过）。
          这样一改，对照真正证明的是「**json 一变页面就跟着变**」——页面若把数抄死在 HTML 里就不会红。
        """
        P0, D0 = load(PARAM, DUIZHAO)
        P = json.loads(json.dumps(P0, ensure_ascii=False))
        D = json.loads(json.dumps(D0, ensure_ascii=False))
        if mutate_p:
            mutate_p(P)
        if mutate_d:
            mutate_d(D)
        d = os.path.join(OUTD, "_page_probe_" + tag)
        shutil.rmtree(d, ignore_errors=True)
        os.makedirs(os.path.join(d, "demo"), exist_ok=True)
        os.makedirs(os.path.join(d, os.path.dirname(REL_PARAM)), exist_ok=True)
        shutil.copyfile(os.path.join(ROOT, PAGE), os.path.join(d, PAGE))
        for rel, obj in ((REL_PARAM, P), (REL_DZ, D)):
            with open(os.path.join(d, rel), "w", encoding="utf-8") as fh:
                json.dump(obj, fh, ensure_ascii=False, indent=1)
        dom2, ek2 = probe_at(d, page_rel)
        if ek2:
            return None, ek2
        fs2, _ = judge(dom2, P0, D0)
        return fs2, ""

    fs2, ek2 = probe_tampered(
        "c2", mutate_d=lambda D: D["构件"][0].__setitem__("门扇", D["构件"][0]["门扇"] + 1))
    if ek2:
        bad.append("对照 C2 没量到：%s" % ek2)
        log("  对照 %-20s → ✘没量到（%s）" % ("C2 一层门扇+1", ek2))
    else:
        ctl("C2 一层门扇+1", fs2, ["②", "③"])

    fs3, ek3 = probe_tampered("c3", mutate_p=lambda P: P.__setitem__("更新", "1999-01-01 00:00:00"))
    if ek3:
        bad.append("对照 C3 没量到：%s" % ek3)
        log("  对照 %-20s → ✘没量到（%s）" % ("C3 参数更新时刻改", ek3))
    else:
        ctl("C3 参数更新时刻改", fs3, ["①"])

    fs4, ek4 = probe_tampered("c4", mutate_d=lambda D: D.__setitem__("生成时刻", "1999-01-01 00:00:00"))
    if ek4:
        bad.append("对照 C4 没量到：%s" % ek4)
        log("  对照 %-20s → ✘没量到（%s）" % ("C4 对照生成时刻改", ek4))
    else:
        ctl("C4 对照生成时刻改", fs4, ["①", "②"])

    for t in ("c2", "c3", "c4"):
        shutil.rmtree(os.path.join(OUTD, "_page_probe_" + t), ignore_errors=True)

    _, ek5 = probe_at(ROOT, "demo/_no_such_page.html")
    ok5 = bool(ek5)
    log("  对照 %-20s → %s（%s）" % ("C5 页面不存在", "✔(rc=4 路)" if ok5 else "✘居然打开了",
                                    ek5 or "量到了"))
    if not ok5:
        bad.append("对照 C5 页面不存在时没走「没量到」那条路")

    log("-" * 78)
    log("J-10.9-04 总判 : %s" % ("PASS" if not bad else "FAIL（%d 条）" % len(bad)))
    for x in bad:
        log("  ✗ " + x)

    readings = dict(head)
    readings["n_violations"] = len(bad)
    readings["rc4 路"] = "页面取不到 / 浏览器没装 / 20 s 内没画出来 / json 读不成"
    return finish(0 if not bad else 1, out, readings)


if __name__ == "__main__":
    sys.exit(main())
