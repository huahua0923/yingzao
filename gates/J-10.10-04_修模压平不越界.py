# -*- coding: utf-8 -*-
r"""J-10.10-04 修模·第三刀（地面拟合压平）**不越界** —— 有损的那一刀，门开在「动过的点 ⊆ 声明的点」。

【判据】`_flatten/<块>/<块>.glb`（s3 压平件）相对 `_clean/<块>/<块>.glb`（s2 清洗件），**逐片**满足
  五条**互相独立**的约束（★ 不许合并成一个 bool，铁律 174）：
    ① **片结构逐位不变**：两侧几何名集合相同、逐片顶点数与**面表逐位**相等（本刀不动面）；
    ② ★★ **契约**：**未声明**的顶点**三分量逐位**不变（不含任何容差）；
    ③ **声明顶点只许动高程**：被动的分量只能是第 1 个（`y`＝U）；`x`（＝E）、`z`（＝−N）**逐位**不变；
    ④ **声明点落盘后落在平面上**，两条**互相独立**的尺子（★ 不许合并，铁律 183）：
       ④b 按**工具口径**（`plane_fit` 从 `tools/flatten_ground` **import**，单一来源铁律 174）拟出的平面，
          残差 ≤ **√3·ULP**（三个坐标分量各最多偏 1 个 float32 ULP ⇒ 残差 ≤ √3·ULP）——
          ★ 阈值**算出来的**，不手打（铁律 103）；
       ④a **SVD 独立口径**：s3 的声明点**自己**共面（不假设「高程是 E,N 的函数」，所以竖直面也认）。
      ★★ 这一格第一版判的是 `|ΔU| ≤ 1 ULP` —— **点移动了多远**，形状是错的：压平**本来就要求点动**
        （实测最远 0.3496 m），拿 1 ULP 去量位移＝把「按设计压平」读成「坏了」。1 ULP 管的是**落盘量化**；
    ⑤ **非空**：块数 > 0、声明点数 > 0、**实际动过的点数 > 0**（三者任一为 0 ⇒ 本闸**没量到** ⇒ rc=4）。

  ★ 判据的核心量是 **「工具实际动过的顶点集 ⊆ 声明集」**，而**实际动过的集合由本闸自己算**
    （逐片比 s2 与 s3 的顶点字节），**不读** `_flatten/_index.json` 里工具的自评（铁律 187）。

【量具】`trimesh 5.1` 读两侧 glb，`numpy` 逐位比（`==`，IEEE754 位等价）。
  声明集从 `_index.json` 记的 `sel_file` 读出，**先按 `sel_sha256` 重算哈希核对**（声明文件本身要是那一份）。
  ★ 本闸**不是**在核「工具有没有按它自己说的做」，而是在核「件有没有按**契约**做」——
    索引只用来**找到**声明文件并**证明它没被换过**，其余读数全部本闸自算。

【量具盲区】★ 本闸**只判「有没有越界」**，下面这几类它**一个字都不给结论**：
  · **不判「声明的是不是地面」**：本闸**无法**知道那批点该不该压 ——
    实测反例：旧口径（面心 ≤ 最低面心 + 2 m）选出的 395.7 m² 里绝大多数是**楼底下那层面（≈454.4 m）**。
    「压的是不是地面」是**人的判读**，不是几何性质；本闸只保证「你说动哪些，就只动了哪些」。
  · **不判压完对不对**：平面拟合的坡度、标高是否与真实地形一致，本闸**无独立参照**。
    （原出口门「压平后对 DSM 残差必须下降」**已作废**：DSM ＝ **最高面**、实景网格 ＝ **完整表面**，
      两者在同一 (E,N) 上差 11.38 m 是**定义差不是误差**，见 `tools/reality_placement.py`。）
  · **不判纹理**：只核 UV 通道**逐位**没动；压平后 UV 拉伸是否可接受属人判（要看渲染图）。
  · **不判「声明了却没动」是不是错**：点本来就落在平面上 ⇒ 不动是对的。本闸**只报数**不判红。
  · ★ **④ 的分辨力约 0.2 mm，比它更小的平面误差本闸看不见**：容差 `√3·ULP ≈ 2.11e-04 m` 是**上界**
    （被 E≈776 m 处的 ULP 主导），而**实测残差 1.743e-06 m 只占上界的 0.8%** ——
    判词必须把两个数**并排印**（本闸已印），否则「PASS」会被读成「残差 = 容差」。
  · 只量 `_clean/` 与 `_flatten/` 里**都已生成**的块；两侧块名不一致 ⇒ 报告里点名。

【正对照】（必配，五条，每条落**读数**不只落 bool）—— 甲/戊直接调本闸的**纯函数** `compare_piece`，
  测的就是本闸本体（不是另写一份口径）：
  甲 **刑具**：喂一份「把一个**未声明**顶点偷偷改了」的 s3 ⇒ 必须**红**（②当场响）。尺子的分辨力来源。
  乙 **真做事**：整块比 ⇒ 必须**真的动到 ≥1 个声明点**；否则 ①③④ 三条**恒绿**。
  丙 **空声明**：声明集为空 ⇒ 必须走 **rc=4「没量到」**，**不是** PASS（铁律 137）。
  丁 **量不到**：`_flatten/` 缺席 ⇒ **rc=4**（与 rc=1「做错了」是两件事）。
  戊 **越界下标**：声明里塞一个**超出顶点数**的下标 ⇒ 必须**红**（证明②的下标核对有牙齿）。

三态：`RC_PASS=0 / RC_FAIL=1 / RC_NOGAUGE=4`。
"""
from __future__ import annotations

