# -*- coding: utf-8 -*-
r"""照片比对 —— 拿 **2024 航拍 DSM** 当独立证据，量三维出件的平面落位与高度。

为什么要有它（用户 2026-10-19「尤其是缺用照片比对」）：
  现在所有判据都建立在**同一份 DXF** 上（源图 vs 轮廓）。DXF 与生成件同错时，闸全绿。
  DSM 由影像空三生成，**不经过 CAD**，是另一条链路的证据。本工具量三件事：
    ① 配准：模型平面足迹 vs DSM「高且平」屋面掩膜，旋转 + 全平移面搜索（FFT），
       给出转角、平移、IoU；
    ② 高度：配准后逐格 `DSM 高 − 模型顶面高 − δ`，报残差中位/P90 与超差占比；
    ③ 伪证：人为把模型挪 (dE,dN) 后重跑，搜索必须把它找回来，否则尺子不可信。
  ★ 不重写几何：模型来自 `06_su/contours`（与出件同一份），DSM 来自航测 GeoTIFF。
  ★ 模型与 DSM 落在**同一张 1 m 网格**上（同一个 E0/N0 锚点、同一窗口），
    2026-10-19 第一版各画各的再裁，结果是两套坐标互不认识、IoU 恒 0。

参数全在 `rebuild/构件库/参数.json::照片比对`（锚点、窗口、阈值、开关），改表不改码。
输出：`rebuild/_work/photo_<栋>.json`
用法：python -X utf8 -I rebuild/tools/compare_photo.py --bid c006
退出码：0 量到 · 2 参数/数据缺（未量到，不是通过） · 3 伪证失败（尺子不可信）

★ 盲区（铁律 158）：
  · DSM 是 **2024 年**航测；此后改扩建不在影像里。
  · 屋面掩膜按「高且平」取最大连通块；比主屋面低的小屋顶（楼梯间/机房）会漏在外面，
    模型侧却是**全楼足迹** ⇒ IoU 天然偏低。所以 IoU 只作粗筛，细判看边界距离与高度。
  · 树冠遮挡处 DSM 无真值；只统计配准重叠区。
  · 高度是**相对地面(5 分位)**的相对高，δ 由重叠区中位吸收，不标定绝对高程。
  · 平面负偏移的极限是锚点误差；转角由搜索给出时，四边近正方形的楼可能 90° 多解。
"""
from __future__ import annotations

import json
import math
import os
import sys

import numpy as np
import rasterio.features
from rasterio.enums import MergeAlg
from rasterio.transform import from_origin
from PIL import Image
from scipy import ndimage
from scipy.signal import fftconvolve
from shapely.geometry import Polygon

HERE = os.path.dirname(os.path.abspath(__file__))
CDUT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

import building as B                                                     # noqa: E402

PARAMS = os.path.join(CDUT, "rebuild", "构件库", "参数.json")
UP = 4                    # 栅格化倍率（4 ⇒ 0.25 m 画、1 m 汇总）


def load_params(bid):
    with open(PARAMS, encoding="utf-8") as fh:
        base = json.load(fh)
    ph = dict(base.get("照片比对") or {})
    per = (ph.get("楼栋") or {}).get(bid) or {}           # 锚点表就在 照片比对 下
    per = dict(per)
    per.update((base.get("楼栋") or {}).get(bid) or {})   # 顶层楼栋可覆盖同名键
    ph.update(per)
    ph["_per"] = per
    return base, ph


def _contours(root):
    d = os.path.join(root, "06_su", "contours")
    with open(os.path.join(d, "index.json"), encoding="utf-8") as fh:
        floors = json.load(fh)
    out = []
    for f in floors:
        p = os.path.join(d, f["floor"] + ".json")
        if not os.path.exists(p):
            continue
        with open(p, encoding="utf-8") as fh:
            j = json.load(fh)
        z0 = float(j.get("z0_m") or 0.0) * 1000.0
        out.append(dict(floor=f["floor"], z0=z0, polys=j["polys"]))
    return out


