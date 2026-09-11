# -*- coding: utf-8 -*-
"""源 DXF(与 DWG 同一套几何)忠实渲染 → 每层一张 CAD 样式 PNG。

画：LWPOLYLINE(含 bulge 圆弧内插)/LINE/ARC/CIRCLE/SPLINE/INSERT 折线 + TEXT/MTEXT(房间号)。
跳：DIMENSION/ACAD_TABLE/MULTILEADER 纯标注(易太乱)。
按 floor_of 切层 → to_local 到楼层局部坐标(与 floor JSON/building.html 同基准)。
白底黑线，实体线宽尊重 DXF lineweight(默认 ~0.8px)，文字按图纸实际字高换算可读大小。
输出 data/buildings/<name>/dxf_plan/floor{F}.png + 每栋 index.html + 总目录 _dxf_index.html。
用法: python -u _dxf_cad_render.py [<name> ...]   (不带参数=全部楼)
"""
import os, sys, json, glob, re
sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
sys.path[:0] = [r"D:\gym3d\backend\web", r"D:\gym3d\backend\vision",
                r"D:\gym3d\backend", r"D:\gym3d"]
import ezdxf
from ezdxf import path as ezpath
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "DengXian"]
plt.rcParams["axes.unicode_minus"] = False

BASE = r"D:\gym3d\data\buildings"
COL_DEFAULT = "#111111"
SKIP = {"DIMENSION", "ACAD_TABLE", "MULTILEADER", "HATCH", "ATTDEF"}


def _cn_from_dxf(p):
    """从 dxf 文件名抽中文楼名：'C025-第一教学楼.dxf' → '第一教学楼'。"""
    base = os.path.splitext(os.path.basename(p.dxf))[0]
    cn = re.sub(r"^[A-Za-z]+\d+[-_ ]*", "", base).strip(" -_")
    return cn or base


def _is_axis_layer(e):
    """轴线定位辅助线不画：图层名含「轴/AXIS」（资产管理图统一规约 = 图层「3轴线」）。"""
    try:
        lay = e.dxf.layer or ""
    except Exception:
        return False
    return ("轴" in lay) or ("AXIS" in lay.upper())


def _is_anno_layer(e):
    """资产管理图上的表格式文字标注整层隐藏：面积/房间号/使用单位/房间用途(MTEXT) +
    Defpoints(房间边界线)。这些是资产登记信息，不是建筑实体线，画出来糊成一片。
    墙体图层(如 c041「4.2墙体」里的门号 MTEXT)保留。"""
    try:
        lay = (e.dxf.layer or "").strip()
    except Exception:
        return False
    if "defpoints" in lay.lower():
        return True
    return any(k in lay for k in ("面积", "房间号", "使用单位", "房间用途",
                                  "房号", "编号", "汇总"))


def _aci_color(e):
    """近似 ACI→RGB；7(白/普通)画成深灰。"""
    try:
        if e.dxf.hasattr("true_color"):
            tc = e.dxf.true_color
            if tc not in (None, 0):
                return "#%06x" % (tc & 0xFFFFFF)
    except Exception:
        pass
    try:
        aci = e.dxf.color
        if aci is None:
            aci = 7
        if aci < 1:
            aci = 7
        c = {
            1: "#e00000", 2: "#e8c000", 3: "#00b050", 4: "#00c8d0",
            5: "#0040e0", 6: "#d040c0", 7: "#222222", 8: "#666666",
            9: "#b0b0b0",
        }.get(int(aci))
        if c:
            return c
    except Exception:
        pass
    return COL_DEFAULT


