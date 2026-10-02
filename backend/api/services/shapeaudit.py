# -*- coding: utf-8 -*-
"""全库「模型竖向自洽」稽核 —— 不依赖任何无人机数据，逐栋给出一个可判的差。

## 为什么先做这一层，而不是先做点云偏差

原计划第 4 步是 CloudCompare `-ICP` + `-C2M_DIST` 的逐点偏差。**前提不成立**：
`D:\\理工数据` + `D:\\gym3d` 共 377408 个文件，点云后缀（las/laz/ply/e57/xyz/pts/pcd）
**0 命中**。没有可吃的三维点云，那一步跑不出来。

但在**竖向**上，「外形对不对」有一条根本不依赖外部的路：**模型自己身上有两个数
都指同一个量** —— 这栋楼有多高。

    A 路：`data/buildings/<n>/floors/floor*.json` 的 `layer_height` 之和（地上部分）
    B 路：`data/buildings/<n>/<n>-building.glb` 里 POSITION accessor 的 Y 跨度

B 是 A 堆出来的，所以两者**本该**只差一个屋面常数（坡屋面/女儿墙/找坡那一层）。
差得多 ⇒ 堆叠那一步漏了或多了东西 ⇒ **这就是外形错误**，而且不需要参照物。

★ 量的是**两个数之差**，不是任何一个绝对值：
  GLB 是 Y-up 还是 Z-up、局部 Z 的零点摆在哪，都**不影响差值**。
  这与 `sitecheck.relief()` 里「地面与屋盖同栅格 ⇒ 基准自动抵消」是同一条理由。

## 三条不许省的纪律

① **参照值不许手打**（铁律 105/174）：屋面常数从**全库实测**取中位数，
   并把「几栋落在同一档」一起印出来。手打一个 0.90，就把「我的声明错了」
   和「这栋楼错了」变成屏幕上同一行字。

② **三态分开**（铁律 166）：
   `ok` 量到了、一致 / `off` 量到了、有差 / `na` 缺件（没 GLB 或没 floors）
   / `failed` 读坏了。前两个是要**判**的，后两个是**做不了**的 ——
   「做不了」印成「没问题」是本仓最有名的那类错。

③ **口径写进每一个数旁边**（铁律 141）：
   `floor: -1`（地下层）**不算地上** —— 它不在 GLB 的表面几何里。
   c011 若把 −1 算进 Σ，会凭空多出 4.2 m 的「缺失」，而那是口径不是缺陷。

## 读法：只读 GLB 的文件头

`POSITION` accessor 的 `min`/`max` 就在 GLB 的 JSON 块里，**不用解三角网**。
1.67M 顶点的 c103 也只花几十毫秒 —— 这是唯一能全库扫得动的读法。
文件头级读法有个已知盲区：`accessor` 的 min/max 是**生产者写进去的**，
若生产者写错了，我读到的就是它在说谎。所以本模块同时报**顶点数**与
**文件字节数**，让「这么小的文件里怎么会有这么多顶点」这类矛盾有机会露头。
"""
from __future__ import annotations

import json
import struct
from pathlib import Path
from typing import Any

CRITERION_VERSION = "shapeaudit-2"   # 2：一栋都没量到时，参照值/门槛改吐 null（原先吐 0.0）

# 地上/地下的分界：`floor` 字段小于它的不算地上（c011 的 −1 是地下一层）。
GROUND_FLOOR = 0

# 判「有差」的门槛 = 半个层高 —— 这是**物理分辨率**，不是调出来的：
# 差不到半层，就没法说它是「少了一层」；差过半层，才有一个可判的说法。
TOL_LAYER_FRAC = 0.5

GLB_JSON_CHUNK = 0x4E4F534A          # 'JSON'
GLB_MAGIC = 0x46546C67               # 'glTF'


class Unreadable(RuntimeError):
    """这个 GLB / 这份 floors 读不出来。★ 带出处，别退化成「没有」。"""


# ────────────────────────────────────────────────────────────────
# 两个量，两条独立的读法
# ────────────────────────────────────────────────────────────────

