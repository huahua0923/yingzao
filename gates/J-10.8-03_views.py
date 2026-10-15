# -*- coding: utf-8 -*-
"""J-10.8-03 · 正式件 `rebuild/06_su/` 的三视图**渲染**画的是不是这栋楼。

★ 全仓第一条**看像素**的判据 —— 其余判据量的都是 `v`/`g`/`f` 行与 DXF 坐标。
  加它的直接原因：数量全绿时，图片层出过一次事故都没人知道
  （`rebuild/构件清单.md:125`：三视图里正立面与俯视**对调，且两张还都「看着挺像」**）。

判据
 ① 四件齐、非空：`c006_su_{iso,front,top}.png` 前景（`alpha>8`）占比落在
    [0.5%, 95%]；`对比三视图.png` ≥ 200 px 见方且抽样色数 ≥ 100。
    —— 出图失败会留下**有字节数**的纯色/透明图，`os.path.exists` 看不见这种坏。
 ② 三视图两两不同：三张的像素 md5 必须互不相同。
    —— 抓「同一张出三遍」「这轮出图静默失败、盘上留的是上一轮那张」。
 ③ **俯视**前景 宽/高 必须对上**源图**：`rebuild/01_cad/raw/1层.dxf` 的 `4.2墙体`
    外接矩形 128940×83640 mm ⇒ 1.5415，±8%。
 ④ **正视**前景 宽/高 必须对上**同一件的 OBJ**：`c006_su.obj` 三轴尺寸里
    (平面最大边 ÷ 高度轴尺寸) ⇒ 129300/50500 = 2.560，±8%。
    —— ★这一条量的是**跨件一致性**：OBJ 是数、PNG 是像素，两边各自独立算出的长宽比
       必须一样。渲染器把轴搞反（正立面画成俯视）、读错文件、相机被改，都会在这里红。

量具
  PIL+numpy 读 PNG；前景 = `alpha>8`；外接矩形 = `(xs.min, ys.min, xs.max, ys.max)`；
  比值 = `(xmax-xmin+1)/(ymax-ymin+1)`。对照侧：ezdxf 读 1 层 DXF 的 `4.2墙体` 外接矩形；
  OBJ 侧只读 `v` 行取三轴极值，**高度轴按 `EXPORT.md` 为该件声明的朝向取**。

量具盲区（★先声明，再判）
 · **透视**：相机是透视投影 ⇒ 前景外接矩形**不等于**正交轮廓，所以给的是 ±8% 的带、
   不是等号。带外才红。
 · **只量外接矩形**：轮廓**里面**的东西（八角厅在不在、女儿墙有没有、少一层、门洞位置）
   这四条**全盲**。要抓「少一层」得另立判据（逐层前景高度带），本判据不假装能抓。
 · **只认 alpha**：四张里三张是 RGBA、背景是透明（实测角点 `alpha=0`）；
   按亮度切前景会把整幅当前景（实测 `lum<245` 占比 = **1.000**）⇒ 禁用亮度阈值。
   `对比三视图.png` 是 RGB（无 alpha）⇒ 对它只做①，不做②③④。
 · **不判「像不像」**：本判据不含任何「美观/相似度」判词；相似度不是可复现的判据。

正对照（每条必须**因该因**而红；下面的「新增 N 条」是相对 C1 基线的**差集**，
        不是违反总数 —— 件本身若有违反，对照不许继承它，铁律 183/197）
 C1 真件        —— 基线，必须 0 条违反
 C2 正视←俯视    —— ②④ 红（同一张出两遍 + 视角对调）
 C3 正视/俯视互换 —— ③④ 红
 C4 正视←空图    —— ①④ 红（④ 报「量不到」，不与「比例对了」同形）
 C5 件不在       —— SKIP(rc=4)，另起一个进程真跑一遍验它
 C6 高度轴换一根 —— ④ 红（证明④真在用 OBJ 的轴，不是恒绿）

三态：rc=0 PASS ／ rc=1 FAIL ／ rc=4 SKIP（图或 OBJ 不在）
"""
import hashlib
import json
import os
import subprocess
import sys