import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import numpy as np  # noqa: E402
import trimesh  # noqa: E402

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTDIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_out")
CLEAN = os.path.join(REPO, "_clean")
FLAT = os.path.join(REPO, "_flatten")

sys.path.insert(0, REPO)
from tools.flatten_ground import SEL_VER, f32_ulp, plane_fit, sha256_file  # noqa: E402

GID = "J-10.10-04"
RC_PASS, RC_FAIL, RC_NOGAUGE = 0, 1, 4

_LOG = []


def log(*a):
    s = " ".join(str(x) for x in a)
    print(s)
    _LOG.append(s)


def _write_json(rc, **kv):
    d = {"pass": rc == 0, "rc": rc}
    d.update(kv)
    os.makedirs(OUTDIR, exist_ok=True)
    p = os.path.join(OUTDIR, GID + ".json")
    with open(p, "wb") as f:                       # 字节层写盘（铁律 79）
        f.write(json.dumps(d, ensure_ascii=False, indent=1).encode("utf-8"))
    log("  写出:", p)


def _rc_missing_dirs(clean_dir, flat_dir):
    """「量不到」的判定 —— ★ **本闸只有这一处**（铁律 174）。`main()` 与正对照丁共用。"""
    if not os.path.isdir(clean_dir):
        return "clean"
    if not os.path.isdir(flat_dir):
        return "flatten"
    return None


def _nogauges(n_blocks, n_decl, n_moved):
    """★ 「没量到」的**唯一**判定（铁律 174）—— `main()` 与正对照丙共用同一条。"""
    if n_blocks <= 0:
        return RC_NOGAUGE, "一块都没处理"
    if n_decl <= 0:
        return RC_NOGAUGE, "声明点数为 0 ⇒ 没有可核的东西"
    if n_moved <= 0:
        return RC_NOGAUGE, "声明点**一个都没动**（点本来就落在平面上？还是声明挑错了？）—— 两者同形"
    return None, None


# ------------------------------------------------------------------ 核心（纯函数）

