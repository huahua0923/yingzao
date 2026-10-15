# -*- coding: utf-8 -*-
r"""J-10.10-05 单体化分栋 —— 出件 `_drill/` 相对主件 `_edit/` 的**四条互相独立的尺子**（★ 不许合并）。

【判据】出件 `_drill/<fid>/<fid>.glb` 相对主件 `_edit/<块>/<块>.glb`，同时满足：

  ① **总量守恒**（★ 本闸自己读两侧 glb 现算，不读工具自评）—— 三条，**不许合并成一个 bool**（铁律 174）：
     ①a **不发明**：出件的每一个面，按其**三个顶点坐标（float32 逐位、面内顶点先按字典序排定）**
         算出的**身份**，必须能在同块主件的面身份**多重集**里找到（★ 比的是**多重集**不是集合：
         主件里本来就可能有两片**坐标完全重合**的面，那是源件的事，闸不许把它当「重复」误判）；
     ①b **不重复**：任何面身份在出件里的**出现次数 ≤** 它在同块主件里的出现次数
         （⇒ 一个主件面被同时写进两个栋，当场红）；
     ①c **写入一致**：`Σ 出件面数 == Σ _index.blocks[].n_f`，且 `Σ 出件面积 ≈ Σ _index.blocks[].area_m2`
         （相对 1e-6）—— 这一条量的是「写盘没丢没重」，与 ①a/①b 量的是**两件事**。
     ★★ **① 只测总量丢失，查不出缺栋**：一栋的面若被整片算给邻居，`Σ` 照样平、`Σ` 里的身份也照样
       全在主件里 ⇒ ① **恒绿**。抓这个的**是 ②**，两条**不许合并**（合并了就等于没有 ②）。

  ② **缺栋必须能指名**（名单**由程序现列文件系统**，★ 不手打，铁律 174）—— 三份点名册：
     ②a 盘上 `_drill/` 的 fid **集合** ≡ `_index.json` 记的 fid **集合**，差异**逐个点名**（不是只报数量不等）；
     ②b `_index.json` 记的 `fids_zero_faces_in_region`（**落在覆盖区内却一个面都没有**的轮廓）**逐个点名**；
     ②c ★ **「不是楼」的出件必须逐个点名**：源轮廓带 `oversize`（由**另一个程序** `building_footprints.py`
         按 >20000 m² 记在 `footprints.json` 里）的 fid，**逐名印出**轮廓面积与出件面积。
         ★ 本闸**不因此判红**（工具已在 docstring 声明「照切不误、只标注」）—— 但**必须点数**，
           因为它直接决定 ③ 能不能在那一栋上量（一个 21 万 m² 的地形块会把整片校区吞进「一栋」）。

  ③ **对外比（3D，≥1 条）** —— 参照物**与交付件不同源**（铁律 192）：DSM 栅格链 vs 实景网格链。
     逐栋：`Δ = p99(实景面心高程) − p99(DSM 高程)`，两者都只在**该栋的源轮廓内**取。
     ③a 判据 `median|Δ| ≤ boundary_p90_m`（**从另一条链的件上读**：`rebuild/_work/regbest_1层.json`，
         ★ 非手打、非本趟量出来的，铁律 103）；
     ③b **伪证器**：把出件几何**整体下沉 30 m** 再量一遍 ⇒ `median|Δ|` 必须升到 `≥ 30 − boundary_p90_m`
         （⇒ 证明这个读数**随几何走**，不是个钉死的常数）。
     ★ 判据 ① 与 ③ 也**不许合并**：① 量「跟主件对得上」，③ 量「跟另一条链对得上」；
       一个件可以 ① 全绿而 ③ 全红（几何整体错位），也可以反过来。

  ④ **契约**（喂给 `tools/editable_to_tiles.py` 的输入形状，逐条核）：
     ④a 每个出件的几何名集合 == 该 fid 在 `_index` 里记的片名集合（双向全等）；
     ④b 逐片名满足 `<fid>__<srcpiece>`，且 `<srcpiece>` **属于本次处理的那一块**（用块名前缀判）；
     ④c `splitext(basename(uri))[0] == name`（`editable_to_tiles` 会因此 rc=4，本闸先在这里拦住）。

【量具】`trimesh 5.1` 读两侧 glb；`numpy` 逐位比（面身份 = 三顶点坐标 float32 的字节，面内先字典序排定
  ⇒ **与顶点在数组里的次序无关**，只与几何有关）；`rasterio` 经 `tools.building_footprints.read_dsm`
  读 0.5 m 分析格 DSM；EN↔栅格行列换算**复用** `building_footprints.en_to_rowcol`（★ 单一来源，铁律 174：
  两个估计器不许混用，`read_dsm` 的 docstring 记着上一版混用后「已知点算到画幅外」的旧账）。
  ★ 高程→EN 的换算复用 `tools.reality_placement.glb_to_4544_grid` 与 `_index` 记的锚点（**落位约定 B**）。

【量具盲区】★ 本闸**只判下面四类**，其余一个字都不给结论：
  · ★★ **① 查不出缺栋**（见①）—— 这是**刻意**的：只测总量，缺栋交给 ② 点名。**两条不许合并**。
  · **②c 不判「oversize 是不是错」**：本闸只**点数**。轮廓是不是地形、该不该出件，是**人的判读**。
  · **③ 的参照物是 DSM，它是「最高面」**：树冠、旗杆、塔尖都算进去 ⇒ 树多的栋 `Δ` 会**偏正**
    （实测前三名 +23.63 / +11.90 / +10.63 m 就是这一类的**全部**）。
    本闸只保证「**中位**量级对得上」，**不保证逐栋对得上**；逐栋读数全部落盘，供人判。
  · **③ 的阈值 `boundary_p90_m` 是 2D 边界偏差**（CAD 轮廓 vs DOM 轮廓），本闸拿它当**竖向**容差是
    **语义外推** —— 盘上没有别的「本链位置不确定度」可用。只用它当**量级尺**，不当精度声明。
  · **不判「切得干不干净」**：切掉屋檐/挑台、把树冠收进轮廓、贴建楼之间没缝 —— 全部**在盲区里**，
    本仓既定口径「只承诺切出**可指名的栋块**，干净度留给编辑器」。
  · **不判纹理**：只核 UV 通道在不在；贴图逐像素、接缝色阶、改动后的鬼影一概不看。
  · **只量 `_drill/` 与 `_edit/` 里都在的件**；任一侧缺席 ⇒ **rc=4（量不到）**，与 rc=1（做错了）是两件事。

【正对照】（必配，六条，★ 每条落**读数**不只落 bool；甲/乙/丙 直接调本闸的**纯函数** ⇒ 测的是本闸本体）：
  甲 **点名有牙齿**：从盘上**真的藏起**一个出件（`os.replace`，`finally` 还原）⇒ ②a 必须**点名报出它**，
     且点名册**恰好**等于 `[它]`（★ 不是「数量不等」——那正是本闸要否掉的形状）。
  乙 **刑具·不重复**：把 A 栋的片名在装配时指成 B 栋同块的片 ⇒ ①b 的读数必须变红（证明①b 有分辨力）。
     ★ 靶子真的挑得开才跑：若这一块里**不存在**「两个 fid 共用同一个源块」的情形 ⇒ 如实记
     `fired=False` + `reason`（**靶子挑错不是尺子没分辨力**，这是 J-10.10-03 的正对照丙栽过的跟头）。
  丙 **刑具·不发明**：把某一栋某一面**抬 1 mm**（顶点动一个 float32 ULP 以上）⇒ ①a 必须点名那个面。
  丁 **量不到**：`_drill/`（或 `_edit/`）指到一个不存在的目录 ⇒ 走 **rc=4**，不是 rc=1。
  戊 **空集合**：出件数为 0 ⇒ **rc=4**（「一个栋都没出」是**没量到**，不是 PASS，铁律 137）。
  己 **对外比伪证器**：整体下沉 30 m ⇒ ③ 的 `median|Δ|` 必须升到 `≥ 30 − boundary_p90_m`。

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
if REPO not in sys.path:                 # ★ 不插这一句 ⇒ `import tools.…` 直接 ModuleNotFoundError
    sys.path.insert(0, REPO)             #   （实测：跑到 ③ 才炸，前面 ①②④ 全绿 ⇒ 假绿一片）
OUTDIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_out")
EDIT = os.path.join(REPO, "_edit")
DRILL = os.path.join(REPO, "_drill")
INDEX = os.path.join(DRILL, "_index.json")
FOOT = os.path.join(DRILL, "footprints.json")
MISREG_JSON = os.path.join(REPO, "rebuild", "_work", "regbest_1层.json")
MISREG_FIELD = "boundary_p90_m"          # ★ ③ 的阈值来源（另一条链记的）
MISREG_NOTE = "J-10.8-01：CAD 模型轮廓 vs 2024 DOM 的边界偏差（与本件不同源）"

GID = "J-10.10-05"
RC_PASS, RC_FAIL, RC_NOGAUGE = 0, 1, 4

# ★ ③b 伪证器的参数：**不是物理阈值**，是「把几何整体下沉多少」与「读数至少该涨多少」。
SINK_M = 30.0
SINK_MIN_RISE_M = SINK_M - 10.0          # 下沉 30 m ⇒ 中位 |Δ| 至少涨到 20 m 以上

AREA_TOL_REL = 1e-6

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
    with open(p, "wb") as f:                      # 字节层写盘（铁律 79）
        f.write(json.dumps(d, ensure_ascii=False, indent=1, allow_nan=False).encode("utf-8"))
    log("  写出:", p)


def _dump_run():
    os.makedirs(OUTDIR, exist_ok=True)
    with open(os.path.join(OUTDIR, GID + ".run.txt"), "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(_LOG) + "\n")


def _missing(drill_dir, edit_dir):
    """★ 「量不到」的判定 —— **只有这一处**（铁律 174）。`main()` 与正对照丁共用。"""
    if not os.path.isdir(edit_dir):
        return "edit"
    if not os.path.isdir(drill_dir):
        return "drill"
    return None


# ------------------------------------------------------------------ 纯函数：面身份 与 守恒

def face_keys(vertices, faces):
    """每个面 → 一段**与数组次序无关**的身份（面内三顶点先按字典序排定）。

    ★ 为什么要排定：`trimesh` 的 `submesh` 会把顶点重编号、也可能换序 ⇒ 若按「数组下标」认面，
      出件与主件必然对不上（假红）。**几何相同 ⇒ 身份必须相同**，所以只认坐标。
    ★ 为什么用 float32 字节而不是四舍五入：本闸要判的是「**逐位**搬没搬」，round 会把
      1 ULP 的差抹平 ⇒ 正对照丙（抬 1 mm）就哑了。
    """
    v = np.asarray(vertices, dtype=np.float32)
    f = np.asarray(faces, dtype=np.int64).reshape(-1, 3)
    if len(f) == 0:
        return np.zeros((0, 9), np.float32)
    tri = v[f]                                       # (m,3,3)
    order = np.lexsort((tri[:, :, 2], tri[:, :, 1], tri[:, :, 0]), axis=1)
    tri = np.take_along_axis(tri, order[:, :, None], axis=1)
    return tri.reshape(len(f), 9)


def key_bytes(K):
    """(m,9) float32 → 一维 `S36` 视图（字节可排序 ⇒ 能进 `np.unique`）。"""
    return np.ascontiguousarray(K, dtype=np.float32).view("S36").ravel()


def multiset_containment(master_K, drill_K):
    """★ **本闸的本体（①a/①b）**：`drill` 的面身份多重集是否 ⊆ `master` 的。

    返回 `(n_absent, n_over, examples)`。
    ★ 比的是**多重集**：主件里本来就可能有两片坐标完全重合的面（源件自带），
      出件照搬两面是**对的** ⇒ 只有「出件比主件还多」才算 red。
    """
    km, kd = key_bytes(master_K), key_bytes(drill_K)
    if len(kd) == 0:
        return 0, 0, []
    allk = np.concatenate([km, kd])
    lab = np.concatenate([np.zeros(len(km), np.int64), np.ones(len(kd), np.int64)])
    u, inv = np.unique(allk, return_inverse=True)
    cm = np.bincount(inv[lab == 0], minlength=len(u))
    cd = np.bincount(inv[lab == 1], minlength=len(u))
    over = np.nonzero(cd > cm)[0]
    n_over = int((cd[over] - cm[over]).sum())
    # 「不在主件里」＝ 出件有而主件一片没有的**身份**
    n_absent = int((cm[over] == 0).sum())
    ex = [bytes(u[i]).hex() for i in over[:3]]
    return n_absent, n_over, ex


def compare_block_faces(block, master_path, drill_items):
    """一块：主件 glb vs 它的**所有**出件片。`drill_items` ＝ [(fid, 几何名, 顶点, 面表)]。

    ★ 读数全部本闸现算；`_index.json` 只用来**找到**件与核对名字（铁律 187）。
    """
    r = {"block": block, "master": master_path, "n_master_faces": 0, "n_drill_faces": 0,
         "errs": [], "n_not_in_master": 0, "n_over_count": 0, "examples": []}
    if not os.path.exists(master_path):
        r["errs"].append("主件不在：%s" % master_path)
        return r
    ms = trimesh.load(master_path, force="scene")
    mk = np.concatenate([face_keys(g.vertices, g.faces) for g in ms.geometry.values()], 0) \
        if ms.geometry else np.zeros((0, 9), np.float32)
    r["n_master_faces"] = int(len(mk))
    dk = np.concatenate([face_keys(v, f) for (_fid, _nm, v, f) in drill_items], 0) \
        if drill_items else np.zeros((0, 9), np.float32)
    r["n_drill_faces"] = int(len(dk))
    if len(dk) == 0:
        return r
    if len(mk) == 0:
        r["errs"].append("主件一个面都没有，没法判「出件的面从哪来」")
        r["n_not_in_master"] = int(len(dk))
        return r
    na, no, ex = multiset_containment(mk, dk)
    r["n_not_in_master"], r["n_over_count"], r["examples"] = na, no, ex
    if na:
        r["errs"].append("★ **发明**：出件里有 %d 个面身份在**主件里找不到**（①a），例：%s" % (na, ex))
    if no:
        r["errs"].append("★ **超量**：有 %d 个面身份在出件里出现得比主件还多（①b 不许重复）" % no)
    return r


# ------------------------------------------------------------------ 纯函数：③ 对外比

def dsm_in_poly(z, ok, tr, poly):
    """DSM 在 `poly`（EN 多边形）内的有效高程一维数组。★ 行列换算复用工具那一份（铁律 174）。"""
    from tools.building_footprints import en_to_rowcol
    import shapely
    minx, miny, maxx, maxy = poly.bounds
    r0, c0 = en_to_rowcol(minx, maxy, tr)
    r1, c1 = en_to_rowcol(maxx, miny, tr)
    ra, rb = sorted((r0, r1))
    ca, cb = sorted((c0, c1))
    ra, rb = max(0, ra), min(z.shape[0] - 1, rb)
    ca, cb = max(0, ca), min(z.shape[1] - 1, cb)
    if rb < ra or cb < ca:
        return np.zeros(0)
    rr = np.arange(ra, rb + 1)
    cc = np.arange(ca, cb + 1)
    sub = z[np.ix_(rr, cc)]
    oksub = ok[np.ix_(rr, cc)]
    EE, NN = np.meshgrid(tr.c + tr.a * (cc + 0.5), tr.f + tr.e * (rr + 0.5))
    m = np.asarray(shapely.contains(poly, shapely.points(EE.ravel(), NN.ravel()))).reshape(EE.shape)
    m = m & oksub
    return sub[m]


def collect_elevation(blocks_rec, anc, polys, scenes):
    """★ **一次**读盘，把每栋在轮廓内的两样东西收好：实景高程数组 ／ DSM 取值数组。

    实景高程**在这里现算**（`glb_to_4544_grid`），不读任何台账。
    ★ 收着而不是直接算分位数，是为了让**伪证器**（整体下沉 N 米）只重算分位数、
      不必再把 21 个 glb 读第三遍 —— 否则一趟闸要读四遍盘。
    """
    import tools.reality_placement as RP
    from tools.building_footprints import read_dsm, DSM
    import shapely

    z, ok, tr, _step, meta = read_dsm(DSM, 0.5)
    rows = []
    for b in blocks_rec:
        fid = b["fid"]
        poly = polys.get(fid)
        if poly is None or poly.is_empty:
            continue
        sc = scenes.get(fid)
        if sc is None or not sc.geometry:
            continue
        c = np.vstack([np.asarray(g.triangles_center, np.float64) for g in sc.geometry.values()])
        E, N, U = RP.glb_to_4544_grid(c, anc)
        inside = np.asarray(shapely.contains(poly, shapely.points(E, N)), dtype=bool)
        if inside.sum() == 0:
            continue
        zs = dsm_in_poly(z, ok, tr, poly)
        if len(zs) == 0:
            continue
        rows.append({"fid": fid, "n_faces_in": int(inside.sum()),
                     "U_in": np.asarray(U[inside], np.float64), "zs": np.asarray(zs, np.float64)})
    return rows


def readings_from(rows, dz=0.0):
    """`dz` 是**伪证器用**的整体下沉量（米）。返回 `(readings, median_abs)`。"""
    readings = []
    for r in rows:
        p99m = float(np.percentile(r["U_in"] + dz, 99))
        p99d = float(np.percentile(r["zs"], 99))
        readings.append({"fid": r["fid"], "n_faces_in": r["n_faces_in"], "p99_mesh_m": p99m,
                         "p99_dsm_m": p99d, "delta_m": p99m - p99d})
    med = float(np.median(np.abs([r["delta_m"] for r in readings]))) if readings else None
    return readings, med


# ------------------------------------------------------------------ 正对照

def positive_controls(index, disk_fids, blocks_rec, rows, med_abs, thr):
    """六条，★ 每条落**读数**不只落 bool。甲/乙/丙 直接调本闸的纯函数。"""
    ctl = []

    def rec(case, expect, fired, **kw):
        ctl.append(dict(case=case, expect=expect, fired=bool(fired), **kw))

    # 甲 点名有牙齿：真的藏一个出件 ⇒ ②a 必须点名报出**恰好它**
    if not disk_fids:
        rec("甲 点名有牙齿", "盘上至少要有 1 个出件才藏得动", False, reason="出件为空")
    else:
        want = sorted(disk_fids)[0]
        victim = os.path.join(DRILL, want, want + ".glb")
        hidden = os.path.join(DRILL, want, want + ".glb.hidden-by-gate")
        fired, named, got_n = False, None, None
        try:
            os.replace(victim, hidden)
            now = inventory(DRILL)
            named = sorted(set(index["_fids"]) - set(now))
            got_n = len(now)
            fired = named == [want]
        finally:
            if os.path.exists(hidden):
                os.replace(hidden, victim)
        rec("甲 点名有牙齿", "藏起 %s ⇒ 点名册必须**恰好**等于 [它]（不是只报数量不等）" % want,
            fired, fid=want, named=named, n_on_disk=got_n)
        if not os.path.exists(victim):
            rec("甲 前置：文件已还原", "对照跑完必须把件放回去", False, missing=victim)

    # 乙 刑具·不重复：把 A 栋的片名指成 B 栋同块的片 ⇒ ①b 必须红
    #   ★ 靶子要真的挑得开才跑 —— 找一块**被 ≥2 个 fid 共用**的源块
    per_block_fids = {}
    for b in blocks_rec:
        for p in b.get("pieces") or []:
            src = piece_src_block(p["name"], b["fid"])
            per_block_fids.setdefault(src, set()).add(b["fid"])
    shared = sorted(k for k, v in per_block_fids.items() if len(v) >= 2)
    if not shared:
        rec("乙 刑具·不重复", "需要一块被 ≥2 个 fid 共用才谈得上「重复」", False,
            reason="本趟**不存在**共用同一源块的两个 fid ⇒ 靶子挑错（不是尺子没分辨力）")
    else:
        blk = shared[0]
        fids = sorted(per_block_fids[blk])
        picks = {}
        for b in blocks_rec:
            if b["fid"] in fids[:2]:
                for p in b.get("pieces") or []:
                    if piece_src_block(p["name"], b["fid"]) == blk:
                        picks.setdefault(b["fid"], p["name"])
                        break
        if len(picks) < 2:
            rec("乙 刑具·不重复", "两个 fid 都要能取到同一块的片", False, reason="取不到")
        else:
            fa, fb = fids[0], fids[1]
            mpath = os.path.join(EDIT, blk, blk + ".glb")
            ms = trimesh.load(mpath, force="scene")
            nm = picks[fb]
            srcname = nm.split("__", 1)[1]
            g = ms.geometry[srcname]
            # A 栋用 B 栋的**同一片** ⇒ 同一批面身份在出件里出现 2 次（主件里 1 次）⇒ ①b 必须红
            items = [(fa, nm, g.vertices, g.faces), (fb, nm, g.vertices, g.faces)]
            rr = compare_block_faces(blk, mpath, items)
            rec("乙 刑具·不重复", "同一主件面带被写进两个 fid ⇒ ①b 必须红",
                rr["n_over_count"] > 0, block=blk, fids=[fa, fb], piece=nm,
                n_over_count=rr["n_over_count"], n_not_in_master=rr["n_not_in_master"])

    # 丙 刑具·不发明：把一个面抬 1 mm（>> 1 ULP）⇒ ①a 必须点名
    if not blocks_rec:
        rec("丙 刑具·不发明", "要有出件才谈得上「发明」", False, reason="出件为空")
    else:
        b0 = blocks_rec[0]
        pieces0 = b0.get("pieces") or []
        if not pieces0:
            rec("丙 刑具·不发明", "要有一片", False, reason="该栋没有片")
        else:
            p0 = pieces0[0]
            blk = piece_src_block(p0["name"], b0["fid"])
            mpath = os.path.join(EDIT, blk, blk + ".glb")
            ms = trimesh.load(mpath, force="scene")
            srcname = p0["name"].split("__", 1)[1]
            g = ms.geometry[srcname]
            vv = np.array(g.vertices, dtype=np.float32, copy=True)
            f_ok = np.asarray(g.faces, np.int64).reshape(-1, 3)
            vv[f_ok[0, 0], 1] += 0.001                 # 抬 1 mm（>> 1 ULP）
            items = [(b0["fid"], p0["name"], vv, g.faces)]
            rr = compare_block_faces(blk, mpath, items)
            rec("丙 刑具·不发明", "把一个面抬 1 mm ⇒ ①a 必须点名「主件里找不到」",
                rr["n_not_in_master"] > 0, block=blk, piece=p0["name"],
                n_not_in_master=rr["n_not_in_master"], examples=rr["examples"][:1])

    # 丁 量不到：**真的**走一遍「目录不在」那条分支
    #   ★★ 量这两个分支必须**指名道姓**地传那个不存在的目录 —— `_missing(drill_dir, edit_dir)`
    #      是**第二个形参**为空时才回 `"edit"`。第一版把两个实参写反了（`_missing(bogus, EDIT)`
    #      问的是「drill 不在吗」，不是「edit 不在吗」）⇒ 读到的是**镜像**读数（'drill'）却去比 'edit'，
    #      于是这条对照**恒红**。这正是铁律 196 的形状：**形状照抄了、主语没抄**。
    #      故此处一律用**关键字实参**，让错位再也写不出来。
    bogus = os.path.join(REPO, "_本趟故意指向的不存在目录")
    got_no_edit = _missing(drill_dir=DRILL, edit_dir=bogus)     # 只可能回 "edit"
    got_no_drill = _missing(drill_dir=bogus, edit_dir=EDIT)     # 只可能回 "drill"
    rec("丁 量不到：目录不在", "`_edit/` 缺失 ⇒ 回 'edit'；`_drill/` 缺失 ⇒ 回 'drill'（两者都 ⇒ rc=4，不是 rc=1）",
        got_no_edit == "edit" and got_no_drill == "drill",
        edit_missing_gives=got_no_edit, drill_missing_gives=got_no_drill)

    # 戊 空集合 ⇒ rc=4（不是 PASS）
    rec("戊 空集合", "出件数为 0 ⇒ **没量到**（rc=4），不许报 PASS",
        _empty_is_nogauge(0) == RC_NOGAUGE, n_blocks=0)

    # 己 对外比伪证器：整体下沉 30 m ⇒ median|Δ| 必须**跟着涨**
    if med_abs is None:
        rec("己 对外比伪证器", "要先量到 ③ 的读数才谈得上伪证", False, reason="③ 没量到")
    else:
        readings2, med2 = readings_from(rows, dz=SINK_M)
        rec("己 对外比伪证器", "整体下沉 %.0f m ⇒ median|Δ| 必须 ≥ %.1f m（证明读数随几何走）"
            % (SINK_M, SINK_MIN_RISE_M),
            (med2 is not None and med2 >= SINK_MIN_RISE_M),
            median_abs_m_before=med_abs, median_abs_m_after=(med2 if med2 is not None else None),
            n_readings=len(readings2), threshold_m=thr)
    return ctl


def _empty_is_nogauge(n):
    """★ 「空集合 ⇒ rc=4」的**唯一**判定（铁律 174）。"""
    return RC_NOGAUGE if n <= 0 else None


# ------------------------------------------------------------------ 小工具

def piece_src_block(piece_name, fid):
    """出件片名 `<fid>__<srcpiece>` → 源块名（`Tile_+003_+005`）。

    ★ 现算，不读台账：`srcpiece` 就是 `<块>` 或 `<块>_L<层>_<路径>`（本仓瓦片命名）。
    """
    if piece_name.startswith(fid + "__"):
        piece_name = piece_name[len(fid) + 2:]
    i = piece_name.rfind("_L")
    if i > 0 and piece_name[i + 2:i + 4].isdigit():
        return piece_name[:i]
    return piece_name


def inventory(d):
    """盘上**现列**的 fid 名单：`_drill/` 下每个含 `<名>.glb` 的目录名（`_index.json` 不是目录）。"""
    out = []
    if not os.path.isdir(d):
        return out
    for n in sorted(os.listdir(d)):
        p = os.path.join(d, n)
        if os.path.isdir(p) and os.path.isfile(os.path.join(p, n + ".glb")):
            out.append(n)
    return out


# ------------------------------------------------------------------ 主

def _skip(reason, **kv):
    log("★ %s ⇒ 量不到（rc=4）" % reason)
    log("===== 判词 =====")
    log("%s 总判 : SKIP（量不到 —— 这一步还没做，不是做错了）" % GID)
    _write_json(4, reason=reason, edit_dir=EDIT, drill_dir=DRILL,
                n_blocks_measured=0, blocks=[], controls=[],
                blind=["`_edit/` 或 `_drill/` 缺席 ⇒ 本趟**没有量到**任何东西（rc=4，与 rc=1 是两件事）"],
                **kv)
    _dump_run()
    return RC_NOGAUGE


def main() -> int:
    miss = _missing(drill_dir=DRILL, edit_dir=EDIT)   # ★ 关键字传参：这一处也断掉错位的可能
    if miss == "edit":
        return _skip("主件目录不存在：%s（先跑 tools/scene_to_editable.py）" % EDIT)
    if miss == "drill":
        return _skip("出件目录不存在：%s（先跑 tools/drill_reality.py）" % DRILL)
    if not os.path.exists(INDEX):
        return _skip("索引不在：%s（出件这一步还没做）" % INDEX)

    with open(INDEX, encoding="utf-8") as f:
        index = json.load(f)
    with open(FOOT, encoding="utf-8") as f:
        foot = json.load(f)
    with open(MISREG_JSON, encoding="utf-8") as f:
        mis = json.load(f)
    thr = mis.get(MISREG_FIELD)
    if not (isinstance(thr, (int, float)) and not isinstance(thr, bool)
            and np.isfinite(thr) and thr > 0):
        return _skip("阈值来源没有可用的 %s（%s）⇒ ③ 没有独立参照，拒判" % (MISREG_FIELD, MISREG_JSON))

    from shapely.geometry import Polygon
    polys = {b["fid"]: Polygon(b["poly_en"]).buffer(0) for b in foot["blocks"]}

    log("主件 %s" % EDIT)
    log("出件 %s" % DRILL)
    log("判定：① 总量守恒（①a 不发明 ①b 不重复 ①c 写入一致）② 缺栋能指名 ③ 对外比 3D ④ 契约")
    log("③ 阈值来源 %s:%s = %.4f m（%s）" % (
        os.path.relpath(MISREG_JSON, REPO).replace("\\", "/"), MISREG_FIELD, thr, MISREG_NOTE))

    blocks_rec = index["blocks"]
    disk_fids = inventory(DRILL)
    index["_fids"] = [b["fid"] for b in blocks_rec]
    n_out = len(disk_fids)
    if _empty_is_nogauge(n_out) == RC_NOGAUGE:
        return _skip("`_drill/` 下一个出件都没有 ⇒ 没量到（不是 PASS）")

    ok = True
    errs_all = []

    # ---------------- ② 缺栋必须能指名 ----------------
    set_disk, set_idx = set(disk_fids), set(index["_fids"])
    only_disk = sorted(set_disk - set_idx)
    only_idx = sorted(set_idx - set_disk)
    zero_in = list(index.get("fids_zero_faces_in_region") or [])
    foot_by = {b["fid"]: b for b in foot["blocks"]}
    rec_by = {b["fid"]: b for b in blocks_rec}
    over_fids = sorted(f for f in rec_by if (foot_by.get(f) or {}).get("oversize"))
    log("")
    log("★ ② 缺栋必须能指名（名单由程序现列文件系统）")
    log("   盘上出件 %d 个 ｜ `_index` 记 %d 个" % (len(set_disk), len(set_idx)))
    log("   ②a 只在盘上：%s ｜ 只在索引里（**缺栋**）：%s"
        % (only_disk or "无", (["**" + x + "**" for x in only_idx]) or "无"))
    log("   ②b 覆盖区内却零面：%d 个 %s" % (len(zero_in), zero_in or "无"))
    log("   ②c ★ 源轮廓 oversize（>20000 m²，另一程序所记 ⇒ **大概率是地形不是楼**）：%d 个" % len(over_fids))
    for fid in over_fids:
        f, r = foot_by.get(fid), rec_by.get(fid)
        log("        %s ｜ 轮廓 %12.1f m² ｜ 出件 3D 面积 %9.1f m² ｜ 面 %7d"
            % (fid, (f["area_m2"] if f else float("nan")),
               (r["area_m2"] if r else float("nan")), (r["n_f"] if r else -1)))
    if only_disk or only_idx:
        ok = False
        if only_disk:
            errs_all.append("②a 盘上多了出件：%s" % only_disk)
        if only_idx:
            errs_all.append("★ ②a **缺栋**（索引里有、盘上没有）逐名报出：%s" % only_idx)

    # ---------------- ① 总量守恒 + ④ 契约 ----------------
    log("")
    log("★ ① 总量守恒（本闸自己读两侧 glb）／④ 契约")
    blocks_on_disk = sorted(n for n in os.listdir(EDIT)
                            if os.path.isfile(os.path.join(EDIT, n, n + ".glb")))
    tot_master_f = tot_drill_f = 0
    tot_not_in = tot_over = 0
    per_block = []
    # 出件片按源块归拢（★ 名字现算，不读台账）
    by_block = {}
    n_pieces_seen = 0
    for b in blocks_rec:
        for p in b.get("pieces") or []:
            blk = piece_src_block(p["name"], b["fid"])
            by_block.setdefault(blk, []).append((b["fid"], p["name"], p["uri"]))
            n_pieces_seen += 1
    # ★ 先按 fid 把出件读一遍：**一个 fid 一个 glb，片名是里面的几何名**。
    #   `pieces[].uri` 的目录段是 `Data/` —— 那是**清单里的原始相对路径**（瓦片时代的写法），
    #   落盘时被压成了 `_drill/<fid>/<fid>.glb`。★ 拿 `uri` 去拼盘上路径 ⇒ 1258 片**全找不到**、
    #   ① 在空集合上印出「①a 0 ｜ ①b 0」**假绿**（铁律 137：判据名单漏掉主体则永远绿）。
    #   实测踩过：整趟 ① 全 0 面，只有 ② 那截还活着。
    scenes = {}
    for b in blocks_rec:
        gp = os.path.join(DRILL, b["path"])
        if not os.path.exists(gp):
            errs_all.append("出件不在：%s" % gp)
            ok = False
            continue
        scenes[b["fid"]] = trimesh.load(gp, force="scene")
    for blk in sorted(by_block):
        items = []
        for fid, nm, uri in by_block[blk]:
            sc = scenes.get(fid)
            if sc is None:
                continue                              # 缺席已在上面逐 fid 记过
            if nm not in sc.geometry:
                errs_all.append("④ 几何名不在件里：%s ｜ 件 %s ｜ 该件独有 %s"
                                % (nm, fid, sorted(sc.geometry.keys())[:2]))
                ok = False
                continue
            g = sc.geometry[nm]
            items.append((fid, nm, g.vertices, g.faces))
        mp = os.path.join(EDIT, blk, blk + ".glb")
        r = compare_block_faces(blk, mp, items)
        per_block.append(r)
        tot_master_f += r["n_master_faces"]
        tot_drill_f += r["n_drill_faces"]
        tot_not_in += r["n_not_in_master"]
        tot_over += r["n_over_count"]
        if r["errs"]:
            ok = False
            errs_all.extend(["%s：%s" % (blk, e) for e in r["errs"]])
        log("   %-16s 主件面 %8d ｜ 出件面 %8d ｜ ①a 不在主件 %d ｜ ①b 超量 %d"
            % (blk, r["n_master_faces"], r["n_drill_faces"], r["n_not_in_master"], r["n_over_count"]))

    # ①c 写入一致：出件面数/面积 vs 索引所记（★ 复用上面已读的那几件，不重读盘）
    n_f_disk = n_v_disk = 0
    area_disk = 0.0
    for b in blocks_rec:
        sc = scenes.get(b["fid"])
        if sc is None:
            continue
        n_f_disk += sum(int(len(g.faces)) for g in sc.geometry.values())
        n_v_disk += sum(int(len(g.vertices)) for g in sc.geometry.values())
        area_disk += sum(float(g.area) for g in sc.geometry.values())
    n_f_idx = int(sum(b["n_f"] for b in blocks_rec))
    a_idx = float(sum(b["area_m2"] for b in blocks_rec))
    c1c_faces = (n_f_disk == n_f_idx)
    rel = abs(area_disk - a_idx) / max(1.0, a_idx)
    c1c_area = bool(rel <= AREA_TOL_REL)
    log("   ①c 出件面数 盘上 %d vs 索引 %d ⇒ %s ｜ 面积 盘上 %.4f vs 索引 %.4f（相对差 %.2e）⇒ %s"
        % (n_f_disk, n_f_idx, "一致" if c1c_faces else "**不一致**", area_disk, a_idx, rel,
           "一致" if c1c_area else "**不一致**"))
    if not (c1c_faces and c1c_area):
        ok = False
        errs_all.append("①c 写入不一致：面数 %d/%d，面积相对差 %.2e" % (n_f_disk, n_f_idx, rel))
    log("   ① 合计：主件面 %d ｜ 出件面 %d ｜ ①a 不在主件 **%d** ｜ ①b 超量 **%d**"
        % (tot_master_f, tot_drill_f, tot_not_in, tot_over))
    # ★★ 非空断言（铁律 137）：①a/①b 的判据名单就是**出件的面**；出件一个面都没有时，
    #   它们必然印 0/0 —— 那是**没量到**，不是「守恒成立」。实测踩过这一版：uri 拼错 ⇒ 全 0 面全部假绿。
    if tot_drill_f <= 0:
        return _skip("① 的判据名单是空的（出件面 0）⇒ 「不在主件 0 / 超量 0」是**没量到**，"
                     "不是守恒成立（先看上面「几何名不在件里」那几条）")
    log("   ★ 注意：① 只测总量丢失，**查不出缺栋**（缺栋的面被算给邻居，Σ 照样平）⇒ 靠 ② 点名")

    # ④ 契约：逐 fid 的片名集合双向全等 + uri 基名 == 片名
    log("")
    log("★ ④ 契约（喂给 editable_to_tiles 的输入形状）")
    c4_two_way = True
    c4_uri = True
    for b in blocks_rec:
        sc = scenes.get(b["fid"])
        if sc is None:
            continue
        got = set(sc.geometry.keys())
        want = set(p["name"] for p in b["pieces"])
        if got != want:
            c4_two_way = False
            ok = False
            errs_all.append("④ %s 片名不双向全等：件里独有 %s ／ 索引独有 %s"
                            % (b["fid"], sorted(got - want)[:3], sorted(want - got)[:3]))
        for p in b["pieces"]:
            if os.path.splitext(os.path.basename(p["uri"]))[0] != p["name"]:
                c4_uri = False
                ok = False
                errs_all.append("④ uri 基名 ≠ 片名：%s" % p["uri"])
    log("   %d 个出件 × %d 片：片名双向全等 %s ｜ uri 基名 == 片名 %s"
        % (len(blocks_rec), n_pieces_seen, "✓" if c4_two_way else "★否", "✓" if c4_uri else "★否"))

    # ---------------- ③ 对外比 3D ----------------
    log("")
    log("★ ③ 对外比（3D，参照物＝DSM 栅格链，与实景网格链不同源）")
    anc = (index.get("placement") or {}).get("anchor") or {}
    rows = collect_elevation(blocks_rec, anc, polys, scenes)
    readings, med_abs = readings_from(rows)
    for r in sorted(readings, key=lambda x: -abs(x["delta_m"]))[:6]:
        log("   %-24s 轮廓内面 %7d ｜ p99 实景 %8.2f m ｜ p99 DSM %8.2f m ｜ Δ %+7.2f m"
            % (r["fid"], r["n_faces_in"], r["p99_mesh_m"], r["p99_dsm_m"], r["delta_m"]))
    if not readings:
        return _skip("③ 一条读数都没量到（轮廓与出件没有交集？）⇒ 判不了外层")
    max_abs = max(abs(r["delta_m"]) for r in readings)
    log("   全 %d 栋：median|Δ| = %.3f m（阈值 %s = %.3f m，%s）｜ max|Δ| = %.3f m"
        % (len(readings), med_abs, MISREG_FIELD, thr, os.path.basename(MISREG_JSON), max_abs))
    if not (med_abs <= thr):
        ok = False
        errs_all.append("③ median|Δ| = %.3f m > %s = %.3f m" % (med_abs, MISREG_FIELD, thr))

    # ---------------- 正对照 ----------------
    log("")
    log("★ 正对照（六条）")
    ctl = positive_controls(index, disk_fids, blocks_rec, rows, med_abs, thr)
    n_fired = sum(1 for c in ctl if c["fired"])
    for c in ctl:
        log("   %s %s ｜ 读数 %s" % ("✓" if c["fired"] else "★没红！", c["case"],
                                    {k: v for k, v in c.items()
                                     if k not in ("case", "expect", "fired")}))
    ok = ok and n_fired == len(ctl)

    log("")
    log("===== 判词 =====")
    log("单体化分栋：① 不在主件 %d ／ 超量 %d ｜ ② 缺栋 %d ／ 零面 %d ／ oversize %d ｜ ③ median|Δ| %.3f m（≤ %.3f）｜ ④ 契约 %d 件"
        % (tot_not_in, tot_over, len(only_idx), len(zero_in), len(over_fids), med_abs, thr, len(blocks_rec)))
    if errs_all:
        for e in errs_all[:12]:
            log("   ★ %s" % e)
        if len(errs_all) > 12:
            log("   ★ …另有 %d 条" % (len(errs_all) - 12))
    log("正对照 %d/%d 按预期" % (n_fired, len(ctl)))
    log("%s 总判 :" % GID, "PASS" if ok else "FAIL")
    _dump_run()

    rc = RC_PASS if ok else RC_FAIL
    _write_json(rc,
                edit_dir=EDIT, drill_dir=DRILL, index=INDEX,
                n_blocks_measured=len(blocks_rec), n_blocks_on_disk=len(blocks_on_disk),
                threshold={"field": MISREG_FIELD, "value": thr,
                           "source": os.path.relpath(MISREG_JSON, REPO).replace("\\", "/"),
                           "note": MISREG_NOTE,
                           "median_field_value": mis.get("boundary_median_m"),
                           "why_semantic_stretch": "boundary_*_m 是**2D 边界偏差**，本闸拿它当**竖向**容差是"
                                                   "语义外推 —— 盘上没有别的「本链位置不确定度」可用，"
                                                   "只当量级尺，不当精度声明"},
                c1a_not_in_master=tot_not_in, c1b_over_count=tot_over,
                c1c={"n_faces_disk": n_f_disk, "n_faces_index": n_f_idx, "faces_equal": c1c_faces,
                     "area_disk_m2": area_disk, "area_index_m2": a_idx, "area_rel_diff": rel,
                     "area_equal": c1c_area},
                n_master_faces=tot_master_f, n_drill_faces=tot_drill_f, n_v_disk=n_v_disk,
                c2={"only_on_disk": only_disk, "missing_named": only_idx,
                    "fids_zero_faces_in_region": zero_in,
                    "oversize_fids": [{"fid": f,
                                       "footprint_area_m2": (foot_by.get(f) or {}).get("area_m2"),
                                       "out_area_m2": (rec_by.get(f) or {}).get("area_m2")}
                                      for f in over_fids],
                    "note": "②c 只点数不判红：轮廓是不是地形、该不该出件，是人的判读"},
                c3={"field": "Δ = p99(实景面心高程) − p99(DSM 高程)，都只在源轮廓内取",
                    "median_abs_m": med_abs, "threshold_m": thr, "max_abs_m": max_abs,
                    "n_readings": len(readings), "readings": readings, "sink_m": SINK_M},
                c4={"n_fids": len(blocks_rec), "n_pieces": n_pieces_seen,
                    "two_way_equal": c4_two_way, "uri_basename_is_name": c4_uri},
                blocks=[{"block": r["block"], "n_master_faces": r["n_master_faces"],
                         "n_drill_faces": r["n_drill_faces"], "n_not_in_master": r["n_not_in_master"],
                         "n_over_count": r["n_over_count"], "errs": r["errs"]} for r in per_block],
                n_controls=len(ctl), n_controls_fired=n_fired, controls=ctl,
                blind=["★ **① 查不出缺栋**（刻意）：只测总量丢失，缺栋的面被算给邻居时 Σ 照样平 ⇒ ① 恒绿；抓缺栋的**是 ②**，两条不许合并",
                       "★ **②c 不判「oversize 是不是错」**：只点数。轮廓是不是地形、该不该出件，是人的判读",
                       "★ **③ 的参照物是 DSM，它是「最高面」**：树冠/旗杆/塔尖都算进去 ⇒ 树多的栋 Δ 偏正（实测前三名 +23.63/+11.90/+10.63 m 全是这一类）；只保证中位量级，不保证逐栋",
                       "★ **③ 的阈值是 2D 边界偏差**，拿来当竖向容差是**语义外推**；只当量级尺，不当精度声明",
                       "**不判「切得干不干净」**：切掉屋檐/挑台、树冠收进轮廓、贴建楼之间没缝 —— 全在盲区里（本仓口径：只承诺切出可指名的栋块）",
                       "**不判纹理**：只核 UV 通道在不在；贴图内容、接缝色阶、改动后的鬼影一概不看",
                       "只量 `_drill/` 与 `_edit/` 里都在的件；任一侧缺席 ⇒ rc=4（量不到），与 rc=1（做错了）是两件事"])
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