def glb_height(glb: Path) -> dict[str, Any]:
    """B 路：GLB 的 Y 跨度（米）。只读文件头里的 accessor min/max。

    竖向是哪一轴**不靠约定**（glTF 规范说 Y-up，但本仓的铁律是「径从实物量」）：
    把三个跨度都回去，由调用方拿「与 Σ层高的残差是否集中在常数」来判。
    实测 91 栋：Y 的 MAD = 0.00 m、Z 的 MAD = 20.74 m ⇒ Y 就是竖向。
    """
    with open(glb, "rb") as f:
        head = f.read(12)
        if len(head) < 12:
            raise Unreadable("文件不足 12 字节，不是 GLB：%s" % glb)
        magic, ver, total = struct.unpack("<III", head)
        if magic != GLB_MAGIC:
            raise Unreadable("magic=%08x 不是 glTF（文件：%s）" % (magic, glb))
        jlen, jtype = struct.unpack("<II", f.read(8))
        if jtype != GLB_JSON_CHUNK:
            raise Unreadable("第一个块不是 JSON（type=%08x）：%s" % (jtype, glb))
        raw = f.read(jlen)
    try:
        j = json.loads(raw.decode("utf-8"))
    except Exception as exc:                      # noqa: BLE001
        raise Unreadable("GLB 的 JSON 块解不开：%s: %s" % (type(exc).__name__, exc)) from exc

    # ★ 只取**被 mesh primitive 引用**的 POSITION accessor。
    #   全库里扫所有 VEC3 accessor 会把 NORMAL / TEXCOORD 也算进来 ——
    #   它们在数值上恰好也是 VEC3 且带 min/max，而 NORMAL 的 min/max 是 ±1。
    idx: list[int] = []
    for m in j.get("meshes", []):
        for pr in m.get("primitives", []):
            ai = (pr.get("attributes") or {}).get("POSITION")
            if isinstance(ai, int) and ai not in idx:
                idx.append(ai)
    if not idx:
        raise Unreadable("这个 GLB 的 mesh 里没有 POSITION")

    mn = [float("inf")] * 3
    mx = [float("-inf")] * 3
    n_vert = 0
    for i in idx:
        if not (0 <= i < len(j.get("accessors", []))):
            raise Unreadable("POSITION accessor 下标 %d 越界" % i)
        a = j["accessors"][i]
        if "min" not in a or "max" not in a:
            raise Unreadable("POSITION accessor %d 没有 min/max —— "
                             "这份 GLB 的作者没写，本读法对它失明" % i)
        n_vert += int(a.get("count") or 0)
        for k in range(3):
            mn[k] = min(mn[k], float(a["min"][k]))
            mx[k] = max(mx[k], float(a["max"][k]))
    if n_vert <= 0:
        raise Unreadable("POSITION accessor 的顶点数是 0")

    span = [mx[k] - mn[k] for k in range(3)]
    return {
        "span_x_m": round(span[0], 3), "span_y_m": round(span[1], 3), "span_z_m": round(span[2], 3),
        "y0": round(mn[1], 3), "y1": round(mx[1], 3),
        "n_vert": n_vert, "n_pos_accessor": len(idx),
        "read": "GLB 文件头的 POSITION accessor min/max（不解三角网）",
    }