def _sampled_pts(e, p, F, dist=0.05):
    """实体→本层局部点列（含圆弧内插）。ezdxf 1.4: make_path().flattening()"""
    pts = []
    try:
        path = ezpath.make_path(e)
        pts = [(float(v.x), float(v.y)) for v in path.flattening(dist)]
    except Exception:
        try:
            if e.dxftype() == "LWPOLYLINE":
                pts = [(float(a), float(b)) for a, b in e.get_points("xy")]
            elif e.dxftype() == "LINE":
                pts = [(e.dxf.start.x, e.dxf.start.y), (e.dxf.end.x, e.dxf.end.y)]
        except Exception:
            return []
    if len(pts) < 2:
        return []
    if e.dxftype() == "LWPOLYLINE":
        try:
            if e.closed:
                pts.append(pts[0])
        except Exception:
            pass
    return pts


def _entity_floor(e):
    """实体锚点→floor。"""
    t = e.dxftype()
    try:
        if t == "LWPOLYLINE":
            ps = e.get_points("xy")
            if not ps:
                return None
        elif t == "LINE":
            ps = [(e.dxf.start.x, e.dxf.start.y), (e.dxf.end.x, e.dxf.end.y)]
        elif t in ("TEXT", "MTEXT"):
            ps = [(e.dxf.insert.x, e.dxf.insert.y)]
        elif t == "INSERT":
            ps = [(e.dxf.insert.x, e.dxf.insert.y)]
        elif t in ("ARC", "CIRCLE"):
            ps = [(e.dxf.center.x, e.dxf.center.y)]
        else:
            return None
    except Exception:
        return None
    cx = sum(x for x, y in ps) / len(ps)
    cy = sum(y for x, y in ps) / len(ps)
    return cx, cy


def _explode_insert(e):
    out = []
    try:
        for v in e.virtual_entities():
            out.append(v)
    except Exception:
        pass
    return out


def _in_box(x, y, box, m=6.0):
    x0, y0, x1, y1 = box
    return (x0 - m) <= x <= (x1 + m) and (y0 - m) <= y <= (y1 + m)


def collect_floor(doc, p, F, box=None):
    """收集 F 层主副本实体: polylines=[(pts,color,lw)], texts=[(x,y,text,h,rot,kind)]
    box=(x0,y0,x1,y1) = 该层 outline 包围盒(识别主副本范围)，剔掉并排/镜像多副本与杂项。"""
    polys, texts = [], []
    pool = []
    for e in doc.modelspace():
        if e.dxftype() in SKIP:
            continue
        if e.dxftype() == "INSERT":
            pool.extend(_explode_insert(e))
        else:
            pool.append(e)
    from recognizer.profile import to_local, floor_of
    # 图面单位→米 换算（源图纸多为 mm）
    try:
        uscale = to_local(p, 1.0, 0.0, F)[0] - to_local(p, 0.0, 0.0, F)[0]
    except Exception:
        uscale = 0.001
    x0, y0, x1, y1 = box
    bw = (x1 - x0) + 5.0      # 轮廓尺寸上限(+5m 容差)
    bh = (y1 - y0) + 5.0
    def _overlap(pl):
        xa = min(q[0] for q in pl); xb = max(q[0] for q in pl)
        ya = min(q[1] for q in pl); yb = max(q[1] for q in pl)
        if (xb - xa) > bw or (yb - ya) > bh:   # 大于轮廓太多 = 图框/跨副本框线
            return False
        return not (xb < x0 - 1.5 or xa > x1 + 1.5 or yb < y0 - 1.5 or ya > y1 + 1.5)
    for e in pool:
        t = e.dxftype()
        if t in SKIP or _is_axis_layer(e) or _is_anno_layer(e):
            continue
        xy = _entity_floor(e)
        if xy is None:
            continue
        try:
            f = int(round(floor_of(p, xy[0], xy[1])))
        except Exception:
            continue
        if f != F:
            continue
        col = _aci_color(e)
        lw = 0.8
        if t in ("LWPOLYLINE", "LINE", "ARC", "CIRCLE", "SPLINE", "ELLIPSE"):
            pts = _sampled_pts(e, p, F)
            if not pts:
                continue
            pts = [to_local(p, x, y, F) for x, y in pts]
            if len(pts) < 2:
                continue
            if box is not None and not _overlap(pts):
                continue
            polys.append((pts, col, lw))
        elif t == "TEXT":
            h = float(e.dxf.height or 0.2) * uscale
            try:
                r = float(e.dxf.rotation or 0)
            except Exception:
                r = 0
            lx, ly = to_local(p, e.dxf.insert.x, e.dxf.insert.y, F)
            if box is not None and not _in_box(lx, ly, box):
                continue
            texts.append((lx, ly, e.dxf.text, h, r, "text"))
        elif t == "MTEXT":
            h = float(e.dxf.char_height or 0.2) * uscale
            try:
                r = float(e.dxf.rotation or 0)
            except Exception:
                r = 0
            try:
                txt = e.plain_text()
            except Exception:
                txt = e.text
            lx, ly = to_local(p, e.dxf.insert.x, e.dxf.insert.y, F)
            if box is not None and not _in_box(lx, ly, box):
                continue
            texts.append((lx, ly, txt, h, r, "mtext"))
    return polys, texts


