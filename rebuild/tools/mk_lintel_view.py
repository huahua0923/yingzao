# -*- coding: utf-8 -*-
r"""门头墙的**看得见**的量具：逐层把「墙带 / 细料 / 门扇 / 已建门头板 / 漏掉的扇」画成 PNG。

★★ 为什么有这个文件（2026-10-16，用户明令）：
    「你的量具很麻烦吗？我也看不到，你能不能修改量具」
  此前所有读数只打到终端、图只写进 %TEMP%（`cdut_see_win.py`）—— 用户看不见。
  现在图与读数都落到**服务中的** `demo/lintel_check/`，并生成 `demo/lintel_check.html`。

★ 它量的就是**交付的那个函数**：调 `build3d.lintel_module`（链上同一个入口），
  不是另写一份算法（铁律 187/192：量具与交付件必须同作用域、同一次读数）。

颜色（深底）：
  墙带 = 灰 ｜ 细料 thin_open(W,清边半径) 削掉的那部分 = 品红 ｜ 门扇 = 红
  已建门头板 = 橙 ｜ 漏掉的门 = 青圈

★ 顺带做一次 A/B（这一趟真正要回答的问题）：
  `洞口宽_mm` 的中位数，在**原始墙带**和**削掉细料后的墙带**上分别是多少。
  若「削细料」后中位数从 1450 变大 ⇒ 中位 1450 是**画在洞口里的细线**（门弧/门槛线）切的，
  不是洞口真的只有 1450 宽。

用法： python rebuild/tools/mk_lintel_view.py [层 ...]      默认 1层 3层 8层
输出： demo/lintel_check/<层>.png  +  demo/lintel_check.html
"""
import os
import sys
import json
import html

ROOT = r"D:\项目\cdut3d"
sys.path.insert(0, os.path.join(ROOT, "rebuild", "tools"))
sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

import numpy as np                                       # noqa: E402
import cv2                                              # noqa: E402
from shapely.ops import unary_union                     # noqa: E402
from shapely.geometry import box                        # noqa: E402

import build3d as B3                                    # noqa: E402
import redraw as RD                                     # noqa: E402
import parts_lib as PL                                  # noqa: E402

OUTDIR = os.path.join(ROOT, "demo", "lintel_check")
CROPDIR = os.path.join(OUTDIR, "miss")      # 漏掉的每一扇的放大格（点整层图上的青圈跳到这里）
PAGE = os.path.join(ROOT, "demo", "lintel_check.html")
PJ = os.path.join(ROOT, "rebuild", "构件库", "参数.json")

RES = 50.0              # mm / 像素（整层一张图；太大会自动放粗）
MAXPX = 24_000_000      # 单图像素上限
CROP_RES = 10.0         # mm / 像素（放大格：门扇 37.5 厚 = 3.75 px，这个分辨率才看得见）
CROP_HALF = 3000.0      # 放大格看 6 m × 6 m
BG = (28, 28, 28)
C_WALL, C_THIN, C_LEAF, C_PLATE, C_MISS = \
    (95, 95, 95), (255, 0, 255), (0, 0, 255), (0, 165, 255), (255, 255, 0)

_X0 = _Y1 = 0.0


def _pv(key, dflt):
    """参数.json 里的值（只读）。读不到就**说出来**再退回默认（铁律 199：不静默）。"""
    try:
        with open(PJ, "r", encoding="utf-8") as f:
            d = json.load(f)
        return float(d["构件"]["门"][key]["值"])
    except Exception as e:
        print("!! 参数读不到 %s（%s）⇒ 用默认 %.0f" % (key, e, dflt))
        return float(dflt)


def _to_px(x, y):
    return int(round((x - _X0) / RES)), int(round((_Y1 - y) / RES))


def _polys(x):
    if x is None:
        return []
    if isinstance(x, (list, tuple)):
        return [g for e in x for g in PL.polys_of(e)]
    return PL.polys_of(x)


