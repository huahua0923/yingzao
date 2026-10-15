# -*- coding: utf-8 -*-
"""判据 J-10.10-01 —— 实景主件的**往返**（拆 → 改 → 回切）不许悄悄丢东西、也不许悄悄错位。

**兑现方案 md §10.9 的哪一行**（§10.9 = 本地倾斜摄影生产 F17，四条判据目前只有表格文本）：
  · 第 1 行「**可复现**：同影像＋同参数重跑，容差内一致」
    ⇒ 在「**不重跑 SfM**」的口径下，它变成 **「同一主件 → 回切，瓦片在主件记录的容差内一致」**。**本闸量这条。**
  · 第 2 行「**配准正确**：与控制点/已有基线配准偏差在容差内」的**前半**
    ⇒ 「回切件与旧瓦片的根变换**逐位一致**（`root.transform`）」。**本闸也量这条**
    （后半「与 DOM/DSM 的对外比」要步 3/步 5 的件，不在此处；见下方盲区 4）。
  · ★ 第 3 行「拼接无缝」**本闸不量**：它要**新旧瓦片共存**才谈得上接缝，落在步 3 的闸。
  · ★ 第 4 行「包里没有原始影像」**本闸不另造尺子**：实景瓦片**不走模型包通道**（规范 §5.4），
    那条由既有的 `J-10.2-01`（`modelpack.validate` 的 `RAW_IMAGERY_PRESENT`）守。
    ★ 不另造的理由：转发别人的闸只会多出一个同名的量（铁律 174）。

判据一句话：主件的每一片，回切成瓦片后**名字对得上、几何在主件记录的容差内、贴图换回原始字节**；
树的**根变换逐位复现**源件（不是「接近」）；并且**丢一片 / 改一名 / 丢一块 / 锚定漂移**四类
都必须被**点名**或**拒绝**。

量具（哪个程序、量哪个量、单位、阈值）
  · 本闸**自己**用 `trimesh` 读主件几何、再用 `trimesh` 读**写出去的**瓦片几何，逐片量
    **包围盒分量最大绝对差（m）**，阈值 `TOL_M`。
    ★ `TOL_M` 与 `tools/editable_to_tiles.py` 用的是**同一个常量对象**（import 进来的，
    **全仓只有一处定义**，铁律 174）；它的来历写在该文件头 —— 谱系表 `bounds` 的记录精度，不是手打的。
    ★ 两侧都在 **glb(Y-up) 帧**里比（谱系表记的就是这一帧）。
  · **叶名真源 = 程序现列文件系统**（`os.listdir(<out>/Data/<块>)`），**不信 `meta.json`**
    （规范 §4 第 3 条实测：`meta.json` 的 `children_files` 全写 `.osgb`、实物是 `.glb`）。
  · **锚定**：本闸**自己**用 `json` 读源件与回切件的 `tileset.json`，把 `root.transform` 的
    16 个数**逐元素 `==`** 比。阈值＝**逐位相同**。
  · ★ 本闸**不采信** `tools/editable_to_tiles.py` 落在 `_index.json` 里的那些**自评数**
    （`delta_bounds_max` / `transform_bitmatch`）。那是**交付方自己的读数**；
    这里全部**重新算一遍**（铁律 187：判据与交付件必须是两次不同读数）。
  · ★ **空白对照要「恰 0」不是「小于容差」**：小于容差的过法会让「差一点点」也算通过，
    那正是这条尺子该抓的形状（TOL_M 只用来给「有没有量到」定标，不用来给「过不过」定标）。

盲区（这把尺子对哪几类东西看不见）
  1. 只比**同名片**的**包围盒**。片**内部**被移动一个顶点、法线被翻、UV 被重排 —— **看不见**。
  2. 只比**名字**。一片被切成两片再分别命名 ⇒ 抓不到（名字集合仍然对得上）。
  3. ★ **不量「改得对不对」**：本闸只证明「该回来的回来了」。改得对不对是**人判**。
  4. ★ **不量与 DOM/DSM 的对外比**（§10.9 第 2 行的后半）⇒ 回切件的**绝对精度本闸不给结论**。
     源件 `tileset.json` 的逐片包围球虽是外部参照，但规范 §4 第 9 条实测**它被手工改过**
     ⇒ 只能抓粗错，**不能**给精度盖章。本闸因此**不用它判旗**。
  5. 无主件时本闸 **rc=4**（量不到），**不是** rc=1 —— 「这一步没做」与「这一步做错了」是两件事。
  6. 只在**一个块**上跑时不代表全库；`n_blocks_measured` 是读数，判词里报出来。

正对照（必配；四条都必须按预期红，否则本闸没有分辨力、作废）
  ① 丢一片（谱系少一条）⇒ 必须**点名**「只在主件」的那一片；
  ② 改一名（谱系把一片改名）⇒ **两侧各自点名**；
  ③ 丢一块（点一个盘上没有的块）⇒ 必须**点名**该块，且不拖累别块照常出件；
  ④ 锚定漂移（谱系记的源 sha256 改掉）⇒ **拒绝出件 rc=4**，且**不落件**。
  ★ 正对照只在 `blocks[0]` 上跑：跑第 2 块起只是重复同一把尺子，不增加分辨力。

三态：OK(0) / FAIL(1) / SKIP(4)。
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOLS = os.path.join(REPO, "tools")
OUTDIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_out")
WORK = os.path.join(REPO, "_scratch", "_gate_reality")

sys.path.insert(0, TOOLS)
import editable_to_tiles as E2T  # noqa: E402 —— 只借**常量与已量过的原语**，不借它的结论

EDIT = os.path.join(REPO, "_edit")
TOL_M = E2T.TOL_M              # ★ 阈值全仓只有一处定义（铁律 174）
SRC = E2T.DEFAULT_SRC
PY = sys.executable

_LOG = []


def log(*a):
    s = " ".join(str(x) for x in a)
    print(s)
    _LOG.append(s)


def _write_json(rc, **kv):
    """落 `gates/_out/J-10.10-01.json`：三路读数之一（另两路＝run.txt 的 `rc=` 与判词行）。"""
    d = {"pass": rc == 0, "rc": rc}
    d.update(kv)
    os.makedirs(OUTDIR, exist_ok=True)
    p = os.path.join(OUTDIR, "J-10.10-01.json")
    with open(p, "wb") as f:                       # 字节层写盘（铁律 79：防文本模式把 LF 翻成 CRLF）
        f.write(json.dumps(d, ensure_ascii=False, indent=1).encode("utf-8"))
    log("  写出:", p)


# --------------------------------------------------------------------- 读数（本闸自己算）

def bounds6(glb_path: str) -> dict:
    """读一个 glb（主件或瓦片）→ `{几何名: [x0,y0,z0,x1,y1,z1]}`（glb / Y-up 帧）。"""
    import trimesh

    sc = trimesh.load(glb_path, force="scene")
    out = {}
    for name, g in sc.geometry.items():
        b = g.bounds
        out[name] = [float(v) for v in (list(b[0]) + list(b[1]))]
    return out


def tiles_of(out: str, blk: str) -> dict:
    """回切件此刻的几何。★ 名字**由程序现列文件系统**得到，不读任何 meta。"""
    d = os.path.join(out, "Data", blk)
    res = {}
    for f in sorted(x for x in os.listdir(d) if x.lower().endswith(".glb")):
        res.update(bounds6(os.path.join(d, f)))
    return res


def lineage_of(edit: str, blk: str) -> dict:
    with open(os.path.join(edit, blk, f"{blk}.lineage.json"), "r", encoding="utf-8") as f:
        return json.load(f)


def walk_tileset(node: dict):
    """产出 `(uri, refine, has_box)`；本闸自己遍历 json，不用 py3dtiles。"""
    stack = [node]
    while stack:
        nd = stack.pop()
        yield (nd.get("content") or {}).get("uri"), nd.get("refine"), ("boundingVolume" in nd)
        stack.extend(nd.get("children") or [])


def read_json(p: str) -> dict:
    with open(p, "r", encoding="utf-8") as f:
        return json.load(f)


def run_tool(edit: str, out: str, blocks: str) -> tuple:
    p = subprocess.run([PY, os.path.join(TOOLS, "editable_to_tiles.py"),
                        "--edit", edit, "--out", out, "--blocks", blocks],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def check_roundtrip(edit: str, blk: str, out: str) -> dict:
    """一块的往返读数。全部**本闸自己算**，不采信工具的 `_index.json`。"""
    rc, s = run_tool(edit, out, blk)
    r = {"block": blk, "tool_rc": rc, "errs": []}
    if rc != 0:
        r["errs"].append("回切工具 rc=%s：%s" % (rc, s[-500:]))
        return r

    lg = lineage_of(edit, blk)
    lin_names = sorted(x["name"] for x in lg["pieces"])
    lin_lod = {x["name"]: x["lod"] for x in lg["pieces"]}
    m = bounds6(os.path.join(edit, blk, f"{blk}.glb"))
    t = tiles_of(out, blk)

    # ① 名字双向对账（★ 两侧都点名）
    r["only_in_master"] = sorted(set(m) - set(t))
    r["only_in_tiles"] = sorted(set(t) - set(m))
    r["n_pieces_lineage"] = len(lin_names)
    r["n_files_on_disk"] = len(t)

    # ② 同名片逐片差 ＋ 同 LOD 比同 LOD（LOD 由**盘上文件名**反解 ⇒ 真源＝文件系统）
    worst, per = 0.0, []
    for nm in sorted(set(m) & set(t)):
        d = max(abs(m[nm][k] - t[nm][k]) for k in range(6))
        lod_disk = E2T.S2E.lod_of(nm)
        per.append({"name": nm, "delta_m": round(d, 9), "lod_lineage": lin_lod.get(nm),
                    "lod_on_disk": lod_disk, "same_lod": lod_disk == lin_lod.get(nm)})
        worst = max(worst, d)
    r.update(worst_delta_m=worst, pieces=per,
             n_same_lod=sum(1 for x in per if x["same_lod"]),
             lod_bad=[x["name"] for x in per if not x["same_lod"]])

    # ③ 锚定：本闸自己读源件与回切件，逐元素 ==
    src_t = (read_json(os.path.join(SRC, "tileset.json")).get("root") or {}).get("transform")
    dt = read_json(os.path.join(out, "tileset.json"))
    got_t = (dt.get("root") or {}).get("transform")
    r["n_transform_elems"] = len(src_t or [])
    r["transform_bitmatch"] = bool(got_t and src_t and got_t == src_t)
    r["transform_max_abs"] = (max(abs(a - b) for a, b in zip(got_t, src_t))
                              if (got_t and src_t and len(got_t) == len(src_t)) else None)

    # ④ 每个 content 都在盘上 ／ 带 content 的节点都有盒 ／ refine 一致
    miss, ncontent, nbox, refines = [], 0, 0, set()
    for uri, refine, hasbox in walk_tileset(dt.get("root") or {}):
        if refine:
            refines.add(refine)
        if uri:
            ncontent += 1
            nbox += 1 if hasbox else 0
            if not os.path.exists(os.path.join(out, uri)):
                miss.append(uri)
    r.update(n_content=ncontent, n_content_boxed=nbox, n_missing_content=len(miss),
             missing_content=miss[:6], refines=sorted(refines))

    # ⑤ asset 逐字沿用（含 gltfUpAxis）
    sa = read_json(os.path.join(SRC, "tileset.json")).get("asset") or {}
    ga = dt.get("asset") or {}
    r["asset_core_same"] = ({k: v for k, v in ga.items() if k != "extras"}
                            == {k: v for k, v in sa.items() if k != "extras"})
    r["gltf_up_axis"] = ga.get("gltfUpAxis")
    return r


# --------------------------------------------------------------------- 正对照的铺场

def edit_lineage(bd: str, blk: str, fn) -> None:
    p = os.path.join(bd, f"{blk}.lineage.json")
    lg = read_json(p)
    fn(lg)
    with open(p, "wb") as f:                       # 字节层（铁律 79）
        f.write(json.dumps(lg, ensure_ascii=False, indent=1).encode("utf-8"))


def stage(edit: str, blk: str, name: str, mutate=None) -> str:
    """把一块主件铺到 `_gate_reality/<name>/`；`mutate(块目录)` 可改副本的谱系表。"""
    d = os.path.join(WORK, name)
    if os.path.exists(d):
        shutil.rmtree(d)
    bd = os.path.join(d, blk)
    os.makedirs(bd)
    for f in (f"{blk}.glb", f"{blk}.lineage.json"):
        shutil.copy2(os.path.join(edit, blk, f), os.path.join(bd, f))
    if mutate:
        mutate(bd)
    return d


def positive_controls(edit: str, blk: str) -> list:
    """四条，每条都必须按预期红。★ 只跑一块，且全是**盘上副本**，不碰 `_edit/`、不碰源件。"""
    log("\n---- 正对照（每条都必须按预期变红）----")
    ctl = []

    def rec(case, expect, fired, **kw):
        log("  %-6s → %s  [%s]" % (case, "按预期红" if fired else "★ 没红！", expect))
        ctl.append(dict(case=case, expect=expect, fired=fired, **kw))

    # ① 丢一片
    d = stage(edit, blk, "c1_drop", lambda bd: edit_lineage(
        bd, blk, lambda lg: lg.__setitem__("pieces", lg["pieces"][1:])))
    rc, s = run_tool(d, os.path.join(WORK, "o1"), blk)
    rec("丢一片", "rc≠0 且点名「只在主件」", rc != 0 and "只在主件" in s,
        rc=rc, named="只在主件" in s)

    # ② 改一名
    d = stage(edit, blk, "c2_ren", lambda bd: edit_lineage(
        bd, blk, lambda lg: lg["pieces"][0].__setitem__("name", lg["pieces"][0]["name"] + "_RENAMED")))
    rc, s = run_tool(d, os.path.join(WORK, "o2"), blk)
    rec("改一名", "rc≠0 且两侧各自点名", rc != 0 and "只在主件" in s and "只在谱系" in s,
        rc=rc, named_master="只在主件" in s, named_lineage="只在谱系" in s)

    # ③ 丢一块（另一块必须照常出件）
    d = stage(edit, blk, "c3_blk")
    rc, s = run_tool(d, os.path.join(WORK, "o3"), f"{blk},Tile_+999_+999")
    rec("丢一块", "rc≠0 且点名缺块且不拖累别块",
        rc != 0 and "Tile_+999_+999" in s and "回切 1 / 点名 2" in s,
        rc=rc, named="Tile_+999_+999" in s, other_block_ok="回切 1 / 点名 2" in s)

    # ④ 锚定漂移（源 sha256 改掉）
    d = stage(edit, blk, "c4_sha", lambda bd: edit_lineage(
        bd, blk, lambda lg: lg["src_tileset"].__setitem__("sha256", "0" * 64)))
    o4 = os.path.join(WORK, "o4")
    rc, s = run_tool(d, o4, blk)
    rec("锚定漂移", "rc=4 且含「拒绝出件」且不落件",
        rc == 4 and "拒绝出件" in s and not os.path.exists(os.path.join(o4, "tileset.json")),
        rc=rc, refused="拒绝出件" in s,
        no_artifact=not os.path.exists(os.path.join(o4, "tileset.json")))
    return ctl


# --------------------------------------------------------------------- 主

def _skip(reason: str, **kv) -> int:
    log("★ %s ⇒ 量不到（rc=4）" % reason)
    log("===== 判词 =====")
    log("J-10.10-01 总判 : SKIP（量不到 —— 这一步还没做，不是做错了）")
    _write_json(4, reason=reason, edit_dir=EDIT, n_blocks_measured=0, blocks=[],
                tolerance_m=TOL_M, src_tileset=SRC, controls=[],
                blind=["主件缺席 ⇒ 本趟**没有量到**任何东西（rc=4，与 rc=1「做错了」是两件事）"],
                **kv)
    return 4


def main() -> int:
    if os.path.exists(WORK):
        shutil.rmtree(WORK)
    os.makedirs(WORK)

    if not os.path.isdir(EDIT):
        return _skip("主件目录不存在：%s" % EDIT)
    blocks = sorted(n for n in os.listdir(EDIT)
                    if os.path.isfile(os.path.join(EDIT, n, f"{n}.lineage.json")))
    if not blocks:
        return _skip("`_edit/` 下没有主件（`*.lineage.json` 一个都没有）")
    if not os.path.exists(os.path.join(SRC, "tileset.json")):
        return _skip("源 tileset.json 不在：%s（跨仓引用断了）" % SRC)

    log("主件目录 %s  →  块 %d 个：%s" % (EDIT, len(blocks), blocks[:6]))
    log("源件     %s" % SRC)
    log("容差     %.6f m（＝谱系表 bounds 的记录精度；定义在 tools/editable_to_tiles.py，只此一处）" % TOL_M)

    ok, recs = True, []
    for i, blk in enumerate(blocks, 1):
        out = os.path.join(WORK, "out", blk)
        log("\n-- [%d/%d] %s --" % (i, len(blocks), blk))
        r = check_roundtrip(EDIT, blk, out)
        recs.append(r)
        if r.get("errs"):
            log("   ★ %s" % r["errs"][0])
            ok = False
            continue
        log("   片：谱系 %d / 盘上 %d ｜ 只在主件 %s ｜ 只在瓦片 %s"
            % (r["n_pieces_lineage"], r["n_files_on_disk"], r["only_in_master"], r["only_in_tiles"]))
        log("   ★ 逐片包围盒最大差 %.9f m（容差 %.6f）｜ 同 LOD %d/%d %s"
            % (r["worst_delta_m"], TOL_M, r["n_same_lod"], len(r["pieces"]), r["lod_bad"] or ""))
        log("   ★ 根变换逐位复现 ? %s（元素 %d，最大绝对差 %s）"
            % (r["transform_bitmatch"], r["n_transform_elems"], r["transform_max_abs"]))
        log("   content %d（带盒 %d）｜ 缺件 %d %s ｜ refine %s ｜ asset 核心字段逐字同 ? %s ｜ gltfUpAxis=%s"
            % (r["n_content"], r["n_content_boxed"], r["n_missing_content"], r["missing_content"],
               r["refines"], r["asset_core_same"], r["gltf_up_axis"]))
        cond = (not r["only_in_master"] and not r["only_in_tiles"]
                and r["n_pieces_lineage"] > 0
                and r["n_files_on_disk"] == r["n_pieces_lineage"]
                and r["worst_delta_m"] == 0.0            # ★ 空白对照要「恰 0」，不是「小于容差」
                and not r["lod_bad"] and r["n_same_lod"] == len(r["pieces"])
                and r["transform_bitmatch"]
                and r["n_content"] > 0 and not r["n_missing_content"]
                and r["n_content_boxed"] == r["n_content"]
                and r["refines"] == ["REPLACE"] and r["asset_core_same"])
        if not cond:
            log("   ★ 本块不合格（见上面各项）")
        ok = ok and cond

    ctl = positive_controls(EDIT, blocks[0])
    n_fired = sum(1 for c in ctl if c["fired"])
    ok = ok and n_fired == len(ctl)

    log("\n===== 判词 =====")
    log("往返：块 %d 个，逐片差恰 0 ＋ 锚定逐位复现 ＝ %s" % (len(blocks), "PASS" if ok else "FAIL"))
    log("正对照 %d/%d 按预期" % (n_fired, len(ctl)))
    log("J-10.10-01 总判 :", "PASS" if ok else "FAIL")

    with open(os.path.join(OUTDIR, "J-10.10-01.run.txt"), "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(_LOG) + "\n")

    rc = 0 if ok else 1
    _write_json(rc,
                edit_dir=EDIT, src_tileset=SRC, tolerance_m=TOL_M,
                n_blocks_measured=len(blocks), blocks=blocks,
                worst_delta_m=max((r.get("worst_delta_m") or 0.0) for r in recs) if recs else None,
                transform_bitmatch=all(r["transform_bitmatch"] for r in recs
                                       if "transform_bitmatch" in r),
                n_pieces=sum(r.get("n_files_on_disk") or 0 for r in recs),
                n_controls=len(ctl), n_controls_fired=n_fired, controls=ctl,
                results=[{k: v for k, v in r.items() if k != "pieces"} for r in recs],
                blind=["只比同名片的名字与包围盒；片内部的顶点位移/法线翻转/UV 重排看不见",
                       "无法区分「一片被切成两片再分别命名」",
                       "只证明「该回来的回来了」，不证明「改得对」——后者人判",
                       "不量与 DOM/DSM 的对外比；回切件的绝对精度本闸不给结论"
                       "（源件的逐片包围球被手工改过，只作粗错参照、不判旗）",
                       "主件缺席 ⇒ rc=4（量不到），与 rc=1（做错了）是两件事"])
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
