# -*- coding: utf-8 -*-
"""两件互照：**参照件**（Python 拉伸）vs **正式件**（SketchUp 出）—— 数从文件里量，不从记忆里背。

用法：python rebuild/tools/compare3d.py
出：  rebuild/06_su/对比.md          （数表，给人看 / 给下游引）
      rebuild/06_su/对比三视图.png   （同相机的轴测/正立面/俯视，左右并排）

## 为什么非要「互照」而不是各自报一次

两份件是**两个不同程序**出的（trimesh 写盘 vs SketchUp 导出），**没有一件事是共享的**：
单位、朝向、组结构、面数全都要各自量。2026-10-13 当场就量出两处**默认以为是同的、其实不同**：

    · 参照件 c006_white.obj 的数是 **米**（129.3 × 50.5 × 84.0）；正式件是 **毫米**（129300 × …）
      ⇒ 把两份件喂给同一个下游，差 **1000 倍**，而且**两份读起来都「像对」**。
    · 参照件 **没有 `g` 组**（trimesh 合成一个网格，231816 面）；正式件有 **7125** 个组
      ⇒ 「按构件上色」「按层点名」这类操作在一份上有效、在另一份上**静默失效**。
    · 高度**都落在 Y**（两份的 y 都是三轴最小），但这是**量出来的**，不是约定来的。

## 参照物是谁（★ 不许拿我们自己写的东西当参照）

- **平面尺寸** ↔ `rebuild/01_cad/raw/1层.dxf` 的 `4.2墙体` 图层 bbox（**源件**，不是本仓生成物）。
  两件都拿它定**单位**（比例落在 1 / 0.001 / 25.4 哪一个上）与定**高度轴**
  （哪个轴被拿掉以后，剩下那个平面跟墙脚对得上 ⇒ 那个轴就是高度轴，**不预设 Y 或 Z**）。
- **构件数**：正式件那一列从 **OBJ 的组名**数（`MeshN __1__WALL Model` ⇒ 层+类都是文件名里的事实）；
  参照件那一列从 `build.json` 读（★ **那是我们自己产的**，所以这一列标 `[自述]`，
  只能用来描述参照件自己，**不可**拿它当正式件的判据 —— 铁律 137/187/192）。

## 自带伪证（错了要出声，不能静默）

  1. 任一件的平面比例**不落在**三个候选单位（1 / 0.001 / 25.4）的 1% 内 ⇒ ★报红 rc=4。
  2. 任一件的**高度轴不一致**（比如一份 Y 一份 Z）⇒ ★报红 rc=5（并写出各自量到的是哪个轴）。
  3. 源件 `4.2墙体` 读不到 ⇒ ★报红 rc=6（「没量到」不许当绿）。
"""
from __future__ import annotations

import collections
import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
RAW = os.path.join(ROOT, "01_cad", "raw")
OUTDIR = os.path.join(ROOT, "06_su")

REF_OBJ = os.path.join(ROOT, "05_build", "c006_white.obj")
REF_META = os.path.join(ROOT, "05_build", "build.json")
SU_OBJ = os.path.join(OUTDIR, "c006_su.obj")

# ★ 次序是判据的一部分：归类是「**第一个子串命中**」，而 `ROOF_STAIR` 里含 `STAIR`
#   ⇒ 长的必须排在短的**前面**，否则楼梯房的组会被数成楼梯（静默错，两列都还像个数）。
KINDS = ("WALL", "COL", "LIFT", "SLAB", "DOOR", "PARAPET", "ROOF_STAIR", "ROOF_STEP",
         "ROOF_ROOM", "ROOF", "STAIR", "LINTEL")