def render_floor(name, F, polys, texts, out_path, disp=None):
    """disp = 图内标题(如 'c025 第一教学楼')；None 则只标 F。"""
    if not polys:
        return False
    xs = [pt[0] for pl, _, _ in polys for pt in pl]
    ys = [pt[1] for pl, _, _ in polys for pt in pl]
    if texts:
        xs += [t[0] for t in texts]; ys += [t[1] for t in texts]
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    dx = max(x1 - x0, 1e-6); dy = max(y1 - y0, 1e-6)
    figW = 11.0
    figH = max(2.8, min(16.0, figW * dy / dx * 1.0))
    fig, ax = plt.subplots(figsize=(figW, figH), dpi=130)
    ax.set_facecolor("white")
    mar = 0.6
    ax.set_xlim(x0 - mar, x1 + mar)
    ax.set_ylim(y0 - mar, y1 + mar)
    ax.set_aspect("equal", adjustable="box")
    for pl, col, lw in polys:
        xs2 = [q[0] for q in pl]; ys2 = [q[1] for q in pl]
        ax.plot(xs2, ys2, color=col, lw=lw, solid_capstyle="round",
                solid_joinstyle="round", zorder=2)
    # 字号：按文字真高(米)在 y 向的比例 → 点(pt)
    axesH_px = fig.dpi * (figW - 0.9) * (dy / dx) * 1.0
    for (tx, ty, txt, h, rot, kind) in texts:
        if not txt or not str(txt).strip():
            continue
        # 高度 m → px(估)；font px ≈ pt*dpi/72
        txt_px = h / dy * axesH_px
        fs = max(2.0, min(36.0, txt_px / (fig.dpi / 72.0)))
        lines = str(txt).split("\n")
        if kind == "mtext":
            ax.text(tx, ty, "\n".join(lines), fontsize=fs, color=col_dark(col),
                    ha="left", va="top", rotation=rot, zorder=5,
                    linespacing=1.25)
        else:
            ax.text(tx, ty, str(txt), fontsize=fs, color=col_dark(col),
                    ha="left", va="baseline", rotation=rot, zorder=5)
    if disp:
        ax.set_title(f"{disp} · {F + 1}层", fontsize=15, color="#111111",
                     fontweight="bold", pad=12)
    ax.axis("off")
    fig.savefig(out_path, bbox_inches="tight", pad_inches=0.15, facecolor="white")
    plt.close(fig)
    return True


def col_dark(col):
    return "#1a1a1a"


