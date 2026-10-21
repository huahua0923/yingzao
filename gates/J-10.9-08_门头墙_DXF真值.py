# -*- coding: utf-8 -*-
r"""J-10.9-08 · 门头墙的**外部真值**尺子：拿原始图纸里的真门，去量交出来的板。

★ 为什么必须有这条（2026-10-16 用户口令「**你做好后和原始的 dxf 对比，就知道哪里错了**」）：
  `J-10.9-01` 量的是**我自己的账目**（几何 vs 对照.json）—— 它 PASS 而件照样错，
  这一轮就发生了：板立成 1 m 厚的菱形，J-10.9-01 全绿（它第 49 行的注释自己写着
  「要判因果得回 `01_cad/raw/*.dxf` 逐条看墙线」，且明说本闸不核）。用户报
  「有的门上的墙补得太厚了」之后才补出这条**唯一外部真值**：`rebuild/01_cad/raw/<层>.dxf`
  里的 `$DorLib2D$` INSERT（一樘门一个块）。**真值不来自我的手**，所以它不会跟着我的判断一起漂。

判据（都是**棘轮**：只许变好，不许变坏；比的是同一把尺子前后两趟的读数）
 ① 真值源不变：逐层 DXF 真门数必须**逐位等于**基线里记的数。
    —— 真值源一改（换了底图 / 换了取块口径），后面几条棘轮就全是**拿新真值比旧件**，
       读数会变得没有意义 ⇒ 这一条先红，把话说明白。
 ② 真门有板：逐层「被板压住的真门」数 ≥ 基线同层值，且全楼合计 ≥ 基线合计。
 ③ 空板数：全楼「不压任何一樘真门」的板数 ≤ 基线（板必须补在某樘真门上）。
 ④ 板厚棘轮：全楼**最大板厚** ≤ 基线；板厚 > `刀口_板厚` 的块数 ≤ 基线。
    —— `刀口_板厚` 是**人给的一把刀**，不是真值（见下「量具盲区」），只用来做棘轮。
 ⑤ 基线不在 ⇒ SKIP(rc=4)（没量到基线 ≠ 坏了）。`--record` 现取一次读数落成基线。

量具
 真值侧：`redraw.blocks_grouped_wcs(raw/<层>.dxf, prefix="$DorLib2D$")` —— 一樘门一条记录，
     bbox = 该块**全部折线的点**的包围盒（与 `%TEMP%\cdut_dxf_probe.py` 同一口径）。
     为什么复用 `redraw` 而不是自己读块：门块大量带**负缩放**，块里 ARC/CIRCLE 的圆心是 **OCS**，
     自己算会飞到 x≈−100000（`redraw.blocks_grouped_wcs` 的注释里记着这条教训）——只有一份实现。
 件侧：`rebuild/06_su/contours/<层>.json` 的 **LINTEL** 环。
 厚度：`rebuild/tools/lintel_thickness.py` 的**内切半径**法（不是外接矩形短边，见该文件注释）。

量具盲区（★先声明，再判）
 · 「真门有板」的定义是**相交**（板 `buffer(1.0, join_style=2)` 碰真门的 bbox）。
   真门的 bbox 把**开着的门扇与开启弧**也算进去了 ⇒ 它比门洞大，
   一块立在门洞上的板自然与它相交。**分辨力只到「有没有」**，到不了「盖没盖全」。
 · **板厚这一格没有外部真值**：图纸里没有「门头板厚」这东西，只有墙厚。
   `刀口_板厚` 是我给的（本楼墙厚中位 300 + 2×缝合 30 + 栅格余量），
   **只当棘轮的刻度，不是判据**。真正的判据是用户的眼睛 + 这一格读数不许变大。
 · 只认 `rebuild/06_su/contours/`：`packs/` 里那一份与页面显示的数本闸不核。
 · 真值只说明「这樘门在图上存在」，不说明**洞口在哪面墙上** ——
   板立错方向但压在门洞上，本闸照样给「有板」。
 · 只量平面，不量 z。
 · 基线只存**数**与**件指纹**，不存真门几何 —— 存了就会有人拿它当第二份真值（铁律 174）。

正对照（每条必须**因该因**而红；`新增 N 条` 是相对 C1 的差集）
 C1 真件            —— 基线，必须 0 条
 C2 抹掉一层的板     —— ② 红
 C3 真值源多一樘门   —— ① 红（真值源变了，棘轮读数作废）
 C4 基线刀口调紧     —— ④ 红
 C5 contours 不在    —— SKIP(rc=4)，**另起一个进程真跑**验 rc

三态：rc=0 PASS ／ rc=1 FAIL ／ rc=4 SKIP
用法：python gates/J-10.9-08_门头墙_DXF真值.py                 # 判（要基线）
      python gates/J-10.9-08_门头墙_DXF真值.py --record        # 现取一次读数落基线
      python gates/J-10.9-08_门头墙_DXF真值.py --contours <dir> --out <txt>
"""
import glob
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime

