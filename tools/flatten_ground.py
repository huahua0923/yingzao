# -*- coding: utf-8 -*-
r"""修模·第三刀：**地面拟合压平**（只改高程，不动拓扑）。s2 清洗件进，s3 压平件出。

★★ 这一刀与前两刀**性质不同**——前两刀的「该动哪一块」由**几何自己**决定
   （重合点、分量面积），所以能自动化；**压平不一样：「哪一片是地面」是人的判读，不是几何性质。**

   ★ 凭什么这么说（实测，`_scratch/_probe_残差.py` ④，2026-10-15）：
     拿「朝上面里、面心高 ≤ 最低面心 + 2 m」这条**自动口径**选地面，本块选出 **395.7 m²**、
     占朝上总面积的 **45.3%**；而同一块上「DSM 判为地面（≤455）」在足迹里只有 **50.2 m²**。
     ⇒ 那条口径选出来的**大半不是地面**，是**楼底下那层面**（454.4 m 的平台）。
     ⇒ ★ **本工具因此绝不自带「猜地面」的口径**；否则它会一声不响地把楼板压成地形。

★★ 本件的契约（一句话）：**只动 `--sel-file` 里点名的那批顶点，一个不多。**
   ★ 名单**按几何**点名（`_clean/<块>/<块>.glb` **实测是 5 个几何**）：`sel["geom"] = {几何名: [本地下标]}`。
     下标**不是**全局的 —— 一个几何的顶点表不许被另一个几何的下标动到。
   未点名的每一个顶点的**每一个分量逐位不变**。选谁由人过目
   （`--pick-box` 只产出**候选名单**给人看），工具**不替人决定哪片是地面**。

★★ 原来的出口门「压平后对 DSM 残差必须下降」**已实测作废**（见 `tools/reality_placement.py`
   docstring）：DSM ＝ **最高面**、实景网格 ＝ **完整表面**（含竖直外墙）⇒ 同一 (E,N) 上
   网格跨 454.5→467 而 DSM 只给一个数；且本块足迹上 DSM **71.8% 无值**。
   那是**定义差不是误差**，任何阈值都会被它主导。
   ⇒ 本刀的出口门改立在**「越没越界」**这一维（`gates/J-10.10-04_修模压平不越界.py`），
   ★ 并如实声明：**本刀没有任何独立参照能证明「压出来的地面与真实地形一致」。**

★★ 落位口径：进出的 glb 都在**瓦片 ENU**（经 `RP.gltf_yup_to_enu`）。
   `修模` 只改**高程 U** ⇒ 落到 glb 里就是**只改第 1 个分量（y）**，x=E、z=−N **逐位不动**
   （逆变换 `RP.enu_to_gltf_yup` 与本文件同源）⇒ 「改了哪些点」可以**按位**核，不必引入容差。

用法：
    # ① 产出**候选**名单（给人过目；落 _scratch，不落 _flatten）
    python tools/flatten_ground.py --blocks Tile_+003_+005 \
        --pick-box 770,1180,800,1200 --pick-up 20 --pick-zmax 460 --sel-out _scratch/sel_T5.json
    # ② 按点名清单压平
    python tools/flatten_ground.py --blocks Tile_+003_+005 --sel-file _scratch/sel_T5.json
    # ③ 只压成水平的（不改坡度）
    python tools/flatten_ground.py --blocks X --sel-file s.json --level

退出码：0 压完 · 1 有块被拒 / 自检对不上（**不落盘**）· 4 没有可压的件、或名单为空（**没量到**）
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

import numpy as np  # noqa: E402
import trimesh  # noqa: E402

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
from tools import reality_placement as RP  # noqa: E402

CLEAN = os.path.join(REPO, "_clean")
FLATTEN = os.path.join(REPO, "_flatten")
SEL_VER = "cdut3d-flatten-sel/1"

RC_PASS, RC_FAIL, RC_NOGAUGE = 0, 1, 4


def log(*a):
    print(" ".join(str(x) for x in a))


def sha256_file(p: str) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for c in iter(lambda: f.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()


def utc_now() -> str:
    """ISO-8601 UTC（本仓数据文件里凡时刻一律这个形状）。"""
    import datetime
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------- 核心（纯函数）
def plane_fit(verts_glb, idx, level: bool = False):
    """对点名那批顶点拟一个高程平面 `U = a·E + b·N + c`。`level=True` ⇒ 强制水平（a=b=0）。

    ★ 返回的是**数据算出来的**三个数，不是挑的（铁律 103）。
    """
    v = np.asarray(verts_glb, dtype=float)[np.asarray(idx, dtype=int)]
    E, N, U = v[:, 0], -v[:, 2], v[:, 1]
    if level or len(idx) < 3:
        return 0.0, 0.0, float(U.mean())
    A = np.c_[E, N, np.ones(len(E))]
    coef, *_ = np.linalg.lstsq(A, U, rcond=None)
    return float(coef[0]), float(coef[1]), float(coef[2])


def apply_flatten(verts_glb, idx, plane):
    """把 `idx` 点到的顶点的**高程**吸附到平面；**其余分量一个都不碰**。

    ★ 纯函数（不改入参）—— 闸门与正对照都直接调它，测的就是本工具本体。
    返回 `(新顶点, 逐位动过的布尔掩膜)`。★ **按 IEEE754 位比较**，不用容差。
    """
    v = np.array(verts_glb, dtype=float, copy=True)
    before = v.copy()
    a, b, c = plane
    idx = np.asarray(idx, dtype=int)
    if idx.size:
        E, N = v[idx, 0], -v[idx, 2]
        v[idx, 1] = a * E + b * N + c
    moved = ~np.all(v == before, axis=1)
    return v, moved


def f32_ulp(x):
    """把 float64 值写成 float32 再读回来，**允许**的量化误差上界（1 ULP）。

    ★★ 这是「按位核」这条例外的**唯一**来源，必须说明白：
      glb 里 POSITION 是 **float32** ⇒
        · **没被我改过的**顶点：float32→float64 提升是**精确**的 ⇒ 仍然**逐位相等**；
        · **被我故意改过的**那个分量：落盘后差 **≤ 1 ULP**（实测 1.743e-06 ≤ 3.815e-06 m）。
      ⇒ 判据必须**分成两条**（未点名逐位 / 点名 ≤1ULP），**不许合成一条「逐位」** ——
        合成之后，「按设计改了」会被读成「坏了」，而那正是本工具唯一该做的事。
        本工具第一版就是这么写的，落盘往返当场报 False（**尺子错，不是件错**）。
    """
    x = np.asarray(x, dtype=float)
    return np.spacing(np.float32(np.abs(x))).astype(float)


def scene_stack(sc):
    """把一个 `Scene` 摊成 **(几何名顺序, 全局顶点表, 全局面表, 各几何顶点数)**。

    ★★ 为什么要摊：`_clean/<块>/<块>.glb` **实测是 5 个几何**（5 片），不是单几何
      （本工具第一版假定单几何，跑起来当场抛错 —— 那是**要的行为**，没静默挑一个，铁律 137）。
      ⇒ 面表里的下标必须**加累积偏移**才能与顶点表对齐；跨几何的「相邻面」也随之成立。
    """
    names = list(sc.geometry.keys())
    verts, faces, counts, off = [], [], [], 0
    for n in names:
        g = sc.geometry[n]
        v = np.asarray(g.vertices, dtype=float)
        f = np.asarray(g.faces, dtype=int)
        verts.append(v)
        faces.append(f + off if f.size else f.reshape(0, 3))
        counts.append(len(v))
        off += len(v)
    return names, np.vstack(verts), np.vstack(faces), counts


def pick_box(sc, box, up_deg, z_max):
    """**候选**名单：ENU 轴上盒 ∩ （至少有一个相邻面朝上）∩ （高程 ≤ z_max）。

    ★ 它只产出**候选**。本函数**不知道**选出来的是不是地面 —— 那是人看名单/看图说了算；
      实测反例：旧口径（面心 ≤ 最低面心 + 2 m）选出的 395.7 m² 里绝大多数是**楼底下那层面**。

    ★ 返回 `{几何名: [该几何的本地下标, ...]}` —— **不是**全局下标。
      契约按**几何**成立：写回时一个几何的顶点表不许被另一个几何的下标动到。
    """
    names, V, F, counts = scene_stack(sc)
    E, N, U = V[:, 0], -V[:, 2], V[:, 1]
    x0, y0, x1, y1 = box
    m = (E >= min(x0, x1)) & (E <= max(x0, x1)) & (N >= min(y0, y1)) & (N <= max(y0, y1))
    if z_max is not None:
        m &= U <= z_max
    if up_deg is not None and len(F):
        n = np.cross(V[F[:, 1]] - V[F[:, 0]], V[F[:, 2]] - V[F[:, 0]])
        ln = np.linalg.norm(n, axis=1)
        good = ln > 1e-12
        nz = np.zeros(len(F))
        nz[good] = n[good, 2] / ln[good]          # 朝上分量（U 轴）
        uptri = nz >= np.cos(np.radians(up_deg))
        vu = np.zeros(len(V), bool)
        vu[F[uptri].ravel()] = True
        m &= vu
    out, off = {}, 0
    for n, k in zip(names, counts):
        loc = np.where(m[off:off + k])[0]          # ★ 摊回本地下标
        if loc.size:
            out[n] = [int(i) for i in loc]
        off += k
    return out


# ---------------------------------------------------------------- 单块处理
def load_block(block: str, root: str):
    """读 `_clean/<块>/<块>.glb`。★ 返回 `(Scene, 路径)` —— **Scene 可以多几何**。"""
    p = os.path.join(root, block, block + ".glb")
    if not os.path.isfile(p):
        return None, p
    sc = trimesh.load(p, force="scene")
    if not sc.geometry:
        raise ValueError("%s 里一个几何都没有" % p)
    return sc, p


def do_block(block: str, sel: dict, level: bool, dry: bool,
             clean_dir: str = CLEAN, out_dir: str = FLATTEN):
    """压平一块。名单按**几何**给（`sel["geom"]`），**逐几何**核「动过的 ⊆ 点名的」。

    ★ 一个几何算错就**整块拒写**（不许「写一半」——半个件比不写更难查）。
    """
    sc, src = load_block(block, clean_dir)
    if sc is None:
        log("  [%s] _clean 下没有件 ⇒ 跳过" % block)
        return None
    names, _V, _F, counts = scene_stack(sc)
    by_geom = sel.get("geom") or {}
    unknown = [n for n in by_geom if n not in names]
    if unknown:
        log("  [%s] 名单里有本件没有的几何 %s ⇒ 拒块" % (block, unknown[:3]))
        return {"block": block, "rc": RC_FAIL}

    total_sel = sum(len(by_geom.get(n) or []) for n in names)
    if total_sel == 0:
        log("  [%s] 名单为空 ⇒ 没量到（rc=4），不写盘" % block)
        return {"block": block, "rc": RC_NOGAUGE}

    new_v, gm, n_moved, uv_any = {}, {}, 0, False
    for n in names:
        g = sc.geometry[n]
        v0 = np.asarray(g.vertices, dtype=float)
        if g.visual.uv is not None:
            uv_any = True
        idx = np.asarray(by_geom.get(n) or [], dtype=int)
        if idx.size == 0:
            new_v[n] = v0
            continue
        bad = idx[(idx < 0) | (idx >= len(v0))]     # ★ 越界点名单：拒块（不静默丢，铁律 137）
        if bad.size:
            log("  [%s/%s] 名单里有越界下标 %s ⇒ 拒块" % (block, n, bad[:5].tolist()))
            return {"block": block, "rc": RC_FAIL}
        a, b, c = plane_fit(v0, idx, level=level)
        v1, moved = apply_flatten(v0, idx, (a, b, c))
        # ---- 自检（★ 工具自己也核一遍；闸门另有独立复算，铁律 187）----
        inside = np.zeros(len(v0), bool)
        inside[idx] = True
        outside = np.where(moved & ~inside)[0]
        if outside.size:
            log("  [%s/%s] ★ 自检失败：有 %d 个**未点名**的顶点被改了 ⇒ 拒块"
                % (block, n, outside.size))
            return {"block": block, "rc": RC_FAIL}
        u1 = v1[idx, 1]
        resid = np.abs(u1 - (a * v1[idx, 0] + b * (-v1[idx, 2]) + c))
        new_v[n] = v1
        n_moved += int(moved.sum())
        gm[n] = {"n_vert": int(len(v0)), "n_sel": int(idx.size),
                 "n_moved": int(moved.sum()),
                 "plane": {"a": a, "b": b, "c": c},
                 "resid_max_after_m": float(resid.max()) if resid.size else None}
    if dry:
        log("  [%s] %d 个几何  点名 %d  实动 %d （--dry：不写盘）"
            % (block, len(gm), total_sel, n_moved))
        return {"block": block, "rc": RC_PASS, "n_sel": total_sel, "n_moved": n_moved, "geom": gm}

    for n in names:
        sc.geometry[n].vertices = new_v[n]
    dst_dir = os.path.join(out_dir, block)
    os.makedirs(dst_dir, exist_ok=True)
    dst = os.path.join(dst_dir, block + ".glb")
    sc.export(dst)

    # ---- 落盘后**重读**核对（第二把尺子：不采信内存里的 v1）----
    # ★ 分三条**互相独立**的尺子，不许合成一个 bool（铁律 183）：
    #   ① 未点名顶点三分量**逐位**不变（这才是契约）；② 点名顶点落盘后 ≤1 float32 ULP；
    #   ③ 面表与 UV **逐位**不变（本工具一个面、一个 UV 都不该碰）。
    sc2 = trimesh.load(dst, force="scene")
    n2 = list(sc2.geometry.keys())
    ok_keys = set(n2) == set(names)
    rest_exact = ok_keys
    moved_within_ulp, worst_ord = ok_keys, None
    face_exact, uv_exact = ok_keys, ok_keys
    for n in names:
        g2, g1 = sc2.geometry.get(n), sc.geometry[n]
        if g2 is None:
            rest_exact = moved_within_ulp = face_exact = uv_exact = False
            break
        v2 = np.asarray(g2.vertices, dtype=float)
        v1 = new_v[n]
        if v2.shape != v1.shape:
            rest_exact = moved_within_ulp = False
            break
        idx = np.asarray(by_geom.get(n) or [], dtype=int)
        rest = np.setdiff1d(np.arange(len(v1)), idx, assume_unique=True) if idx.size \
            else np.arange(len(v1))
        rest_exact &= bool(np.all(v2[rest] == v1[rest]))
        if idx.size:
            d = np.abs(v2[idx, 1] - v1[idx, 1])
            ulp = f32_ulp(v1[idx, 1])
            ok_u = bool(np.all(d <= ulp))
            moved_within_ulp &= ok_u
            if ulp.size:
                frac = float((d / np.maximum(ulp, 1e-300)).max())
                worst_ord = frac if worst_ord is None else max(worst_ord, frac)
        face_exact &= bool(np.all(np.asarray(g2.faces) == np.asarray(g1.faces)))
        u2 = None if g2.visual.uv is None else np.asarray(g2.visual.uv, dtype=float)
        u1 = None if g1.visual.uv is None else np.asarray(g1.visual.uv, dtype=float)
        if (u1 is None) != (u2 is None):
            uv_exact = False
        elif u1 is not None:
            uv_exact &= bool(u1.shape == u2.shape and np.all(u1 == u2))
    ok_round = ok_keys and rest_exact and moved_within_ulp and face_exact and uv_exact
    idx_file = os.path.join(dst_dir, "_index.json")
    with open(idx_file, "wb") as f:                 # 字节层写盘（铁律 79）
        f.write(json.dumps({
            "block": block, "at": utc_now(), "src": src, "src_sha256": sha256_file(src),
            "dst": dst, "dst_sha256": sha256_file(dst),
            "sel_file": sel.get("_path"), "sel_sha256": sel.get("_sha256"),
            "geom_names_src": names, "geom_names_dst": n2, "geom_names_match": ok_keys,
            "n_vert": int(sum(counts)), "n_geoms": len(names),
            "n_sel": int(total_sel), "n_moved": int(n_moved),
            "geom": gm,
            "roundtrip": {"rest_bitwise_exact": rest_exact,
                          "moved_within_1ulp": moved_within_ulp,
                          "moved_worst_ulp_fraction": worst_ord,
                          "face_bitwise_exact": face_exact,
                          "uv_bitwise_exact": uv_exact,
                          "all": ok_round},
            "uv_present": uv_any,
        }, ensure_ascii=False, indent=1).encode("utf-8"))
    log("  [%s] %d 个几何  点名 %d  实动 %d" % (block, len(names), total_sel, n_moved))
    log("        往返：未点名逐位=%s  点名≤1ULP=%s(最差 %.3f ULP)  面逐位=%s  UV逐位=%s"
        % (rest_exact, moved_within_ulp, worst_ord or 0.0, face_exact, uv_exact))
    log("        → %s" % dst)
    return {"block": block, "rc": RC_PASS if ok_round else RC_FAIL,
            "n_sel": total_sel, "n_moved": n_moved, "roundtrip_exact": ok_round, "geom": gm}


def main() -> int:
    ap = argparse.ArgumentParser(description="修模·第三刀：地面拟合压平（只改高程）")
    ap.add_argument("--blocks", nargs="*", default=None, help="只压这几个块（默认：_clean 下全部）")
    ap.add_argument("--clean", default=CLEAN)
    ap.add_argument("--flatten", default=FLATTEN)
    ap.add_argument("--sel-file", default=None, help="点名清单（apply 用）")
    ap.add_argument("--sel-out", default=None, help="--pick-box 的候选名单落这里")
    ap.add_argument("--pick-box", default=None, help="候选框，瓦片 ENU：x0,y0,x1,y1")
    ap.add_argument("--pick-up", type=float, default=20.0, help="候选：面法向与 +U 夹角上限（度）")
    ap.add_argument("--pick-zmax", type=float, default=None, help="候选：高程上限（米）")
    ap.add_argument("--level", action="store_true", help="压成水平面（不改坡度）")
    ap.add_argument("--dry", action="store_true", help="只算不写盘")
    args = ap.parse_args()
    clean_dir, out_dir = args.clean, args.flatten

    blocks = args.blocks
    if not blocks:
        if not os.path.isdir(clean_dir):
            log("_clean 不存在 ⇒ 没量到（rc=4）")
            return RC_NOGAUGE
        blocks = sorted(d for d in os.listdir(clean_dir)
                        if os.path.isdir(os.path.join(clean_dir, d)))

    # ---- 模式一：产出候选名单 ----
    if args.pick_box:
        if not args.sel_out:
            log("--pick-box 必须同时给 --sel-out ⇒ 没写盘")
            return RC_FAIL
        box = [float(x) for x in args.pick_box.split(",")]
        if len(box) != 4:
            log("--pick-box 要 4 个数：x0,y0,x1,y1")
            return RC_FAIL
        n = 0
        payload = {"z": SEL_VER, "at": utc_now(), "mode": "box", "box_enu": box,
                   "up_deg": args.pick_up, "z_max": args.pick_zmax, "blocks": {}}
        for b in blocks:
            sc, src = load_block(b, clean_dir)
            if sc is None:
                log("  [%s] _clean 下没有件 ⇒ 跳过" % b)
                continue
            gm = pick_box(sc, box, args.pick_up, args.pick_zmax)
            k = sum(len(v) for v in gm.values())
            payload["blocks"][b] = {"src": src, "src_sha256": sha256_file(src), "geom": gm}
            n += k
            log("  [%s] 候选 %d 个顶点（%d 个几何命中）" % (b, k, len(gm)))
        if n == 0:
            log("★ 候选为空 ⇒ 没量到（rc=4）：**别把空名单当成「不用压」**（铁律 137）")
            return RC_NOGAUGE
        os.makedirs(os.path.dirname(os.path.abspath(args.sel_out)), exist_ok=True)
        with open(args.sel_out, "wb") as f:
            f.write(json.dumps(payload, ensure_ascii=False, indent=1).encode("utf-8"))
        log("候选名单落盘（★ 人过目后再拿去 apply）：%s  共 %d 点" % (args.sel_out, n))
        return RC_PASS

    # ---- 模式二：按名单压平 ----
    if not args.sel_file:
        log("要么 --pick-box（产候选），要么 --sel-file（压平）⇒ 没量到（rc=4）")
        return RC_NOGAUGE
    with open(args.sel_file, encoding="utf-8") as f:
        sel = json.load(f)
    if sel.get("z") != SEL_VER:
        log("名单版本不认识：%s（本工具要 %s）" % (sel.get("z"), SEL_VER))
        return RC_FAIL
    sel["_path"] = os.path.abspath(args.sel_file)
    sel["_sha256"] = sha256_file(args.sel_file)

    rcs, rows = [], []
    for b in blocks:
        s = dict(sel.get("blocks", {}).get(b) or {})
        if not s:
            log("  [%s] 名单里没有这一块 ⇒ 跳过" % b)
            continue
        # ★★ 来源必须随**块条目**一起下去：`do_block` 读的是块条目 `s`，不是顶层 `sel`。
        #   第一版把 `_path`/`_sha256` 写在**顶层** ⇒ 落盘 `sel_file: null`
        #   ⇒ 闸（J-10.10-04）找不到声明文件、**整个判据降级成「声明点 0 个」**（铁律 196 的形状：
        #   主语被悄悄换掉 —— 形状照抄了、主语没抄）。这里补一句断言，缺就直接崩，不许静默写 null。
        if not sel.get("_path") or not sel.get("_sha256"):
            raise RuntimeError("内部错误：声明文件的 _path/_sha256 不在顶层 sel 上 ⇒ "
                               "不许落盘一个 sel_file=null 的索引（闸会因此找不到声明）")
        s["_path"] = sel["_path"]
        s["_sha256"] = sel["_sha256"]
        try:
            r = do_block(b, s, args.level, args.dry, clean_dir, out_dir)
        except Exception as e:                     # ★ 崩了要说「崩了」，不许与「没量到」同形（铁律 199）
            log("  [%s] ★ 崩了：%s: %s" % (b, type(e).__name__, e))
            r = {"block": b, "rc": RC_FAIL, "crash": "%s: %s" % (type(e).__name__, e)}
        if r:
            rcs.append(r["rc"])
            rows.append(r)
    if not rcs:
        log("★ 一块都没处理 ⇒ 没量到（rc=4）")
        return RC_NOGAUGE
    n_moved = sum(r.get("n_moved", 0) for r in rows)
    log("总判：%d 块，实动 %d 点，rc 集合 %s" % (len(rows), n_moved, sorted(set(rcs))))
    if any(r.get("crash") for r in rows):
        return RC_FAIL
    if n_moved == 0 and not args.dry:
        log("★ 一个点都没动 ⇒ 没量到（rc=4）：名单里的点**本来就在同一平面上**，"
            "这既可能是「已经平了」，也可能是「名单挑错了」——两者同形（铁律 199）")
        return RC_NOGAUGE
    return RC_PASS if all(r == RC_PASS for r in rcs) else RC_FAIL


if __name__ == "__main__":
    raise SystemExit(main())
