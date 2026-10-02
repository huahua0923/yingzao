# -*- coding: utf-8 -*-
"""GLB 几何级探针 —— 只读。回答「面上的事实」，不下结论。

## 为什么要有它

`glb_gate.py` 量的是 **GLB 与 floors 是否一致**：顶点数、颜色族、窗数、楼板平面。
**它一个判据都没看三角形本身。** 于是只存在于面一级的缺陷 ——
「1px 细线横穿露天」「屋面板挑出立面」「立面看穿」—— 在全部判据绿着的时候照样存在。
这正是「模型一直有问题，而查不出是哪里」的那条缝。

## 量什么

  A  基本量、颜色族、属性清单（有没有 NORMAL）
  B  退化面（零面积）
  C  针状面（最短边 <1cm 且 最长边 >8m）—— 正面看是一条 1px 线
  D  连通块 —— 按位置合并顶点后；游离的小块 = 悬空板 / 细线
  E  四向消隐 —— 封闭的背景区域 = 视线穿过去了
  G  逐高度分带的面数与面积 —— 空带就是缺了一层

## 两个我第一版栽过的坑（留着当反面教材）

1. **`mesh.visual.vertex_colors` 在 c006 上抛 AttributeError**（trimesh 把它读成
   TextureVisuals：1 个 material、0 image、0 texture）。我第一版用 try/except 兜成
   zeros ⇒ 430888 个面全被判成 roof、100% 对不上常量，**屏幕上是一个漂亮的结论**。
   ⇒ 现在直接解 GLB 的 COLOR_0，读不到就出声，不兜底（本仓铁律 16）。
2. **`order // 3` 当面孔索引只在「完全不共享顶点」的网格上成立**。c006 的顶点共享比是
   1.886:1 ⇒ 那个索引指向**随机的面**，D 那一节整节作废。⇒ 现在的邻接是从
   `f` 反查顶点→面，与是否共享顶点无关。

用法（本仓脚本不用 argparse，见 CLAUDE.md 铁律 9）：
    python _scratch/_glb_probe.py c006
报告写到 _scratch/_glb_probe_<name>.txt，消隐图写到 _glb_probe_<name>_<视图>.png。
"""
import ast
import io
import json
import os
import re
import struct
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# ---------------------------------------------------------------- 调色板
# ★ 第一版把 `glb_common.py:41-48` 那 8 个常量当成"调色板"，于是报「65.703% 的面
#   对不上任何常量」—— 而第一名那个颜色占了 66% 的顶点。那不是"少量游离色"。
#   真因：交付件用的是 `recognizer/standard.py` 的 STYLE_DEFAULT，
#   被本楼 `profile.json` 的 `style`（**写成 #hex**）覆盖；`glb_common` 那 8 个
#   只是**兜底默认**，其中 C_WALL / C_ROOF / C_DOOR 在 c006 上一个顶点都没有。
#   ⇒ 是我拿错了表，不是模型错了。**量具的形状必须从实物读回来**（铁律 23/30）。
_HEXF = re.compile(r"#([0-9a-fA-F]{6})\b")


def _hex2rgb(h):
    h = h.strip().lstrip("#")
    return [int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)]


def load_palette(name):
    """从**仓库里**读本楼的调色板，返回 [(rgb, 名字, 出处)]。

    优先级：本楼 profile.style > STYLE_DEFAULT > glb_common 的 C_* 常量 > 各模块里的 hex。
    不 import 任何 backend 模块（import 会执行模块体，本仓栽过 —— 铁律 59），全走 ast。
    """
    out, seen = [], set()

    def add(rgb, nm, src):
        k = tuple(int(x) for x in rgb)
        if k in seen:
            return
        seen.add(k)
        out.append(([int(x) for x in rgb], nm, src))

    pf = os.path.join(ROOT, "data", "buildings", name, "profile.json")
    if os.path.isfile(pf):
        st = (json.load(io.open(pf, encoding="utf-8")) or {}).get("style") or {}
        for k in sorted(st):
            v = st[k]
            if isinstance(v, str) and _HEXF.fullmatch(v.strip()):
                add(_hex2rgb(v), "style." + k, "profile.json")

    def scan_assigns(path, rel, want_prefix=None):
        if not os.path.isfile(path):
            return
        try:
            t = ast.parse(io.open(path, encoding="utf-8").read())
        except SyntaxError:
            return
        for nd in ast.walk(t):
            if not isinstance(nd, ast.Assign):
                continue
            for tg in nd.targets:
                nm = getattr(tg, "id", None)
                if not nm or (want_prefix and not nm.startswith(want_prefix)):
                    continue
                try:
                    v = ast.literal_eval(nd.value)
                except Exception:                                  # noqa: BLE001
                    continue
                if isinstance(v, dict):
                    for k2 in sorted(v):
                        vv = v[k2]
                        if isinstance(vv, str) and _HEXF.fullmatch(vv.strip()):
                            add(_hex2rgb(vv), nm + "." + str(k2), rel)
                if (isinstance(v, (list, tuple)) and len(v) == 3
                        and all(isinstance(x, int) and 0 <= x <= 255 for x in v)):
                    add(list(v), nm, rel)

    scan_assigns(os.path.join(ROOT, "backend", "recognizer", "standard.py"),
                 "recognizer/standard.py", "STYLE_DEFAULT")
    scan_assigns(os.path.join(ROOT, "backend", "modeling", "glb_common.py"),
                 "modeling/glb_common.py", "C_")

    # 剩下的 hex：楼梯/柱/楼板/场地这些散在各模块里的常量
    files = []
    for d in ("backend/modeling", "backend/recognizer",
              "backend/recognizer/profiles"):
        p = os.path.join(ROOT, *d.split("/"))
        if os.path.isdir(p):
            files += [os.path.join(p, fn) for fn in sorted(os.listdir(p))
                      if fn.endswith(".py")]
    for fp in files:
        rel = os.path.relpath(fp, ROOT).replace("\\", "/")
        txt = io.open(fp, encoding="utf-8", errors="replace").read()
        for i, ln in enumerate(txt.split("\n"), 1):
            if ln.lstrip().startswith("#"):
                continue
            for m in _HEXF.finditer(ln):
                add(_hex2rgb("#" + m.group(1)), "hex", "%s:%d" % (rel, i))
    return out