def compare_piece(v0, f0, uv0, v1, f1, uv1, decl):
    """**本闸的本体**：比 s2/s3 的**一片**。纯函数 ⇒ 正对照甲/戊直接喂它（测的就是它）。

    `decl` 是**本地下标**列表（`_clean` 那一侧的编号）。返回 `(errs, readings)`。
    ★ 实际动过的集合**在这里现算**（`v1 != v0` 逐位），不看任何台账。
    """
    errs, rd = [], {}
    v0 = np.asarray(v0, dtype=float)
    v1 = np.asarray(v1, dtype=float)
    idx = np.asarray(decl, dtype=int)

    # ---- ① 片结构：顶点数、面表逐位 ----
    rd["n_vert"] = (int(len(v0)), int(len(v1)))
    rd["n_face"] = (int(len(f0)), int(len(f1)))
    if v1.shape != v0.shape:
        errs.append("顶点数变了：%s → %s（本刀只改坐标，不改拓扑）" % (v0.shape, v1.shape))
        return errs, rd
    if f1.shape != f0.shape or not bool(np.all(np.asarray(f1) == np.asarray(f0))):
        errs.append("面表被动了（%s → %s，或逐位不等）—— 本刀一个面都不许碰"
                    % (np.asarray(f0).shape, np.asarray(f1).shape))
    if (uv0 is None) != (uv1 is None):
        errs.append("UV 通道在不在都变了（s2 %s / s3 %s）"
                    % ("有" if uv0 is not None else "无", "有" if uv1 is not None else "无"))
    elif uv0 is not None:
        u0, u1 = np.asarray(uv0, dtype=float), np.asarray(uv1, dtype=float)
        rd["uv_bitwise_exact"] = bool(u0.shape == u1.shape and np.all(u0 == u1))
        if not rd["uv_bitwise_exact"]:
            errs.append("UV 被动了（逐位不等）—— 本刀不改 UV")

    # ---- 声明下标先过界检（★ 越界点名单：红，不静默丢，铁律 137）----
    bad = idx[(idx < 0) | (idx >= len(v0))]
    if bad.size:
        errs.append("声明里有 %d 个**越界**下标（顶点数 %d），例如 %s"
                    % (bad.size, len(v0), bad[:5].tolist()))
        return errs, rd

    # ---- 实际动过的集合：**现算**（逐位比）----
    moved = ~np.all(v1 == v0, axis=1)
    rd["n_moved"] = int(moved.sum())
    rd["n_decl"] = int(idx.size)
    decl_mask = np.zeros(len(v0), bool)
    if idx.size:
        decl_mask[idx] = True

    # ---- ② 契约：未声明顶点三分量逐位不变 ----
    out_of_bounds = np.where(moved & ~decl_mask)[0]
    rd["n_moved_outside_decl"] = int(out_of_bounds.size)
    if out_of_bounds.size:
        ex = out_of_bounds[0]
        errs.append("★ **越界**：有 %d 个**未声明**的顶点被改了，例如下标 %d（Δxyz=%s）"
                    % (out_of_bounds.size, int(ex),
                       np.round(v1[ex] - v0[ex], 8).tolist()))

    # ---- ③ 声明顶点只许动高程（第 1 个分量）----
    if idx.size:
        dx = v1[idx, 0] != v0[idx, 0]
        dz = v1[idx, 2] != v0[idx, 2]
        rd["n_decl_moved_in_x"] = int(dx.sum())
        rd["n_decl_moved_in_z"] = int(dz.sum())
        if dx.any() or dz.any():
            errs.append("声明顶点动了**水平**分量（x 动 %d 个、z 动 %d 个）——"
                        "压平只许改高程（glb 第 1 个分量 y）" % (int(dx.sum()), int(dz.sum())))
        rd["n_decl_not_moved"] = int((~moved[idx]).sum())   # ★ 只报数，不判红（点本就在平面上是对的）

    # ---- ④ 声明点**落在平面上**：两条**互相独立**的尺子（★ 不许合并，铁律 183）----
    #   ★★ 这一格第一版判的是 `|v1[idx,1] − v0[idx,1]| ≤ 1 ULP` —— **点移动了多远**。
    #     那是**错的形状**：压平**本来就要求点动**（实测最远动了 0.3496 m），拿「1 ULP」去量「动了多远」，
    #     等于把「按设计压平」读成「坏了」。1 ULP 管的是**落盘量化**，不是位移。
    #     （同族错误在本任务里已出现第四次；处置一律是**改判据、不放宽断言**。）
    if idx.size:
        a0, b0, c0 = plane_fit(v0, idx)              # ★ 平面口径**从工具 import**（单一来源，铁律 174）
        E1 = v1[idx, 0]
        N1 = -v1[idx, 2]
        U1 = v1[idx, 1]
        res_b = np.abs(U1 - (a0 * E1 + b0 * N1 + c0))
        # 阈值：三个坐标分量各最多偏 1 个 float32 ULP，单位法向 ⇒ 残差 ≤ √3·ULP。**算出来的**，不手打。
        ulp_max = float(max(f32_ulp(v1[idx, 0]).max(), f32_ulp(v1[idx, 1]).max(),
                            f32_ulp(-v1[idx, 2]).max()))
        tol = float(np.sqrt(3.0) * ulp_max)
        rd["plane_tol_m"] = tol
        rd["plane_resid_max_m"] = float(res_b.max())
        rd["on_tool_plane"] = bool(res_b.max() <= tol)
        if not rd["on_tool_plane"]:
            w = int(np.argmax(res_b))
            errs.append("声明点**不在平面上**：最差下标 %d 残差 %.3e m > √3·ULP=%.3e m"
                        % (int(idx[w]), res_b[w], tol))

        # ④a **独立几何**：s3 的声明点**自己**共面（SVD；不假设「高程是 E,N 的函数」，
        #     所以它连竖直面也认 —— 与 ④b 走的是**两条不同的路**，可互为伪证器）
        P = np.c_[E1, N1, U1]
        Pc = P - P.mean(0)
        if len(P) >= 4:
            _u, _s, vh = np.linalg.svd(Pc, full_matrices=False)
            res_a = np.abs(Pc @ vh[-1])
            rd["svd_coplanar_max_resid_m"] = float(res_a.max())
            rd["svd_coplanar"] = bool(res_a.max() <= tol)
            if not rd["svd_coplanar"]:
                errs.append("声明点**不共面**（SVD 独立口径）：最大离面 %.3e m > √3·ULP=%.3e m"
                            % (res_a.max(), tol))
        else:
            rd["svd_coplanar"] = None                # 少于 4 点拟不出平面 ⇒ 只报 None，不判红
        rd["max_vert_shift_m"] = float(np.abs((v1[idx] - v0[idx])[:, 1]).max())   # ★ 只报数
    return errs, rd