import numpy as np
from PIL import Image

sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

# ★ HERE = 本脚本所在目录（gates/）。产物默认路径**一律用它拼**，不认当前工作目录 ——
#   否则换个 CWD 跑，json 就落到别处，页面上那条判据的「顶层字段」一格会**静默为空**。
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = r"D:\项目\cdut3d"
SU = os.path.join(ROOT, "rebuild", "06_su")
DXF1 = os.path.join(ROOT, "rebuild", "01_cad", "raw", "1层.dxf")
EXPORT = os.path.join(SU, "EXPORT.md")
OUTD = os.path.join(ROOT, "gates", "_out")
OUT = os.path.join(OUTD, "J-10.8-03.run.txt")

# ★ 本闸**已声明的盲区**（逐条抄自本文件 docstring 的「量具盲区」，不新编）——
#   落进 json 的 `blind` 字段，好让页面上「这条判据对什么全盲」跟着读数一起露脸。
BLIND = [
    "透视投影：前景外接矩形≠正交轮廓，给的是 ±8% 带、不是等号",
    "只量外接矩形：轮廓内部（八角厅/女儿墙/少一层/门洞位置）全盲",
    "只认 alpha：禁用亮度阈值（实测按亮度切会把整幅当前景，lum<245 占比 1.000）",
    "不判「像不像」：不含任何美观/相似度判词（相似度不是可复现的判据）",
]

OBJ = os.path.join(SU, "c006_su.obj")
EXTRA = "对比三视图.png"
ISO, FRONT, TOP = "c006_su_iso.png", "c006_su_front.png", "c006_su_top.png"
VIEWS = (ISO, FRONT, TOP)

WALL_LAYER = "4.2墙体"
FG_MIN, FG_MAX = 0.005, 0.95
TOL = 0.08                      # 允许 |实测比 / 期望比 − 1|
EXTRA_MIN_PX, EXTRA_MIN_COLORS = 200, 100

_LOG = []


def log(s):
    _LOG.append(s)
    print(s)


def write(path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as fh:
        fh.write(("\n".join(_LOG) + "\n").encode("utf-8").replace(b"\r\n", b"\n"))


def json_path(out_txt):
    """★ 产物 json 落到哪。

    ★ 默认与 run.txt 同编号：`gates/_out/J-10.8-03.json`（用 HERE 拼）。
    ★ 为什么还要看 `--out`：C5 那条正对照**另起一个进程**真跑本脚本验 rc —— 它把
      `--out` 改到探针文件；json 若写死，子进程那份 rc=4 的 SKIP 会先落到正牌路径上，
      主进程万一后头崩了，页面上留下的就是子进程的 SKIP，**「没做」被当成「坏了」**
      （铁律 199）。所以 json 跟 run.txt 走：同一个 --out 目录、同一个编号。
    """
    if out_txt == OUT:
        return os.path.join(HERE, "_out", "J-10.8-03.json")
    if out_txt.endswith(".run.txt"):
        return out_txt[:-len(".run.txt")] + ".json"
    return os.path.splitext(out_txt)[0] + ".json"


def finish(rc, out, readings):
    """★ 三路读数的**唯一出口**：本闸所有 `return <rc>` 都从这儿走。

    ★ 为什么要一个出口：页面对每条判据取三路独立读数（产物 json 的 `pass` /
      run.txt 里的 `rc=` / run.txt 的判词行）。任何一个 return 绕过这里，那一格
      就永远是空的 —— 本闸原先只落 run.txt、**不落 json**，所以页面上只有两路读数
      （用户 2026-10-14 明令：把缺的那一路补上）。
    ★ `readings` 只放**本闸真量到的**数，一个不编（铁律 174）；`pass` 只由 rc 定，
      不另造一个判据。
    """
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
def stats(a):
    """a: HxWx4 uint8 → 前景占比 / 外接矩形 / 宽高比 / 像素 md5。"""
    m = a[..., 3] > 8
    n = int(m.sum())
    if n == 0:
        return {"fg": 0.0, "bbox": None, "ratio": None, "md5": hashlib.md5(a.tobytes()).hexdigest()}
    ys, xs = np.where(m)
    b = (int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max()))
    return {"fg": n / float(a.shape[0] * a.shape[1]), "bbox": b,
            "ratio": (b[2] - b[0] + 1) / float(b[3] - b[1] + 1),
            "md5": hashlib.md5(a.tobytes()).hexdigest()}