def _local_raster(conts, step_mm):
    """把模型画进**以它的平面 bbox 中心为原点**的方阵。返回 (z, 半宽_mm, 边长px)。

    ★ 2026-10-19：第一版以局部原点(0,0)为图心 ⇒ 模型与 DSM 差 +132 m，配准顶到窗口边。
      锚点 `E/N` 指的是**楼栋 bbox 中心**（与 gym3d sitecheck 的 plan_bbox 同一口径），
      不是绘图局部原点。z 为 mm 绝对顶标高，无实体处 = -1e6；重叠时高的赢。
    """
    from shapely.affinity import translate

    xs, ys = [], []
    for f in conts:
        for r in f["polys"]:
            for x, y in r["ring"]:
                xs.append(x)
                ys.append(y)
    if not xs:
        return None, 0.0, 0
    cx, cy = (min(xs) + max(xs)) / 2.0, (min(ys) + max(ys)) / 2.0
    half = max(max(xs) - cx, cx - min(xs), max(ys) - cy, cy - min(ys)) + 3000.0
    n = int(math.ceil(2 * half / step_mm))
    n += n % 2
    half = n * step_mm / 2.0
    tr = from_origin(-half, half, step_mm, step_mm)
    shapes = []
    for f in conts:
        for r in f["polys"]:
            try:
                g = translate(Polygon(r["ring"], r.get("holes") or []).buffer(0),
                              -cx, -cy)
            except Exception:                                            # noqa: BLE001
                continue
            if not g.is_empty:
                shapes.append((g, f["z0"] + float(r.get("z") or 0.0)))
    shapes.sort(key=lambda t: t[1])
    z = rasterio.features.rasterize(
        ((g, v) for g, v in shapes), out_shape=(n, n), transform=tr,
        fill=-1e6, dtype="float32", merge_alg=MergeAlg.replace)
    return z, half, n


def _reduce(z, n, up):
    m = n // up
    blk = z[: m * up, : m * up].reshape(m, up, m, up)
    out = blk.max(axis=(1, 3))
    out[out < -1e5] = -1e6          # 单位是 mm；填充是 -1e6
    return out, m