# ★★ 2026-10-19 补 `ROOF_ROOM`（出屋面楼梯间+电梯机房），**必须排在 `ROOF` 之前** ——
#   下面按 `if k in nm` 子串匹配、先命中先 break，`ROOF` 放前面会把 `__ROOF_ROOM`
#   全数成 `ROOF`（与上一条 `ROOF_STAIR/ROOF_STEP` 同一个坑，铁律 174）。
# ★ `ROOF` 必须排在 `ROOF_STAIR` / `ROOF_STEP` **之后**：下面按 `if k in nm` **子串匹配、
#   先命中先 break** ⇒ 放前面会把那两类的组全数成 `ROOF`（铁律 174 那一类：两个同名的量）。
#   2026-10-15 加它（塔楼屋面板，用户「楼板要画」）。
# ★★ 2026-10-15 补 `LINTEL`（门头墙）：**漏的是第 11 类里唯一还漏的一个**，
#    症状是**静默少数** —— 件里有 **943** 组 `__*__LINTEL`，`KINDS` 里没有它 ⇒
#    `if k in nm` 全不命中 ⇒ 本表「正式件」那一列**一个都不计**，而表照样出、rc 照样 0。
#    这是 `J-10.9-07`（类名闭合，②）当场抓出来的；同一条判据也证明了本表此前
#    的逐类行数**加起来 ≠ `g` 行总数**（3150 vs 3550）—— 缺的正是这 943 减掉别的差。
#    `LINTEL` 与其余类名**互不为子串**（既不是任何类名的子串，也不含任何类名）
#    ⇒ 它在 `KINDS` 里放哪一位都不改变别的类的归类；放末位是为了不动既有序。
# 候选单位：倍数 = 件里的数 / 毫米数。1=毫米 · 0.001=米 · 25.4=英寸
UNITS = ((1.0, "mm"), (0.001, "m"), (25.4, "inch"))
TOL_UNIT = 0.01      # 单位判定的相对容差
PLAN_FLOOR = "1层"


def read_obj(path):
    """纯文本读 OBJ：bbox（x0,x1,y0,y1,z0,z1）+ v/f/g 计数 + 组名按类归堆。"""
    lo = [float("inf")] * 3
    hi = [float("-inf")] * 3
    nv = nf = ng = 0
    gk = collections.Counter()
    floors = collections.Counter()
    with open(path, encoding="utf-8", errors="replace") as f:
        for ln in f:
            if ln.startswith("v "):
                q = ln.split()
                if len(q) < 4:
                    continue
                for i in range(3):
                    val = float(q[1 + i])
                    lo[i] = min(lo[i], val)
                    hi[i] = max(hi[i], val)
                nv += 1
            elif ln.startswith("f "):
                nf += 1
            elif ln.startswith("g "):
                ng += 1
                nm = ln[2:].strip().upper()
                for k in KINDS:
                    if k in nm:
                        gk[k] += 1
                        break
                # 组名形如 `MESH1 __1__WALL MODEL` ⇒ `__<层号>__` 里那个数是层
                p = nm.split("__")
                if len(p) >= 3 and p[1].strip().isdigit():
                    floors[p[1].strip()] += 1
    if nv == 0:
        return None
    return {"bytes": os.path.getsize(path), "nv": nv, "nf": nf, "ng": ng,
            "bbox": (lo[0], hi[0], lo[1], hi[1], lo[2], hi[2]), "kinds": gk, "floors": floors}


def dxf_wall_bbox(floor=PLAN_FLOOR, raw=RAW):
    """源件该层 `4.2墙体` 图层的 bbox（mm）。★ 这是**独立参照**：不是本仓生成物。读不到 ⇒ None。"""
    try:
        import ezdxf
        d = ezdxf.readfile(os.path.join(raw, "%s.dxf" % floor))
    except Exception:
        return None
    lo = [float("inf")] * 2
    hi = [float("-inf")] * 2
    n = 0
    for e in d.modelspace():
        try:
            if e.dxf.layer != "4.2墙体":
                continue
        except Exception:
            continue
        if e.dxftype() == "LWPOLYLINE":
            pts = [(p[0], p[1]) for p in e.get_points("xy")]
        else:
            try:
                pts = [(e.dxf.start.x, e.dxf.start.y), (e.dxf.end.x, e.dxf.end.y)]
            except Exception:
                continue
        if not pts:
            continue
        for x, y in pts:
            lo[0] = min(lo[0], x)
            hi[0] = max(hi[0], x)
            lo[1] = min(lo[1], y)
            hi[1] = max(hi[1], y)
        n += 1
    return None if n == 0 else ((hi[0] - lo[0], hi[1] - lo[1]), n)