def _lin_to_srgb_arr(c):
    x = c.astype(np.float64) / 255.0
    y = np.where(x <= 0.0031308, x * 12.92,
                 1.055 * np.power(np.maximum(x, 1e-12), 1 / 2.4) - 0.055)
    return np.clip(np.round(y * 255.0), 0, 255).astype(np.int64)


def _srgb_to_lin_arr(c):
    x = c.astype(np.float64) / 255.0
    y = np.where(x <= 0.04045, x / 12.92,
                 np.power((x + 0.055) / 1.055, 2.4))
    return np.clip(np.round(y * 255.0), 0, 255).astype(np.int64)


# 渲染用色（只是给消隐图看的，与被测颜色无关）。键 = 名字最后一段（facade/inner/...）
PALETTE = {
    "facade": (160, 30, 30), "inner": (250, 250, 250), "glass": (0, 90, 255),
    "frame": (250, 200, 0), "roof": (60, 60, 60), "stair": (0, 180, 0),
    "door": (255, 120, 0), "column": (160, 0, 200), "slab": (170, 170, 170),
    "parapet": (90, 60, 40), "wall": (120, 40, 40), "?": (120, 120, 120),
}


def _draw_col(nm):
    return PALETTE.get(str(nm).split(".")[-1], PALETTE["?"])
# GL 的 componentType 是 glTF 枚举值，不是 numpy 的 typestr
_CT = {5120: np.int8, 5121: np.uint8, 5122: np.int16,
       5123: np.uint16, 5125: np.uint32, 5126: np.float32}
_NC = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4}


# ---------------------------------------------------------------- 读 GLB
def load_glb(path):
    """直接解 GLB（不走 trimesh）。返回 dict(v, f, col, attrs, note)。"""
    b = io.open(path, "rb").read()
    if b[:4] != b"glTF":
        raise ValueError("不是 GLB: %s" % path)
    off, j, bin_ = 12, None, None
    while off < len(b):
        clen, ctype = struct.unpack_from("<II", b, off)
        off += 8
        ch = b[off:off + clen]
        off += clen
        if ctype == 0x4E4F534A:
            j = json.loads(ch.decode("utf-8"))
        elif ctype == 0x004E4942:
            bin_ = ch

    def acc(i):
        a = j["accessors"][i]
        bv = j["bufferViews"][a["bufferView"]]
        dt = np.dtype(_CT[int(a["componentType"])]).newbyteorder("<")
        n = _NC[a["type"]]
        st = bv.get("byteStride") or dt.itemsize * n
        base = bv.get("byteOffset", 0) + a.get("byteOffset", 0)
        buf = np.frombuffer(bin_, dtype=np.uint8)
        if st == dt.itemsize * n:
            out = np.frombuffer(bin_, dtype=dt, count=a["count"] * n, offset=base)
        else:                       # 交错缓冲：逐条搬
            idx = (np.arange(a["count"])[:, None] * st
                   + np.arange(n)[None, :] * dt.itemsize) + base
            out = buf[idx].copy().view(dt).reshape(a["count"], n)
        return out.reshape(a["count"], n)

    prims = j["meshes"][0]["primitives"]
    v, col, f, base, al = [], [], [], 0, []
    for pr in prims:
        a = pr["attributes"]
        p = acc(a["POSITION"]).astype(np.float64)
        v.append(p)
        if "COLOR_0" in a:
            cc = acc(a["COLOR_0"])
            col.append(cc[:, :3].astype(np.int64))
            if cc.shape[1] >= 4:
                al.append(cc[:, 3].astype(np.int64))
            else:
                al.append(np.full(len(cc), 255, dtype=np.int64))
        else:
            col.append(None)
            al.append(np.zeros(0, dtype=np.int64))
        if "indices" in pr:
            ix = acc(pr["indices"]).astype(np.int64).ravel() + base
        else:
            ix = np.arange(len(p), dtype=np.int64) + base
        f.append(ix.reshape(-1, 3))
        base += len(p)
    v = np.vstack(v)
    f = np.vstack(f)
    cl = np.vstack([c for c in col if c is not None]) if any(
        c is not None for c in col) else None
    attrs = sorted(set().union(*[set(pr["attributes"]) for pr in prims]))
    al = np.concatenate(al) if al else None
    return {"v": v, "f": f, "col": cl, "alpha": al, "attrs": attrs,
            "n_prim": len(prims), "n_mat": len(j.get("materials", []))}


