# -*- coding: utf-8 -*-
r"""多视角取证 —— 从 2022 五镜头原片里，给一栋楼挑出「看得见它」的几张片子。

为什么要有它（用户 2026-10-19「影像有多角度」）：
  `compare_photo.py` 只拿 DSM（俯视高度场）比，**看不见立面**；五镜头里 1~4 号是 45° 斜视，
  正好补这一块。这个件只做一件事：按楼栋的锚点与体量，把原片裁成「四张斜视 + 一张俯视」，
  并记下每张的角度、距离、航高、裁图框——供人和下游判据引用。

★ 系统工程口径（用户 2026-10-19）：本件**不认识任何楼栋名字**。楼栋只以 `bid` 进来，
  锚点/体量全部从 `参数.json::照片比对.楼栋[bid]` 与 `06_su/contours` 现算；
  镜头与航带的几何全在 `参数.json::照片比对.视角源`。换一栋楼＝换一个 bid，不加一行代码。

姿态口径（两条都从数据现算，不用无法核对的 ω/φ/κ 约定）：
  · 航向 = 前后两帧 POS 的前向差分；
  · 斜视方位 = 航向 + `倾斜方位_deg[cam]`（云台机位是刚性固定的）。
  · 航高 = POS h − DSM 在该点的地面高（两者高程基准已在 10 个控制点上验成一致，中位 −0.02 m）。

用法：
  python -X utf8 -I rebuild/tools/compare_views.py --bid c001
  出件：rebuild/_work/views_<bid>.json + rebuild/_work/views_<bid>/*.png
"""
import argparse
import json
import math
import os
import re
import sys

import numpy as np

sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

HERE = os.path.dirname(os.path.abspath(__file__))
CDUT = os.path.dirname(os.path.dirname(HERE))
PARAMS = os.path.join(CDUT, "rebuild", "构件库", "参数.json")
WORK = os.path.join(CDUT, "rebuild", "_work")
BID_RE = re.compile(r"^[A-Za-z0-9_]{1,32}$")
sys.path.insert(0, HERE)
import building as B                                                     # noqa: E402


def load_params(bid):
    with open(PARAMS, encoding="utf-8") as fh:
        base = json.load(fh)
    ph = dict(base.get("照片比对") or {})
    per = dict((ph.get("楼栋") or {}).get(bid) or {})
    per.update((base.get("楼栋") or {}).get(bid) or {})
    ph.update(per)
    return ph, per


def _anchor(bid, per):
    try:
        E0 = float(per.get("E"))
        N0 = float(per.get("N"))
    except (TypeError, ValueError):
        raise ValueError("%s 没有 E/N 锚点（写在 参数.json::照片比对.楼栋 下）" % bid)
    rot = per.get("rot_deg")
    return E0, N0, (0.0 if rot is None else float(rot))


def _root_of(bid):
    """出件根**只认 `building.root_for`**（c006 是 rebuild/ 本身，其余 rebuild/<bid>/）。

    ★ 铁律 196：这里原来自写了一份 `CDUT/<bid>` + `packs/...` 的猜测，和全链的主语不一致
      —— 猜错了只会报「找不到 contours」，看起来像「这栋没出图」。
    """
    root = B.root_for(bid)
    if not os.path.isdir(os.path.join(root, "06_su", "contours")):
        raise ValueError("找不到 %s 的 06_su/contours（%s）" % (bid, root))
    return root


def _extent(root):
    """楼栋平面半宽(m)与最高顶标高(m, 以楼栋 0 标高为基)。

    ★ 与 compare_photo 同一口径：取**全部楼层**环的 bbox（楼层 z0 各自不同，
      平面 bbox 与楼层无关，所以直接并集）。
    """
    d = os.path.join(root, "06_su", "contours")
    idx = os.path.join(d, "index.json")
    if not os.path.exists(idx):
        raise ValueError("没有 06_su/contours/index.json：这栋还没出图")
    with open(idx, encoding="utf-8") as fh:
        floors = json.load(fh)
    xs, ys, ztop = [], [], None
    for f in floors:
        p = os.path.join(d, f["floor"] + ".json")
        if not os.path.exists(p):
            continue
        with open(p, encoding="utf-8") as fh:
            j = json.load(fh)
        z0 = float(j.get("z0_m") or 0.0) * 1000.0      # m → mm（z 是 mm，与 compare_photo 同口径）
        for r in j["polys"]:
            for x, y in r["ring"]:
                xs.append(float(x))
                ys.append(float(y))
            z = z0 + float(r.get("z") or 0.0)
            ztop = z if ztop is None else max(ztop, z)
    if not xs:
        raise ValueError("contours 里没有环")
    half = max(max(xs) - min(xs), max(ys) - min(ys)) / 2000.0
    return half, (ztop or 0.0) / 1000.0                # 返回 m