def load(p):
    return np.asarray(Image.open(p).convert("RGBA"))


def obj_extents(p):
    """只读 `v` 行 ⇒ (行数, 三轴尺寸)。OBJ 的 v 与索引无关，这里不碰 f。"""
    lo, hi, n = [1e30] * 3, [-1e30] * 3, 0
    with open(p, "r", encoding="utf-8", errors="replace") as fh:
        for ln in fh:
            if not ln.startswith("v "):
                continue
            t = ln.split()
            for k in range(3):
                v = float(t[1 + k])
                lo[k] = v if v < lo[k] else lo[k]
                hi[k] = v if v > hi[k] else hi[k]
            n += 1
    return n, [hi[k] - lo[k] for k in range(3)]


def height_axis():
    """从 EXPORT.md 里该件那一行取「哪根轴朝上」。返回 (下标, 轴名, 行原文)。"""
    row = ""
    with open(EXPORT, "r", encoding="utf-8", errors="replace") as fh:
        for ln in fh:
            if os.path.basename(OBJ) in ln:
                row = ln.strip()
                break
    up = row.upper()
    for i, ax in enumerate("XYZ"):
        if ("%s 朝上" % ax) in up or ("%s_UP" % ax) in up:
            return i, ax, row
    return None, None, row


def plan_extent(p, layer):
    import ezdxf
    from ezdxf import bbox as ezb
    doc = ezdxf.readfile(p)
    ents = [e for e in doc.modelspace() if e.dxf.layer == layer]
    if not ents:
        return None, None, 0
    ext = ezb.extents(ents)
    return (ext.extmax[0] - ext.extmin[0]), (ext.extmax[1] - ext.extmin[1]), len(ents)


def extra_check(p):
    a = np.asarray(Image.open(p).convert("RGB"))
    h, w = a.shape[:2]
    cols = len(np.unique(a[::8, ::8].reshape(-1, 3), axis=0))
    log("  ① %-20s %d×%d ｜ 抽样色数 %d" % (EXTRA, w, h, cols))
    if w < EXTRA_MIN_PX or h < EXTRA_MIN_PX or cols < EXTRA_MIN_COLORS:
        return ["① %s 是 %d×%d、抽样色数 %d —— 太小或近乎纯色（并排图没画出来 / 只画了一张空底）"
                % (EXTRA, w, h, cols)]
    return []