def _gallery_html(name, floors, cn="", od=""):
    """每层并排 A|B：左=源图纸，右=第一轮识别叠加(有 dxf_plan_recog 则并排, 否则单图)。

    od = dxf_plan 输出目录；据此推 ../dxf_plan_recog。计数(caption)读 floor JSON。
    同一套 to_local 局部坐标 → A/B 天然同基准可叠看。"""
    disp = f"{name} · {cn}".strip(" ·") if cn else name
    base = os.path.dirname(od) if od else os.path.join(BASE, name)
    recdir = os.path.join(base, "dxf_plan_recog")
    rows = []
    any_pair = False
    for F in floors:
        has_rec = os.path.exists(os.path.join(recdir, f"floor{F}.png"))
        cap = f"{disp} · {F + 1}层"
        extra = ""
        if has_rec:
            any_pair = True
            fj = os.path.join(base, "floors", f"floor{F}.json")
            if os.path.exists(fj):
                try:
                    fl = json.load(open(fj, encoding="utf-8"))
                    ol = fl.get("outline")
                    area = (int((max(x for x, _ in ol) - min(x for x, _ in ol)) *
                                (max(y for _, y in ol) - min(y for _, y in ol)))
                            if ol else None)
                    extra = (f"　门 {len(fl.get('doors', []))} · "
                             f"楼梯井 {len(fl.get('stairwells', []))} · "
                             f"房间 {len(fl.get('rooms', []))}"
                             + (f" · 面积 {area}㎡" if area else ""))
                except Exception:  # noqa: BLE001
                    extra = ""
        if has_rec:
            rows.append(
                '<figure class=cmp><div class=pair>'
                f'<div class=side><span class=tag>源图纸 A</span>'
                f'<img loading="lazy" src="floor{F}.png" alt="{name} F{F} 源图纸"></div>'
                f'<div class=side><span class=tag>识别叠加 B</span>'
                f'<img loading="lazy" src="../dxf_plan_recog/floor{F}.png" '
                f'alt="{name} F{F} 识别"></div>'
                f'</div><figcaption>{cap}{extra}</figcaption></figure>')
        else:
            rows.append(f'<figure><img loading="lazy" src="floor{F}.png" '
                        f'alt="{name} {F + 1}层">'
                        f'<figcaption>{cap}</figcaption></figure>')
    if any_pair:
        h1 = f"{disp} · 逐层对照：源图纸(真值) vs 第一轮识别叠加"
        leg = ("每层并排：左 A = 忠实源 CAD 线稿；右 B = 识别叠加 "
               "(灰实心=识别墙 / 红=门 / 绿块=楼梯井 / 蓝=柱 / 灰细线=源墙垫底)。"
               "同一层左右看：B 缺元素=识别漏、B 墙碎或连成块=墙识别错。"
               "标题带 门/楼梯井/房间/面积 计数可对照。")
    else:
        h1 = f"{disp} · 每层源图纸（CAD 样式，每层一文件）"
        leg = ("直接从源 DXF(=DWG 同一套几何)忠实画：连续墙线/门/楼梯踏步/房间号文字。"
               "并非识别重构图，可与建筑实际图纸核对。")
    return ("<!DOCTYPE html><html lang=zh><head><meta charset=utf-8>"
            f"<title>{disp} 每层图纸</title><style>"
            "body{font-family:sans-serif;background:#eef0f3;margin:0;padding:16px}"
            "h1{font-size:17px;color:#222;margin:4px 0 6px}"
            "p.leg{font-size:12px;color:#555;margin:0 0 12px}"
            "a{color:#0366d6;text-decoration:none}"
            "figure,figure.cmp{display:block;background:#fff;border:1px solid #d4d8dd;"
            "border-radius:6px;padding:10px;margin:0 0 14px}"
            "div.pair{display:grid;grid-template-columns:1fr 1fr;gap:10px}"
            "div.side{position:relative}"
            "span.tag{position:absolute;top:6px;left:6px;z-index:2;"
            "background:rgba(255,255,255,.92);color:#222;font:600 11px/1 sans-serif;"
            "padding:2px 7px;border-radius:4px;border:1px solid #c9ced6}"
            "img{width:min(1080px,100%);height:auto;border:1px solid #e0e3e7}"
            "div.pair img{width:100%}"
            "figcaption{font-size:12px;color:#333;margin-top:5px}"
            "@media(max-width:900px){div.pair{grid-template-columns:1fr}}"
            "</style></head><body>"
            f"<h1>{h1}</h1>"
            f"<p class=leg>{leg}</p>"
            f"<p><a href=\"../_dxf_index.html\">← 总目录</a>"
            + ('　<a href="../compare.html">整页对照版(含全部楼目录)</a>'
               if any_pair else "")
            + "</p>" + "".join(rows) + "</body></html>")