def _draw(im, polys, color, holes_to_bg=False, bg=BG):
    """填多边形。★ 墙带**带内环**（房间就是它的内环）——只填外环会把整间房涂成墙，
    所以外环填 color、内环回填底色（本机在 G6/页面上吃过这个亏）。"""
    n = 0
    for g in polys:
        if g is None or g.geom_type != "Polygon":
            continue
        ext = np.array([_to_px(x, y) for x, y in g.exterior.coords], np.int32)
        cv2.fillPoly(im, [ext], color, lineType=cv2.LINE_8)
        if holes_to_bg:
            for r in g.interiors:
                ir = np.array([_to_px(x, y) for x, y in r.coords], np.int32)
                cv2.fillPoly(im, [ir], bg, lineType=cv2.LINE_8)
        n += 1
    return n


def _tag(name):
    # ★ 「地下1层」只取数字会退化成「1F」，与「1层」**撞名**（放大格文件名/热区名会同名覆盖）——
    #   所以地下单独加前缀 B。
    return ("B" if "地下" in name else "") + "".join(ch for ch in name if ch.isdigit()) + "F"


def _img_write(path, im):
    """★ 不用 cv2.imwrite：非 ASCII 路径下它**静默失败**（本机实测）⇒ 走 imencode + 字节写。"""
    ok, buf = cv2.imencode(".png", im)
    if not ok:
        raise RuntimeError("png 编码失败: %s" % path)
    with open(path, "wb") as f:
        f.write(buf.tobytes())
    return len(buf)