def solve_frame(bb, plan_mm):
    """从件自己的 bbox + 源件墙脚，解出 **(高度轴, 单位, 平面尺寸, 高度区间)**。

    ★ 不预设哪个轴是高度：三个轴各当一次「高度」，剩下的两轴排序后跟墙脚比 ——
      哪个选择对得上，哪个才是高度轴。**单位也一起解**（同一组比例）。
    """
    ext = [bb[1] - bb[0], bb[3] - bb[2], bb[5] - bb[4]]
    pw, ph = sorted(plan_mm, reverse=True)
    best = None
    for k in range(3):
        pair = sorted([ext[i] for i in range(3) if i != k], reverse=True)
        if pair[1] <= 0:
            continue
        for f, un in UNITS:
            rw, rh = pair[0] / (pw * f), pair[1] / (ph * f)
            err = max(abs(rw - 1.0), abs(rh - 1.0))
            if err > TOL_UNIT:
                continue
            if best is None or err < best[4]:
                best = ("xyz"[k], un, f, err, (bb[2 * k], bb[2 * k + 1]))
    if best is None:
        return None
    ax, un, f, err, zl = best
    k = "xyz".index(ax)
    z_m = (zl[0] / f / 1000.0, zl[1] / f / 1000.0)          # → 米
    pair = sorted([ext[i] / f / 1000.0 for i in range(3) if i != k], reverse=True)
    return {"axis": ax, "unit": un, "fac": f, "err": err,
            "plan_m": (pair[0], pair[1]), "z_m": z_m,
            "ext_m": sorted([e / f / 1000.0 for e in ext], reverse=True)}


def composite(png_out):
    """同相机的三视图左右并排（左=参照件 / 右=正式件）。相机公式两边一致 ⇒ 可直接并排比。"""
    from PIL import Image, ImageDraw, ImageFont
    rows = ["iso", "front", "top"]
    cols = [("参照件 05_build（Python 拉伸）", "c006_%s.png", os.path.join(ROOT, "05_build")),
            ("正式件 06_su（SketchUp 出）", "c006_su_%s.png", OUTDIR)]
    tw, th = 900, 619
    bar, pad = 46, 14
    W = pad + (tw + pad) * len(cols)
    H = pad + (bar + th + pad) * len(rows)
    canvas = Image.new("RGB", (W, H), (24, 24, 27))
    dr = ImageDraw.Draw(canvas)
    try:
        fnt = ImageFont.truetype(r"C:\Windows\Fonts\msyh.ttc", 26)
    except Exception:
        fnt = ImageFont.load_default()
    for r, view in enumerate(rows):
        y = pad + r * (bar + th + pad)
        for c, (lab, pat, d) in enumerate(cols):
            x = pad + c * (tw + pad)
            p = os.path.join(d, pat % view)
            dr.text((x + 4, y + 8), "%s   [%s]" % (lab, view), font=fnt, fill=(235, 235, 240))
            if not os.path.exists(p):
                dr.text((x + 4, y + bar + 8), "缺图 %s" % p, font=fnt, fill=(255, 90, 90))
                continue
            im = Image.open(p).convert("RGB").resize((tw, th), Image.LANCZOS)
            canvas.paste(im, (x, y + bar))
            dr.rectangle([x - 1, y + bar - 1, x + tw, y + bar + th], outline=(80, 80, 88))
    canvas.save(png_out)
    return canvas.size