# ------------------------------------------------------------------ 逐块

def load_pieces(p):
    return dict(trimesh.load(p, force="scene").geometry)


def compare_block(blk, decl_by_geom):
    """`_clean/<blk>` vs `_flatten/<blk>` 逐片比。★ 读数全部本闸自己算，不读台账。"""
    src = os.path.join(CLEAN, blk, blk + ".glb")
    dst = os.path.join(FLAT, blk, blk + ".glb")
    r = {"block": blk, "src": src, "dst": dst, "errs": [], "pieces": {}}
    if not os.path.exists(src):
        r["errs"].append("s2 清洗件不在：%s" % src)
        return r
    if not os.path.exists(dst):
        r["errs"].append("s3 压平件不在（本块没压）：%s" % dst)
        return r

    a, b = load_pieces(src), load_pieces(dst)
    only_a, only_b = sorted(set(a) - set(b)), sorted(set(b) - set(a))
    r["only_in_clean"], r["only_in_flatten"] = only_a, only_b
    if only_a or only_b:
        r["errs"].append("两侧片名对不上：_clean 独有 %s，_flatten 独有 %s"
                         % (only_a or "无", only_b or "无"))
        return r
    unknown = sorted(n for n in decl_by_geom if n not in a)
    if unknown:
        r["errs"].append("声明里有本件没有的几何：%s" % unknown[:3])

    n_moved = n_decl = 0
    for name in sorted(a):
        ga, gb = a[name], b[name]
        uv0 = None if ga.visual.uv is None else np.asarray(ga.visual.uv)
        uv1 = None if gb.visual.uv is None else np.asarray(gb.visual.uv)
        errs, rd = compare_piece(ga.vertices, ga.faces, uv0,
                                 gb.vertices, gb.faces, uv1,
                                 decl_by_geom.get(name) or [])
        rd["piece"] = name
        r["pieces"][name] = rd
        n_moved += rd.get("n_moved") or 0
        n_decl += rd.get("n_decl") or 0
        if errs:
            r["errs"].extend(["%s：%s" % (name, e) for e in errs])
    r["n_pieces"] = len(a)
    r["n_decl"] = n_decl
    r["n_moved"] = n_moved
    r["n_moved_outside_decl"] = sum(v.get("n_moved_outside_decl") or 0 for v in r["pieces"].values())
    return r