def main(floors):
    clean = _pv("门头墙_清边半径", 100.0)
    h_of = {n: h for n, _z, h in B3.FLOORS}
    miss_keys = ("层", "门扇", "有门头", "漏了", "漏因", "量到洞口", "洞口宽_mm", "墙厚_mm",
                 "块", "面积合计_m2", "清边丢块", "收边没治好")

    src, union_all = {}, []
    for n in floors:
        v = RD.geometry(n)
        ws, dp = B3.wall_polys(v), B3.door_polys(v)
        src[n] = (v, ws, dp)
        union_all += list(ws) + list(dp)
    bb = unary_union(union_all).bounds
    pad = 4000.0
    global _X0, _Y1, RES
    while True:
        w = int((bb[2] - bb[0] + 2 * pad) / RES) + 1
        h = int((bb[3] - bb[1] + 2 * pad) / RES) + 1
        if w * h <= MAXPX or RES > 400.0:
            break
        RES *= 1.5
    _X0, _Y1 = bb[0] - pad, bb[3] + pad
    print("画布 %d×%d px ｜ 1 px = %.1f mm ｜ 细料判据 清边半径 %.0f mm" % (w, h, RES, clean))

    os.makedirs(OUTDIR, exist_ok=True)
    cards = []
    for n in floors:
        v, ws, dp = src[n]
        W = unary_union(ws)
        out = B3.lintel_module(v, h_of[n], dp, floor=n)            # ★ 链上同一个入口（只回板）
        diag = B3.LINTEL_AUDIT[-1]
        plates = [g for t in out for g in _polys(t[0]) if g.geom_type == "Polygon"]
        #   A/B 扫刀口半径：把「比 2r 薄」的料削掉再量一遍洞口宽。
        #   r 从链上的 4（SU 碎边闸）扫到 60（能削掉 37.5 的门弧/门槛线，240 的墙不动）——
        #   若 1450 在 r=60 后变大，切它的就是画在洞口里的**细线**（铁律 103：阈值要量不要拍）。
        keep = {r: unary_union([q for g in _polys(W) for q in PL.thin_open(g, r)])
                for r in (clean, 60.0)}      # thin_open 回的是**块列表** ⇒ 必须摊平
        thin = W.difference(keep[60.0])
        ab = []
        for r in (clean, 60.0):
            kw = _polys(keep[r])
            if not kw:
                ab.append((r, 0, -1.0, (W.area - keep[r].area) / 1e6))   # 没量到 ≠ 量到 0
                continue
            _e, dd = PL.lintel_module(kw, dp, h_of[n] * 1000.0)
            gw = dd.get("洞口宽_mm") or []
            ab.append((r, int(dd.get("量到洞口") or 0),
                       gw[1] if len(gw) == 3 else -1.0, (W.area - keep[r].area) / 1e6))

        im = np.full((h, w, 3), BG, np.uint8)
        _draw(im, _polys(W), C_WALL, holes_to_bg=True)
        _draw(im, _polys(thin), C_THIN)
        _draw(im, plates, C_PLATE)
        _draw(im, dp, C_LEAF)
        pb = [g.buffer(1.0, join_style=2) for g in plates]
        miss = [g for g in dp if not any(g.buffer(1.0, join_style=2).intersects(p) for p in pb)]
        hits = []                                   # 青圈在整层图上的像素位 ⇒ 给 <map> 做热区
        for i, g in enumerate(miss):
            c = g.representative_point()
            px, py = _to_px(c.x, c.y)
            cv2.circle(im, (px, py), 9, C_MISS, 2, lineType=cv2.LINE_8)
            cv2.putText(im, str(i + 1), (px + 11, py - 11),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, C_MISS, 2, lineType=cv2.LINE_8)
            hits.append((px, py))

        g1 = diag.get("洞口宽_mm") or []
        # ★ 门垛那把尺子的两个计数（治「补得太厚」的关键两支）：`门垛改薄` 生效了几扇、
        #   `两端量不到`（⇒ tk 原样留着、板就厚）几扇。判「残件落在哪一支」全靠这两个数。
        say = ("%s  leaves=%d lintel=%d miss=%d | gap_med %.0f | %s | thin(60) %.1f m2 | "
               "门垛改薄 %s / 两端量不到 %s / 中位定 %s / 洞口不含扇 %s(剔 %s)"
               % (_tag(n), len(dp), int(diag.get("有门头") or 0), int(diag.get("漏了") or 0),
                  g1[1] if len(g1) == 3 else -1,
                  " ".join("r%.0f:%s(%d扇,削%.1fm2)" % (r, ("%.0f" % m) if m >= 0 else "无", k, a)
                           for r, k, m, a in ab),
                  thin.area / 1e6,
                  diag.get("墙厚用门垛截面改薄的"),
                  diag.get("两端门垛都量不到的"),
                  diag.get("墙厚用中位截面定的"),
                  diag.get("洞口不含本扇的板"),
                  diag.get("其中过闸剔掉的")))
        for i, t in enumerate([
                "gray = wall band | magenta = thin(clean_r) | orange = built lintel | red = leaf",
                "cyan ring = MISSED leaf   |   %s" % say,
                "1 px = %.1f mm   [cdut3d lintel self-check]" % RES]):
            cv2.putText(im, t, (12, 28 + 26 * i), cv2.FONT_HERSHEY_SIMPLEX, 0.75,
                        (235, 235, 235), 2, lineType=cv2.LINE_8)
        path = os.path.join(OUTDIR, "%s.png" % n)
        nb = _img_write(path, im)
        print("  %s" % say)
        print("    ⇒ %s  %.0f KB ｜ 图上漏圈 %d（判据读到的漏 %s，不一致就得查）"
              % (path, nb / 1024.0, len(miss), diag.get("漏了")))
        # ★ 最厚的几扇**逐扇点名**（用户报「补得太厚」时要能直接去那个坐标看）：
        #   只印读数，不印判词 —— 是不是病由 `lintel_thickness.py --probe` 在**该坐标**上判。
        #   ★ 第二个读数 = **洞口含不含本扇**（`_off`，0 = 含）：不等于 0 就是「这块板建到
        #     别的墙上去了」的签名 —— 第三刀的候选就靠它点名（读数，不是判词）。
        for _f in (diag.get("最厚的门头") or [])[:4]:
            print("      ★ 厚 %7.1f mm ｜ 触墙点 (%.0f, %.0f) ｜ 量法 %s ｜ 洞口宽 %.0f ｜ 墙向 %.1f° ｜ %s"
                  % (_f[0], _f[1], _f[2], _f[3], _f[4],
                     (_f[6] if len(_f) > 6 else -1),
                     ("洞口**含**本扇" if (_f[5] if len(_f) > 5 else 0.0) <= 0.0
                      else "洞口**不含**本扇（沿墙差 %.0f mm）" % _f[5])))
            if len(_f) > 12:
                print("           扇质心沿墙 %.1f ｜ 洞口 %.1f~%.1f ｜ 扇框 %s ｜ 板框 %s ｜ 截面锚 C %s"
                      % (_f[10], _f[11], _f[12], _f[7], _f[8], _f[9]))

        # ── 放大格：漏掉的每一扇单独画一张，供用户点开自己判「真门还是飘着的」──────────
        crops, blank = [], []
        for i, g in enumerate(miss):
            c = g.representative_point()
            dP = min((g.distance(p) for p in plates), default=-1.0)
            dW = g.distance(W)
            win = box(c.x - CROP_HALF, c.y - CROP_HALF, c.x + CROP_HALF, c.y + CROP_HALF)
            npx = int(2 * CROP_HALF / CROP_RES)
            cim = np.full((npx, npx, 3), BG, np.uint8)
            cap = "#%d 离最近板 %.0f mm ｜ 离墙 %.0f mm ｜ 扇面积 %.0f mm² ｜ 中心 (%.0f, %.0f)" % (
                i + 1, dP, dW, g.area, c.x, c.y)
            try:
                # 复用整层那条 _draw：临时把画布原点/比例换成这一格，画完在 finally 里还原
                # （铁律 192：同一把尺子/同一次读数，不另写一份绘制）
                gX0, gY1, gr = _X0, _Y1, RES
                _X0, _Y1, RES = win.bounds[0], win.bounds[3], CROP_RES
                try:
                    _draw(cim, _polys(W.intersection(win)), C_WALL, holes_to_bg=True)
                    _draw(cim, [q for p in plates if p.intersects(win)
                                for q in _polys(p.intersection(win))], C_PLATE)
                    _draw(cim, [q for p in dp if p.intersects(win)
                                for q in _polys(p.intersection(win))], C_LEAF)
                    _draw(cim, _polys(g.intersection(win)), C_MISS)      # 本扇高亮
                finally:
                    _X0, _Y1, RES = gX0, gY1, gr
                drew = int((cim != BG).any(axis=2).sum())
            except Exception as e:                   # 崩了 ⇒ 说「崩了」，不当「画了空的」（铁律 199）
                drew = -1
                cv2.putText(cim, "crop 崩了: %s" % type(e).__name__, (10, 32),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 255), 2, lineType=cv2.LINE_8)
            if drew <= 0:
                blank.append(i + 1)
            for k, t in enumerate(
                    ["#%d  离最近板 %.0f mm ｜ 离墙 %.0f mm" % (i + 1, dP, dW),
                     "扇面积 %.0f mm² ｜ 中心 (%.0f, %.0f)" % (g.area, c.x, c.y),
                     "1px=%.0fmm ｜ 灰=墙 品红=细料 橙=已建板 红=门扇 青=这一扇" % CROP_RES]):
                cv2.putText(cim, t, (10, 28 + 26 * k), cv2.FONT_HERSHEY_SIMPLEX, 0.62,
                            (235, 235, 235), 1, lineType=cv2.LINE_8)
            os.makedirs(CROPDIR, exist_ok=True)
            fn = "%s_%02d.png" % (_tag(n), i + 1)
            _img_write(os.path.join(CROPDIR, fn), cim)
            crops.append((i + 1, fn, cap))
        if crops:
            print("    放大格 %d 张 ⇒ %s ｜ 画上去像素=0 的 %d 张%s"
                  % (len(crops), CROPDIR, len(blank),
                     ("★ 空的是 %s，得查" % blank) if blank else "（每格都画上了东西）"))
        cards.append((n, path, nb, diag, ab, say, len(miss), len(dp), crops, hits))

    rows = []
    for n, path, nb, diag, ab, say, nm, nl, crops, hits in cards:
        tg = _tag(n)
        kv = "".join("<tr><td>%s</td><td><b>%s</b></td></tr>"
                     % (html.escape(str(k)), html.escape(json.dumps(diag.get(k), ensure_ascii=False)))
                     for k in miss_keys)
        kv += "".join("<tr><td>A/B 刀口 r=%.0f mm（削掉 %.2f m² 细料）量到洞口 / 宽中位</td>"
                      "<td>%d 扇 / %s</td></tr>"
                      % (r, a, k, ("%.0f mm" % m) if m >= 0 else "没量到")
                      for r, k, m, a in ab)
        # 整层图 + 热区（点青圈跳到那一扇的放大格）；图名含中文 ⇒ 沿用本页既有的裸 href 写法
        if hits:
            areas = "".join("<area shape=\"circle\" coords=\"%d,%d,16\" href=\"#m_%s_%02d\" "
                            "title=\"放大 #%d\">" % (px, py, tg, i + 1, i + 1)
                            for i, (px, py) in enumerate(hits))
            ov = ("<img src=\"lintel_check/%s.png\" usemap=\"#ov%s\" alt=\"%s\">"
                  "<map name=\"ov%s\">%s</map>"
                  % (n, tg, html.escape(n), tg, areas))
        else:
            ov = "<img src=\"lintel_check/%s.png\" alt=\"%s\">" % (n, html.escape(n))
        figs = "".join(
            "<figure id=\"m_%s_%02d\"><img src=\"lintel_check/miss/%s\" alt=\"%s #%d\">"
            "<figcaption>%s</figcaption></figure>"
            % (tg, idx, fn, html.escape(n), idx, html.escape(cap))
            for idx, fn, cap in crops)      # ★ crops 里存的已是 1 基序号；再 +1 会整体错位一格
        rows.append(
            "<section><h2>%s</h2><p class=say>%s</p>%s"
            "<p class=note>图上青圈 %d 个（判据读到漏 %s 扇）%s</p>"
            "<div class=misses>%s</div><table>%s</table></section>"
            % (html.escape(n), html.escape(say), ov, nm, diag.get("漏了"),
               "　<b>点青圈</b>或下面的小图 ＝ 跳到那一扇的放大格；青=这一扇、橙=已建板、"
               "灰=墙、红=门扇。" if crops else "（这层没漏，无需放大）",
               figs, kv))
    with open(PAGE, "w", encoding="utf-8") as f:
        f.write("<!doctype html><meta charset=utf-8><title>cdut3d 门头墙自检</title>"
                "<style>body{background:#141414;color:#ddd;font:14px/1.6 system-ui,'Microsoft YaHei'}"
                "img{max-width:100%%;border:1px solid #444;margin:8px 0}"
                "table{border-collapse:collapse;font-size:13px}"
                "td{border:1px solid #333;padding:2px 8px}"
                "h2{color:#ffb84d;margin:22px 0 4px}.say{color:#8fd}.note{color:#999}"
                ".misses{display:grid;gap:10px;grid-template-columns:repeat(auto-fill,minmax(340px,1fr));margin:10px 0}"
                ".misses figure{margin:0}figure img{max-width:100%%;border:1px solid #444}"
                "figcaption{color:#999;font-size:12px;padding-top:2px}"
                "figure:target{outline:2px solid #0ff;outline-offset:3px}</style>"
                "<h1>门头墙自检（看得见的量具）</h1>"
                "<p>灰=墙带 · <span style='color:#f0f'>品红=细料(比 2×清边半径 薄)</span> · "
                "<span style='color:#fa0'>橙=已建门头板</span> · "
                "<span style='color:#f55'>红=门扇</span> · "
                "<span style='color:#0ff'>青圈=没建上板的门</span>"
                "　判据：<code>gates/J-10.9-01_门头墙.py</code>　生成器："
                "<code>rebuild/tools/mk_lintel_view.py</code></p>%s</body>"
                % "".join(rows))
    print("页面 ⇒ %s" % PAGE)


if __name__ == "__main__":
    main(sys.argv[1:] or ["1层", "3层", "8层"])