from shapely.geometry import Polygon

sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = r"D:\项目\cdut3d"
RAW = os.path.join(ROOT, "rebuild", "01_cad", "raw")
CONTOURS = os.path.join(ROOT, "rebuild", "06_su", "contours")
TOOLS = os.path.join(ROOT, "rebuild", "tools")
OUTD = os.path.join(HERE, "_out")
OUT = os.path.join(OUTD, "J-10.9-08.run.txt")
BASE = os.path.join(OUTD, "J-10.9-08.baseline.json")
sys.path.insert(0, TOOLS)
sys.path.insert(0, HERE)
import redraw as RD                                                      # noqa: E402
import lintel_thickness as LT                                            # noqa: E402
import _items as I                                                       # noqa: E402

# ★ 人给的刀口（**不是真值**，见 docstring「量具盲区」第 2 条）：
#   本楼墙厚中位 300 + 2×缝合 30 + 栅格余量 ⇒ 400。只当棘轮的刻度用。
刀口_板厚 = 400.0
TOL = 1.0                       # 浮点余量，不是物理容差

BLIND = [
    "「真门有板」= 板（外扩 1 mm）与真门 **bbox** 相交。bbox 把开着的门扇与开启弧也算进去，"
    "比门洞大 ⇒ 分辨力只到「有没有」，到不了「盖没盖全」",
    "**板厚没有外部真值**：图纸里没有「门头板厚」这件东西。刀口_板厚=400 是人给的刻度，"
    "只用于棘轮（不许变大），不是判据；判据是用户的眼睛",
    "只认 rebuild/06_su/contours/：packs/ 里那一份与页面显示的数本闸不核",
    "真值只说「这樘门在图上存在」，不说洞口在哪面墙上 —— 板立错方向但压在门洞上照样算「有板」",
    "只量平面，不量 z",
    "基线只存数与件指纹，不存真门几何（存了就是第二份真值）",
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
    """★ 产物 json 与 run.txt 同编号、同目录（C5 子进程换 --out 时不污染正牌路径）。"""
    if out_txt == OUT:
        return os.path.join(OUTD, "J-10.9-08.json")
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


# ---------------- 量具 ----------------
def 真门(raw_dir=None):
    """{层: {"doors": [(x0,y0,x1,y1,name), …], "退化块": n}} —— 图纸里的 `$DorLib2D$`，一樘一条。"""
    raw_dir = raw_dir or RAW
    out = {}
    for p in sorted(glob.glob(os.path.join(raw_dir, "*.dxf"))):
        lay = os.path.basename(p)[:-4]
        gs, bad = [], 0
        for g in RD.blocks_grouped_wcs(p, prefix=RD.DOOR_PREFIX):
            xs = [q[0] for _pts, _c in g["polys"] for q in _pts]
            ys = [q[1] for _pts, _c in g["polys"] for q in _pts]
            if not xs:
                bad += 1
                continue
            gs.append((min(xs), min(ys), max(xs), max(ys), g["name"]))
        if gs or bad:
            out[lay] = {"doors": gs, "退化块": bad}
    return out


def 板(contours_dir=None):
    """{层: [Polygon, …]} —— 交付件里的 LINTEL 环。"""
    contours_dir = contours_dir or CONTOURS
    out = {}
    for p in sorted(glob.glob(os.path.join(contours_dir, "*层.json"))):
        lay = os.path.basename(p)[:-5]
        with open(p, "r", encoding="utf-8") as fh:
            d = json.load(fh)
        gs = []
        for r in d.get("polys", []):
            if r.get("layer") != "LINTEL":
                continue
            try:
                g = Polygon(LT.ring_pts(r["ring"]))
            except Exception:
                continue
            if not g.is_valid:
                g = g.buffer(0)
            if g.geom_type == "Polygon" and not g.is_empty and g.area > 0:
                gs.append(g)
        out[lay] = gs
    return out


def _bboxes(ds):
    return [Polygon([(d[0], d[1]), (d[2], d[1]), (d[2], d[3]), (d[0], d[3])]) for d in ds]


def 量(door, pl, 刀口):
    """两侧读数。层级只用于 ① / ②，③④ 走全楼一把尺子。"""
    per_door = {lay: len(door[lay]["doors"]) for lay in door}
    per_hit, per_plate = {}, {}
    for lay in sorted(pl):
        per_plate[lay] = len(pl[lay])
        bs = _bboxes(door.get(lay, {"doors": []})["doors"])
        per_hit[lay] = sum(1 for b in bs
                           if any(g.buffer(1.0, join_style=2).intersects(b) for g in pl[lay]))
    thicks = []
    for lay in sorted(pl):
        for g in pl[lay]:
            thicks.append(LT.thickness(list(g.exterior.coords)))
    # 空板：不压**本层**任何一樘真门 bbox
    bare = 0
    for lay in sorted(pl):
        bs = _bboxes(door.get(lay, {"doors": []})["doors"])
        for g in pl[lay]:
            gb = g.buffer(1.0, join_style=2)
            if not any(gb.intersects(b) for b in bs):
                bare += 1
    return {
        "真门_逐层": per_door,
        "真门有板_逐层": per_hit,
        "真门": sum(per_door.values()),
        "真门有板": sum(per_hit.values()),
        "退化块_合计": sum(door[lay]["退化块"] for lay in door),
        "板_逐层": per_plate,
        "板": sum(per_plate.values()),
        "空板": bare,
        "板厚最大": round(max(thicks), 1) if thicks else 0.0,
        "板厚_超刀口块数": sum(1 for t in thicks if t > 刀口),
        "刀口_板厚": 刀口,
    }


def 指纹(paths):
    """读数所对的**件指纹**（程序算，不手打）。"""
    h = hashlib.sha256()
    for p in sorted(paths):
        with open(p, "rb") as fh:
            h.update(os.path.basename(p).encode("utf-8"))
            h.update(fh.read())
    return h.hexdigest()


def judge(cur, base):
    """棘轮判据。cur / base 同形（见 `量`）。返回违反条目。"""
    fs = []
    # ① 真值源不变（逐层比，按身份不按合计 —— 铁律 194）
    cd, bd = cur["真门_逐层"], base["真门_逐层"]
    for lay in sorted(set(cd) | set(bd)):
        if lay not in bd:
            fs.append("① %s 真值里多出整整一层（基线里没有）—— 真值源换了" % lay)
        elif lay not in cd:
            fs.append("① %s 在真值里没了（基线里 %d 樘）—— 真值源换了" % (lay, bd[lay]))
        elif cd[lay] != bd[lay]:
            fs.append("① %s 真门 %d ≠ 基线 %d —— 真值源变了，下面几条棘轮读数一律作废"
                      % (lay, cd[lay], bd[lay]))
    if cd == bd and cur["真门"] != base["真门"]:
        fs.append("① 真门合计 %d ≠ 基线 %d" % (cur["真门"], base["真门"]))
    # ② 真门有板（棘轮，逐层 + 合计）
    ch, bh = cur["真门有板_逐层"], base["真门有板_逐层"]
    for lay in sorted(set(ch) | set(bh)):
        if ch.get(lay, -1) < bh.get(lay, 0):
            fs.append("② %s 真门有板 %d < 基线 %d（这一层变差了）"
                      % (lay, ch.get(lay, -1), bh.get(lay, 0)))
    if cur["真门有板"] < base["真门有板"]:
        fs.append("② 真门有板合计 %d < 基线 %d" % (cur["真门有板"], base["真门有板"]))
    # ③ 空板
    if cur["空板"] > base["空板"]:
        fs.append("③ 空板 %d > 基线 %d（多出 %d 块板没补在任何一樘真门上）"
                  % (cur["空板"], base["空板"], cur["空板"] - base["空板"]))
    # ④ 板厚棘轮
    if cur["板厚最大"] > base["板厚最大"] + TOL:
        fs.append("④ 板厚最大 %.1f > 基线 %.1f（补得更厚了）"
                  % (cur["板厚最大"], base["板厚最大"]))
    if cur["板厚_超刀口块数"] > base["板厚_超刀口块数"]:
        fs.append("④ 板厚 > %.0f 的 %d 块 > 基线 %d 块"
                  % (cur["刀口_板厚"], cur["板厚_超刀口块数"], base["板厚_超刀口块数"]))
    return fs


# ---------------- 判据清单（一条一个函数） ----------------
_GATE = "J-10.9-08"
_CTX = {}


def _need(*keys):
    for k in keys:
        if k not in _CTX:
            raise I.没量到("前置读数缺：%s" % k)


def _hit(rule):
    """`judge()` 里以该规则号开头的违反条（同一份读数，不另算一遍 —— 铁律 018）。"""
    return [x for x in _CTX["fails"] if x.startswith(rule)]


def c1_真值源():
    _need("cur", "fails")
    cur, fs = _CTX["cur"], _hit("①")
    base = _CTX["base"]
    _raw = os.path.relpath(RAW, ROOT).replace("\\", "/")
    _base = os.path.relpath(BASE, ROOT).replace("\\", "/")
    return I.结果(not fs, "%d 层 / %d 樘" % (len(cur["真门_逐层"]), cur["真门"]),
                  "；".join(fs) if fs else "逐层逐位等于基线",
                  参数=[
                      I.参数("真门_逐层[%s]" % lay,
                             base["真门_逐层"].get(lay, "—（基线无此层）"),
                             "%s/%s.dxf::$DorLib2D$ ← %s::真门_逐层" % (_raw, lay, _base),
                             cur["真门_逐层"].get(lay, "—（真值里无此层）"),
                             "真值源变了 ⇒ 先查 %s/%s.dxf 是否换图/取块口径变了，"
                             "再重跑 J-10.9-08（必要时 --record 重记基线）" % (_raw, lay))
                      for lay in sorted(set(cur["真门_逐层"]) | set(base["真门_逐层"]))
                  ] + [
                      I.参数("真门合计", base["真门"],
                             "%s/*.dxf::$DorLib2D$ 全楼合计 ← %s::真门" % (_raw, _base),
                             cur["真门"],
                             "合计变了 ⇒ 先按上面逐层定位哪层真值变，"
                             "再查 %s 是否换图，然后重跑 J-10.9-08" % _raw)
                  ])


def c2_有板():
    _need("cur", "fails")
    cur, fs = _CTX["cur"], _hit("②")
    base = _CTX["base"]
    _raw = os.path.relpath(RAW, ROOT).replace("\\", "/")
    _con = os.path.relpath(CONTOURS, ROOT).replace("\\", "/")
    _base = os.path.relpath(BASE, ROOT).replace("\\", "/")
    return I.结果(not fs, "%d/%d" % (cur["真门有板"], cur["真门"]),
                  "；".join(fs) if fs else "≥ 基线 %d" % base["真门有板"],
                  参数=[
                      I.参数("真门有板_逐层[%s]" % lay,
                             base["真门有板_逐层"].get(lay, "—（基线无此层）"),
                             "%s/%s.json::polys[layer=LINTEL] ∩ "
                             "%s/%s.dxf::$DorLib2D$ ← %s::真门有板_逐层"
                             % (_con, lay, _raw, lay, _base),
                             cur["真门有板_逐层"].get(lay, "—（件里无此层）"),
                             "这层有真门没被板压住 ⇒ 先查 rebuild/tools/build3d.py "
                             "该层门头补板的取洞，重跑 build3d.py 与 export_contours.py，"
                             "再重跑 J-10.8-01 与 J-10.9-08")
                      for lay in sorted(set(cur["真门有板_逐层"]) | set(base["真门有板_逐层"]))
                  ] + [
                      I.参数("真门有板合计", base["真门有板"],
                             "全楼：%s/*.json::polys[layer=LINTEL] ∩ "
                             "%s/*.dxf::$DorLib2D$ ← %s::真门有板" % (_con, _raw, _base),
                             cur["真门有板"],
                             "合计变少 ⇒ 按上面逐层定位，先查 rebuild/tools/build3d.py "
                             "的门头补板，重跑 build3d.py 与 export_contours.py，"
                             "再重跑 J-10.8-01 与 J-10.9-08")
                  ])


def c3_空板():
    _need("cur", "fails")
    cur, fs = _CTX["cur"], _hit("③")
    base = _CTX["base"]
    _raw = os.path.relpath(RAW, ROOT).replace("\\", "/")
    _con = os.path.relpath(CONTOURS, ROOT).replace("\\", "/")
    _base = os.path.relpath(BASE, ROOT).replace("\\", "/")
    return I.结果(not fs, "%d 块" % cur["空板"],
                  "；".join(fs) if fs else "≤ 基线 %d" % base["空板"],
                  参数=[
                      I.参数("空板", base["空板"],
                             "%s/*.json::polys[layer=LINTEL] 中不压任何 "
                             "%s/*.dxf::$DorLib2D$ 真门 bbox 的板数 ← %s::空板"
                             % (_con, _raw, _base),
                             cur["空板"],
                             "多出的板没补在任何真门上 ⇒ 查 rebuild/tools/build3d.py "
                             "立板取洞/取墙，重跑 build3d.py 与 export_contours.py，"
                             "再重跑 J-10.8-01 与 J-10.9-08")
                  ])


def c4_板厚():
    _need("cur", "fails")
    cur, fs = _CTX["cur"], _hit("④")
    base = _CTX["base"]
    _con = os.path.relpath(CONTOURS, ROOT).replace("\\", "/")
    _base = os.path.relpath(BASE, ROOT).replace("\\", "/")
    _src = ("%s/*.json::polys[layer=LINTEL] 经 "
            "rebuild/tools/lintel_thickness.py::thickness（内切半径）" % _con)
    return I.结果(not fs,
                  "最大 %.0f / 超刀口 %d 块"
                  % (cur["板厚最大"], cur["板厚_超刀口块数"]),
                  "；".join(fs) if fs else
                  "≤ 基线 %.0f / %d 块" % (base["板厚最大"],
                                           base["板厚_超刀口块数"]),
                  参数=[
                      I.参数("板厚最大",
                             "%.1f（基线 %.1f + TOL %.1f）"
                             % (base["板厚最大"] + TOL, base["板厚最大"], TOL),
                             _src + " ← %s::板厚最大" % _base,
                             "%.1f" % cur["板厚最大"],
                             "板补厚了 ⇒ 查 rebuild/tools/build3d.py 门头补板的"
                             "厚度取法（洞口沿墙跨）与 _punch_across，"
                             "重跑 build3d.py 与 export_contours.py，"
                             "再重跑 J-10.8-01 与 J-10.9-08"),
                      I.参数("板厚_超刀口块数",
                             "≤ 基线 %d 块（块的判据：板厚 > 刀口_板厚=%.0f，"
                             "刀口是人给的刻度不是真值）"
                             % (base["板厚_超刀口块数"], 刀口_板厚),
                             _src + " ← %s::板厚_超刀口块数" % _base,
                             cur["板厚_超刀口块数"],
                             "超刀口的块数变多 ⇒ 同「板厚最大」查 build3d.py "
                             "的补板厚度，重跑 build3d.py 与 export_contours.py，"
                             "再重跑 J-10.8-01 与 J-10.9-08；"
                             "★ 刀口只当棘轮刻度，别拿它当真值")
                  ])


def _ctl(name, fs_, want):
    """正对照：相对**真基线**那一趟的差集，必须不多不少红在 `want` 这几条上。"""
    new = [x for x in fs_ if x not in _CTX["fails"]]
    got = sorted({x[0] for x in new})
    ok = bool(new) and got == sorted(want)
    实测 = "新增 %d 条" % len(new)
    _raw = os.path.relpath(RAW, ROOT).replace("\\", "/")
    _con = os.path.relpath(CONTOURS, ROOT).replace("\\", "/")
    参数 = []
    if want == ["②"]:
        _w = sorted(_CTX["pl"])[0] if _CTX["pl"] else "—"
        参数 = [
            I.参数("抹掉的是",
                   "%s 的 真门有板_逐层 置 0（原 %d）"
                   % (_w, _CTX["cur"]["真门有板_逐层"].get(_w, 0)),
                   "%s/%s.json::polys[layer=LINTEL]（C2 对照人为抹掉该层全部板）"
                   % (_con, _w),
                   实测,
                   "对照没红 ⇒ 判据没分辨力，先查对照输入是否退化"
                   "（该层原本就没有板 / 基线已退化）"),
            I.参数("期望红在哪条规则", "只红 ②（该层真门有板跌破基线）",
                   "gates/J-10.9-08_门头墙_DXF真值.py::judge() ② 棘轮",
                   "红在 %s" % ("".join(got) or "—"),
                   "对照没红 ⇒ 判据没分辨力，先查对照输入是否退化"),
        ]
    elif want == ["①"]:
        _w = (sorted(_CTX["cur"]["真门_逐层"])[0]
              if _CTX["cur"]["真门_逐层"] else "—")
        参数 = [
            I.参数("抹掉的是",
                   "真值 %s +1 樘门（原 %d）"
                   % (_w, _CTX["cur"]["真门_逐层"].get(_w, 0)),
                   "%s/%s.dxf::$DorLib2D$（C3 对照人为多算一樘）" % (_raw, _w),
                   实测,
                   "对照没红 ⇒ 判据没分辨力，先查对照输入是否退化"
                   "（该层真值原本是否读空）"),
            I.参数("期望红在哪条规则", "只红 ①（真值源逐层逐位变了，棘轮读数作废）",
                   "gates/J-10.9-08_门头墙_DXF真值.py::judge() ① 真值源不变",
                   "红在 %s" % ("".join(got) or "—"),
                   "对照没红 ⇒ 判据没分辨力，先查对照输入是否退化"),
        ]
    elif want == ["④"]:
        _n4 = int(_CTX["cur"]["板厚_超刀口块数"])
        参数 = [
            I.参数("抹掉的是",
                   "基线 板厚_超刀口块数 := %d（件实测 %d − 1）" % (_n4 - 1, _n4),
                   "%s/*.json::polys[layer=LINTEL] 经 "
                   "rebuild/tools/lintel_thickness.py::thickness"
                   "（C4 对照把基线调紧）" % _con,
                   实测,
                   "对照没红 ⇒ 判据没分辨力，先查对照输入是否退化"
                   "（件里已无超刀口的板）"),
            I.参数("期望红在哪条规则", "只红 ④（超刀口块数超过调紧后的基线）",
                   "gates/J-10.9-08_门头墙_DXF真值.py::judge() ④ 板厚棘轮",
                   "红在 %s" % ("".join(got) or "—"),
                   "对照没红 ⇒ 判据没分辨力，先查对照输入是否退化"),
        ]
    return I.结果(ok, 实测,
                  "%s；要 %s，实得 %s" % (name, "".join(want), "".join(got) or "—"),
                  参数=参数)


def c5_抹一层板():
    _need("cur", "base", "fails", "pl")
    which = sorted(_CTX["pl"])[0] if _CTX["pl"] else None
    if not which:
        raise I.没量到("件里一块板都没有，造不出「抹掉一层」")
    c2 = json.loads(json.dumps(_CTX["cur"]))
    c2["真门有板_逐层"][which] = 0
    c2["真门有板"] = sum(c2["真门有板_逐层"].values())
    return _ctl("C2 抹掉%s的板" % which, judge(c2, _CTX["base"]), ["②"])


def c6_真值多一樘():
    _need("cur", "base", "fails")
    c3 = json.loads(json.dumps(_CTX["cur"]))
    if not c3["真门_逐层"]:
        raise I.没量到("真值侧一层都没有，造不出「多一樘」")
    _l0 = sorted(c3["真门_逐层"])[0]
    c3["真门_逐层"][_l0] += 1
    return _ctl("C3 真值+1樘门", judge(c3, _CTX["base"]), ["①"])


def c7_刀口调紧():
    """★ 期望值必须**从件的实测数推**（铁律 103/187）：原写法把基线设成「基线自己少一块」，
    它只在**件 ≈ 基线**时才红 —— 2026-10-16 剔掉 26 块厚板、件变薄之后这个伪证器
    **静默失效**（闸 rc=1，看着像在守、其实没守）。改成按**件**造：基线 = 件少一块
    ⇒ 只要件里还有超刀口的板，④ 必然红。件里一块都没有时**造不出来**（0−1 与 0 相等），
    那时如实报「不成立」（铁律 199：把「没量到」与「崩了」分开），不当成过；
    ④ 的棘轮本身仍由 `c4_板厚` 对着**真基线**量。"""
    _need("cur", "base", "fails")
    _n4 = int(_CTX["cur"]["板厚_超刀口块数"])
    if _n4 < 1:
        return I.结果(True, "不成立",
                      "件里 0 块超刀口的板，造不出「比件少一块」的基线",
                      参数=[I.参数(
                          "件里超刀口的板",
                          "≥ 1 块才造得出「比件少一块」的基线（刀口_板厚=%.0f）"
                          % 刀口_板厚,
                          "%s/*.json::polys[layer=LINTEL] 经 "
                          "rebuild/tools/lintel_thickness.py::thickness"
                          % os.path.relpath(CONTOURS, ROOT).replace("\\", "/"),
                          "%d 块" % _n4,
                          "对照没红 ⇒ 判据没分辨力，先查对照输入是否退化"
                          "（刀口/板厚读数是否已无超限块）")])
    b4 = json.loads(json.dumps(_CTX["base"]))
    b4["板厚_超刀口块数"] = _n4 - 1
    return _ctl("C4 基线刀口调紧", judge(_CTX["cur"], b4), ["④"])


def c8_件不在():
    """C5 件不在 ⇒ SKIP：**另起一个进程真跑**（把「没做」与「坏了」分开）。"""
    _need("cur", "base", "fails")
    tmp = os.path.join(OUTD, "_dxftruth_skip_probe.txt")
    env = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    r = subprocess.run([sys.executable, os.path.abspath(__file__),
                        "--contours", os.path.join(CONTOURS, "_no_such_dir"),
                        "--out", tmp],
                       cwd=ROOT, capture_output=True, env=env)
    return I.结果(r.returncode == 4, "rc=%d" % r.returncode,
                  "C5 contours 不在；要 4，实得 %d" % r.returncode,
                  参数=[I.参数(
                      "contours 目录",
                      "不存在 ⇒ 闸必须 SKIP(rc=4)",
                      "%s/_no_such_dir（C5 对照故意给的假目录）"
                      % os.path.relpath(CONTOURS, ROOT).replace("\\", "/"),
                      "rc=%d" % r.returncode,
                      "对照没红 ⇒ 判据没分辨力，先查 --contours 指向不存在目录时"
                      "是否退化成 rc=0/1；重跑 J-10.9-08 与 J-10.8-00")])


CHECKS = [
    ("①", "真值源不变（逐层逐位）", c1_真值源),
    ("②", "真门有板 ≥ 基线", c2_有板),
    ("③", "空板不增", c3_空板),
    ("④", "板厚不超基线", c4_板厚),
    ("⑤", "对照：抹一层的板要红", c5_抹一层板),
    ("⑥", "对照：真值多一樘要红", c6_真值多一樘),
    ("⑦", "对照：基线刀口调紧要红", c7_刀口调紧),
    ("⑧", "对照：件不在要 SKIP", c8_件不在),
]


def main():
    global RAW, CONTOURS, BASE
    argv = sys.argv[1:]
    out = I.从argv(OUT, argv)
    if "--contours" in argv:
        CONTOURS = argv[argv.index("--contours") + 1]
    if "--raw" in argv:
        RAW = argv[argv.index("--raw") + 1]
    if "--base" in argv:
        BASE = argv[argv.index("--base") + 1]
    rec = "--record" in argv

    _LOG.clear()
    log("J-10.9-08 · 门头墙的**外部真值**尺子（原始 DXF 真门 vs 交付件）")
    log("  真值 %s ｜ 件 %s" % (RAW, CONTOURS))

    door = 真门()
    rfiles = sorted(glob.glob(os.path.join(RAW, "*.dxf")))
    cpaths = sorted(glob.glob(os.path.join(CONTOURS, "*层.json")))
    if not rfiles or not cpaths:
        log("★ 没量到：真值侧 %d 个 dxf、件侧 %d 个 json ⇒ SKIP(rc=4)" % (len(rfiles), len(cpaths)))
        return finish(4, out, {"n_raw": len(rfiles), "n_contours": len(cpaths)})
    pl = 板()
    cur = 量(door, pl, 刀口_板厚)
    fp = 指纹(cpaths)
    cur["件指纹"] = fp
    cur["时刻"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    log("  真门 %d 樘（%d 层）｜ 件 板 %d 块（%d 层）｜ 真门有板 %d ｜ 空板 %d ｜ 退化块 %d"
        % (cur["真门"], len(cur["真门_逐层"]), cur["板"], len(cur["板_逐层"]),
           cur["真门有板"], cur["空板"], cur["退化块_合计"]))
    log("  板厚：最大 %.1f ｜ >刀口(%.0f) 的 %d 块 ｜ ★ 刀口是人给的刻度，不是真值"
        % (cur["板厚最大"], cur["刀口_板厚"], cur["板厚_超刀口块数"]))
    log("  件指纹 %s" % fp[:16])

    if rec:
        os.makedirs(OUTD, exist_ok=True)
        with open(BASE, "w", encoding="utf-8") as fh:
            json.dump(cur, fh, ensure_ascii=False, indent=1)
        log("  ★ --record：基线写 %s（读数一律现取，没有手打数）" % BASE)
        return finish(0, out, dict(cur, 记基线=True, 基线=BASE))

    if not os.path.exists(BASE):
        log("★ 没量到基线 %s ⇒ SKIP(rc=4)（先 `--record` 记一次）" % BASE)
        return finish(4, out, dict(cur, 基线=BASE, 缺失=[os.path.basename(BASE)]))

    with open(BASE, "r", encoding="utf-8") as fh:
        base = json.load(fh)
    log("  基线 %s（%s，件指纹 %s）"
        % (os.path.basename(BASE), base.get("时刻", "?"), str(base.get("件指纹", "?"))[:16]))
    if base.get("件指纹") != fp:
        log("  ★ 件指纹与基线不同 ⇒ 比的是**不同一趟的件**（棘轮意义照旧，但读数变化可能来自别处）")

    base_fs = judge(cur, base)
    log("C1 真件 ⇒ 违反 %d 条%s" % (len(base_fs), " ⇒ 放行" if not base_fs else ""))
    for x in base_fs:
        log("    " + x)
    _CTX.clear()
    _CTX.update(cur=cur, base=base, pl=pl, fails=base_fs)

    rep = I.跑(_GATE, CHECKS, log=log, 宽=26)
    readings = dict(cur)
    readings["n_violations"] = sum(1 for r in rep.rows if r["status"] == "fail")
    readings["items"] = rep.items
    return finish(rep.rc, out, readings)


if __name__ == "__main__":
    sys.exit(main())