def read_sel(index_json):
    """从 `_flatten/<blk>/_index.json` **只**取 `sel_file`/`sel_sha256`，**重算哈希核对**。

    ★ 只这两个字段的用途是「**找到**声明文件 + **证明它没被换过**」——
      工具自评的 `n_moved` / `roundtrip` **一个都不读**（铁律 187）。
    """
    if not os.path.exists(index_json):
        return None, "索引不在：%s" % index_json
    with open(index_json, encoding="utf-8") as f:
        ix = json.load(f)
    sp = ix.get("sel_file")
    if not sp or not os.path.isfile(sp):
        return None, "索引记的声明文件不在：%s" % sp
    got = sha256_file(sp)
    if got != ix.get("sel_sha256"):
        return None, "声明文件**被换过**：%s 现哈希 %s ≠ 索引记的 %s" % (sp, got, ix.get("sel_sha256"))
    with open(sp, encoding="utf-8") as f:
        sel = json.load(f)
    if sel.get("z") != SEL_VER:
        return None, "声明文件版本不认识：%s（本闸要 %s）" % (sel.get("z"), SEL_VER)
    sel["_src_path"] = sp
    return sel, None


# ------------------------------------------------------------------ 正对照

def positive_controls(blk, decl_by_geom):
    """五条正对照。★ 每条不只落 bool，落**读数**（学 J-07.9.4-03 的 controls 段）。"""
    ctl = []

    def rec(case, expect, fired, **kw):
        ctl.append(dict(case=case, expect=expect, fired=bool(fired), **kw))

    src = os.path.join(CLEAN, blk, blk + ".glb")
    dst = os.path.join(FLAT, blk, blk + ".glb")
    if not (os.path.exists(src) and os.path.exists(dst)):
        rec("甲~乙 前置", "s2 与 s3 都要在才能跑对照", False, src=src, dst=dst)
        return ctl

    a, b = load_pieces(src), load_pieces(dst)
    names = sorted(set(a) & set(b))
    if not names:
        rec("甲~乙 前置", "两侧要有同名片", False)
        return ctl

    # ★ 「拿哪一片、拿哪个下标」由**现算**定死（不手打，铁律 174）：
    #   甲要一个**未声明**的下标才谈得上「越界」；若整片都被声明了，就换下一片。
    pick = None
    for n in names:
        decl = set(int(i) for i in (decl_by_geom.get(n) or []))
        free = [i for i in range(len(np.asarray(a[n].vertices))) if i not in decl]
        if free:
            pick = (n, free[0])
            break

    # 甲 刑具：偷偷改一个**未声明**顶点 ⇒ ② 必须当场响
    if pick is None:
        rec("甲 刑具：改一个未声明顶点", "需要一片里存在未声明的顶点", False,
            reason="所有片的所有顶点都在声明集里 ⇒ 「越界」无从发生（靶子挑错，不是尺子没分辨力）")
    else:
        n, i = pick
        ga, gb = a[n], b[n]
        vv = np.array(gb.vertices, dtype=float, copy=True)
        vv[i, 1] += 1.0                            # 偷偷抬 1 m（未声明）
        errs, rd = compare_piece(ga.vertices, ga.faces,
                                 None if ga.visual.uv is None else np.asarray(ga.visual.uv),
                                 vv, gb.faces,
                                 None if gb.visual.uv is None else np.asarray(gb.visual.uv),
                                 decl_by_geom.get(n) or [])
        rec("甲 刑具：改一个未声明顶点", "必须红（②未声明顶点逐位不变 当场响）",
            any("越界" in e for e in errs), piece=n, tampered_idx=int(i),
            n_moved_outside_decl=rd.get("n_moved_outside_decl"),
            first_err=(errs[0][:120] if errs else None))

    # 乙 阴性对照：整块必须**真的动到东西**（否则 ①③④ 恒绿）
    tot = 0
    for n in names:
        va = np.asarray(a[n].vertices, dtype=float)
        vb = np.asarray(b[n].vertices, dtype=float)
        if va.shape == vb.shape:
            tot += int((~np.all(vb == va, axis=1)).sum())
    rec("乙 阴性对照：真动到声明点", "整块比 ⇒ 必须动到 ≥1 个顶点（否则①③④恒绿）",
        tot > 0, n_vert_changed_total=tot)

    # 丙 空声明 ⇒ 必须 rc=4（★ 直接走 `_nogauges` 那条判定，不是恒真式）
    rc_c, _why = _nogauges(n_blocks=1, n_decl=0, n_moved=1)
    rec("丙 空声明", "声明点数为 0 ⇒ 没量到（rc=4），**不许**报 PASS",
        rc_c == RC_NOGAUGE, n_decl=0, got_rc=rc_c)

    # 丁 量不到：**真的**走一遍「目录不在」那条分支
    bogus = os.path.join(REPO, "_本趟故意指向的不存在目录")
    rec("丁 量不到：目录不在", "`_clean/`／`_flatten/` 缺失 ⇒ 各归各的分支（⇒ rc=4，不是 rc=1）",
        _rc_missing_dirs(bogus, FLAT) == "clean" and _rc_missing_dirs(CLEAN, bogus) == "flatten",
        probe_dir=bogus, got_clean=_rc_missing_dirs(bogus, FLAT),
        got_flatten=_rc_missing_dirs(CLEAN, bogus))

    # 戊 越界下标：声明里塞一个超出顶点数的 ⇒ 必须红
    if pick is None:
        rec("戊 越界下标", "需要一片能调 compare_piece", False, reason="没有可用片")
    else:
        n, _i = pick
        ga, gb = a[n], b[n]
        over = [int(len(np.asarray(ga.vertices)))]
        errs, _rd = compare_piece(ga.vertices, ga.faces,
                                  None if ga.visual.uv is None else np.asarray(ga.visual.uv),
                                  gb.vertices, gb.faces,
                                  None if gb.visual.uv is None else np.asarray(gb.visual.uv),
                                  over)
        rec("戊 越界下标", "声明里含超出顶点数的下标 ⇒ 必须红",
            any("越界" in e for e in errs), piece=n, bad_idx=over,
            first_err=(errs[0][:120] if errs else None))
    return ctl