def _master_html(items):
    lis = "".join(f'<li><a href="{n}/dxf_plan/index.html">{n} {cn}</a>'
                  f' <small>{cnt}层</small></li>' for n, cn, cnt in items)
    return ("<!DOCTYPE html><html lang=zh><head><meta charset=utf-8>"
            "<title>全部建筑源图纸总目录</title><style>"
            "body{font-family:sans-serif;background:#eef0f3;padding:18px}"
            "h1{font-size:19px;color:#222}p{font-size:12px;color:#555}"
            "a{color:#0366d6;text-decoration:none}li{margin:5px 0}"
            "small{color:#999}</style></head><body>"
            "<h1>源图纸总目录（每栋一页 · 每层一图）</h1>"
            "<p>忠实源 DXF 出图（CAD 样式）。点入单栋逐层查看。</p><ul>"
            + lis + "</ul></body></html>")


def main():
    names = sorted(d for d in os.listdir(BASE)
                   if os.path.isdir(os.path.join(BASE, d, "floors")))
    if sys.argv[1:]:
        names = [n for n in names if n in sys.argv[1:]]
    import run_step
    from recognizer.profile import floor_of  # noqa: F401  (warm import)
    tot = 0; failed = []; master = []
    for i, name in enumerate(names, 1):
        try:
            p = run_step.load_profile(name)
            doc = ezdxf.readfile(p.dxf)
        except Exception as e:  # noqa: BLE001
            failed.append((name, "*", f"读源失败 {str(e)[:80]}")); continue
        cn = _cn_from_dxf(p)
        disp = f"{name} · {cn}"
        fd = os.path.join(BASE, name, "floors")
        floors = sorted(int(os.path.basename(f)[5:-5])
                        for f in glob.glob(os.path.join(fd, "floor*.json")))
        od = os.path.join(BASE, name, "dxf_plan")
        os.makedirs(od, exist_ok=True)
        ok = 0
        for F in floors:
            try:
                box = None
                fj = os.path.join(fd, f"floor{F}.json")
                if os.path.exists(fj):
                    fl = json.load(open(fj, encoding="utf-8"))
                    ol = fl.get("outline")
                    if ol:
                        box = (min(q[0] for q in ol), min(q[1] for q in ol),
                               max(q[0] for q in ol), max(q[1] for q in ol))
                polys, texts = collect_floor(doc, p, F, box)
                if render_floor(name, F, polys, texts,
                                os.path.join(od, f"floor{F}.png"), disp):
                    ok += 1
                else:
                    failed.append((name, F, "无几何"))
            except Exception as e:  # noqa: BLE001
                failed.append((name, F, str(e)[:90]))
        tot += ok
        with open(os.path.join(od, "index.html"), "w", encoding="utf-8") as f:
            f.write(_gallery_html(name, floors, cn, od))
        master.append((name, cn, len(floors)))
        print(f"[{i}/{len(names)}] {name:6s} {ok}/{len(floors)} 层", flush=True)
    if not sys.argv[1:]:   # 单栋调试跑不动全楼总目录，避免清成只剩一栋
        with open(os.path.join(BASE, "_dxf_index.html"), "w", encoding="utf-8") as f:
            f.write(_master_html(master))
    print(f"\n=== 完成 {tot} 张 / {len(names)} 栋 / 失败 {len(failed)} ===")
    for nm, F, err in failed[:30]:
        print(f"  FAIL {nm} F{F}: {err}")


if __name__ == "__main__":
    main()