def _load_pos(path):
    """Pic/<cam>.txt：名字 经度 纬度 高程 ω φ κ；返回 [{name,E,N,h,k,head}]。"""
    from pyproj import Transformer
    tr = Transformer.from_crs("EPSG:4326", "EPSG:4544", always_xy=True)
    out = []
    with open(path, encoding="utf-8", errors="replace") as fh:
        for ln in fh:
            q = ln.rstrip("\n").split("\t")
            if len(q) < 7:
                continue
            try:
                E, N = tr.transform(float(q[1]), float(q[2]))
                out.append(dict(name=q[0].strip(), E=E, N=N, h=float(q[3]),
                                k=float(q[6])))
            except ValueError:
                continue
    for i, r in enumerate(out):
        a = out[max(0, i - 1)]
        b = out[min(len(out) - 1, i + 1)]
        dE, dN = b["E"] - a["E"], b["N"] - a["N"]
        r["head"] = (math.degrees(math.atan2(dE, dN)) + 360.0) % 360.0 if (dE or dN) else 0.0
    return out


def _ground_sampler(tif):
    import rasterio
    ds = rasterio.open(tif)
    band = ds.read(1)

    def at(E, N):
        r, c = ds.index(E, N)
        if not (0 <= r < ds.height and 0 <= c < ds.width):
            return None
        v = band[max(0, r - 1):r + 2, max(0, c - 1):c + 2].astype(float)
        v = v[v > -1000]
        return float(np.median(v)) if v.size else None

    return at


def _ground_around(at, E0, N0, half, r_in=1.15, r_out=2.2, q=0.10):
    """楼外一圈的地面高：环形取 10 分位。返回 None 表示整圈都没值。"""
    vals = []
    for rad in np.arange(half * r_in, half * r_out + 1e-6, 4.0):
        for t in np.arange(0.0, 360.0, 12.0):
            a = math.radians(t)
            z = at(E0 + rad * math.sin(a), N0 + rad * math.cos(a))
            if z is not None:
                vals.append(z)
    return float(np.percentile(vals, q * 100.0)) if vals else None


def _unit(az_deg, tilt_deg):
    """光学轴单位向量 (E,N,U)：方位 az（自北顺时针）、**偏离正下视的倾角** tilt。

    ★ `倾斜_deg` 的口径就是「离天底多少度」：0 = 正下视，45 = 45° 斜视。
      第一版按「俯角」写（0=水平）⇒ cam5 的 0 变成了水平前视，投影点落到画面外，
      五路全报「没有机位把这栋楼框住」——那是尺子读反，不是没有片子。
    """
    a = math.radians(az_deg)
    t = math.radians(tilt_deg)
    return np.array([math.sin(a) * math.sin(t), math.cos(a) * math.sin(t), -math.cos(t)])


def _frame(a):
    """给光学轴 a 造 (右, 上) 两个像平面基向量（世界 ENU）。"""
    up = np.array([0.0, 0.0, 1.0])
    r = np.cross(up, a)
    n = float(np.linalg.norm(r))
    if n < 1e-6:                                  # 正下视：取东为「右」、北为「上」
        r = np.array([1.0, 0.0, 0.0])
        n = 1.0
    r = r / n
    u = np.cross(a, r)
    return r, u / float(np.linalg.norm(u))


def project(cam_xyz, a, target):
    """世界点 → 像平面坐标 (x_m, y_m, z_m)，z_m>0 在镜头前。单位 m。"""
    r, u = _frame(a)
    v = np.asarray(target, dtype=float) - np.asarray(cam_xyz, dtype=float)
    return float(v @ r), float(v @ u), float(v @ a)