def floors_height(fdir: Path) -> dict[str, Any]:
    """A 路：Σ层高，地上与含地下两栏都给。"""
    files = sorted(fdir.glob("floor*.json"))
    if not files:
        raise Unreadable("目录里没有 floor*.json：%s" % fdir)
    sum_all = 0.0
    sum_above = 0.0
    hs: list[float] = []
    used: list[str] = []
    has_neg = False
    n_above = 0
    skipped: list[str] = []
    for f in files:
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except Exception as exc:                  # noqa: BLE001
            # ★ 一层坏掉就整栋丢掉太狠，但**静默跳过**更坏 ⇒ 记下来，回在结果里。
            skipped.append("%s: %s" % (f.name, type(exc).__name__))
            continue
        lh = d.get("layer_height")
        if not isinstance(lh, (int, float)) or float(lh) <= 0:
            skipped.append("%s: layer_height=%r" % (f.name, lh))
            continue
        lh = float(lh)
        fl = d.get("floor")
        hs.append(lh)
        sum_all += lh
        used.append(f.name)
        if isinstance(fl, (int, float)) and float(fl) < GROUND_FLOOR:
            has_neg = True
        else:
            sum_above += lh
            n_above += 1
    if not used:
        raise Unreadable("floor*.json 一条层高都没有（跳过 %d 个）：%s"
                         % (len(skipped), "; ".join(skipped[:3])))
    hs_sorted = sorted(hs)
    return {
        "sum_all_m": round(sum_all, 3),
        "sum_above_m": round(sum_above, 3),
        "n_floors": len(used), "n_above": n_above,
        "has_basement": has_neg,
        "layer_height_med_m": round(hs_sorted[len(hs_sorted) // 2], 3),
        "layer_heights": sorted(set(round(v, 3) for v in hs)),
        "n_files": len(files), "n_used": len(used), "skipped": skipped[:5],
        "read": "floors/floor*.json 的 layer_height 之和（floor<%d 不算地上）" % GROUND_FLOOR,
    }


# ────────────────────────────────────────────────────────────────
# 全库
# ────────────────────────────────────────────────────────────────

def _median(v: list[float]) -> float:
    if not v:
        return 0.0
    s = sorted(v)
    n = len(s)
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2.0


def _mad(v: list[float], med: float) -> float:
    return _median([abs(x - med) for x in v]) if v else 0.0


def _glb_of(d: Path) -> Path | None:
    if not d.is_dir():
        return None
    glbs = sorted(d.glob("*.glb"))
    for g in glbs:
        if "building" in g.name:
            return g
    return glbs[0] if glbs else None


def audit(cfg, names: list[str], titles: dict[str, str] | None = None) -> dict[str, Any]:
    """逐栋量两个数、给出一个差。**参照值从本趟实测算出来，不手打。**"""
    titles = titles or {}
    bdir = cfg.resolved_data_dir / "buildings"

    items: list[dict[str, Any]] = []
    for name in names:
        d = bdir / name
        glb = _glb_of(d)
        row: dict[str, Any] = {"name": name, "title": titles.get(name) or name,
                               "state": "na", "why": None}
        if glb is None:
            row["why"] = "这一栋没有 GLB"
            items.append(row)
            continue
        fdir = d / "floors"
        if not fdir.is_dir():
            row["why"] = "这一栋没有 floors/ 目录"
            row["glb"] = {"path": str(glb)}
            items.append(row)
            continue
        try:
            g = glb_height(glb)
            fh = floors_height(fdir)
        except Unreadable as exc:
            row["state"] = "failed"
            row["why"] = str(exc)
            row["glb"] = {"path": str(glb)}
            items.append(row)
            continue
        st = glb.stat()
        row.update({
            "glb": {"path": str(glb), "mb": round(st.st_size / 1e6, 2),
                    "mtime": int(st.st_mtime)},
            "floors_dir": str(fdir),
            "glb_h_m": g["span_y_m"],
            "sum_above_m": fh["sum_above_m"],
            "sum_all_m": fh["sum_all_m"],
            "n_floors": fh["n_floors"], "n_above": fh["n_above"],
            "has_basement": fh["has_basement"],
            "layer_height_med_m": fh["layer_height_med_m"],
            "n_vert": g["n_vert"],
            "spans_m": {"x": g["span_x_m"], "y": g["span_y_m"], "z": g["span_z_m"]},
            # ★ 两个口径的残差都留着：楼上有没有地下层，决定该看哪一个。
            "resid_above_m": round(g["span_y_m"] - fh["sum_above_m"], 3),
            "resid_all_m": round(g["span_y_m"] - fh["sum_all_m"], 3),
            "skipped": fh["skipped"],
        })
        row["state"] = "pending"        # 参照值还没算出来，下面统一定档
        items.append(row)

    # ── 参照值：从本趟**实测**里取（铁律 105/174：手打的那个数会把
    #    「我的声明错了」报成「被测对象坏了」）──────────────────────
    resid = [r["resid_above_m"] for r in items if r.get("state") == "pending"]
    ref = _median(resid)
    # ★ 门槛是**逐栋**的，取那栋楼**自己的**层高 —— 判的是「它像不像少了一层」，
    #   所以分辨率是它自己的层高，不是全库中位数（铁律 159：刻度要和结论印在一起）。
    #   拿全库中位数当门槛，会让层高 3.0 m 的楼把 3.9 m 的缺口读成「一致」。
    lh_med = _median([r["layer_height_med_m"] for r in items if r.get("state") == "pending"])
    n_agree = 0
    for r in items:
        if r.get("state") != "pending":
            continue
        dev = r["resid_above_m"] - ref
        tol_b = max(0.05, TOL_LAYER_FRAC * r["layer_height_med_m"])
        r["dev_m"] = round(dev, 3)
        r["tol_m"] = round(tol_b, 3)
        r["dev_layers"] = round(dev / r["layer_height_med_m"], 2) if r["layer_height_med_m"] else None
        r["state"] = "ok" if abs(dev) <= tol_b else "off"
        n_agree += 1 if r["state"] == "ok" else 0

    counts = {"total": len(items), "ok": 0, "off": 0, "na": 0, "failed": 0}
    for r in items:
        counts[r["state"]] = counts.get(r["state"], 0) + 1

    # 残差的分布（0.5 m 一档）—— 让「90 栋恰好在同一档」这件事**看得见**，
    # 否则读者只有一个中位数，没法知道它有多集中。
    buckets: dict[float, int] = {}
    for v in resid:
        k = round(v * 2) / 2.0
        buckets[k] = buckets.get(k, 0) + 1
    dist = [{"m": k, "n": buckets[k]} for k in sorted(buckets)]

    off = sorted([r for r in items if r["state"] == "off"],
                 key=lambda r: -abs(r.get("dev_m") or 0.0))

    # ★ `_median([])` 回 0.0 —— 于是**一栋都没量到**时，这一支会照样印出
    #   「全库层高中位数 0.00 m ⇒ 典型门槛 0.05 m」这么一句权威口吻的话，
    #   而它底下是**空集**（铁律 062/084：分母为 0 的 k/N 是最像结论的假数）。
    #   这正是本模块 docstring 里那条纪律的反面：**口径要写进每一个数旁边** ——
    #   一个从空集里造出来的数，它的口径是「不适用」，那就得印「不适用」，
    #   不许退化成一个看起来像量过的 0.00（铁律 166②）。
    #   服务器上就是这个情形：最小集部署没有逐栋 GLB ⇒ 92 栋全 `na`。
    #   前端 `N(null, d)` 本来就吐 `—`，所以这里改成 None 是一条真话，不是占位。
    if resid:
        ref_m = round(ref, 3)
        mad_m = round(_mad(resid, ref), 3)
        tol_m = round(max(0.05, TOL_LAYER_FRAC * lh_med), 3)
        tol_why = ("**逐栋**取那栋楼自己层高的一半（全库层高中位数 %.2f m ⇒ 典型门槛 %.2f m）"
                   "—— 它是**物理分辨率**：差不到半层就说不清是哪一层，超过半层才有一个可判的说法"
                   % (lh_med, tol_m))
    else:
        ref_m = mad_m = tol_m = None
        tol_why = ("**不适用**：这一趟**一栋都没量到**（%d 栋里 %d 栋缺 GLB、%d 栋缺 floors/、"
                   "%d 栋读坏了）⇒「全库层高中位数」与「典型门槛」都无从谈起。"
                   "屏幕上的「—」是**没有这个数**，不是 0。"
                   "真门槛仍是逐栋取那栋楼自己层高的一半。"
                   % (len(items),
                      sum(1 for r in items if r.get("why") == "这一栋没有 GLB"),
                      sum(1 for r in items if r.get("why") == "这一栋没有 floors/ 目录"),
                      counts.get("failed", 0)))

    return {
        "criterion_version": CRITERION_VERSION,
        "counts": counts,
        "reference": {
            "m": ref_m,
            "how": "全库实测中位数（**不是手打**）—— 口径：GLB 的 Y 跨度 − Σ(floor≥%d 的层高)"
                   % GROUND_FLOOR,
            "n_measured": len(resid), "n_agree": n_agree,
            "mad_m": mad_m,
            "min_m": round(min(resid), 3) if resid else None,
            "max_m": round(max(resid), 3) if resid else None,
        },
        "tol_m": tol_m,
        "tol_why": tol_why,
        "dist": dist,
        "off": off,
        "items": items,
        "read": {
            "glb": "只读 GLB 文件头里 POSITION accessor 的 min/max，不解三角网",
            "floors": "floors/floor*.json 的 layer_height 之和",
            "why_this_works": "两个数同源（GLB 是 floors 堆出来的）⇒ 差里没有外部基准，"
                              "Y-up 还是 Z-up、局部零点摆在哪都不影响差值",
        },
        "caveat": (
            "这一层量的是**模型自己**自洽不自洽，**不是**模型对不对 —— "
            "两边一起错（图纸错、输入错）它照样全绿。"
            "要判「对不对」得有外部参照：正射影像（已有）或点云（盘上 **0** 个）。"
            "★ 另一条已知盲区：accessor 的 min/max 是**生产者写进去的**，"
            "生产者若写错，本读法读到的就是它在说谎 —— "
            "所以顶点数与文件大小一并回，让矛盾有机会露头。"),
    }