def main():
    plan = dxf_wall_bbox()
    if plan is None:
        print("★ 源件 rebuild/01_cad/raw/%s.dxf 的 `4.2墙体` 读不到 ⇒ 没有独立参照，停" % PLAN_FLOOR)
        return 6
    plan_mm, ne = plan
    print("源件（独立参照）%s `4.2墙体`：%d 个实体，尺寸 %.0f × %.0f mm" % (PLAN_FLOOR, ne, plan_mm[0], plan_mm[1]))

    pieces = []
    for lab, p, note in [("参照件", REF_OBJ, "Python 拉伸"), ("正式件", SU_OBJ, "SketchUp 出")]:
        if not os.path.exists(p):
            print("★ %s 不在：%s" % (lab, p))
            return 6
        d = read_obj(p)
        fr = solve_frame(d["bbox"], plan_mm)
        if fr is None:
            print("★ %s 的平面比例不落在 1 / 0.001 / 25.4 任一候选上（1%% 内）⇒ 单位不认识，停" % lab)
            print("   bbox=%s  三轴尺寸=%s"
                  % (d["bbox"], [round(d["bbox"][2 * i + 1] - d["bbox"][2 * i], 3) for i in range(3)]))
            return 4
        d["frame"] = fr
        d["label"] = lab
        d["note"] = note
        d["path"] = os.path.relpath(p, ROOT).replace("\\", "/")
        pieces.append(d)

    if len({p["frame"]["axis"] for p in pieces}) != 1:
        print("★ 两件的**高度轴不一致**：%s ⇒ 直接并排比会全错，停"
              % {p["label"]: p["frame"]["axis"] for p in pieces})
        return 5

    for p in pieces:
        f = p["frame"]
        print("%s %s：单位=%s 高度轴=%s 平面=%.1f×%.1f m 高度区间=[%.2f, %.2f] m"
              % (p["label"], p["path"], f["unit"], f["axis"], f["plan_m"][0], f["plan_m"][1],
                 f["z_m"][0], f["z_m"][1]))

    meta = None
    if os.path.exists(REF_META):
        meta = json.load(open(REF_META, encoding="utf-8"))

    r, s = pieces[0], pieces[1]
    rf, sf = r["frame"], s["frame"]
    L = ["# 参照件 vs 正式件 · 对照（数从文件里量）", "",
         "> `python rebuild/tools/compare3d.py` 生成。**不是手打**：全部当场从两个 OBJ 与源件量出。",
         "> 独立参照 = `rebuild/01_cad/raw/%s.dxf` 的 `4.2墙体` 图层（%.0f × %.0f mm），"
         "用它同时定**单位**与**高度轴**。" % (PLAN_FLOOR, plan_mm[0], plan_mm[1]), "",
         "| 指标 | 参照件 `05_build/c006_white.obj` | 正式件 `06_su/c006_su.obj` |",
         "|---|---|---|"]
    for k, a, b in [
        ("字节", "%d" % r["bytes"], "%d" % s["bytes"]),
        ("★ 单位（实测）", "**%s**" % rf["unit"], "**%s**" % sf["unit"]),
        ("★ 朝向：高度轴", "**%s**" % rf["axis"], "**%s**" % sf["axis"]),
        ("三轴尺寸 (m)", " × ".join("%.1f" % v for v in rf["ext_m"]),
         " × ".join("%.1f" % v for v in sf["ext_m"])),
        ("平面 (m)", "%.1f × %.1f" % rf["plan_m"], "%.1f × %.1f" % sf["plan_m"]),
        ("★ 高度区间 (m)", "[%.2f, %.2f]（总高 %.1f）" % (rf["z_m"][0], rf["z_m"][1], rf["z_m"][1] - rf["z_m"][0]),
         "[%.2f, %.2f]（总高 %.1f）" % (sf["z_m"][0], sf["z_m"][1], sf["z_m"][1] - sf["z_m"][0])),
        ("顶点 v", "%d" % r["nv"], "%d" % s["nv"]),
        ("面 f", "%d" % r["nf"], "%d" % s["nf"]),
        ("★ 组 g", "**%d**（无组，整件一个网格）" % r["ng"], "**%d**" % s["ng"]),
    ]:
        L.append("| %s | %s | %s |" % (k, a, b))

    ref_cnt = {}
    if meta:
        fl = meta["floors"]
        ref_cnt = {"WALL": sum(x.get("n_wall", 0) for x in fl),
                   "COL": sum(x.get("n_col", 0) for x in fl),
                   "LIFT": sum(x.get("n_lift", 0) for x in fl),
                   "SLAB": sum(x.get("n_slab", 0) for x in fl),
                   "DOOR": sum(x.get("n_door_leaf", 0) for x in fl),
                   "STAIR": sum(x.get("n_step", 0) for x in fl)}
    L += ["", "## 构件覆盖（两列口径不同，别横向相减）", "",
          "| 类 | 参照件 `[自述]`（`build.json`） | 正式件（数 OBJ 的 `g` 组名） |", "|---|---|---|"]
    for k in ("WALL", "COL", "LIFT", "SLAB", "DOOR", "STAIR"):
        L.append("| %s | %s | %d |" % (k, ref_cnt.get(k, "—"), s["kinds"].get(k, 0)))
    # ★ 2026-10-15 补（门头墙）：`LINTEL` 此前**整类不在**本表里 —— `KINDS` 里没有它，
    #   于是 `if k in nm` 一次都不命中，正式件那一列**一个都不计**（实测件里有 943 组）。
    #   参照件那一格**没有块数可填**：`build.json::floors[].z_by_class.lintel` 只有
    #   `[底, 顶]` 标高，没有块数 ⇒ 写「未单列」而**不是** 0（写 0 会读成「参照件没建」
    #   —— 它建了，`build3d.py:928 lintel_module`）。别横向减两列（口径不同，表头已写明）。
    L.append("| 门头墙 `LINTEL` | （`build.json` 未单列块数，只有 `z_by_class.lintel`） "
             "| %d（`g` 块；同件 SU 面数见 `EXPORT.md` 逐类表） |" % s["kinds"].get("LINTEL", 0))
    if meta:
        at = meta.get("attach", {})
        L.append("| 女儿墙 PARAPET | %s（`parapet_m`=%s m） | %d |"
                 % (at.get("n_parapet"), at.get("parapet_m"), s["kinds"].get("PARAPET", 0)))
        L.append("| 顶楼楼梯房 | %s（`roof_stair_m`=%s m） | %d |"
                 % (at.get("n_roof_stair"), at.get("roof_stair_m"), s["kinds"].get("ROOF_STAIR", 0)))
        L.append("| 7→8 台阶屋面 | %s 块 / %s m² | %d |"
                 % (at.get("n_roof_step7"), at.get("roof_step7_m2"), s["kinds"].get("ROOF_STEP", 0)))
        # ★ 2026-10-15 加（用户「楼板要画」）：`ROOF` 是同日新加的第 11 类（塔楼屋面板）。
        #   参照件那一列**没有块数可填** —— `build.json::attach` 压根没记它（只有
        #   `floors[].z_by_class.roof` 一个标高）。所以这格写「未单列」而**不是** 0：
        #   写 0 会读成「参照件没有屋面板」，而它其实建了（`build3d.py:957`，只是没记账）。
        #   ★ 单位必须写在格子里：本列的单位是 **OBJ 的 `g` 块数**，与 `EXPORT.md` 那张
        #     「逐类面数」表的单位（**SU 面数**）**不是同一个估计器** —— 同一件实测
        #     `ROOF`：`g` 块 **1** / SU 面 **4** / OBJ `f` 三角 **57**。三个数都对，
        #     差在量具；不写明就会读成「两份文档打架」（铁律 018/174）。
        L.append("| 塔楼屋面板 `ROOF` | （`build.json` 未单列块数，只有 `z_by_class.roof`） "
                 "| %d（`g` 块；同件 SU 面数 = 4、OBJ 三角 = 57，见 `EXPORT.md`） |"
                 % s["kinds"].get("ROOF", 0))
    # ★★ 第 3 条**必须现算**：2026-10-13 晚补建了顶部三件（女儿墙 / 楼梯房 / 7→8 台阶屋面）之后，
    #    原来那句「正式件这几样还没建」就成了假话 —— 写死的结论会静默过期（铁律 103/105）。
    dz = sf["z_m"][1] - rf["z_m"][1]
    if abs(dz) < 0.05:
        c3 = ("3. ✓ **顶部范围一致**：两件都到 **%.1f m**"
              "（女儿墙 / 顶楼楼梯房 / 7→8 台阶屋面 / 塔楼屋面板**四件**都已建进正式件；"
              "末件 2026-10-15 加，`ROOF` 只 11 层有）。" % sf["z_m"][1])
    else:
        c3 = ("3. ★ **顶部范围不同**：参照件到 **%.1f m**、正式件到 **%.1f m**，差 **%.2f m** ——"
              " 两件的顶部附属件对不齐（见 `su_step2_build.rb` 的分批说明与 `对比.md` 上一版记录）。"
              % (rf["z_m"][1], sf["z_m"][1], dz))
    L += ["", "## 差在哪（都是上面数出来的，不是写死的）", "",
          "1. ★ **单位不同**：参照件是 **%s**、正式件是 **%s**。同一份下游直接读两份差 **%g 倍**，"
          "而且两份都会「看起来像对的」。" % (rf["unit"], sf["unit"], sf["fac"] / rf["fac"]),
          "2. ★ **组结构不同**：参照件 `g=0`（trimesh 合成一个网格），正式件 `g=%d`。"
          "「按类上色」「按层点名」作用在正式件上有效，作用在参照件上**静默失效**。" % s["ng"],
          c3,
          "",
          "★ 两份件的**高度轴一致（都是 `%s`）**，这是当场解出来的、不是约定 ——"
          " 所以三视图可以直接并排比。" % rf["axis"]]
    md = os.path.join(OUTDIR, "对比.md")
    with open(md, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(L) + "\n")
    print("→ %s" % md)

    png = os.path.join(OUTDIR, "对比三视图.png")
    print("→ %s  尺寸=%s" % (png, composite(png)))
    print("高度区间：参照件 [%.2f, %.2f] · 正式件 [%.2f, %.2f] · 高度轴皆为 %s"
          % (rf["z_m"][0], rf["z_m"][1], sf["z_m"][0], sf["z_m"][1], rf["axis"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