def pick(pos, E0, N0, h_rel, ph, cam, gnd, f_px, W, H):
    """给每个机位打分：这栋楼的**楼顶**在不在画面里、方位对不对、距离合不合适。"""
    dep = float((ph.get("倾斜_deg") or {}).get(str(cam), 0.0))
    az_off = float((ph.get("倾斜方位_deg") or {}).get(str(cam), 0.0))
    tol = float(ph.get("方位容差_deg", 22.0))
    r0, r1 = (ph.get("距离比") or [0.55, 1.6])[:2]
    hmin = float(ph.get("最小航高_m", 50.0))
    out = []
    for r in pos:
        g = gnd(r["E"], r["N"])
        if g is None:
            continue
        agl = r["h"] - g
        if agl < hmin:
            continue
        dE, dN = E0 - r["E"], N0 - r["N"]
        dist = math.hypot(dE, dN)
        brg = (math.degrees(math.atan2(dE, dN)) + 360.0) % 360.0
        az = (r["head"] + az_off) % 360.0
        if dep < 1.0:
            if dist > 0.95 * agl:
                continue
            score = dist / agl
        else:
            dd = abs((brg - az + 180.0) % 360.0 - 180.0)
            if dd > tol:
                continue
            ratio = dist / max(agl, 1.0)
            if not (r0 <= ratio <= r1):
                continue
            score = dd / tol + abs(ratio - 1.0)
        # 楼顶必须真落在画面里（用该机位的视轴算，不用近似）
        a = _unit(az, dep)
        x, y, z = project((r["E"], r["N"], r["h"]), a, (E0, N0, g + h_rel))
        if z <= 0.0:
            continue
        if abs(x / z * f_px) > 0.46 * W or abs(y / z * f_px) > 0.46 * H:
            continue
        out.append(dict(score=score, px=x / z, py=y / z, dist=dist, brg=brg,
                        agl=agl, head=r["head"], az=az, dep=dep, name=r["name"]))
    out.sort(key=lambda d: d["score"])
    return out


def _distinct(cands, n):
    """同一航带连拍十几张：按「距离/方位」去重，取分数最好的 n 张。"""
    chosen = []
    for c in cands:
        if all(abs(c["dist"] - o["dist"]) > 20.0 or
               abs((c["brg"] - o["brg"] + 180) % 360 - 180) > 15.0 for o in chosen):
            chosen.append(c)
        if len(chosen) >= n:
            break
    return chosen


def _crop(root_src, pat, cam, c, W, H, f_px, half_m, slack, thumb, out):
    """按投影中心裁一块；斜视按 1/cos 拉长，保证立面也在框里。"""
    from PIL import Image
    p = os.path.join(root_src, pat.format(cam=cam, name=c["name"]))
    im = Image.open(p).convert("RGB")
    cx = W / 2.0 + c["px"] * f_px
    cy = H / 2.0 - c["py"] * f_px
    gsd = c["agl"] / f_px                       # 沿视线的 m/px
    r_px = (half_m / gsd) * slack
    r_px *= 1.0 + 0.6 * math.sin(math.radians(c["dep"]))
    r_px = max(120.0, min(r_px, 0.5 * max(W, H)))
    box = (int(cx - r_px), int(cy - r_px), int(cx + r_px), int(cy + r_px))
    box = (max(0, box[0]), max(0, box[1]), min(W, box[2]), min(H, box[3]))
    if box[2] - box[0] < 8 or box[3] - box[1] < 8:
        return None
    im.crop(box).resize((thumb, int(round(thumb * (box[3] - box[1]) /
                                           float(box[2] - box[0])))), Image.LANCZOS).save(out)
    return os.path.relpath(out, CDUT).replace("\\", "/")