# ---------------- 判据 ----------------
def judge(imgs, extra_p, front_want, plan_src):
    fs, S = [], {n: stats(imgs[n]) for n in VIEWS}

    for n in VIEWS:
        s = S[n]
        log("  ① %-20s 前景占比 %.4f ｜ 外接矩形 %s ｜ 宽/高 %s"
            % (n, s["fg"], s["bbox"], "—" if s["ratio"] is None else "%.4f" % s["ratio"]))
        if not (FG_MIN <= s["fg"] <= FG_MAX):
            fs.append("① %s 前景占比 %.4f 不在 [%.3f, %.2f] —— 出图失败会留下一张"
                      "**有字节数**的纯色/透明图" % (n, s["fg"], FG_MIN, FG_MAX))
    fs += extra_check(extra_p)

    seen = {}
    for n in VIEWS:
        h = S[n]["md5"]
        if h in seen:
            fs.append("② %s 与 %s 像素完全相同（同一张出了两遍 / 这轮出图失败、盘上是上一轮那张）"
                      % (n, seen[h]))
        else:
            seen[h] = n

    rt = S[TOP]["ratio"]
    if rt is None:
        fs.append("③ 俯视图前景为空 ⇒ **量不到**长宽比（不与「比例对了」同形）")
    else:
        e3 = abs(rt / plan_src - 1.0)
        log("  ③ 俯视 宽/高 %.4f vs 源图 %s/%s 平面 %.4f（差 %.2f%%）"
            % (rt, os.path.basename(DXF1), WALL_LAYER, plan_src, e3 * 100))
        if e3 > TOL:
            fs.append("③ 俯视图前景 宽/高 %.4f 对不上源图平面 %.4f（差 %.2f%%，超过 ±%.0f%%）"
                      % (rt, plan_src, e3 * 100, TOL * 100))

    rf = S[FRONT]["ratio"]
    if rf is None:
        fs.append("④ 正视图前景为空 ⇒ **量不到**长宽比（不与「比例对了」同形）")
    elif front_want is None:
        fs.append("④ 件的高度轴没量到（EXPORT.md 没声明）⇒ 量不到正立面该有的比例")
    else:
        e4 = abs(rf / front_want - 1.0)
        log("  ④ 正视 宽/高 %.4f vs 件 OBJ 平面最大边/高度轴 %.4f（差 %.2f%%）"
            % (rf, front_want, e4 * 100))
        if e4 > TOL:
            fs.append("④ 正视图前景 宽/高 %.4f 对不上这件 OBJ 的 %.4f（差 %.2f%%，超过 ±%.0f%%）"
                      " —— 正立面画成了别的视角 / 相机被改 / 读的不是这件"
                      % (rf, front_want, e4 * 100, TOL * 100))
    return fs