def dsm_grid(path, E0, N0, half_m, grid_m):
    """DSM → 窗口方阵（行向下 = N 减小，列向右 = E 增大）。"""
    import rasterio
    from rasterio.windows import from_bounds
    with rasterio.open(path) as ds:
        nod = float(ds.nodata) if ds.nodata is not None else -9999.0
        win = from_bounds(E0 - half_m, N0 - half_m, E0 + half_m, N0 + half_m,
                          ds.transform)
        a = ds.read(1, window=win, boundless=True, fill_value=nod).astype(np.float32)
        res = abs(ds.res[0])
    a = np.where(a <= nod + 1.0, np.nan, a)
    k = max(1, int(round(grid_m / res)))
    n0, n1 = (a.shape[0] // k) * k, (a.shape[1] // k) * k
    a = a[:n0, :n1].reshape(n0 // k, k, n1 // k, k)
    with np.errstate(all="ignore"):
        a = np.nanmedian(a, axis=(1, 3))
    return a


def roof_mask(H, min_h, flat_m):
    good = np.isfinite(H)
    ground = float(np.nanpercentile(H[good], 5.0)) if good.any() else 0.0
    hh = np.where(good, H - ground, np.nan)
    mx = ndimage.maximum_filter(np.nan_to_num(hh, nan=-999), size=3, mode="nearest")
    mn = ndimage.minimum_filter(np.nan_to_num(hh, nan=999), size=3, mode="nearest")
    D = good & (hh > min_h) & ((mx - mn) < flat_m)
    lab, nl = ndimage.label(D)
    if nl:
        sizes = ndimage.sum(D, lab, range(1, nl + 1))
        D = lab == (int(np.argmax(sizes)) + 1)
    return D, ground, hh


def _embed(a, G, fill):
    """把小方阵按**中心对齐**塞进 G×G。"""
    n = a.shape[0]
    out = np.full((G, G), fill, a.dtype)
    r0, c0 = (G - n) // 2, (G - n) // 2
    r1, c1 = min(G, r0 + n), min(G, c0 + n)
    out[r0:r1, c0:c1] = a[max(0, -r0):max(0, -r0) + (r1 - r0),
                          max(0, -c0):max(0, -c0) + (c1 - c0)]
    return out


def _iou_peak(M, D):
    """全平移面 IoU。返回 (峰值, drow, dcol)；drow>0=模型下移(N减)，dcol>0=右移(E增)。"""
    mf, df = M.astype(np.float32), D.astype(np.float32)
    inter = fftconvolve(mf, df[::-1, ::-1], mode="full")
    uni = mf.sum() + df.sum() - inter
    with np.errstate(invalid="ignore", divide="ignore"):
        S = np.where(uni > 0, inter / uni, 0.0)
    i, j = np.unravel_index(int(np.argmax(S)), S.shape)
    return float(S[i, j]), i - (M.shape[0] - 1), j - (M.shape[1] - 1)


def _rot_f(a, deg):
    """浮点阵列绕图心旋转；NaN 先换成哨兵再放回（PIL 的 F 模式不吃 NaN）。"""
    if deg % 360 == 0:
        return a.copy()
    sent = -1e6
    b = np.where(np.isfinite(a), a, sent).astype(np.float32)
    im = Image.fromarray(np.ascontiguousarray(b), "F")
    out = np.asarray(im.rotate(deg, resample=Image.NEAREST, expand=False))
    return np.where(out <= sent / 2, np.nan, out).astype(np.float64)


def _rot_mask(m, deg):
    im = Image.fromarray((m * 255).astype(np.uint8), "L")
    return np.asarray(im.rotate(deg, resample=Image.NEAREST, expand=False)) > 127


def _shiftf(a, dr, dc, fill=np.nan):
    out = np.full(a.shape, fill, a.dtype)
    h, w = a.shape
    ys0, ys1 = max(0, dr), min(h, h + dr)
    xs0, xs1 = max(0, dc), min(w, w + dc)
    if ys1 > ys0 and xs1 > xs0:
        out[ys0:ys1, xs0:xs1] = a[ys0 - dr:ys1 - dr, xs0 - dc:xs1 - dc]
    return out


def _boundary(m):
    return m & ~ndimage.binary_erosion(m, iterations=1)


def _conv(a, k):
    """全平移面求和（不归一，归一交给调用方按实际重叠格数做）。"""
    return fftconvolve(a.astype(np.float32),
                       k.astype(np.float32)[::-1, ::-1], mode="full")


def _shiftb(m, dr, dc):
    """布尔掩膜零填充平移；★ 不许用 np.roll —— 它是**环形**的，会把足迹绕到对面，
       伪证器因此把「人为挪 15 m」报成「找回 +247 m」（2026-10-19 实测）。"""
    out = np.zeros_like(m)
    h, w = m.shape
    ys0, ys1 = max(0, dr), min(h, h + dr)
    xs0, xs1 = max(0, dc), min(w, w + dc)
    if ys1 > ys0 and xs1 > xs0:
        out[ys0:ys1, xs0:xs1] = m[ys0 - dr:ys1 - dr, xs0 - dc:xs1 - dc]
    return out


def _f(x, nd=2):
    """非有限数 → None（铁律 123：nan 进 json.dump 会落成裸 NaN，别的语言读不回来）。"""
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return None if not math.isfinite(v) else round(v, nd)


def _shiftf(a, dr, dc, fill):
    """浮点阵列零填充平移（与 `_shiftb` 同口径；NaN 用 fill 顶住，平移后再放回）。"""
    out = np.full_like(a, fill)
    h, w = a.shape
    ys0, ys1 = max(0, dr), min(h, h + dr)
    xs0, xs1 = max(0, dc), min(w, w + dc)
    if ys1 > ys0 and xs1 > xs0:
        out[ys0:ys1, xs0:xs1] = a[ys0 - dr:ys1 - dr, xs0 - dc:xs1 - dc]
    return out


def run(bid, verbose=True, force_rot=None):
    base, ph = load_params(bid)
    if not ph.get("enabled", True):
        return dict(ok=False, why="参数.json::照片比对.enabled = false")
    if not ph.get("dsm") or not os.path.exists(ph["dsm"]):
        return dict(ok=False, why="DSM 不在：%s" % ph.get("dsm"))
    if "E" not in ph or "N" not in ph:
        return dict(ok=False, why="参数.json::楼栋 里没有 %s 的 E/N 锚点" % bid)

    root = B.root_for(bid)
    conts = _contours(root)
    if not conts:
        return dict(ok=False, why="没有轮廓（先跑 轮廓 步）")

    HALF = float(ph.get("窗口半宽_m") or 130.0)
    GRID = float(ph.get("网格_m") or 1.0)
    E0, N0 = float(ph["E"]), float(ph["N"])

    z, half, n = _local_raster(conts, GRID * 1000.0 / UP)
    if z is None:
        return dict(ok=False, why="模型轮廓为空")
    Zg, m = _reduce(z, n, UP)                     # 1 m 顶标高（mm）
    valid = Zg > -1e5
    if not valid.any():
        return dict(ok=False, why="模型栅格为空")
    M0 = valid                                     # 平面足迹
    ztop = float(Zg[valid].max())

    Hd = dsm_grid(ph["dsm"], E0, N0, HALF, GRID)
    G = Hd.shape[0]
    if m > G:
        return dict(ok=False, why="模型 %.0f m 超出窗口 %.0f m，调大 窗口半宽_m"
                    % (m * GRID, 2 * HALF))
    D, ground, hh = roof_mask(Hd, float(ph.get("屋面_离地_m") or 3.0),
                              float(ph.get("屋面_平度_m") or 0.6))
    if verbose:
        print("模型 %s：顶面 %.1f m，足迹 %.0f m²（%d×%d @ %.1f m）"
              % (bid, ztop / 1000.0, M0.sum() * GRID * GRID, m, m, GRID))
        print("DSM 窗口 %d×%d：地面(5%%) %.2f m，屋面掩膜 %.0f m²"
              % (G, G, ground, D.sum() * GRID * GRID))
    if D.sum() < 20:
        return dict(ok=False, why="DSM 屋面掩膜太小（%.0f m²）⇒ 锚点或窗口不对"
                    % (D.sum() * GRID * GRID))

    Mw = _embed(M0, G, False)
    Zm = _embed(np.where(M0, Zg / 1000.0, np.nan), G, np.nan)   # 绝对顶标高 m
    Dz = np.nan_to_num(np.clip(hh, 0.0, None), nan=0.0).astype(np.float32)
    ones = np.ones_like(Dz)
    RING = 4                                  # 外圈带宽（格）

    def contrast(Mr):
        """足迹内平均离地高 − 外圈平均离地高（树在内外一样 ⇒ 抵消）。"""
        Rr = ndimage.binary_dilation(Mr, iterations=RING) & ~Mr
        ci = _conv(Dz, Mr) / np.maximum(_conv(ones, Mr), 1e-6)
        cr = _conv(Dz, Rr) / np.maximum(_conv(ones, Rr), 1e-6)
        s = ci - cr
        bad = (_conv(ones, Mr) < 0.9 * Mr.sum()) | (_conv(ones, Rr) < 0.9 * Rr.sum())
        return np.where(bad, -99.0, s), Rr

    MINH = float(ph.get("屋面_离地_m") or 3.0)

    def resid(Mr, Zf, keep=False):
        """只比**两边都立着**的格：DSM 离地 > MINH 且 模型顶 > MINH。

        ★ 2026-10-19：`Zf` **必须是与 `Mr` 同一转角的顶高场**。第一版只转了足迹掩膜
          （`_rot_mask`），顶高场 `Zm` 一直没转 ⇒ 比的是「转过的足迹 ∩ 没转的高度」，
          c006 报残差中位 3.52 / P90 35.32 m；把高度场一起转之后是 0.2 / 7.6 m。
          这正是「写好的函数不等于被调用的函数」（铁律 17）。

        ★ 2026-10-19：第一版拿整个足迹比，c006 有 1/4 的足迹格 DSM 就是地面（院子/通道），
          残差被这些格撑到 P90 38 m —— 那是「足迹比实体大」这个**另一个缺陷**，混进来
          会让高度这一项恒红（铁律 198：两个量混进同一个 bool 就恒红）。
          所以拆成两个读数：高度残差（只比实体） + 空足迹占比（DSM 判为地面）。

        keep=True 时额外带回逐格数组（诊断热点用；伪证那一趟不需要）。
        """
        base = Mr & np.isfinite(hh) & np.isfinite(Zf)
        if base.sum() < 20:
            return None
        empty = float(((hh <= MINH) & base).sum()) / float(base.sum())
        ov = base & (hh > MINH) & (Zf > MINH)
        if ov.sum() < 20:
            return dict(delta=float("nan"), med=float("nan"), p90=float("nan"),
                        bad=float("nan"), n=0, empty=empty)
        dh = hh[ov] - Zf[ov]
        d = float(np.median(dh))
        # ★ 残差按「模型 − DSM」带符号：正 = 模型比影像高（多半是建高了/多了一层）
        signed = np.where(ov, hh - Zf - d, np.nan)   # ★ 必须用同转角的 Zf
        r = np.abs(dh - d)
        out = dict(delta=d, med=float(np.median(r)),
                   p90=float(np.percentile(r, 90)),
                   bad=float((r > float(ph.get("高度_红_m") or 2.0)).mean()),
                   n=int(ov.sum()), empty=empty)
        if keep:
            out["_ov"] = ov
            out["_sgn"] = signed
        return out

    # ——— 热点：把残差按 10 m 方格汇总，指出「是哪几块对不上」 ————
    def hotspots(ov, sgn, Zf):
        """残差按 `热点_格_m` 方格聚合；返回 [(E, N, 格数, r中位, 超差占比, 模型高, 影像高)]。

        ★ 只做**定位**，不改任何阈值：读数是「这一格对不上多少米」，判词仍由人看。
        """
        k = max(1, int(round(float(ph.get("热点_格_m") or 10.0) / GRID)))
        ny, nx = G // k, G // k
        if ny < 1 or nx < 1:
            return []
        rr, cc = np.nonzero(ov)
        if rr.size == 0:
            return []
        tid = (rr // k) * nx + (cc // k)
        vals = sgn[rr, cc]
        zd = hh[rr, cc]
        zm = Zf[rr, cc]
        minn = int(ph.get("热点_最少格") or 20)
        rows = []
        for t in np.unique(tid):
            m = tid == t
            if int(m.sum()) < minn:
                continue
            ty, tx = int(t) // nx, int(t) % nx
            ec = E0 - HALF + (tx * k + 0.5 * k) * GRID
            nc = N0 + HALF - (ty * k + 0.5 * k) * GRID
            v = np.abs(vals[m])
            rows.append(dict(
                E=float(ec), N=float(nc), 格数=int(m.sum()),
                残差中位_m=float(np.median(v)),
                超差占比=float((v > float(ph.get("高度_红_m") or 2.0)).mean()),
                符号中位_m=float(np.median(vals[m])),
                模型高_m=float(np.median(zm[m])),
                影像高_m=float(np.median(zd[m]))))
        rows.sort(key=lambda q: (-q["残差中位_m"], -q["超差占比"]))
        return rows[: int(ph.get("热点_条数") or 12)]

    def heat_png(ov, sgn, Zf, pth):
        """残差热力图：灰 = DSM 离地高，红 = 模型偏高，蓝 = 模型偏低。

        另出一张 `_zoom`：只画足迹外扩 10 m，左=模型顶高、右=DSM−模型，
        用来分辨「整块低几米」与「边缘错一格」（热点表分不出这两者）。
        """
        try:
            import matplotlib
            matplotlib.use("Agg")
            import matplotlib.pyplot as plt
            from matplotlib.colors import ListedColormap
        except Exception as e:                                           # noqa: BLE001
            return "matplotlib 不可用（%s）" % e
        fig, ax = plt.subplots(figsize=(7.2, 7.2), dpi=110)
        v = np.where(np.isfinite(hh), hh, np.nan)
        ax.imshow(v, cmap="Greys", interpolation="nearest")
        ax.contour(ov.astype(float), levels=[0.5], colors="#00c000", linewidths=0.8)
        cmap = ListedColormap(["#2f6fd0", "#7f9fd8", "#dddddd", "#f0a04b", "#d02f2f"])
        sv = np.clip(np.where(ov, sgn, np.nan), -12, 12)
        ax.imshow(sv, cmap=cmap, vmin=-12, vmax=12, interpolation="nearest", alpha=0.75)
        ax.set_title("%s  DSM residual hotspots  red=model too high" % bid, fontsize=10)
        ax.tick_params(labelsize=7)
        fig.tight_layout()
        fig.savefig(pth)
        plt.close(fig)
        # 放大图
        rr, cc = np.nonzero(np.isfinite(Zf))
        if rr.size:
            r0, r1 = max(0, rr.min() - 10), min(G, rr.max() + 11)
            c0, c1 = max(0, cc.min() - 10), min(G, cc.max() + 11)
            f2, a2 = plt.subplots(1, 2, figsize=(14, 6.6), dpi=110)
            for ax, img, ttl, kw in (
                    (a2[0], Zf[r0:r1, c0:c1], "model top (rot %.0f)" % deg,
                     dict(vmin=0, vmax=60)),
                    (a2[1], sgn[r0:r1, c0:c1], "DSM - model (m)",
                     dict(vmin=-15, vmax=15, cmap="RdBu_r"))):
                im = ax.imshow(img, interpolation="nearest", **kw)
                ax.set_title(ttl, fontsize=10)
                f2.colorbar(im, ax=ax, fraction=0.046)
                ax.set_xticks([])
                ax.set_yticks([])
            f2.tight_layout()
            f2.savefig(pth.replace("_map.png", "_zoom.png"))
            plt.close(f2)
        return None

    # —— 转角：参数给定就用；没给就按「锚点处足迹内外高差」搜（**不平移**）——
    rot0 = ph.get("rot_deg") if force_rot is None else force_rot
    ctr = G - 1          # ★ 全平移面 S[i,j] 中 i=j=G-1 才是「零平移」（不是图心）
    if rot0 is not None:
        deg, rot_src = float(rot0), ("命令行 --rot" if force_rot is not None else "参数.json 给定")
    else:
        a0, a1, astep = ph.get("旋转搜索_deg") or [0, 360, 10]
        best = (-1e9, 0.0)
        for d in np.arange(float(a0), float(a1), float(astep)):
            s, _ = contrast(_rot_mask(Mw, float(d)))
            if s[ctr, ctr] > best[0]:
                best = (float(s[ctr, ctr]), float(d))
        f = float(ph.get("旋转精搜_deg") or 2.0)
        for d in (best[1] - f, best[1] + f):
            s, _ = contrast(_rot_mask(Mw, float(d)))
            if s[ctr, ctr] > best[0]:
                best = (float(s[ctr, ctr]), float(d))
        deg, rot_src = best[1], "锚点处足迹内外高差最大"

    # ★ 第二把尺子（铁律 194：两个估计器并列，不拿一个悄悄覆盖另一个）：
    #   按**高度残差中位**重搜转角。足迹内外高差对「大体量落对、局部体量错位」不敏感，
    #   而高度残差直接问「这一格的顶面差多少米」。两者不一致本身就是缺陷线索。
    rot_chk = None
    if str(ph.get("旋转校核") or "1") not in ("0", "false", "False"):
        a0, a1, astep = ph.get("旋转搜索_deg") or [0, 360, 10]
        cand = [(float(d), resid(_rot_mask(Mw, float(d)), _rot_f(Zm, float(d)))) for d in
                np.arange(float(a0), float(a1), float(astep))]
        cand = [(d, r) for d, r in cand if r and r["n"] >= 200]
        if cand:
            d_best, r_best = min(cand, key=lambda q: q[1]["med"])
            f = float(ph.get("旋转精搜_deg") or 2.0)
            for d in (d_best - f, d_best + f, d_best - 2 * f, d_best + 2 * f):
                rq = resid(_rot_mask(Mw, float(d)), _rot_f(Zm, float(d)))
                if rq and rq["n"] >= 200 and rq["med"] < r_best["med"]:
                    d_best, r_best = float(d), rq
            rot_chk = dict(rot_deg=round(d_best, 1), 残差中位_m=round(r_best["med"], 2),
                           比较格数=int(r_best["n"]),
                           与主判据差_deg=round((d_best - float(deg) + 180) % 360 - 180, 1),
                           说明="按高度残差中位重搜（另一把尺子）；只报，不改主判据的转角")
            if verbose:
                print("转角校核（高度残差，另一把尺子）：%.1f° · 残差中位 %.2f m"
                      " ⇒ 与主判据(%s) 差 %+.1f°"
                      % (d_best, r_best["med"], deg, rot_chk["与主判据差_deg"]))

    Mr = _rot_mask(Mw, deg)
    Zmr = _rot_f(Zm, deg)          # ★ 顶高场必须与足迹同转角（铁律 17：函数写了要真的调）
    ssurf, Rr = contrast(Mr)
    s_anchor = float(ssurf[ctr, ctr])
    i, j = np.unravel_index(int(np.argmax(ssurf)), ssurf.shape)
    dE_best, dN_best = (j - (G - 1)) * GRID, -(i - (G - 1)) * GRID
    r0 = resid(Mr, Zmr, keep=True)
    if r0 is None:
        return dict(ok=False, why="配准重叠不足（<20 格）")
    if verbose:
        print("配准：rot %.1f°（%s）  锚点处足迹内−外高差 %+.1f m"
              % (deg, rot_src, s_anchor))
        print("      诊断：全平移面最高点在 dE %+.0f m dN %+.0f m（%+.1f m）"
              "⇒ 若远大于 0 且明显更高，锚点/口径需复核"
              % (dE_best, dN_best, float(ssurf[i, j])))

    # —— 伪证：整链人为挪 (dE,dN)，量到的残差必须**明显变差**，否则尺子分不开 ——
    fdE, fdN = ph.get("伪证_平移_m") or [15.0, -8.0]
    drs, dcs = int(round(-fdN / GRID)), int(round(fdE / GRID))
    Mf = _shiftb(Mr, drs, dcs)
    Zf = _shiftf(Zmr, drs, dcs, np.nan)
    sf, _ = contrast(Mf)
    rf = resid(Mf, Zf)
    s_shift = float(sf[ctr, ctr])
    ok_probe = bool(rf and (rf["med"] > r0["med"] + 1.0 or s_shift < s_anchor - 1.0))
    if verbose:
        print("伪证：人为挪 (%+.0f, %+.0f) ⇒ 残差中位 %.2f m / 高差 %+.1f m"
              "（原 %.2f / %+.1f）  %s"
              % (fdE, fdN, rf["med"] if rf else float("nan"), s_shift,
                 r0["med"], s_anchor, "✓ 分得开" if ok_probe else "✗ 分不开"))

    # —— 热点定位：把「对不上」落到具体方格上（只定位，不判红）——
    hs = hotspots(r0["_ov"], r0["_sgn"], Zmr) if r0.get("_ov") is not None else []
    png = os.path.join(CDUT, "rebuild", "_work", "photo_%s%s_map.png"
                       % (bid, ("_rot%03d" % int(round(deg))) if force_rot is not None else ""))
    os.makedirs(os.path.dirname(png), exist_ok=True)
    png_err = heat_png(r0["_ov"], r0["_sgn"], Zmr, png) if r0.get("_ov") is not None else "无比较格"
    if verbose and hs:
        print("热点（%s m 方格，按残差中位排序）" % ph.get("热点_格_m", 10.0))
        for q in hs[:5]:
            print("  E %.1f N %.1f · %d 格 · 残差中位 %.1f m · 超差 %.0f%%"
                  " · 模型 %.1f / 影像 %.1f m"
                  % (q["E"], q["N"], q["格数"], q["残差中位_m"],
                     100 * q["超差占比"], q["模型高_m"], q["影像高_m"]))

    b_med = b_p90 = float("nan")
    if D.any():
        bd = _boundary(D)
        bg = _boundary(Mr)
        if bg.any() and bd.any():
            dd = ndimage.distance_transform_edt(~bd)[bg] * GRID
            b_med, b_p90 = float(np.median(dd)), float(np.percentile(dd, 90))

    out = dict(
        schema="cdut3d-photo/1", bid=bid, dsm=ph["dsm"], dom=ph.get("dom"),
        窗口=dict(E0=E0, N0=N0, half_m=HALF, grid_m=GRID),
        配准=dict(rot_deg=round(deg, 1), rot_来源=rot_src,
                  dE_m=0.0, dN_m=0.0,
                  说明="平移取参数.json 的锚点，不重搜；下面的 诊断最佳平移 只报不用",
                  足迹内外高差_m=round(s_anchor, 2),
                  诊断最佳平移=dict(dE_m=round(dE_best, 0), dN_m=round(dN_best, 0),
                                    高差_m=round(float(ssurf[i, j]), 2)),
                  IoU_屋面粗筛=(round(_iou_peak(Mr, D)[0], 3) if D.any() else None),
                  高度校核=rot_chk),
        边界=dict(中位_m=None if math.isnan(b_med) else round(b_med, 2),
                  P90_m=None if math.isnan(b_p90) else round(b_p90, 2),
                  说明="模型足迹边到 DSM 屋面掩膜边的距离；屋面非平的不适用"),
        高度=dict(竖向偏移_m=_f(r0["delta"]), 残差中位_m=_f(r0["med"]),
                  残差P90_m=_f(r0["p90"]), 超差占比=_f(r0["bad"], 3),
                  超差阈_m=float(ph.get("高度_红_m") or 2.0),
                  比较格数=int(r0["n"]),
                  空足迹占比=round(r0["empty"], 3),
                  说明="空足迹 = 足迹内 DSM 判为地面的格占比；这是「足迹比实体大」，不是高度差"),
        伪证=dict(人工平移_m=[fdE, fdN],
                  挪后残差中位_m=_f(rf["med"]) if rf else None,
                  挪后高差_m=round(s_shift, 2),
                  通过=ok_probe),
        热点=dict(方格_m=float(ph.get("热点_格_m") or 10.0),
                  最少格=int(ph.get("热点_最少格") or 20),
                  说明="按方格汇总 |DSM−模型−δ|；只定位，不判红。"
                       "符号中位_m = 影像−模型−δ ⇒ 负 = 模型比影像高。"
                       "E/N 为方格中心（EPSG:4544）",
                  条=[dict(E=round(q["E"], 1), N=round(q["N"], 1), 格数=q["格数"],
                           残差中位_m=round(q["残差中位_m"], 2),
                           超差占比=round(q["超差占比"], 3),
                           符号中位_m=round(q["符号中位_m"], 2),
                           模型高_m=round(q["模型高_m"], 2),
                           影像高_m=round(q["影像高_m"], 2)) for q in hs]),
        热点图=None if png_err else png,
        热点放大图=None if png_err else png.replace("_map.png", "_zoom.png"),
        热点图_未出=png_err,
        量到的格数=int(r0["n"]),
        盲区=["2024 航测，此后改扩建不在影像里",
             "屋面掩膜取最大「高且平」连通块，非平屋顶会取到别处 ⇒ IoU 只作粗筛",
             "树冠遮挡处无真值，只统计重叠区",
             "高度为相对地面(5 分位)，δ 由重叠区中位吸收，不标定绝对高程",
             "DSM 是屋顶面；模型顶面取该格最高顶标高，女儿墙/设备基础会造成正偏差",
             "「高度校核」按残差重搜转角：对称平面有 180° 多解（c006 108/292、c001 296/0），"
             "只作线索，不许据此改 rot_deg",
             "热点方格是固定 10 m 窗；跨体量边界的格会混两类读数 ⇒ 必须看 _zoom.png 再判"],
    )
    bad = []

    def _chk(o, pa=""):
        if isinstance(o, dict):
            for k, v in o.items():
                _chk(v, pa + "." + str(k))
        elif isinstance(o, (list, tuple)):
            for i, v in enumerate(o):
                _chk(v, pa + "[%d]" % i)
        elif isinstance(o, float) and not math.isfinite(o):
            bad.append(pa)

    _chk(out)
    if bad:
        raise ValueError("输出里有非有限数（会写成裸 NaN，铁律 123）：%s" % ", ".join(bad))

    stem = "photo_%s" % bid + ("_rot%03d" % int(round(deg)) if force_rot is not None else "")
    p = os.path.join(CDUT, "rebuild", "_work", stem + ".json")
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "wb") as fh:                                            # 字节层（铁律 79）
        fh.write(json.dumps(out, ensure_ascii=False, indent=1,
                            allow_nan=False).encode("utf-8"))

    if verbose:
        print("高度：δ %+.2f m  残差中位 %.2f / P90 %.2f m  |Δ|>%.0f m 占 %.1f%%（%d 格）"
              % (r0["delta"], r0["med"], r0["p90"],
                 float(ph.get("高度_红_m") or 2.0), 100 * r0["bad"], r0["n"]))
        print("      空足迹（足迹内 DSM 是地面）%.1f%%" % (100 * r0["empty"]))
        print("边界：中位 %.2f m / P90 %.2f m（仅当屋面平整时有意义）" % (b_med, b_p90))
        print("⇒ %s" % p)
    return dict(ok=ok_probe, why=None if ok_probe else "伪证失败：尺子不可信",
                data=out, path=p)


def main(argv):
    bid = argv[argv.index("--bid") + 1] if "--bid" in argv else "c006"
    rot = float(argv[argv.index("--rot") + 1]) if "--rot" in argv else None
    r = run(bid, force_rot=rot)
    if not r.get("data"):
        print("★ 未量到：%s" % r.get("why"))
        return 2
    return 0 if r["ok"] else 3


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