def build(bid, verbose=True):
    ph, per = load_params(bid)
    if not ph.get("enabled", True):
        return dict(ok=False, why="参数.json::照片比对.enabled = false")
    src = ph.get("视角源") or {}
    if not src:
        return dict(ok=False, why="参数.json::照片比对.视角源 没配")
    E0, N0, _rot = _anchor(bid, per)
    half, h_top = _extent(_root_of(bid))
    root_src = src["根"]
    W, H = (int(x) for x in src.get("像幅_px", [6000, 4000]))
    f_mm = float(src.get("焦距_mm") or 25.4)
    px_mm = float(src.get("传感器_宽_mm", 23.5)) / W
    f_px = f_mm / px_mm
    n_pick = int(src.get("每相机_取", 3))
    pad = float(src.get("裁图_边_m", 40.0))
    slack = float(src.get("裁图_留量", 1.35))
    thumb = int(src.get("缩图_px", 900))

    gnd = _ground_sampler(ph["dsm"])
    # ★ 锚点 = 楼栋 bbox 中心 ⇒ 该点在**屋顶**上，直接读 DSM 会把屋面当地面（c001 实测差 20 m）。
    #   地面取「楼外一圈」的 10 分位：树冠/矮墙只在少数格里，分位数把它们挤掉。
    g0 = _ground_around(gnd, E0, N0, half)
    if g0 is None:
        return dict(ok=False, why="锚点周围 DSM 无值 ⇒ 锚点不在测区")

    out_dir = os.path.join(WORK, "views_" + bid)
    os.makedirs(out_dir, exist_ok=True)

    rows, miss = [], []
    for cam in (int(c) for c in src.get("相机", [5])):
        p = os.path.join(root_src, str(src["POS"]).format(cam=cam))
        if not os.path.exists(p):
            miss.append(dict(cam=cam, why="没有 POS：%s" % p))
            continue
        # h_top 是「相对楼栋 0 标高」的高度；机位地面 g 加上它＝楼顶的绝对高
        # ★ 传的是 src（视角源），不是 ph：机位几何全在 视角源 里，传上层只会读成默认值
        cands = pick(_load_pos(p), E0, N0, h_top, src, cam, gnd, f_px, W, H)
        chosen = _distinct(cands, n_pick)
        if not chosen:
            miss.append(dict(cam=cam, why="没有机位把这栋楼框住（%d 个候选里 0 个）"
                             % len(cands)))
            continue
        for j, c in enumerate(chosen, 1):
            png = _crop(root_src, str(src["影像"]), cam, c, W, H, f_px,
                        half + pad, slack, thumb,
                        os.path.join(out_dir, "cam%d_%02d.png" % (cam, j)))
            if not png:
                miss.append(dict(cam=cam, why="第 %d 张裁图出界" % j))
                continue
            rows.append(dict(cam=cam, 角度=("俯视" if c["dep"] < 1.0
                                            else "斜视 %.0f°" % c["dep"]),
                             张次=j, 水平距离_m=round(c["dist"], 1),
                             方位_deg=round(c["brg"], 1), 航向_deg=round(c["head"], 1),
                             航高_m=round(c["agl"], 1), 图=png, 文件名=c["name"]))
    res = dict(ok=True, bid=bid, 锚点=[round(E0, 2), round(N0, 2)],
               地面高_m=round(g0, 2), 顶高_m=round(g0 + h_top, 2),
               半宽_m=round(half, 1), 焦距_mm=f_mm,
               地面分辨率_中位_m=(round(float(np.median([r["航高_m"] for r in rows]))
                                    * px_mm / f_mm, 4) if rows else None),
               视角=rows, 缺=miss)
    with open(os.path.join(WORK, "views_%s.json" % bid), "w", encoding="utf-8") as fh:
        json.dump(res, fh, ensure_ascii=False, indent=1)
    if verbose:
        print("锚点 %.2f/%.2f  地面 %.2f  顶高 %.2f  半宽 %.1f m"
              % (E0, N0, g0, g0 + h_top, half))
        for r in rows:
            print("  cam%d #%d  %6.1f m  方位 %6.1f°  航高 %6.1f m  %s"
                  % (r["cam"], r["张次"], r["水平距离_m"], r["方位_deg"],
                     r["航高_m"], os.path.basename(r["图"])))
        for m in miss:
            print("  cam%d 缺：%s" % (m["cam"], m["why"]))
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bid", required=True)
    a = ap.parse_args()
    if not BID_RE.match(a.bid):
        print("bid 不合法", file=sys.stderr)
        return 2
    try:
        r = build(a.bid)
    except (ValueError, KeyError, OSError) as e:
        print("失败：%s" % e, file=sys.stderr)
        return 3
    return 0 if r.get("ok") else 4


if __name__ == "__main__":
    sys.exit(main())