# ------------------------------------------------------------------ 主

def _skip(reason, **kv):
    log("★ %s ⇒ 量不到（rc=4）" % reason)
    log("===== 判词 =====")
    log("%s 总判 : SKIP（量不到 —— 这一步还没做，不是做错了）" % GID)
    os.makedirs(OUTDIR, exist_ok=True)
    _write_json(4, reason=reason, clean_dir=CLEAN, flatten_dir=FLAT,
                n_blocks_measured=0, blocks=[], controls=[],
                blind=["`_clean/` 或 `_flatten/` 缺席 ⇒ 本趟**没有量到**任何东西（rc=4，与 rc=1 是两件事）"],
                **kv)
    with open(os.path.join(OUTDIR, GID + ".run.txt"), "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(_LOG) + "\n")
    return RC_NOGAUGE


def main() -> int:
    miss = _rc_missing_dirs(CLEAN, FLAT)
    if miss == "clean":
        return _skip("s2 清洗件目录不存在：%s（先跑 tools/drop_floaters.py）" % CLEAN)
    if miss == "flatten":
        return _skip("s3 压平件目录不存在：%s（本刀还没跑）" % FLAT)

    blocks = sorted(n for n in os.listdir(FLAT)
                    if os.path.isfile(os.path.join(FLAT, n, n + ".glb")))
    if not blocks:
        return _skip("`_flatten/` 下没有产物（`*.glb` 一个都没有）")

    log("s2 清洗件 %s" % CLEAN)
    log("s3 压平件 %s" % FLAT)
    log("判定：① 片结构逐位不变 ② **未声明顶点三分量逐位不变** ③ 声明顶点只动高程 "
        "④ 声明点落盘在平面上(≤1 ULP) ⑤ 非空")

    ok, recs, sel_used, first_decl = True, [], {}, {}
    for i, blk in enumerate(blocks, 1):
        log("\n-- [%d/%d] %s --" % (i, len(blocks), blk))
        ij = os.path.join(FLAT, blk, "_index.json")
        sel, err = read_sel(ij)
        if err:
            log("   ★ %s" % err)
            ok = False
            recs.append({"block": blk, "errs": [err]})
            continue
        decl = (sel.get("blocks") or {}).get(blk, {}).get("geom") or {}
        if blk == blocks[0]:
            first_decl = decl
        sel_used[blk] = {"sel_file": sel.get("_src_path"), "n_geom": len(decl),
                         "n_decl": sum(len(v) for v in decl.values()),
                         "box_enu": sel.get("box_enu"), "up_deg": sel.get("up_deg"),
                         "z_max": sel.get("z_max")}
        r = compare_block(blk, decl)
        recs.append(r)
        if r.get("errs"):
            for e in r["errs"]:
                log("   ★ %s" % e)
            ok = False
            continue
        log("   片 %d ｜ 声明点 %d ｜ **实动点** %d ｜ 越界点 %d ｜ 声明了没动 %d"
            % (r["n_pieces"], r["n_decl"], r["n_moved"], r["n_moved_outside_decl"],
               sum(v.get("n_decl_not_moved") or 0 for v in r["pieces"].values())))
        for v in r["pieces"].values():
            if v.get("plane_resid_max_m") is not None:
                log("   [%s] 落盘后离面 max %.3e m（容差 √3·ULP=%.3e m）｜ "
                    "SVD 独立口径离面 %s ｜ 最大位移 %.3f m（**只报数**）"
                    % (v["piece"], v["plane_resid_max_m"], v["plane_tol_m"],
                       ("%.3e m" % v["svd_coplanar_max_resid_m"])
                       if v.get("svd_coplanar_max_resid_m") is not None else "点数<4 拟不出",
                       v.get("max_vert_shift_m") or 0.0))

    n_blocks = len(blocks)
    n_decl = sum(r.get("n_decl") or 0 for r in recs)
    n_moved = sum(r.get("n_moved") or 0 for r in recs)
    rc_ng, why_ng = _nogauges(n_blocks, n_decl, n_moved)

    ctl = positive_controls(blocks[0], first_decl)
    n_fired = sum(1 for c in ctl if c["fired"])
    for c in ctl:
        log("   正对照%s %s ｜ 读数 %s" % ("✓" if c["fired"] else "★没红！", c["case"],
                                        {k: v for k, v in c.items() if k not in ("case", "expect", "fired")}))
    ok = ok and n_fired == len(ctl)

    log("\n===== 判词 =====")
    log("压平不越界：块 %d 个，声明点 %d，**实动点 %d**，越界点 %d ⇒ %s"
        % (n_blocks, n_decl, n_moved, sum(r.get("n_moved_outside_decl") or 0 for r in recs),
           "PASS" if ok else "FAIL"))
    log("正对照 %d/%d 按预期" % (n_fired, len(ctl)))

    if rc_ng is not None and ok:
        log("★ %s ⇒ 没量到（rc=4）" % why_ng)
        log("%s 总判 : NOGAUGE（量不到 —— 不是做错了）" % GID)
        with open(os.path.join(OUTDIR, GID + ".run.txt"), "w", encoding="utf-8", newline="\n") as f:
            f.write("\n".join(_LOG) + "\n")
        _write_json(4, reason=why_ng, n_blocks_measured=n_blocks, blocks=blocks,
                    n_decl=n_decl, n_moved=n_moved, controls=ctl, results=recs,
                    declarations=sel_used)
        return RC_NOGAUGE

    log("%s 总判 :" % GID, "PASS" if ok else "FAIL")
    with open(os.path.join(OUTDIR, GID + ".run.txt"), "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(_LOG) + "\n")

    rc = RC_PASS if ok else RC_FAIL
    res_list = [v["plane_resid_max_m"] for r in recs for v in r.get("pieces", {}).values()
                if v.get("plane_resid_max_m") is not None]
    tol_list = [v["plane_tol_m"] for r in recs for v in r.get("pieces", {}).values()
                if v.get("plane_tol_m") is not None]
    _write_json(rc,
                clean_dir=CLEAN, flatten_dir=FLAT,
                n_blocks_measured=n_blocks, blocks=blocks,
                n_decl=n_decl, n_moved=n_moved,
                n_moved_outside_decl=sum(r.get("n_moved_outside_decl") or 0 for r in recs),
                n_decl_not_moved=sum(v.get("n_decl_not_moved") or 0
                                     for r in recs for v in r.get("pieces", {}).values()),
                on_tool_plane=all(v.get("on_tool_plane", True)
                                  for r in recs for v in r.get("pieces", {}).values()),
                svd_coplanar=all(v.get("svd_coplanar", True)
                                 for r in recs for v in r.get("pieces", {}).values()),
                plane_resid_max_m=(max(res_list) if res_list else None),
                plane_tol_m=(max(tol_list) if tol_list else None),
                uv_bitwise_exact=all(v.get("uv_bitwise_exact", True)
                                     for r in recs for v in r.get("pieces", {}).values()),
                declarations=sel_used,
                n_controls=len(ctl), n_controls_fired=n_fired, controls=ctl,
                results=recs,
                blind=["**不判「声明的是不是地面」**：本闸无法知道那批点该不该压 —— 实测旧口径选出的 395.7 m² 里绝大多数是楼底下那层面（≈454.4 m）",
                       "**不判压完对不对**：平面拟合的坡度/标高与真实地形是否一致，本闸无独立参照（原出口门「压平后 DSM 残差下降」已作废：DSM＝最高面、实景＝完整表面，差 11.38 m 是**定义差**）",
                       "**不判纹理**：只核 UV 逐位没动；压平后 UV 拉伸是否可接受属人判（要看渲染图）",
                       "**不判「声明了却没动」是不是错**：点本就在平面上 ⇒ 不动是对的；本闸只报数不判红",
                       "★ **④ 的分辨力约 0.2 mm**：容差 √3·ULP≈2.11e-04 m 是**上界**（被 E≈776 m 处 ULP 主导），实测残差 1.743e-06 m 只占 0.8%；两个数必须并排读，否则 PASS 会被误读成「残差＝容差」",
                       "只量 `_clean/` 与 `_flatten/` 里都已生成的块；两侧块名不一致 ⇒ 报告里点名",
                       "`_clean/`／`_flatten/` 缺席 ⇒ rc=4（量不到），与 rc=1（做错了）是两件事"])
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