def main():
    global OBJ
    argv = sys.argv[1:]
    out = argv[argv.index("--out") + 1] if "--out" in argv else OUT
    if "--obj" in argv:
        OBJ = argv[argv.index("--obj") + 1]

    _LOG.clear()
    log("J-10.8-03 · 三视图渲染是不是这栋楼（正式件目录 %s）" % SU)

    need = [OBJ] + [os.path.join(SU, n) for n in VIEWS + (EXTRA,)]
    miss = [p for p in need if not os.path.exists(p)]
    if miss:
        log("★ 没量到：缺 %d 件 —— %s ⇒ SKIP(rc=4)"
            % (len(miss), [os.path.basename(m) for m in miss]))
        return finish(4, out, {"n_required": len(need), "n_missing": len(miss),
                               "missing": [os.path.basename(m) for m in miss]})

    H = height_axis()
    hai = H[0]
    log("  件朝向（读 %s）：高度轴 = %s ｜ 该行：%s" % (EXPORT, H[1], H[2]))
    nv, ext = obj_extents(OBJ)
    log("  OBJ `v` 行 %d ｜ 三轴尺寸 mm %.0f × %.0f × %.0f" % (nv, ext[0], ext[1], ext[2]))
    front_want = (max(ext[k] for k in range(3) if k != hai) / ext[hai]) if hai is not None else None
    if hai is not None:
        log("  件 OBJ ⇒ 正立面该有的 宽/高 = %.0f / %.0f = %.4f"
            % (max(ext[k] for k in range(3) if k != hai), ext[hai], front_want))

    pl, pd, ne = plan_extent(DXF1, WALL_LAYER)
    if ne == 0:
        log("★ %s 里没有 %r 图层的实体 ⇒ 量不到源图平面 ⇒ SKIP(rc=4)" % (DXF1, WALL_LAYER))
        return finish(4, out, {
            "obj_v_rows": nv, "obj_extents_mm": [int(round(x)) for x in ext],
            "height_axis": H[1], "dxf_layer_entities": ne,
            "front_want_ratio": None if front_want is None else round(front_want, 4)})
    plan_src = pl / pd
    log("  源图 %s 的 %s 外接矩形 %.0f × %.0f mm（%d 个实体）⇒ 平面 宽/进深 = %.4f"
        % (os.path.basename(DXF1), WALL_LAYER, pl, pd, ne, plan_src))

    imgs = {n: load(os.path.join(SU, n)) for n in VIEWS}
    extra_p = os.path.join(SU, EXTRA)
    log("-" * 78)

    base = judge(imgs, extra_p, front_want, plan_src)
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

    ctl("C2 正视←俯视", judge({**imgs, FRONT: imgs[TOP]}, extra_p, front_want, plan_src), ["②", "④"])
    ctl("C3 正视/俯视互换", judge({**imgs, FRONT: imgs[TOP], TOP: imgs[FRONT]},
                                  extra_p, front_want, plan_src), ["③", "④"])
    ctl("C4 正视←空图", judge({**imgs, FRONT: np.zeros_like(imgs[FRONT])},
                              extra_p, front_want, plan_src), ["①", "④"])
    if hai is None:
        log("  对照 C6 略过：高度轴本来就没量到")
    else:
        j = (hai + 1) % 3
        fw2 = max(ext[k] for k in range(3) if k != j) / ext[j]
        ctl("C6 高度轴换一根", judge(imgs, extra_p, fw2, plan_src), ["④"])

    # ★ C5：件不在必须 SKIP —— **另起一个进程真跑一遍**，不是断言函数返回值
    #   （铁律 199：判词必须把「没做」与「坏了」分开，而这件事只有在真 rc 上才看得见）
    tmp = os.path.join(OUTD, "_views_skip_probe.txt")
    env = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    r = subprocess.run([sys.executable, os.path.abspath(__file__),
                        "--obj", os.path.join(SU, "_no_such_obj.obj"), "--out", tmp],
                       cwd=ROOT, capture_output=True, env=env)
    log("  对照 %-22s → %s（rc=%d，要 4）"
        % ("C5 件不在⇒SKIP", "✔" if r.returncode == 4 else "✘", r.returncode))
    if r.returncode != 4:
        bad.append("对照 C5 件不在时没 SKIP（rc=%d，要 4）—— 判词把「没做」与「坏了」混成一个"
                   % r.returncode)

    log("-" * 78)
    log("J-10.8-03 总判 : %s" % ("PASS" if not bad else "FAIL（%d 条）" % len(bad)))
    for x in bad:
        log("  ✗ " + x)

    # ★ 本闸**自己量到的**读数（一个数不编）落进 json —— 判定逻辑一行没动，
    #   只是在出口处把已经算出来的量再抄一份给页面看（用户 2026-10-14 明令）。
    S = {n: stats(imgs[n]) for n in VIEWS}
    exa = np.asarray(Image.open(extra_p).convert("RGB"))
    readings = {
        "obj_v_rows": nv,
        "obj_extents_mm": [int(round(x)) for x in ext],
        "height_axis": H[1],
        "plan_src_ratio": round(plan_src, 4),
        "front_want_ratio": None if front_want is None else round(front_want, 4),
        "views": {n: {"fg": round(S[n]["fg"], 4), "bbox": S[n]["bbox"],
                      "ratio": None if S[n]["ratio"] is None else round(S[n]["ratio"], 4)}
                  for n in VIEWS},
        "extra": {"size_px": [int(exa.shape[1]), int(exa.shape[0])],
                  "sampled_colors": int(len(np.unique(exa[::8, ::8].reshape(-1, 3), axis=0)))},
        "n_violations": len(bad),
    }
    return finish(0 if not bad else 1, out, readings)


if __name__ == "__main__":
    sys.exit(main())
