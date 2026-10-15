# -*- coding: utf-8 -*-
r"""J-10.10-06 回切件的**帧**逐位复现源件 —— 步 3 的第二半（`_drill/` → `_回切_按栋/`）的出口门。

【判据】`_回切_按栋/tileset.json`（**交付件**）的**根帧**与源 `_fly2024_tiles/tileset.json`
  的根帧**逐位相同** —— 「逐位」＝ `struct.pack("<16d", …)` **逐字节**比，**不是** float 容差比、
  **也不是** float `==`（★ 后者对 `-0.0` 与 `+0.0` 会印「相等」，那是**符号位丢了**）。四条：
    ① 根 `transform` 16 个数 **0 字节差**；
    ② 根 `geometricError` **逐位**相等（LOD 细化深度靠它，不是装饰）；
    ③ `asset.version` / `asset.gltfUpAxis` 相同 —— ★ `gltfUpAxis=Y` 是 `(x,−z,y)` 翻转成立的前提；
       换成 `Z` 整个叠层**转 90°**，瓦片在新旧层里会「躺下」，而**这条改动在几何里看不见**；
    ④ ★ **量具适用范围自证**：两侧「带 `transform` 的节点数」**各自恰为 1**（＝只有根）。
       ★ 若不是 1 ⇒ 本闸**盖不到**那些变换 ⇒ **rc=4「没量到」**，不是 PASS 也不是 FAIL（铁律 158）。

  ★★ 另有一条**独立的**佐证，与本判据**不同源**：`_回切_按栋/_index.json` 记的
    `src_tileset.sha256` 必须等于**盘上**源件现算的 sha256 —— 否则「出件帧 == 源帧」这话
    **没有主语**（拿哪一份源件比的？）。两条都查（铁律 187：基线与期望值来自两次不同读数）。

  ★★★ **与 `J-10.10-01` ③ 的关系（必须写死，否则日后被读成「同一个量两条尺子」）**：
    `J-10.10-01` ③ 量的是**同一条谓词**，但**主语不同** —— 它量**单块**、写进**临时工作目录**
    （`_scratch/_gate_reality/`）的那次回切，用来判「`editable_to_tiles` 这个**工具**在单块上复不复现帧」；
    本闸量的是**步 3 交付的 21 块合计件**本身。两者**不许合并**：单块绿推不出合计件绿
    （合计那次是另一次调用、另一次读源件）。★ 若两者哪天**打架**，以**本闸为准**（本闸更严：逐字节 vs `==`）。
    ⇒ 这是「**一条谓词、两个主语**」，不是「两个同名的量」；铁律 174 管的是后者。

【量具】本闸**自己**用 `json` 读两侧的 `tileset.json` ＋ `struct.pack("<16d", …)` 逐字节比。
  ★ **不采信** `editable_to_tiles.py` 打印的「★ 锚定逐位复现 source root.transform ? True（最大差 0.0）」——
    那是**交付方自己的读数**（`_index.json:tileset.verify` 同形）；本闸把它**印出来对照**，但**不作证据**。
  ★ 不比几何：两侧 glb 一个字节都不读（那是 `J-10.10-01` 的活）。

【量具盲区】★ 本闸**只判「帧」**，下面这几类它**一个字都不给结论**：
  · **不判几何**：往返（逐片面数 / 顶点 / 包围盒）本闸**不覆盖**。★ 如实：
    本趟「21 栋逐片包围盒最大差 0.000000 m／顶点差 ≤0／面数差 ≤0」那组读数是
    **`editable_to_tiles.py` 自评**（落在 `_index.json:results[]`），**不是**闸的读数。
  · **不判包围盒**：源件根包围盒是 **sphere**、回切件是 **box**（表达不同，非错）；根包盒由回切**现算**
    ⇒ 它**与源件不同不算错**（源件那 16 个包围盒数**被人手改过**，见 `_fly2024_tiles/tileset.json.bad_inflated`）。
  · **不判 URI 命名**：`Data/Tile_+…/…`（源）vs `Data/bldg_…/…`（出件）**对不上号**是**已知且如实记录**的
    ⇒ 2094 个节点查不到 `geometricError` 而退回根值。★ 本闸**只报 `tileset.verify.geo_err_fallback` 这个数**，不判红。
  · **不判「子节点的变换」**：只把**个数**数出来当 ④；★ 有子变换 ⇒ rc=4（量不到），**不是**「子变换错了」。
  · **不判「源件自己是不是对的」**：源件若被换过/改坏，本闸会照它比 ⇒ 「一致」只说明**没走样**，
    不说明**锚定正确**（锚定正确性属 `_scratch/_probe_转角.py` 那条 A/B 线，且该线**符号未决**）。
  · 只核**这一份**交付件；`_回切_按栋/` 缺席 ⇒ rc=4（量不到），与 rc=1（做错了）是两件事。

【正对照】（必配，六条，每条落**读数**不只落 bool）—— 全部**经读盘路径**（写临时副本再读回），
  测的是本闸本体，不是另写一份口径：
  甲 **刑具·1 ULP**：出件根 `transform` 末位改 1 个 ULP ⇒ 必须**红**（尺子的分辨力来源）。
  乙 ★ **反面教材·容差尺会印绿**：**同一个** 1 ULP 的改动，用 `abs(a-b) < 1e-9` 的**容差口径**去比
     ⇒ 必须**报「相等」** —— 这条证明「为什么必须逐字节」。★ 那个容差比较器**只活在对照里**，绝不许当判据。
  丙 **坐标系约定**：出件 `asset.gltfUpAxis` 改 `Z` ⇒ 必须**红**（几何里看不见的那一类）。
  丁 **根误差**：出件根 `geometricError` 改 1 ULP ⇒ 必须**红**。
  戊 **主语**：出件 `_index.json:src_tileset.sha256` 改成别的一份 ⇒ 必须**红**（「拿哪份源件比的」）。
  己 **量不到**：① 源件/出件不在 ⇒ rc=4；② 合成一份「根之外还有一个 `transform`」⇒ **rc=4**。

三态：`RC_PASS=0 / RC_FAIL=1 / RC_NOGAUGE=4`。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import struct
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import numpy as np  # noqa: E402

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTDIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_out")

sys.path.insert(0, REPO)
from tools.editable_to_tiles import DEFAULT_SRC  # noqa: E402  ★ 源件路径全仓只有一处定义（铁律 174）

GID = "J-10.10-06"
RC_PASS, RC_FAIL, RC_NOGAUGE = 0, 1, 4

# ★ 交付目录名。★ 刻意**不是** `editable_to_tiles.DEFAULT_OUT`（那个是 `_回切_tiles`，步 1 用的名字）——
#   这里是步 3「按栋回切」的交付件。两者**不是**同一个东西，所以**不许**用工具默认值兜底当唯一来源。
DELIV_NAME = "_回切_按栋"
N_ROOT_TRANSFORMS = 1        # ★ 量具覆盖范围：只盖根。多于这个数 ⇒ rc=4（铁律 158）

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
        f.write(json.dumps(d, ensure_ascii=False, indent=1, allow_nan=False).encode("utf-8"))
    log("  写出:", p)


def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


# ------------------------------------------------------------------ 核心（纯函数）

def read_json(path):
    with open(path, "rb") as f:                    # 字节层读（铁律 79）
        return json.loads(f.read().decode("utf-8"))


def count_transform_nodes(node, depth=0, stats=None):
    """数**整棵**树里带 `transform` 的节点数 ＋ 节点总数 ＋ 最大深度。"""
    if stats is None:
        stats = {"n_node": 0, "n_transform": 0, "depth": 0}
    stats["n_node"] += 1
    stats["depth"] = max(stats["depth"], depth)
    if "transform" in node:
        stats["n_transform"] += 1
    for c in (node.get("children") or []):
        count_transform_nodes(c, depth + 1, stats)
    return stats


def frame_facts(path):
    """只抽**帧**相关的字段（一进一出，纯函数 ⇒ 正对照直接喂它）。"""
    raw = open(path, "rb").read()
    d = json.loads(raw.decode("utf-8"))
    root = d.get("root") or {}
    asset = d.get("asset") or {}
    t = root.get("transform")
    st = count_transform_nodes(root)
    return {
        "path": path,
        "sha256": hashlib.sha256(raw).hexdigest(),
        "n_bytes": len(raw),
        "asset_version": asset.get("version"),
        "gltf_up_axis": asset.get("gltfUpAxis"),
        "extras": asset.get("extras"),
        "root_geometric_error": root.get("geometricError"),
        "root_refine": root.get("refine"),
        "has_transform": t is not None,
        "transform": [float(x) for x in t] if t else None,
        "n_transform_nodes": int(st["n_transform"]),
        "n_nodes": int(st["n_node"]),
        "max_depth": int(st["depth"]),
    }


def _bits(x):
    """一个 float 的 IEEE754 位串（float64）。★ `-0.0` 与 `+0.0` 在这里**不相等**（正是我们要的）。"""
    return struct.pack("<d", float(x))


def transform_diff_bytes(a, b):
    """返回 `(逐字节相等?, 不同字节数, 首个不同元素的下标)`。`a`＝源、`b`＝出件。"""
    if a is None or b is None or len(a) != 16 or len(b) != 16:
        return False, None, None
    bs_a = b"".join(_bits(x) for x in a)
    bs_b = b"".join(_bits(x) for x in b)
    n_diff = sum(1 for p, q in zip(bs_a, bs_b) if p != q)
    first = next((i for i in range(16) if _bits(a[i]) != _bits(b[i])), None)
    return n_diff == 0, n_diff, first


def compare_frames(src, dst):
    """**本闸的本体**：比源件与出件的帧。纯函数 ⇒ 正对照全部喂它。返回 `(errs, readings)`。"""
    errs, rd = [], {}
    rd["src_sha256"] = src["sha256"]
    rd["dst_sha256"] = dst["sha256"]
    rd["src_n_nodes"] = src["n_nodes"]
    rd["dst_n_nodes"] = dst["n_nodes"]
    rd["src_n_transform_nodes"] = src["n_transform_nodes"]
    rd["dst_n_transform_nodes"] = dst["n_transform_nodes"]

    # ---- ① 根 transform 逐字节 ----
    if not src["has_transform"] or not dst["has_transform"]:
        errs.append("根 transform 缺席（源 %s / 出件 %s）"
                    % ("有" if src["has_transform"] else "**无**",
                       "有" if dst["has_transform"] else "**无**"))
        return errs, rd
    eq, n_diff, first = transform_diff_bytes(src["transform"], dst["transform"])
    rd["transform_bitmatch"] = bool(eq)
    rd["transform_diff_bytes"] = n_diff
    rd["transform_first_diff_index"] = first
    rd["transform_max_abs"] = max(abs(p - q) for p, q in zip(src["transform"], dst["transform"]))
    if not eq:
        errs.append("★ 根 transform **逐位不等**：%d 个字节不同，首个不同的分量下标 %s" % (n_diff, first))

    # ---- ② 根 geometricError 逐位 ----
    ge_s, ge_d = src["root_geometric_error"], dst["root_geometric_error"]
    rd["root_ge"] = (ge_s, ge_d)
    if ge_s is None or ge_d is None:
        errs.append("根 geometricError 缺席（源 %r / 出件 %r）" % (ge_s, ge_d))
    else:
        rd["root_ge_bitmatch"] = _bits(ge_s) == _bits(ge_d)
        if not rd["root_ge_bitmatch"]:
            errs.append("★ 根 geometricError **逐位不等**：%r vs %r（差 %.3e）"
                        % (ge_s, ge_d, abs(ge_s - ge_d)))

    # ---- ③ asset 版本与 up 轴 ----
    rd["asset_version"] = (src["asset_version"], dst["asset_version"])
    rd["gltf_up_axis"] = (src["gltf_up_axis"], dst["gltf_up_axis"])
    if src["asset_version"] != dst["asset_version"]:
        errs.append("asset.version 不同：%r vs %r" % (src["asset_version"], dst["asset_version"]))
    if src["gltf_up_axis"] != dst["gltf_up_axis"]:
        errs.append("★ asset.gltfUpAxis 不同：%r vs %r —— 这一改**在几何里看不见**，整个叠层转 90°"
                    % (src["gltf_up_axis"], dst["gltf_up_axis"]))
    rd["root_refine"] = (src["root_refine"], dst["root_refine"])
    if src["root_refine"] != dst["root_refine"]:
        errs.append("root.refine 不同：%r vs %r" % (src["root_refine"], dst["root_refine"]))
    return errs, rd


def _apply_ulp(d, i=15, field=("root", "transform")):
    """把 `d` 的某个 float **提高 1 个 ULP**（就地改；只在临时副本上用）。"""
    o = d
    for k in field[:-1]:
        o = o[k]
    v = o[field[-1]][i]
    o[field[-1]][i] = float(np.nextafter(np.float64(v), np.float64(np.inf)))


# ------------------------------------------------------------------ 正对照

def _tol_equal_naive(a, b, tol=1e-9):
    """★ **反面教材**：容差口径。**只允许出现在对照里**，绝不许当判据 ——
    它会把「1 个 ULP 的改动」判成「相等」（见正对照乙）。"""
    return all(abs(p - q) < tol for p, q in zip(a, b))


def positive_controls(src_path, dst_path, tmp):
    """六条，全部**写临时副本再读回**（走读盘路径，不是凭空造 dict）。返回 list of dict。"""
    out = []

    def rec(name, expect, fired, **kv):
        out.append({"case": name, "expect": expect, "fired": bool(fired), **kv})

    src = frame_facts(src_path)

    def mutated(tag, fn, base=None):
        p = os.path.join(tmp, tag)
        d = read_json(base or dst_path)
        fn(d)
        with open(p, "wb") as f:                   # 字节层写盘（铁律 79）
            f.write(json.dumps(d, ensure_ascii=False, allow_nan=False).encode("utf-8"))
        return p

    # 甲 1 ULP ⇒ 必须红
    p = mutated("a_ulp.json", lambda d: _apply_ulp(d))
    fa = frame_facts(p)
    errs, rd = compare_frames(src, fa)
    rec("甲 刑具·根transform 末位 +1ULP", "红", bool(errs),
        n_diff_bytes=rd.get("transform_diff_bytes"), first_diff_index=rd.get("transform_first_diff_index"),
        max_abs=rd.get("transform_max_abs"))

    # 乙 反面教材：同一个改动，容差尺必须印「相等」
    naive_says_equal = _tol_equal_naive(src["transform"], fa["transform"], tol=1e-9)
    rec("乙 反面教材·容差尺(1e-9)对同一改动", "印「相等」(错尺恒绿)", naive_says_equal,
        naive_verdict=("相等" if naive_says_equal else "不等"),
        bitwise_verdict=("不等" if not rd.get("transform_bitmatch") else "相等"))

    # 丙 gltfUpAxis ⇒ Z ⇒ 必须红
    p = mutated("c_upaxis.json", lambda d: d["asset"].__setitem__("gltfUpAxis", "Z"))
    errs, rd = compare_frames(src, frame_facts(p))
    rec("丙 坐标系约定·gltfUpAxis Y→Z", "红", bool(errs),
        up_axis=rd.get("gltf_up_axis"), transform_bitmatch=rd.get("transform_bitmatch"))

    # 丁 根 geometricError +1ULP ⇒ 必须红
    def _ge(d):
        d["root"]["geometricError"] = float(np.nextafter(np.float64(d["root"]["geometricError"]),
                                                         np.float64(np.inf)))
    p = mutated("d_ge.json", _ge)
    errs, rd = compare_frames(src, frame_facts(p))
    rec("丁 根 geometricError +1ULP", "红", bool(errs), root_ge=rd.get("root_ge"),
        bitmatch=rd.get("root_ge_bitmatch"), transform_bitmatch=rd.get("transform_bitmatch"))

    # 戊 主语：合成一份索引，把 src_tileset.sha256 换成别的 ⇒ 用**真索引的比较函数**判
    idx_src = os.path.join(os.path.dirname(dst_path), "_index.json")
    if os.path.isfile(idx_src):
        idx = read_json(idx_src)
        good = src_hash_matches(idx, src["sha256"])
        bad = dict(idx)
        bad["src_tileset"] = dict(idx.get("src_tileset") or {})
        bad["src_tileset"]["sha256"] = "0" * 64
        p = os.path.join(tmp, "e_index.json")
        with open(p, "wb") as f:
            f.write(json.dumps(bad, ensure_ascii=False, allow_nan=False).encode("utf-8"))
        rec("戊 主语·索引记的 src_tileset.sha256 换成 0*64", "红（好索引绿/坏索引红两读都落）",
            (good is True) and (src_hash_matches(read_json(p), src["sha256"]) is False),
            good_index_says=good, bad_index_says=src_hash_matches(read_json(p), src["sha256"]))
    else:
        rec("戊 主语·索引不在 ⇒ 无从核", "本趟没量到", False, note="`_index.json` 缺席")

    # 己 量不到：合成一份「根之外还有一个 transform」⇒ 必须被判「量具盖不到」
    def _extra(d):
        ch = d["root"].get("children") or []
        if ch:
            ch[0]["transform"] = list(d["root"]["transform"])
    p = mutated("f_extra_transform.json", _extra)
    fe = frame_facts(p)
    rec("己 量不到·根之外多一个 transform ⇒ rc=4（不是 PASS/FAIL）",
        "量具覆盖不足", fe["n_transform_nodes"] != N_ROOT_TRANSFORMS,
        n_transform_nodes_src=src["n_transform_nodes"],
        n_transform_nodes_fake=fe["n_transform_nodes"])
    return out


def src_hash_matches(idx, actual_src_sha256):
    """★ 主语核对 —— **只有这一处**（铁律 174）：`main()` 与正对照戊共用同一函数。"""
    rec = (idx.get("src_tileset") or {}).get("sha256")
    if not rec:
        return None                                # 索引没记 ⇒ **没量到**，不是「不符」
    return rec == actual_src_sha256


def _skip(reason, **kv):
    log("★ %s ⇒ 量不到（rc=4）" % reason)
    log("===== 判词 =====")
    log("%s 总判 : SKIP（量不到 —— 这一步还没做，不是做错了）" % GID)
    os.makedirs(OUTDIR, exist_ok=True)
    _write_json(4, reason=reason, controls=[], **kv)
    with open(os.path.join(OUTDIR, GID + ".run.txt"), "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(_LOG) + "\n")
    return RC_NOGAUGE


# ------------------------------------------------------------------ main

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="J-10.10-06 回切件帧逐位")
    ap.add_argument("--out", default=os.path.join(REPO, DELIV_NAME),
                    help="回切交付目录（默认 %s）" % DELIV_NAME)
    a = ap.parse_args(argv)

    src_tileset = os.path.join(DEFAULT_SRC, "tileset.json")
    dst_tileset = os.path.join(a.out, "tileset.json")
    idx_path = os.path.join(a.out, "_index.json")

    # ---- 「量不到」的判定：**只有这一处**（铁律 174）----
    if not os.path.isfile(src_tileset):
        return _skip("源 tileset 不在：%s（跨仓引用断了 —— 只引用不搬，所以它断了就是断了）" % src_tileset)
    if not os.path.isfile(dst_tileset):
        return _skip("回切交付件不在：%s（先跑 tools/editable_to_tiles.py --edit _drill --out %s --all）"
                     % (dst_tileset, DELIV_NAME))

    log("源件  %s" % src_tileset)
    log("出件  %s" % dst_tileset)
    log("判定：① 根 transform 16 数**逐字节** 0 差 ② 根 geometricError 逐位 ③ asset.version/gltfUpAxis "
        "④ 量具自证：带 transform 的节点数**恰为 %d**" % N_ROOT_TRANSFORMS)

    src = frame_facts(src_tileset)
    dst = frame_facts(dst_tileset)
    errs, rd = compare_frames(src, dst)

    # ---- ④ 量具覆盖范围自证（两棵树各数一遍）----
    rd["n_transform_nodes_ok"] = (src["n_transform_nodes"] == N_ROOT_TRANSFORMS
                                  and dst["n_transform_nodes"] == N_ROOT_TRANSFORMS)
    if not rd["n_transform_nodes_ok"]:
        return _skip("带 transform 的节点数不是 %d（源 %d / 出件 %d）⇒ **本闸只盖根**，"
                     "盖不到的那部分它一个字都给不出结论（铁律 158）"
                     % (N_ROOT_TRANSFORMS, src["n_transform_nodes"], dst["n_transform_nodes"]),
                     src_tileset=src_tileset, dst_tileset=dst_tileset,
                     n_transform_nodes_src=src["n_transform_nodes"],
                     n_transform_nodes_dst=dst["n_transform_nodes"], readings=rd)

    # ---- ⑤ 主语：索引记的源件哈希 == 盘上源件现算（**独立读数**，铁律 187）----
    rd["index_present"] = os.path.isfile(idx_path)
    rd["index_src_sha256"] = None
    rd["index_dst_sha256"] = None
    rd["index_verify_selfreport"] = None
    src_hash_ok = None
    if rd["index_present"]:
        idx = read_json(idx_path)
        rd["index_src_sha256"] = ((idx.get("src_tileset") or {}).get("sha256"))
        rd["index_dst_sha256"] = ((idx.get("tileset") or {}).get("sha256"))
        rd["index_verify_selfreport"] = (idx.get("tileset") or {}).get("verify")
        rd["index_out_dir"] = idx.get("out_dir")
        src_hash_ok = src_hash_matches(idx, src["sha256"])
        rd["src_hash_ok"] = src_hash_ok
        rd["dst_hash_ok"] = (rd["index_dst_sha256"] == dst["sha256"])
        if src_hash_ok is False:
            errs.append("★ 索引记的源件 sha256（%s）≠ 盘上源件现算（%s）⇒「出件帧 == 源帧」这话**没有主语**"
                        % (str(rd["index_src_sha256"])[:16], src["sha256"][:16]))
        if not rd["dst_hash_ok"]:
            errs.append("★ 索引记的出件 sha256（%s）≠ 盘上出件现算（%s）⇒ 索引那批读数**不是这件**的"
                        % (str(rd["index_dst_sha256"])[:16], dst["sha256"][:16]))
    else:
        log("   ★ `_index.json` 不在 ⇒ 源件哈希无从核对（这一格本趟**没量到**，不判红）")

    log("")
    log("  ① 根 transform 逐字节 : %s ｜ 不同字节 %s ｜ 首个不同分量 %s ｜ max|Δ|=%.3e"
        % (rd.get("transform_bitmatch"), rd.get("transform_diff_bytes"),
           rd.get("transform_first_diff_index"), rd.get("transform_max_abs") or 0.0))
    log("  ② 根 geometricError   : 逐位 %s ｜ %s" % (rd.get("root_ge_bitmatch"), rd.get("root_ge")))
    log("  ③ asset.version %s ｜ gltfUpAxis %s ｜ root.refine %s"
        % (rd.get("asset_version"), rd.get("gltf_up_axis"), rd.get("root_refine")))
    log("  ④ 带 transform 的节点 : 源 %d / 出件 %d（节点总数 源 %d / 出件 %d）⇒ 量具覆盖 %s"
        % (src["n_transform_nodes"], dst["n_transform_nodes"], src["n_nodes"], dst["n_nodes"],
           "根 ✅" if rd["n_transform_nodes_ok"] else "**不足**"))
    if rd["index_present"]:
        log("  ⑤ 主语 索引记源件哈希 == 盘上现算 ? %s ｜ 出件哈希 == 盘上现算 ? %s"
            % (src_hash_ok, rd.get("dst_hash_ok")))
        log("     工具自评（**只印不采信**）: %s"
            % json.dumps(rd["index_verify_selfreport"], ensure_ascii=False)[:220])

    ok = not errs
    for e in errs:
        log("  ★ %s" % e)

    with tempfile.TemporaryDirectory(prefix=GID + "_") as tmp:
        ctl = positive_controls(src_tileset, dst_tileset, tmp)
    n_fired = sum(1 for c in ctl if c["fired"])
    n_scored = sum(1 for c in ctl if c["fired"] is not None)
    for c in ctl:
        log("   正对照%s %s ｜ 读数 %s" % ("✓" if c["fired"] else "★没红！", c["case"],
                                       {k: v for k, v in c.items()
                                        if k not in ("case", "expect", "fired", "note")}))
    ok = ok and n_fired == n_scored

    log("\n===== 判词 =====")
    log("回切帧逐位：根 transform 16 数**逐字节** %s（不同字节 %s）｜ 帧整体 %s"
        % ("相同" if rd.get("transform_bitmatch") else "**不同**",
           rd.get("transform_diff_bytes"), "PASS" if ok else "FAIL"))
    log("正对照 %d/%d 按预期" % (n_fired, n_scored))

    rc = RC_PASS if ok else RC_FAIL
    log("%s 总判 :" % GID, "PASS" if ok else "FAIL")
    with open(os.path.join(OUTDIR, GID + ".run.txt"), "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(_LOG) + "\n")

    _write_json(rc,
                src_tileset=src_tileset, dst_tileset=dst_tileset, index_json=idx_path,
                n_root_transforms_expected=N_ROOT_TRANSFORMS,
                transform_bitmatch=rd.get("transform_bitmatch"),
                transform_diff_bytes=rd.get("transform_diff_bytes"),
                transform_first_diff_index=rd.get("transform_first_diff_index"),
                transform_max_abs=rd.get("transform_max_abs"),
                root_ge_bitmatch=rd.get("root_ge_bitmatch"),
                asset_version=rd.get("asset_version"), gltf_up_axis=rd.get("gltf_up_axis"),
                root_refine=rd.get("root_refine"),
                n_transform_nodes_src=src["n_transform_nodes"],
                n_transform_nodes_dst=dst["n_transform_nodes"],
                n_nodes_src=src["n_nodes"], n_nodes_dst=dst["n_nodes"],
                src_sha256=src["sha256"], dst_sha256=dst["sha256"],
                index_src_sha256=rd.get("index_src_sha256"),
                index_dst_sha256=rd.get("index_dst_sha256"),
                index_verify_selfreport=rd.get("index_verify_selfreport"),
                readings=rd, n_errors=len(errs), errors=errs,
                n_controls=len(ctl), n_controls_scored=n_scored, n_controls_fired=n_fired,
                controls=ctl,
                blind=["**不判几何**：往返（面数/顶点/包围盒）本闸不覆盖；本趟「21 栋逐片包围盒最大差 0.000000 m／顶点差 ≤0／面数差 ≤0」是 `editable_to_tiles.py` **自评**（`_index.json:results[]`），不是闸的读数",
                       "**不判包围盒**：源件根包围盒是 sphere、出件是 box（表达不同非错）；根包盒由回切**现算** ⇒ 与源件不同不算错（源件那些包围盒数被人手改过，见 `tileset.json.bad_inflated`）",
                       "**不判 URI 命名**：`Data/Tile_+…/…` vs `Data/bldg_…/…` 对不上号是**已知**的 ⇒ 2094 节点退回根 geometricError；本闸只报这个数不判红",
                       "**不判子节点变换**：只数个数当 ④；有子变换 ⇒ rc=4（量不到），不是「子变换错了」",
                       "**不判源件自己是不是对的**：源件被改坏也会照它比 ⇒「一致」只说明没走样，不说明锚定正确（锚定属 A/B 线，且该线**符号未决**）",
                       "只核这一份交付件；`_回切_按栋/` 缺席 ⇒ rc=4（量不到），与 rc=1（做错了）是两件事",
                       "★ **与 `J-10.10-01` ③ 是「一条谓词、两个主语」**：那条量单块临时工作目录的回切（判**工具**），本闸量 21 块合计交付件；两者不许合并，打架时以本闸为准（更严：逐字节 vs `==`）"])
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