# ---------------------------------------------------------------- 小工具
def _areas(v, f):
    e1 = v[f[:, 1]] - v[f[:, 0]]
    e2 = v[f[:, 2]] - v[f[:, 0]]
    return 0.5 * np.linalg.norm(np.cross(e1, e2), axis=1)


def _edges(v, f):
    return np.stack([np.linalg.norm(v[f[:, 1]] - v[f[:, 0]], axis=1),
                     np.linalg.norm(v[f[:, 2]] - v[f[:, 1]], axis=1),
                     np.linalg.norm(v[f[:, 0]] - v[f[:, 2]], axis=1)], axis=1)


def _cls(col, ref):
    """ref = [(rgb, 名字, 出处)]。返回 (最近的名字, L1 距离)。"""
    names = [p[1] for p in ref]
    r = np.array([p[0] for p in ref], dtype=np.int64)
    d = np.abs(col[:, None, :].astype(np.int64) - r[None, :, :]).sum(axis=2)
    return np.array(names, dtype=object)[d.argmin(axis=1)], d.min(axis=1)


def _mode(arr):
    if len(arr) == 0:
        return "?"
    n, c = np.unique(arr, return_counts=True)
    return "%s(%d%%)" % (n[c.argmax()], 100 * c.max() // len(arr))


def _bbox(v, f, sel):
    t = v[f[sel]]
    return (t[:, :, 0].min(), t[:, :, 0].max(),
            t[:, :, 1].min(), t[:, :, 1].max(),
            t[:, :, 2].min(), t[:, :, 2].max())


def _row(sz, bb, extra):
    return ("     %7d 面  x[%7.2f,%7.2f] y[%7.2f,%7.2f] z[%7.2f,%7.2f]  %s"
            % ((sz,) + bb + (extra,)))


# ---------------------------------------------------------------- 各节
def sec_a(g, L):
    v, f = g["v"], g["f"]
    L.append("A. 基本量")
    L.append("   文件 %.1f MB   primitive %d   material %d"
             % (g["size"] / 1e6, g["n_prim"], g["n_mat"]))
    L.append("   ★ 属性清单: %s" % (", ".join(g["attrs"]) or "（空）"))
    if "NORMAL" not in g["attrs"]:
        L.append("     ⇒ **没有 NORMAL**：光照完全由缠绕方向决定，"
                 "缠绕反了的面会渲染成暗面/被背面剔除")
    L.append("   顶点 %d   三角面 %d   顶点共享比 %.3f:1（3.0:1 = 完全不共享）"
             % (len(v), len(f), 3.0 * len(f) / max(len(v), 1)))
    mn, mx = v.min(axis=0), v.max(axis=0)
    L.append("   bbox  x[%.2f, %.2f]  y[%.2f, %.2f]  z[%.2f, %.2f]   尺寸 %.2fx%.2fx%.2f m"
             % (mn[0], mx[0], mn[1], mx[1], mn[2], mx[2],
                mx[0] - mn[0], mx[1] - mn[1], mx[2] - mn[2]))
    L.append("   含 NaN 的顶点: %d" % int(np.isnan(v).any(axis=1).sum()))
    if g.get("alpha") is not None and len(g["alpha"]):
        aL = g["alpha"]
        L.append("   COLOR_0 alpha: min %d  max %d  （255 = 不透明 ⇒ "
                 "「看穿」不是透明度造成的）" % (int(aL.min()), int(aL.max())))
    else:
        L.append("   COLOR_0 alpha: —— 没有 alpha 通道 ——")

    if g["col"] is None:
        L.append("   ★★ COLOR_0 读不到 —— 下面所有颜色结论**不成立**（不兜底）")
        g["cls"] = np.full(len(f), "?", dtype=object)
        return L

    pal = g["pal"]
    pal_s = np.array([p[0] for p in pal], dtype=np.int64)
    pal_l = _srgb_to_lin_arr(pal_s)
    keys = (g["col"][:, 0] << 16) | (g["col"][:, 1] << 8) | g["col"][:, 2]
    uq, ct = np.unique(keys, return_counts=True)
    obs = np.stack([(uq >> 16) & 255, (uq >> 8) & 255, uq & 255], axis=1)
    obs_s = _lin_to_srgb_arr(obs)
    # 空间判定用**逐位精确命中数**，不用误差和 —— 命中数是能复核的整数
    ok_l = (np.abs(obs[:, None, :] - pal_l[None, :, :]).sum(axis=2) == 0).any(axis=1)
    ok_s = (np.abs(obs_s[:, None, :] - pal_s[None, :, :]).sum(axis=2) == 0).any(axis=1)
    use_srgb = int(ok_s.sum()) > int(ok_l.sum())
    L.append("   颜色空间判定: 与仓库调色板**逐位精确命中**的颜色数 —— "
             "存盘值按线性解释 %d/%d，按 sRGB 解释 %d/%d ⇒ 按 **%s** 解释"
             % (int(ok_l.sum()), len(obs), int(ok_s.sum()), len(obs),
                "sRGB" if use_srgb else "线性"))
    g["use_srgb"] = use_srgb
    # 只拿「本楼 style」与「glb_common 兜底常量」当归类表 —— 别的楼的 profile hex 不参与，
    # 否则最近邻会挑到隔壁楼的颜色，屏幕上是一张看着很细、其实无意义的表
    CORE = [p for p in pal if p[1].startswith(("style.", "glb_common.", "C_",
                                              "STYLE_DEFAULT."))]
    # ★ 归类要在**存盘值那个空间**里做：表是 sRGB，fcol 是存盘值 ⇒ 换算表，不换算 fcol
    CORE_SP = CORE if use_srgb else [
        (_srgb_to_lin_arr(np.array(p[0], dtype=np.int64)[None, :])[0].tolist(),
         p[1], p[2]) for p in CORE]

    space = pal_s if use_srgb else pal_l      # 与存盘值同空间的调色板

    def exact(st):
        return np.nonzero(np.abs(space - st).sum(axis=1) == 0)[0]

    L.append("")
    L.append("   实际出现的 %d 种颜色（顶点数 / 存盘值 / 当线性解释的 sRGB / 名字）:"
             % len(uq))
    o = np.argsort(-ct)
    n_undef = 0
    for i in o:
        st, sr = obs[i], obs_s[i]
        hit = exact(st)
        if len(hit):
            nm = "%s  (%s)" % (pal[int(hit[0])][1], pal[int(hit[0])][2])
        else:
            nm = "★★ 仓库里没有定义"
            n_undef += 1
        L.append("     %8d v  (%3d,%3d,%3d) → sRGB(%3d,%3d,%3d)  %s"
                 % (ct[i], st[0], st[1], st[2], sr[0], sr[1], sr[2], nm))
    L.append("   ★ 其中仓库里没有定义的: %d 种（分母 %d）" % (n_undef, len(uq)))

    L.append("")
    L.append("   ★ 配置里写了、但本模型**一个顶点都没用到**的颜色"
             "（兜底常量没被走到 / 两套调色板分叉）:")
    n_dead = 0
    for p in CORE:
        q = np.array(p[0], dtype=np.int64)
        q = q if use_srgb else _srgb_to_lin_arr(q[None, :])[0]
        # 在**观测**空间里数，不是调色板空间 —— exact() 给的是调色板下标，
        # 拿它去索引 ct（按颜色种类计数的表）是两把尺子混用，会 IndexError 或静默错位
        cnt = int(ct[(np.abs(obs - q).sum(axis=1) == 0)].sum())
        if cnt == 0:
            n_dead += 1
            L.append("     %-26s %s  0 个顶点   %s"
                     % (p[1], "#%02x%02x%02x" % tuple(p[0]), p[2]))
    if n_dead == 0:
        L.append("     （无）")
    L.append("     ⇒ 配置项 %d 个，未走到 %d 个（分母就是这一行）" % (len(CORE), n_dead))

    # fcol 是**存盘值**的三顶点均值，与 `space` 同空间 ⇒ 两个分支都不要换算（换算过会全错）
    fcol = np.clip(np.round(g["col"][f].mean(axis=1)), 0, 255).astype(np.int64)
    cls, err = _cls(fcol, CORE_SP)
    g["cls"] = cls
    g["err"] = err
    a = _areas(v, f)
    L.append("")
    L.append("   颜色族（按**上面这张配置表**最近邻归类；面数 / 面积 m2 / 高度范围）:")
    for nm in sorted(set(cls), key=lambda x: -int((cls == x).sum())):
        s = cls == nm
        y = v[f[s]][:, :, 1]
        L.append("     %-22s %8d 面 %11.1f m2   y[%6.2f, %6.2f]"
                 % (nm, int(s.sum()), a[s].sum(), y.min(), y.max()))
    bad = int((err > 12).sum())
    L.append("   ★ 对不上这张表的面的最近距离 L1>12 的: %d (%.3f%%)  ⇒ "
             "非零就意味着还有第三种颜色来源" % (bad, 100.0 * bad / len(f)))
    return L


def sec_bc(g, L):
    v, f = g["v"], g["f"]
    a = _areas(v, f)
    e = _edges(v, f)
    emin, emax = e.min(axis=1), e.max(axis=1)
    L.append("")
    L.append("B. 退化面（面积 < 1e-9 m2 = 零面积）")
    z = a < 1e-9
    L.append("   个数 %d (%.3f%%)" % (int(z.sum()), 100.0 * z.mean()))
    L.append("")
    L.append("C. 针状面：最短边 < 1cm 且 最长边 > 8m —— 正面看是一条 1px 线")
    s = (emin < 0.01) & (emax > 8.0)
    L.append("   个数 %d (%.3f%%)   合计面积 %.4f m2 ⇒ 面积可忽略，长度是楼级的"
             % (int(s.sum()), 100.0 * s.mean(), a[s].sum()))
    if s.any():
        ys = v[f[s]][:, :, 1].mean(axis=1)
        L.append("   按高度分档（1 m 一档，只列非空）:")
        h = np.floor(ys).astype(int)
        line, buf = [], []
        for hh in sorted(set(h.tolist())):
            buf.append("y=%2d:%4d" % (hh, int((h == hh).sum())))
            if len(buf) == 8:
                line.append("     " + "  ".join(buf)); buf = []
        if buf:
            line.append("     " + "  ".join(buf))
        L.extend(line)
        L.append("   最长的 8 条（长度 / 高度 / 颜色族 / 沿哪根轴展开）:")
        fi = np.nonzero(s)[0][np.argsort(-emax[s])[:8]]
        for i in fi:
            t = v[f[i]]
            rng = t.max(axis=0) - t.min(axis=0)
            ax = "xyz"[int(rng.argmax())]
            L.append("     %7.2f m  y=%6.2f  %s 从 %7.2f 到 %7.2f   色 %s"
                     % (emax[i], t[:, 1].mean(), ax, t[:, "xyz".index(ax)].min(),
                        t[:, "xyz".index(ax)].max(), g["cls"][i]))
        big = s & (a > 1.0)
        L.append("   ★ 其中面积 >1 m2 的（不是细线，是薄板）: %d 个, 合计 %.2f m2"
                 % (int(big.sum()), a[big].sum()))
        # 针面到底是「竖着的薄片」还是「横着的薄片」—— 这决定它长什么样
        rng = v[f[s]].max(axis=1) - v[f[s]].min(axis=1)
        ax = rng.argmax(axis=1)
        L.append("   按展开轴统计（分母 %d）: %s" % (
            int(s.sum()),
            "  ".join("%s:%d" % ("xyz"[k], int((ax == k).sum())) for k in range(3))))
        thin = rng.min(axis=1)
        L.append("   最薄方向厚度: 中位 %.4f m  最大 %.4f m  （>0.05 m 的 %d 个）"
                 % (float(np.median(thin)), float(thin.max()),
                    int((thin > 0.05).sum())))
        horiz = np.abs(rng[:, 1]) < 1e-6
        vert = (np.abs(rng[:, 0]) < 1e-6) & (np.abs(rng[:, 2]) < 1e-6)
        L.append("   ★ 针面里：完全**水平**的（三点同高）%d 个、完全**竖直**的 %d 个"
                 % (int(horiz.sum()), int(vert.sum())))
    return L


def sec_d(g, L):
    """D. 连通块。顶点按位置合并后，**由 f 反查顶点→面**建邻接。

    不能用 `顶点号 // 3` 当面孔号 —— 那只在完全不共享顶点的网格上成立
    （见文件头第 2 条）。
    """
    v, f = g["v"], g["f"]
    q = np.round(v / 1e-4).astype(np.int64)
    _, vid = np.unique(q, axis=0, return_inverse=True)
    vid = np.asarray(vid).ravel()
    L.append("")
    L.append("D. 连通块（顶点按 1e-4 m 合并后）")
    L.append("   合并后顶点 %d （原 %d，比值 %.2f）" % (vid.max() + 1, len(v),
                                                len(v) / (vid.max() + 1)))

    fv = vid[f]                                     # (m,3) 每面的三个合并后顶点号
    flat_v = fv.ravel()
    flat_f = np.repeat(np.arange(len(f)), 3)
    o = np.argsort(flat_v, kind="stable")
    sv, sf = flat_v[o], flat_f[o]
    grp = np.split(sf, np.flatnonzero(np.diff(sv)) + 1)
    rows, cols = [], []
    for u in grp:
        if len(u) < 2:
            continue
        uu = np.unique(u)
        if len(uu) < 2:
            continue
        # 星形连接（都连到 uu[0]）：连通分量完全等价，且避免 O(k^2)
        rows.append(np.full(len(uu) - 1, uu[0])); cols.append(uu[1:])
    if not rows:
        L.append("   无邻接 —— 每个面孤立，这本身就是异常")
        return L
    import scipy.sparse as sp
    from scipy.sparse.csgraph import connected_components
    r, c = np.concatenate(rows), np.concatenate(cols)
    A = sp.coo_matrix((np.ones(len(r), dtype=np.int8), (r, c)),
                      shape=(len(f), len(f)))
    ncomp, lab = connected_components(A, directed=False)
    sizes = np.bincount(lab)
    g["lab"] = lab
    g["sizes"] = sizes
    L.append("   ★ 块数 %d（1 = 整体连通；大数 = 有大量游离几何）" % ncomp)
    L.append("   块大小分布: >=1000 面 %d 块; 100~999 %d; 20~99 %d; 5~19 %d; <5 %d"
             % tuple(int(((sizes >= a) & (sizes <= b)).sum())
                     for a, b in ((1000, 10 ** 9), (100, 999), (20, 99), (5, 19), (0, 4))))
    L.append("   最大的 6 块:")
    for k in np.argsort(-sizes)[:6]:
        sel = lab == k
        L.append(_row(sizes[k], _bbox(v, f, sel), "主色 " + _mode(g["cls"][sel])))
    rest = np.argsort(-sizes)[6:]
    small = [k for k in rest if sizes[k] < 20]
    L.append("   ★ 其余 %d 块：其中面数<20 的 %d 块、>=20 的 %d 块"
             % (len(rest), len(small), len(rest) - len(small)))
    if small:
        ssv = np.array([sizes[k] for k in small])
        L.append("     小块的体积分布（面数）: 1 面 %d 块, 2 面 %d, 3~5 面 %d, 6~19 面 %d"
                 % tuple(int(((ssv >= a) & (ssv <= b)).sum())
                         for a, b in ((1, 1), (2, 2), (3, 5), (6, 19))))
    L.append("   ★ 面数 >=20 且 bbox 跨度 >8 m 的块（细长/大跨度 = 悬空板或细线）:")
    n_big = 0
    for k in rest:
        if sizes[k] < 20:
            continue
        bb = _bbox(v, f, lab == k)
        span = max(bb[1] - bb[0], bb[3] - bb[2], bb[5] - bb[4])
        if span > 8.0:
            n_big += 1
            if n_big <= 25:
                L.append(_row(sizes[k], bb, "跨度 %.1f m  主色 %s"
                              % (span, _mode(g["cls"][lab == k]))))
    L.append("     合计 %d 块" % n_big)
    return L


# ---------------------------------------------------------------- E 消隐
def sec_e(g, L, views):
    """画家算法消隐 → 洋红背景里**不接触画面边缘**的连通块 = 视线穿过去了。

    ★ 只问「这一像素有没有被任何面盖住」，**不依赖缠绕方向**，也不依赖深度排序
      正确（每个面都会填像素，顺序错了也照样填）。所以"洋红"就是"真的没有面"。
    """
    from PIL import Image, ImageDraw
    v, f = g["v"], g["f"]
    W = 900
    VS = {"南 front": (0, 1, 2, -1.0), "北 back": (0, 1, 2, +1.0),
          "西 left": (2, 1, 0, -1.0), "东 right": (2, 1, 0, +1.0)}
    use = list(VS)[:views] if views else list(VS)
    cls = g["cls"]
    for nm in use:
        ax, ay, ad, sgn = VS[nm]
        p = v[:, [ax, ay]]
        lo, hi = p.min(axis=0), p.max(axis=0)
        pad = np.maximum(hi - lo, 1e-6) * 0.02
        lo, hi = lo - pad, hi + pad
        H = int(round(W * (hi[1] - lo[1]) / (hi[0] - lo[0])))
        sc = np.array([(W - 1) / (hi[0] - lo[0]), (H - 1) / (hi[1] - lo[1])])
        px = np.empty((len(p), 2))
        px[:, 0] = (p[:, 0] - lo[0]) * sc[0]
        px[:, 1] = (hi[1] - p[:, 1]) * sc[1]        # 行朝下、y 朝上 ⇒ 翻一次
        order = np.argsort((v[:, ad] * sgn)[f].mean(axis=1))
        im = Image.new("RGB", (W, H), (255, 0, 255))
        dr = ImageDraw.Draw(im)
        for i in order:
            t = f[i]
            dr.polygon([tuple(px[t[0]]), tuple(px[t[1]]), tuple(px[t[2]])],
                       fill=_draw_col(cls[i]))
        arr = np.asarray(im)
        bg = (arr[:, :, 0] > 200) & (arr[:, :, 1] < 60) & (arr[:, :, 2] > 200)
        lab, n = _label(bg)
        ca, cb = "xyz"[ax], "xyz"[ay]
        hs = []
        if n:
            bd = (set(lab[0, :].tolist()) | set(lab[-1, :].tolist())
                  | set(lab[:, 0].tolist()) | set(lab[:, -1].tolist()))
            bd.discard(0)
            for k in range(1, n + 1):
                if k in bd:
                    continue
                ys, xs = np.nonzero(lab == k)
                if len(ys) < 4:
                    continue
                hs.append((int(len(ys)), lo[0] + xs.min() / sc[0], lo[0] + xs.max() / sc[0],
                           hi[1] - ys.max() / sc[1], hi[1] - ys.min() / sc[1]))
        hs.sort(reverse=True)
        ys_ = [h[3] for h in hs] + [h[4] for h in hs]
        L.append("")
        L.append("E. %-9s 栅格 %dx%d  背景块 %3d  不接触边缘的 %d 个%s"
                 % (nm, W, H, n, len(hs),
                    ("  全部落在 y[%.2f, %.2f]" % (min(ys_), max(ys_))) if hs else ""))
        for npx, x0, x1, y0, y1 in hs[:20]:
            L.append("   ★ %6d px   %s[%7.2f, %7.2f]  %s[%7.2f, %7.2f]"
                     % (npx, ca, x0, x1, cb, y0, y1))
        if len(hs) > 20:
            L.append("   …… 还有 %d 个未列" % (len(hs) - 20))
        # ★ 判据（数字推出来的，不是写死的字符串 —— 铁律 44）
        m2px = 1.0 / (sc[0] * sc[1])
        tot_px = sum(h[0] for h in hs)
        tot_m2 = tot_px * m2px
        big = [h for h in hs if h[0] * m2px >= 0.05]
        L.append("   ⇒ 屏幕上的看穿面积 %d px = %.2f m2（1 px = %.4f m2）；"
                 "其中 >=0.05 m2 的 %d 块，最大 %.2f m2"
                 % (tot_px, tot_m2, m2px, len(big),
                    max([h[0] * m2px for h in hs]) if hs else 0.0))
        if hs:
            ylo = min(h[3] for h in hs)
            yhi = max(h[4] for h in hs)
            L.append("   ⇒ 这些块的高度范围 y[%.2f, %.2f]（厚 %.2f m），"
                     "**全部落在同一条高度带里** = 一圈水平缝，不是零散亮斑"
                     % (ylo, yhi, yhi - ylo))
        verdict = "看穿（有洞）" if tot_m2 >= 0.5 else "正常（<0.5 m2）"
        L.append("   ⇒ 判词: **%s**  [阈值 0.5 m2，读的是上面那个 %.2f]" % (verdict, tot_m2))
        g.setdefault("see", []).append((nm, tot_m2, len(hs)))
        Image.fromarray(arr).save(os.path.join(
            ROOT, "_scratch", "_glb_probe_%s_%s.png" % (g["name"], nm.split()[0])))
    return L


def _label(mask):
    try:
        from scipy import ndimage
        return ndimage.label(mask)
    except Exception:                                              # noqa: BLE001
        h, w = mask.shape                                    # 缺 scipy 也要能数
        lab = np.zeros((h, w), dtype=np.int32)
        cur = 0
        for i in range(h):
            for jj in range(w):
                if not mask[i, jj] or lab[i, jj]:
                    continue
                cur += 1
                st = [(i, jj)]
                lab[i, jj] = cur
                while st:
                    y, x = st.pop()
                    for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                        yy, xx = y + dy, x + dx
                        if 0 <= yy < h and 0 <= xx < w and mask[yy, xx] and not lab[yy, xx]:
                            lab[yy, xx] = cur
                            st.append((yy, xx))
        return lab, cur


# ---------------------------------------------------------------- G 分带
def sec_g(g, L):
    """G. 逐高度分带 —— 空带就是缺了一层。E 是投影法、这是普查法，两条独立的路。"""
    v, f = g["v"], g["f"]
    a = _areas(v, f)
    cen = v[f].mean(axis=1)
    H = v[:, 1].max()
    step = 0.5
    nb = int(np.ceil(H / step))
    idx = np.clip((cen[:, 1] / step).astype(int), 0, nb - 1)
    L.append("")
    L.append("G. 逐 %.1f m 分带（面**按重心**归带）—— 面积为 0 的带就是那一层没有几何"
             % step)
    L.append("    带       面数      面积 m2   x 跨度            z 跨度            主色")
    for k in range(nb):
        s = idx == k
        y0 = k * step
        if not s.any():
            L.append("   %5.1f-%5.1f      0         0.0   —— 空带 ——" % (y0, y0 + step))
            continue
        bb = _bbox(v, f, s)
        L.append("   %5.1f-%5.1f %6d %11.1f   x[%7.2f,%7.2f] z[%7.2f,%7.2f]  %s"
                 % (y0, y0 + step, int(s.sum()), a[s].sum(), bb[0], bb[1], bb[4],
                    bb[5], _mode(g["cls"][s])))
    return L


def sec_h(g, L, step=0.05):
    """H. 薄层求交普查 —— 层厚 step，凡 [ymin,ymax] **与该层相交**的面都算。

    ★ 与 G 的区别：G 按**重心**归 0.5 m 带，一条跨 3.3 m 的墙整个被算进它重心那一带；
      H 问的是「**这个高度上到底有没有面**」，于是任何缝都跑不掉。
      E 看不了一个面都没有的缝（它滤掉 <4 px ≈ 0.6 m），H 能看见 step 那么厚的缝。
    缝的两种含义（读的时候要分开）：
      · 体量没接上（墙只到这里、上面那块从别处起）⇒ 缺陷；
      · 只有水平板、没有侧壁的位置（板自己的厚度里没有侧面）⇒ 正常。
    所以 H **同时**印每层的面积，面积掉到接近 0 才是缺陷的指纹。
    """
    v, f = g["v"], g["f"]
    t = v[f]
    ymin = t[:, :, 1].min(axis=1)
    ymax = t[:, :, 1].max(axis=1)
    a = _areas(v, f)
    H = float(v[:, 1].max())
    nb = int(np.ceil(H / step))
    edges = np.arange(nb + 1) * step
    hit = np.zeros(nb, dtype=np.int64)
    ar = np.zeros(nb)
    for k in range(nb):
        s = (ymin <= edges[k + 1]) & (ymax >= edges[k])
        hit[k] = int(s.sum())
        ar[k] = float(a[s].sum()) if s.any() else 0.0
    runs, i = [], 0
    while i < nb:
        if hit[i] == 0:
            j = i
            while j + 1 < nb and hit[j + 1] == 0:
                j += 1
            runs.append((i, j))
            i = j + 1
        else:
            i += 1
    L.append("")
    L.append("H. 薄层求交普查（层厚 %.2f m，**相交**即算，不看重心）" % step)
    L.append("   总层数 %d   有面的 %d   一个面都没有的 %d (%.1f%%)"
             % (nb, int((hit > 0).sum()), int((hit == 0).sum()),
                100.0 * (hit == 0).mean()))
    L.append("   ★ 连续空段 %d 处（这一段高度上，全模型无论哪里都没有面）:" % len(runs))
    for i0, j0 in runs:
        L.append("     y[%6.2f, %6.2f]  厚 %5.2f m （%d 层）"
                 % (edges[i0], edges[j0 + 1], edges[j0 + 1] - edges[i0], j0 - i0 + 1))
    if not runs:
        L.append("     （无）")
    pos = np.nonzero(hit > 0)[0]
    L.append("   面积最小的 8 个「有面层」—— 近乎只有一条线横穿（分母 %d）:" % len(pos))
    for k in pos[np.argsort(ar[pos])[:8]]:
        L.append("     y[%6.2f, %6.2f]  %7d 面 %10.2f m2"
                 % (edges[k], edges[k + 1], hit[k], ar[k]))
    L.append("   ★★ 这一节是**全局**判据：它问「有没有一个高度，整个模型哪儿都没有面」。"
             "对任何真楼这个答案都是「没有」⇒ 它**答不了「局部缝」**"
             "（塔楼外墙上一条 0.2 m 的缝，会被同高度的板/内墙挡住视线而看不见）。"
             "局部缝看下一节 I。")
    return L


def sec_i(g, L, cell=0.5, maxgap=0.5, minov=0.5, minsz=50):
    """I. 组件间隙普查 —— 两个**本该接上**的块之间那条缝。

    判据（三个条件同时成立才算一条缝）：
      · 三轴里**恰好一轴**是分开的，间距 sep ∈ (0, maxgap]；
      · 另两轴的重叠 ov > minov（缝得是一条「带」，不是一个点）；
      · 两块都 >= minsz 面（小碎块单独在别处数，混进来会把噪声当缝）。

    ★ 为什么用「组件」而不是「逐柱有没有面」：楼里的**楼层之间天然是空的**
      （只有板、没有侧壁），所以「某高度没有面」在楼内到处都是，逐柱判据全是假阳性。
      而组件相邻性问的是「这两块**故意分开**还是一处漏了」—— 量纲对得上。
    """
    if "lab" not in g:
        L.append("")
        L.append("I. 组件间隙普查：D 节没跑起来（没有 lab），本节跳过 —— 这不是「没有缝」")
        return L
    v, f = g["v"], g["f"]
    lab, sizes = g["lab"], g["sizes"]
    keep = np.nonzero(sizes >= minsz)[0]
    if len(keep) < 2:
        L.append("")
        L.append("I. 组件间隙普查：>=%d 面的块只有 %d 个，凑不成对 ⇒ 本节不适用" % (minsz, len(keep)))
        return L
    bb = np.empty((len(keep), 6))
    for i, k in enumerate(keep):
        bb[i] = _bbox(v, f, lab == k)
    L.append("")
    L.append("I. 组件间隙普查（只拿 >=%d 面的块，%d 个；更小的碎块在 D 节数）"
             % (minsz, len(keep)))
    lo, hi = bb[:, [0, 2, 4]], bb[:, [1, 3, 5]]
    found = []
    n = len(keep)
    for i in range(n):
        if i + 1 >= n:
            break
        a_lo, a_hi = lo[i], hi[i]
        b_lo, b_hi = lo[i + 1:], hi[i + 1:]
        sep = np.maximum(0.0, np.maximum(a_lo, b_lo) - np.minimum(a_hi, b_hi))
        ov = np.minimum(a_hi, b_hi) - np.maximum(a_lo, b_lo)
        nsep = ((sep > 0) & (sep <= maxgap)).sum(axis=1)
        ok = (nsep == 1)
        for j in np.nonzero(ok)[0]:
            other = [k for k in range(3) if sep[j][k] <= 0
                     or sep[j][k] > maxgap]
            if len(other) != 2:
                continue
            if min(ov[j][other[0]], ov[j][other[1]]) < minov:
                continue
            found.append((float(sep[j].max()), float(ov[j][other[0]] * ov[j][other[1]]),
                          int(sizes[keep[i]]), int(sizes[keep[i + 1 + j]]),
                          [round(float(x), 2) for x in bb[i]],
                          [round(float(x), 2) for x in bb[i + 1 + j]]))
    found.sort(key=lambda r: -r[1])
    L.append("   ★ 成对的「带缝」相邻块: %d 对（分母 = %d 对候选）"
             % (len(found), n * (n - 1) // 2))
    if found:
        seps = np.array([r[0] for r in found])
        L.append("   缝宽分布: 中位 %.3f m  最小 %.3f  最大 %.3f；"
                 "其中最窄的 8 条（最像「差一点点没接上」）:"
                 % (float(np.median(seps)), float(seps.min()), float(seps.max())))
        for r in sorted(found, key=lambda r: r[0])[:8]:
            L.append("     缝 %.3f m  重叠面积 %8.2f m2  面数 %d / %d"
                     % (r[0], r[1], r[2], r[3]))
            L.append("       A x%s y%s z%s" % (r[4][0:2], r[4][2:4], r[4][4:6]))
            L.append("       B x%s y%s z%s" % (r[5][0:2], r[5][2:4], r[5][4:6]))
        L.append("   ★ 缝宽**扎堆在同一个值**（而重叠面积很大）= 系统性留缝，"
                 "不是随机误差 —— 那是一个可修的生成参数")
    else:
        L.append("      （无）")
    return L


def main():
    name = sys.argv[1] if len(sys.argv) > 1 else "c006"
    views = 4
    if "--views" in sys.argv:
        views = int(sys.argv[sys.argv.index("--views") + 1])
    bd = os.path.join(ROOT, "data", "buildings", name)
    path = os.path.join(bd, "%s-building.glb" % name)
    g = load_glb(path)
    g["name"] = name
    g["size"] = os.path.getsize(path)
    g["pal"] = load_palette(name)
    L = ["# GLB 几何探针 — %s   （只读；只列事实，不下结论）" % name, ""]
    L.append("调色板来源: 从仓库读 %d 色（本楼 profile.style 优先，其次 STYLE_DEFAULT，"
             "其次 glb_common 的 C_*，最后各模块里的 #hex）" % len(g["pal"]))
    sec_a(g, L)
    sec_bc(g, L)
    sec_d(g, L)
    sec_e(g, L, views)
    sec_g(g, L)
    sec_h(g, L)
    sec_i(g, L)
    # 收尾汇总：把有两义的判据放在一起，方便一眼看完（数字来自上面各节，不重算）
    if g.get("see"):
        L.append("")
        L.append("汇总 · 看穿（E 节，阈值 0.5 m2/视角）:")
        for nm, m2, nb in g["see"]:
            L.append("   %-9s %.2f m2  %d 块  %s"
                     % (nm, m2, nb, "看穿" if m2 >= 0.5 else "正常"))
    out = os.path.join(ROOT, "_scratch", "_glb_probe_%s.txt" % name)
    io.open(out, "w", encoding="utf-8").write("\n".join(L) + "\n")
    print("wrote %s  (%d lines)" % (out, len(L)))


if __name__ == "__main__":
    main()
