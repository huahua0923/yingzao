# -*- coding: utf-8 -*-
r"""J-10.10-07 —— 编辑器这一环的**出口门**（计划 §4 步 4）。

【判据一句话】
  **人在本地软件里改一栋 → 导出 → 导回 → 回切链读得到**；
  并且 ★ **不走「导回」这一步，改动就到不了瓦片**（「读得到」必须靠这条反证才成立）。

【量具（哪个程序、量哪个量、单位、阈值）】
  · **量具＝在 `tempfile` 临时目录上真跑那两条命令行**（`tools/editable_to_tiles.py` 与
    `tools/repair_project.py 导回`），**不是** import 它们的函数来「差不多地」跑一遍 ——
    人用的是命令行，判据就得量命令行。
    ★ 交付件 `_drill/` 与 `_回切_按栋/` 全程**一个字节都不许动**：主件从交付件**拷**进临时目录，
    靠 `--stage-dir` / `--work-dir` / `--archive-dir` 三个覆盖把读**和写**都钉在临时目录里。
  · **几何尺子＝`trimesh` 读回切出来的瓦片**（独立于工具自报）：逐片量
    `bounds`（m，glb 帧）与片心 `center`；**位移量 Δ ＝ 两套回切件里同名片心的欧氏距离**（m）。
  · **改动怎么造**：`blender.exe -b -P <脚本>` 导入主件 → 把**指定那一片**的顶点沿 Blender `z`
    **烘焙平移 +0.5 m**（`for v in o.data.vertices: v.co.z += D`，改**顶点**不改 `o.location`——
    只改 `o.location` 的位移若被导出成**节点矩阵**、顶点一个没动，本尺子会读成「没动」）。
  · **阈值**：位移 `|Δ − 0.5| ≤ 1e-3 m`（＝浮点烘焙 + 谱系表 3 位小数的记录精度）；
    其余片 `Δ ≤ 1e-6 m`（同一主件回切是确定性的，两遍方差实测 0，见 `editable_to_tiles.py` 文件头）。
  · **「改没改」的字节尺子**：`sha256` 现算 —— 主件导回后必须**与导出件逐位相同**且**不等于改前**。
  · **「这片被改坏了没」只许用同形态的两个量**：面数 ＋ **焊后**顶点数（焊接触点 `DIGITS`
    从 `tools/weld_vertices.py` 经 `repair_project` import，判据**不写第二个数**）。
    ★ **未焊顶点数跨 Blender 边界不可比**（Blender 按 UV 缝重拆点，本闸实测 **751 → 2115**）——
    拿它判会**恒为真**、没有分辨力，故只当参考印出来、**不作判据**
    （铁律 183：修好一个错法只算改了一半；`repair_project.piece_counts` 的 docstring 已为此设了 `weld=` 开关）。

【量具盲区（这把尺子对哪几类东西看不见）】
  1. ★ **只盖一栋**：跑的是全 21 栋里**体积最小**的那栋（栋号由闸**现算**，不手打），
     理由是时间。**其余 20 栋没有被本闸量到** ⇒ 本闸 PASS **不等于**「21 栋都能改」。
  2. ★ **只盖「一片被烘焙平移」这一种改法**。删件、补洞、改贴图、改 UV、改拓扑、加物件 ——
     本闸**一条都没量**。
  3. ★ **不核人改得对不对**：位移是闸自己给的 +0.5 m，只为造出「一个可测的差」。
     它**不反映真实修模**，也**不说明**改完更好看/更准。
  4. ★ **「回切件里读到那个位移」只证链路通，不证渲染对**：贴图有没有跟着错位、LOD 切换时
     新旧片接缝裂不裂，本闸都不看（那是 §4 步 5 与 `J-10.10-06` 的射程）。
  5. ★ **看不见节点变换型的改动**：位移若只作为节点 `matrix` 留在出件里（顶点不动），
     本闸的顶点包围盒尺子**读不出** ⇒ 那种改动会显示成「没动」，而它是**真的动了**。
  6. ★ **不复核 `导回` 写进真 `_archive/` 的留档**：为防反复评测往人的回退目录里堆同名废档，
     闸把留档重定向到临时目录（`--archive-dir`）⇒ 「留档写到真 `_archive/`」这一步**不在射程内**
     （它由工具自身的 C1–C7 覆盖）。
  7. ★ **不判源件自己是不是对的**：源瓦片被改坏，本闸会照着它比 ⇒ 「一致」只说明没走样。
  8. ★ 交付件**缺席**（`_drill/` 没有、或 `--src` 的源 tileset 不在）⇒ `rc=4`（**量不到**），
     与 `rc=1`（**做错了**）是两件事。

【正对照（必配；每条都落读数，不只落 bool）】
  · 甲 **不导回 ⇒ 改动必须消失**：那时 `+0.5 m` 的导出件**就在盘上**，但那栋主件**没被导回**
    ⇒ 回切出来的片**必须一动不动**（片心差 == 0）。这条证的是「尺子量的是件、不是盘上有没有那个导出件」。
  · 乙 **导出件里一片改名 ⇒ `导回` 必须 `rc=1` 并点名**，且主件**未被写**（sha256 不变）。
  · 丙 **Δ=0 的导出件 ⇒ 「那片动了」必须为假**（否则本闸那条尺子**恒绿**，整条判据作废）。
    ★ 丙 用的是**真过了一遍 Blender 的**导出件（不是把原文件拷一份），所以它同时答了
    「光走一趟 Blender 往返，会不会把包围盒晃出个假的位移」。
【三态】`rc=0` PASS / `rc=1` FAIL / `rc=4` NOGAUGE（量不到就不出结论——见盲区 8）
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
TOOLS = os.path.join(REPO, "tools")
OUTDIR = os.path.join(HERE, "_out")

GID = "J-10.10-07"
RC_PASS, RC_FAIL, RC_NOGAUGE = 0, 1, 4
MARK = "===== 判词 ====="

# ★ 交付件（步 3 的产物）。★ 刻意**不**用工具的 DEFAULT_*：那两个是步 1 的名字（`_edit`/`_回切_tiles`），
#   与这里**不是同一个东西**，拿默认值兜底当唯一来源就会量错件（铁律 174）。
DELIVER_DRILL = os.path.join(REPO, "_drill")
DELIVER_CUT = os.path.join(REPO, "_回切_按栋")

DELTA_M = 0.5          # 闸自己施加的位移（m）
TOL_MOVE = 1e-3        # 位移读数容差（m）
TOL_STILL = 1e-6       # 「没动」的容差（m）

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


def _sha256(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def _load_module(alias, path):
    """按**路径**加载仓里的工具，只为取常量（★ 不复制它们的数：铁律 174）。"""
    spec = importlib.util.spec_from_file_location(alias, path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _run(argv, cwd=REPO):
    p = subprocess.run(argv, cwd=cwd, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def _tree_digest(roots):
    """交付件全量读数：`{相对路径: [字节数, sha256]}`。开工/收工各算一次（铁律 187）。"""
    out = {}
    for root in roots:
        for dp, _dn, fn in os.walk(root):
            for f in sorted(fn):
                p = os.path.join(dp, f)
                out[os.path.relpath(p, REPO).replace("\\", "/")] = [os.path.getsize(p), _sha256(p)]
    return out


def _tile_bounds(out_root, block, weld=None):
    """独立读回切出的瓦片：`{片名: {"center":[…], "extents":[…], "n_v":…, "n_f":…}}`。

    ★ 片名取**文件名去扩展名**（一片一文件是 `editable_to_tiles.py` 的硬闸），
      不读 `_index.json` —— 那是**工具自报**，判据不许拿它当读数（铁律 187）。
    ★ `weld` ＝ `(weld_one, DIGITS)` 时**另记一份焊后顶点数** `n_v_welded`。
      **为什么必须两侧同形态**：Blender 导出会按 UV 缝**重拆点** ⇒ 未焊顶点数跨
      「改前 / 过了一趟 Blender」这个边界**本来就不同**（本闸实测 751 → 2115）。
      拿未焊数判「这片被改坏了」会**恒为真** —— 那个标记没有分辨力
      （铁律 183：修好一个错法只算改了一半，换个函数拿同一个量还会再犯；
      `repair_project.piece_counts` 的 docstring 已为此设了 `weld=` 开关）。
    """
    import trimesh

    d = os.path.join(out_root, "Data", block)
    if not os.path.isdir(d):
        return None
    res = {}
    for f in sorted(os.listdir(d)):
        if not f.lower().endswith(".glb"):
            continue
        p = os.path.join(d, f)
        sc = trimesh.load(p, force="scene")
        b = sc.bounds
        lo, hi = [float(x) for x in b[0]], [float(x) for x in b[1]]
        n_v = sum(len(g.vertices) for g in sc.geometry.values())
        n_f = sum(len(g.faces) for g in sc.geometry.values())
        rec = {"center": [(lo[i] + hi[i]) / 2.0 for i in range(3)],
               "extents": [hi[i] - lo[i] for i in range(3)],
               "n_v": int(n_v), "n_f": int(n_f), "bytes": os.path.getsize(p)}
        if weld is not None:
            fn, digits = weld
            rec["n_v_welded"] = int(sum(len(fn(g, digits)[0].vertices)
                                        for g in sc.geometry.values()))
        res[os.path.splitext(f)[0]] = rec
    return res


def _dist(a, b):
    return sum((a[i] - b[i]) ** 2 for i in range(3)) ** 0.5


# ---------------------------------------------------------------- Blender 端
_BLEND_EDIT = r'''# -*- coding: utf-8 -*-
"""由 `gates/J-10.10-07` 生成并驱动 —— 在**指定那一片**上烘焙一个顶点平移，一趟导出两份。

★ 为什么改顶点不改 `o.location`：本闸的尺子是**后段回切件里那片的顶点包围盒**。
  只改 `o.location` 的位移若被导出成**节点矩阵**，顶点一个没动 ⇒ 尺子读成「没动」，
  而件其实动了 —— 那种「看不见」是本闸**已声明**的盲区（见盲区 5），不能让它冒充读数。
"""
import bpy, json, sys

# ★ 下面几个值由本闸用 repr() 注入（见「B Blender 改一刀」那段）——
#   **不要**改回 `r"@SRC@"` 那种「带引号的裸串替换」：路径里只要出现一个 `"`
#   就能越出字符串字面量，把闸自己生成的脚本变成可注入的代码。
SRC = @SRC@
OUT_MOVED = @OUT_MOVED@
OUT_ZERO = @OUT_ZERO@
PIECE = @PIECE@
DELTA = @DELTA@


def report(ok, **kv):
    kv["ok"] = ok
    print("EDITJSON " + json.dumps(kv, ensure_ascii=False))
    sys.stdout.flush()


bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=SRC)

# ★ 主件的几何名 = glTF 的 **mesh 名**（`repair_project.piece_counts` 读的就是 `scene.geometry`）；
#   Blender 里落到 `o.name`（节点名）。两者在本仓的出件里同名，但**两侧都认**更稳——
#   只认一侧的话，名字一变就报「找不着」，与「那片真不在」同形（铁律 199）。
hits = [o for o in bpy.data.objects
        if o.type == "MESH" and (o.name == PIECE or o.data.name == PIECE)]
if len(hits) != 1:
    report(False, why="命中的对象数=%d（要恰好 1）" % len(hits),
           pieces=[o.name for o in bpy.data.objects if o.type == "MESH"][:200])
    sys.exit(1)

o = hits[0]
n_v = len(o.data.vertices)
n_f = len(o.data.polygons)
if n_v == 0:
    report(False, why="这片一个顶点都没有，位移看不见")
    sys.exit(1)

for v in o.data.vertices:
    v.co.z += DELTA
o.data.update()
bpy.ops.export_scene.gltf(filepath=OUT_MOVED, export_format="GLB", export_yup=True)

# ★ 丙类正对照用的「过了 Blender 但没动」——同一趟里把顶点**移回去**再导一份，
#   这样「光走一趟往返会不会晃出个假的位移」与真位移**共用同一个进程、同一份导入**。
for v in o.data.vertices:
    v.co.z -= DELTA
o.data.update()
bpy.ops.export_scene.gltf(filepath=OUT_ZERO, export_format="GLB", export_yup=True)

report(True, piece=o.name, mesh=o.data.name, n_v=n_v, n_f=n_f, delta=DELTA)
'''


# ---------------------------------------------------------------- GLB 改名（乙类对照）
def _rename_one_mesh(src, dst, suffix="_改坏了"):
    """把一个 GLB 里**第一个 mesh 的名字**改掉，其余字节照旧（乙类正对照的坏输入）。

    ★ 为什么动 JSON 块而不是在 Blender 里改名：这里要模拟的坏输入是
      「**导出件里一片换了名字**」—— 导出件是什么样就该是什么样，不经第二趟工具。
    ★ 只改 `meshes[0].name`；其余块（二进制 / 补白）原样搬运 ⇒「改名」是本函数**唯一**的改动
      （否则乙类对照会证到别的东西上去）。
    """
    with open(src, "rb") as f:
        b = f.read()
    if b[:4] != b"glTF":
        raise ValueError("不是 GLB：magic=%r" % b[:4])
    off, chunks = 12, []
    while off < len(b):
        ln = int.from_bytes(b[off:off + 4], "little")
        ty = b[off + 4:off + 8]
        chunks.append((ty, b[off + 8:off + 8 + ln]))
        off += 8 + ln
    if not chunks or chunks[0][0] != b"JSON":
        raise ValueError("第一个块不是 JSON：%r" % (chunks[0][0] if chunks else None))
    j = json.loads(chunks[0][1].decode("utf-8"))
    ms = j.get("meshes") or []
    if not ms:
        raise ValueError("这个 GLB 里一个 mesh 都没有")
    old = ms[0].get("name")
    ms[0]["name"] = (old or "") + suffix
    nj = json.dumps(j, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    nj += b" " * ((4 - len(nj) % 4) % 4)                    # JSON 块按 4 字节对齐，用空格补
    out = [len(nj).to_bytes(4, "little") + b"JSON" + nj]
    for ty, data in chunks[1:]:
        out.append(len(data).to_bytes(4, "little") + ty + data)
    body = b"".join(out)
    with open(dst, "wb") as f:                              # ★ 字节层（铁律 79）
        f.write(b"glTF" + (2).to_bytes(4, "little") + len(body).to_bytes(4, "little") + body)
    return old, ms[0]["name"]


# ---------------------------------------------------------------- 主流程
def main(argv=None) -> int:
    errs, blind_note = [], []

    log("%s ===== 编辑能回到回切链（步 4 出口门）=====" % GID)
    log("量具：临时目录上真跑 `editable_to_tiles.py` 与 `repair_project.py 导回` 两条命令行；")
    log("      `trimesh` 独立读回切瓦片的片心/包围盒；改动用 Blender 烘焙顶点平移 %+.1f m。" % DELTA_M)

    # ---------- 前置：源 tileset / 交付件 ----------
    if not os.path.isdir(DELIVER_DRILL) or not os.path.isdir(DELIVER_CUT):
        log("★ 量不到交付件：%s / %s" % (DELIVER_DRILL, DELIVER_CUT))
        return _skip("交付件缺席", errs=["_drill/ 或 _回切_按栋/ 不在"])

    ETT = _load_module("ett_j101007", os.path.join(TOOLS, "editable_to_tiles.py"))
    RP = _load_module("rp_j101007", os.path.join(TOOLS, "repair_project.py"))
    src_tiles, blender = ETT.DEFAULT_SRC, RP.BLENDER
    if not os.path.isfile(os.path.join(src_tiles, "tileset.json")):
        log("★ 量不到源 tileset：%s" % src_tiles)
        return _skip("源 tileset 不在", errs=[src_tiles])
    if not os.path.isfile(blender):
        log("★ 量不到 Blender：%s" % blender)
        return _skip("Blender 不在", errs=[blender])

    # ---------- 交付件基线（⑤ 自证用；铁律 187：开工一次、收工一次，两次独立读数）----------
    t0 = _tree_digest([DELIVER_DRILL, DELIVER_CUT])
    log("\n[⑤基线] 交付件：%d 件 ｜ %d 字节" % (len(t0), sum(v[0] for v in t0.values())))

    # ---------- 选块 / 选片 ----------
    cands = []
    for fid in sorted(os.listdir(DELIVER_DRILL)):
        p = os.path.join(DELIVER_DRILL, fid, fid + ".glb")
        if os.path.isfile(p):
            cands.append((os.path.getsize(p), fid, p))
    if not cands:
        log("★ `_drill/` 下一个可用的主件都没有")
        return _skip("_drill 空")
    cands.sort()
    block, master_src = cands[0][1], cands[0][2]
    log("选块：**体积最小的一栋**（闸现算，不手打栋号）⇒ %s（%.1f MB）"
        % (block, os.path.getsize(master_src) / 1e6))

    import trimesh
    sc = trimesh.load(master_src, force="scene")
    names = sorted(sc.geometry)
    if not names:
        log("★ 主件里一个几何都没有")
        return _skip("主件无几何")
    pick = None
    for n in names:
        g = sc.geometry[n]
        if len(g.vertices) > 0 and len(g.faces) > 0:
            pick = n
            break
    if pick is None:
        log("★ 主件里没有一个非空几何")
        return _skip("主件几何全空")
    log("选片：**名字排序后第一个非空片**（闸现算，不手打片名）⇒ %s（顶点 %d / 面 %d）"
        % (pick, len(sc.geometry[pick].vertices), len(sc.geometry[pick].faces)))
    del sc

    sha_start = _sha256(master_src)
    log("主件改前 sha256 %s…（%d 字节）" % (sha_start[:16], os.path.getsize(master_src)))

    rd = {}
    WELD = (RP.weld_one, RP.DIGITS)      # ★ 焊接触点容差只此一个来源：从 `weld_vertices` 经工具 import
    log("焊接容差 DIGITS=%d（从 `weld_vertices` 取，判据不写第二个数）" % RP.DIGITS)
    with tempfile.TemporaryDirectory(prefix=GID + "_") as T:
        stage, work, arch = (os.path.join(T, n) for n in ("stage", "work", "arch"))
        d = os.path.join(stage, block)
        os.makedirs(d)
        shutil.copyfile(master_src, os.path.join(d, block + ".glb"))
        shutil.copyfile(os.path.join(DELIVER_DRILL, block, block + ".lineage.json"),
                        os.path.join(d, block + ".lineage.json"))
        os.makedirs(work)

        def cut(out_name, st=stage):
            """回切——**跑命令行**（人用的就是这个），不是 import 函数。"""
            o = os.path.join(T, out_name)
            rc, out = _run([sys.executable, os.path.join(TOOLS, "editable_to_tiles.py"),
                            "--edit", st, "--out", o, "--src", src_tiles, "--blocks", block])
            return rc, out, o

        def impt(st, wk, ar):
            return _run([sys.executable, os.path.join(TOOLS, "repair_project.py"), "导回",
                         "--stage", "drill", "--blocks", block,
                         "--stage-dir", st, "--work-dir", wk, "--archive-dir", ar])

        # ---------- A 基线回切 ----------
        log("\n[A] 基线回切（改之前）…")
        rc, out, out_base = cut("out_base")
        if rc != 0:
            log(out[-2500:])
            return _fail("基线回切就没跑通（rc=%d）" % rc, errs=["基线回切 rc=%d" % rc])
        bb = _tile_bounds(out_base, block, weld=WELD)
        if not bb:
            return _fail("基线回切目录里读不到瓦片")
        log("    回切出 %d 片；样例：%s" % (len(bb), sorted(bb)[0][-34:]))
        if pick not in bb:
            return _fail("选中的那片**没出现在回切件里**：%s" % pick[-34:],
                         errs=["回切件里没有 %s" % pick])

        # ---------- B Blender 改一刀 ----------
        log("\n[B] Blender 里把那一片沿 z 烘焙平移 %+.1f m，并同趟导一份「没动」的…" % DELTA_M)
        sp = os.path.join(T, "edit.py")
        ex_moved = os.path.join(work, block + ".导出.glb")
        ex_zero = os.path.join(work, block + ".导出_平移0.glb")
        # ★ 一律用 repr() 注入：它自己处理引号与反斜杠 ⇒ 值里再出现 `"` 也越不出字符串
        #   （原先模板写成 `r"@SRC@"`、这里是裸替换，一个带引号的路径就能改写这脚本）。
        script = (_BLEND_EDIT.replace("@SRC@", repr(os.path.join(d, block + ".glb")))
                  .replace("@OUT_MOVED@", repr(ex_moved)).replace("@OUT_ZERO@", repr(ex_zero))
                  .replace("@PIECE@", repr(pick)).replace("@DELTA@", repr(DELTA_M)))
        with open(sp, "w", encoding="utf-8", newline="\n") as f:
            f.write(script)
        rc, out = _run([blender, "-b", "-P", sp])
        bl = None
        for ln in out.splitlines():
            if ln.startswith("EDITJSON "):
                bl = json.loads(ln[len("EDITJSON "):])
        log("    Blender rc=%s ｜ %s" % (rc, json.dumps(bl, ensure_ascii=False) if bl
                                         else "**没读到 EDITJSON**"))
        rd["blender"] = {"rc": rc, "report": bl}
        if rc != 0 or not bl or not bl.get("ok"):
            log(out[-2500:])
            return _fail("Blender 那一刀没落成", errs=["blender rc=%s report=%s" % (rc, bl)])
        if not os.path.isfile(ex_moved) or not os.path.isfile(ex_zero):
            return _fail("Blender 报成功但导出件不在",
                         errs=["导出件缺席 moved=%s zero=%s"
                               % (os.path.isfile(ex_moved), os.path.isfile(ex_zero))])
        rd["export_moved_sha"], rd["export_zero_sha"] = _sha256(ex_moved), _sha256(ex_zero)
        rd["export_moved_bytes"] = os.path.getsize(ex_moved)
        rd["export_zero_bytes"] = os.path.getsize(ex_zero)

        # ---------- C 导回 ----------
        log("\n[C] 导回（把导出件装回主件）…")
        rc, out = impt(stage, work, arch)
        log("    rc=%d" % rc)
        for ln in out.splitlines():
            if any(k in ln for k in ("逐位原样搬运", "主件 ", "导出件 ", "PASS", "FAIL", "违规",
                                     "台账已过期", "台账里**没有**")):
                log("    │ " + ln.strip())
        sha_after = _sha256(os.path.join(d, block + ".glb"))
        rd.update({"import_rc": rc, "master_sha_before": sha_start, "master_sha_after": sha_after,
                   "export_sha": rd["export_moved_sha"],
                   "master_now_equals_export": sha_after == rd["export_moved_sha"],
                   "master_now_differs_from_before": sha_after != sha_start})
        if rc != 0:
            return _fail("导回 rc=%d（应当 0）" % rc)
        # ★ ① 的**独立**复算：不信工具自报的「逐位原样搬运」，自己再算一遍 sha256
        if not rd["master_now_equals_export"]:
            errs.append("导回后主件**不等于**导出件 ⇒ 搬运被二次加工过")
        if not rd["master_now_differs_from_before"]:
            errs.append("导回后主件**与改前逐位相同** ⇒ 那一片的改动**根本没有进件**")

        # ---------- D 改动后回切 ----------
        log("\n[D] 改动后回切…")
        rc, out, out_edit = cut("out_edit")
        if rc != 0:
            log(out[-2500:])
            return _fail("改动后回切 rc=%d" % rc)
        be = _tile_bounds(out_edit, block, weld=WELD)

        # ② 那片动了多少 / 别的片有没有被牵连
        moved, still, missing = [], [], []
        for k in sorted(bb):
            if k not in be:
                missing.append(k)
                continue
            dv = _dist(bb[k]["center"], be[k]["center"])
            de = max(abs(bb[k]["extents"][i] - be[k]["extents"][i]) for i in range(3))
            rec = {"piece": k, "d_center_m": round(dv, 9), "d_extents_max_m": round(de, 9)}
            (moved if dv > TOL_STILL else still).append(rec)
            if k == pick:
                rd["pick_axis_delta_m"] = [round(be[k]["center"][i] - bb[k]["center"][i], 9)
                                           for i in range(3)]
                rd["pick_d_extents_max_m"] = rec["d_extents_max_m"]
                # ★ 判「这片被改坏了没」只许用**同形态**的两个量：
                #   面数（拓扑）＋**焊后**顶点数。**未焊**顶点数跨 Blender 边界本就不同
                #   （UV 缝会重拆点，实测 751 → 2115）⇒ 拿它判**恒为真**，只当参考印出来。
                rd["pick_n_f"] = [bb[k]["n_f"], be[k]["n_f"]]
                rd["pick_n_v_welded"] = [bb[k]["n_v_welded"], be[k]["n_v_welded"]]
                rd["pick_n_v_raw_not_comparable"] = [bb[k]["n_v"], be[k]["n_v"]]
                rd["pick_total_delta_m"] = rec["d_center_m"]
        rd.update({"n_pieces_base": len(bb), "n_pieces_edit": len(be),
                   "pieces_only_in_base": missing,
                   "pieces_only_in_edit": sorted(set(be) - set(bb)),
                   "moved": moved, "n_moved": len(moved), "n_still": len(still)})

        log("\n[②] 回切件逐片片心位移（基线 → 改动后）：")
        log("     动了的片 %d 片：%s" % (len(moved),
                                        [(m["piece"][-30:], m["d_center_m"]) for m in moved]))
        log("     没动的片 %d 片" % len(still))
        log("     选中那片分轴位移（glb 帧 x/y/z）= %s" % (rd.get("pick_axis_delta_m"),))

        if len(moved) != 1 or moved[0]["piece"] != pick:
            errs.append("应当**只有** `%s` 一片动，实测动了 %d 片 %s"
                        % (pick[-30:], len(moved), [m["piece"][-20:] for m in moved]))
        if pick in be:
            tot = rd["pick_total_delta_m"]
            if abs(tot - DELTA_M) > TOL_MOVE:
                errs.append("选中那片的位移 %.6f m 与施加的 %.3f m 差 %.6f m（容差 %.0e）"
                            % (tot, DELTA_M, abs(tot - DELTA_M), TOL_MOVE))
            if abs(rd["pick_d_extents_max_m"]) > TOL_MOVE:
                errs.append("那片**尺寸也变了** %.6f m ⇒ 量到的不是纯平移" % rd["pick_d_extents_max_m"])
            if rd["pick_n_f"][0] != rd["pick_n_f"][1]:
                errs.append("那片的面数变了 %s ⇒ 那一片的拓扑被动了，不只是平移"
                            % rd["pick_n_f"])
            if rd["pick_n_v_welded"][0] != rd["pick_n_v_welded"][1]:
                errs.append("那片**焊后**顶点数变了 %s（同形态对比）⇒ 那一片的拓扑被动了"
                            % rd["pick_n_v_welded"])
            log("     选中那片：面数 %s（须相等）｜ **焊后**顶点 %s（须相等）"
                % (rd["pick_n_f"], rd["pick_n_v_welded"]))
            log("       （参考·**跨形态不可比**）：未焊顶点 %s —— Blender 按 UV 缝重拆点，"
                % rd["pick_n_v_raw_not_comparable"])
            log("        这个数跨「过没过 Blender」两侧本来就不同，**不作判据**）")
        if missing:
            errs.append("回切件里少了 %d 片：%s" % (len(missing), [m[-24:] for m in missing]))

        # ---------- ③ 正对照 甲：不导回 ⇒ 改动必须消失 ----------
        log("\n[正对照·甲] 不导回 ⇒ 改动必须消失…")
        stage2 = os.path.join(T, "stage2")
        shutil.copytree(os.path.join(DELIVER_DRILL, block), os.path.join(stage2, block))
        rc, out, out_no = cut("out_noimport", st=stage2)
        bn = _tile_bounds(out_no, block) if rc == 0 else None
        if rc != 0 or not bn:
            ctl_a = {"case": "不导回（回切 rc=%d）" % rc, "expect": "那片不动", "fired": None,
                     "note": "回切没跑通 ⇒ 这条对照**没量到**（不等于通过）"}
        else:
            dm = [_dist(bb[k]["center"], bn[k]["center"]) for k in bb if k in bn]
            dmax = max(dm) if dm else None
            ctl_a = {"case": "不导回（+%.1f m 的导出件就在盘上、但没装回主件）" % DELTA_M,
                     "expect": "所有片片心位移 == 0（改动到不了瓦片）",
                     "max_d_center_m": round(dmax, 9) if dmax is not None else None,
                     "n_pieces": len(bn),
                     "export_on_disk_differs_from_master": rd["export_moved_sha"] != sha_start,
                     "fired": (dmax is not None and dmax <= TOL_STILL)}
            if not ctl_a["fired"]:
                errs.append("正对照甲**没红**：不导回却量到位移 %s m ⇒ 尺子量的不是「件」" % dmax)
        log("   " + json.dumps(ctl_a, ensure_ascii=False))

        # ---------- ④ 正对照 乙：导出件一片改名 ⇒ 导回必须 rc=1 且点名 ----------
        log("\n[正对照·乙] 把导出件里一片改名 ⇒ 导回必须点名拒绝、主件不许被写…")
        stage3 = os.path.join(T, "stage3")
        shutil.copytree(os.path.join(DELIVER_DRILL, block), os.path.join(stage3, block))
        work3 = os.path.join(T, "work3")
        os.makedirs(work3)
        bad_ex = os.path.join(work3, block + ".导出.glb")
        old_name, new_name = _rename_one_mesh(ex_moved, bad_ex)
        s3_before = _sha256(os.path.join(stage3, block, block + ".glb"))
        rc3, out3 = impt(stage3, work3, os.path.join(T, "arch3"))
        s3_after = _sha256(os.path.join(stage3, block, block + ".glb"))
        named = new_name in out3
        ctl_b = {"case": "导出件里 `meshes[0].name` 改名：%r → %r" % (old_name, new_name),
                 "expect": "导回 rc=1、消息里点名那个坏名字、主件 sha256 不变",
                 "import_rc": rc3, "renamed_name_in_output": named,
                 "master_unchanged": s3_before == s3_after,
                 "fired": (rc3 == 1 and named and s3_before == s3_after)}
        if not ctl_b["fired"]:
            errs.append("正对照乙**没红**：改名后导回 rc=%s、点名=%s、主件未动=%s"
                        % (rc3, named, s3_before == s3_after))
        log("   " + json.dumps(ctl_b, ensure_ascii=False))
        for ln in out3.splitlines():
            if "违规" in ln:
                log("   │ " + ln.strip()[:200])

        # ---------- ⑥ 正对照 丙：Δ=0 的导出件 ⇒「那片动了」必须为假 ----------
        log("\n[正对照·丙] Δ=0 的导出件（真过了 Blender 往返）⇒「那片动了」必须为假…")
        stage4 = os.path.join(T, "stage4")
        shutil.copytree(os.path.join(DELIVER_DRILL, block), os.path.join(stage4, block))
        work4 = os.path.join(T, "work4")
        os.makedirs(work4)
        shutil.copyfile(ex_zero, os.path.join(work4, block + ".导出.glb"))
        rc4, out4 = impt(stage4, work4, os.path.join(T, "arch4"))
        rc4b, out4b, out_zero = cut("out_delta0", st=stage4)
        bz = _tile_bounds(out_zero, block) if rc4b == 0 else None
        if rc4 != 0 or rc4b != 0 or not bz or pick not in bz:
            ctl_c = {"case": "Δ=0 导出件（导回 rc=%d / 回切 rc=%d / 有那片=%s）"
                             % (rc4, rc4b, bool(bz) and pick in bz),
                     "expect": "那片不动", "fired": None,
                     "note": "链没跑通 ⇒ 这条对照**没量到**（不等于通过）"}
        else:
            dz = _dist(bb[pick]["center"], bz[pick]["center"])
            nd = sum(1 for k in bb if k in bz and _dist(bb[k]["center"], bz[k]["center"]) > TOL_STILL)
            zero_master = os.path.join(stage4, block, block + ".glb")
            ctl_c = {"case": "Δ=0 的导出件（过了 Blender 一趟、顶点移回去再导出）",
                     "expect": "选中那片片心位移 ≤ %.0e m ⇒「那片动了」为假" % TOL_STILL,
                     "pick_d_center_m": round(dz, 9), "n_moved_pieces": nd,
                     "zero_export_differs_from_master_before": _sha256(zero_master) != sha_start,
                     "fired": dz <= TOL_STILL}
            if not ctl_c["fired"]:
                errs.append("正对照丙**没红**：Δ=0 却量到 %.9f m ⇒ 本闸「那片动了」这条尺子**恒绿**，"
                            "整条判据作废" % dz)
            if not ctl_c["zero_export_differs_from_master_before"]:
                log("   （提示：Δ=0 那份导出件与改前**逐位相同** ⇒ 这条对照的输入退化了，"
                    "没证明「过了 Blender 也不晃」）")
                blind_note.append("丙类对照的导出件与改前逐位相同 ⇒ **没证明**「Blender 往返本身不产生假位移」")
        log("   " + json.dumps(ctl_c, ensure_ascii=False))

        ctl = [ctl_a, ctl_b, ctl_c]
        rd["controls"] = ctl
        rd["n_controls_fired"] = sum(1 for c in ctl if c["fired"])
        rd["n_controls_scored"] = sum(1 for c in ctl if c["fired"] is not None)

    # ---------- ⑤ 自证：交付件一个字节都不许动 ----------
    t1 = _tree_digest([DELIVER_DRILL, DELIVER_CUT])
    only0, only1 = sorted(set(t0) - set(t1)), sorted(set(t1) - set(t0))
    chg = sorted(k for k in t0 if k in t1 and t0[k] != t1[k])
    same_tree = not (only0 or only1 or chg)
    if not same_tree:
        errs.append("交付件被动了：消失 %d / 新增 %d / 变了 %d 件（举例 %s）"
                    % (len(only0), len(only1), len(chg), (chg or only1 or only0)[:3]))
    log("\n[⑤ 自证] 交付件开工/收工全量读数：%d 件 ｜ 逐位相同 ? %s" % (len(t0), same_tree))

    log("")
    ok = not errs
    for e in errs:
        log("★ %s" % e)

    log("\n" + MARK)
    log("编辑能回到回切链：主件导回后 == 导出件 %s、≠ 改前 %s ｜ 回切件里动了的片 %d 片（应为 1）"
        % (rd.get("master_now_equals_export"), rd.get("master_now_differs_from_before"),
           rd.get("n_moved")))
    log("选中那片位移 %s m（施加 %.1f m）｜ 交付件未动 %s ｜ 正对照 %s/%s 按预期"
        % (rd.get("pick_total_delta_m"), DELTA_M, same_tree,
           rd.get("n_controls_fired"), rd.get("n_controls_scored")))
    log("%s 总判 : %s" % (GID, "PASS" if ok else "FAIL"))

    _dump_run()
    rc = RC_PASS if ok else RC_FAIL
    _write_json(rc,
                block=block, piece=pick, delta_applied_m=DELTA_M,
                deliver_drill=DELIVER_DRILL, deliver_cut=DELIVER_CUT, src_tileset=src_tiles,
                n_deliver_files_open=len(t0), n_deliver_files_close=len(t1),
                deliver_tree_bitmatch=same_tree,
                deliver_diff={"only_open": only0[:20], "only_close": only1[:20],
                              "changed": chg[:20], "n_changed": len(chg)},
                readings=rd, n_errors=len(errs), errors=errs,
                blind=["★ 只盖**一栋**（全 21 栋里体积最小的那栋，栋号由闸现算）—— 本闸 PASS **不等于** 21 栋都能改",
                       "★ 只盖「一片被烘焙平移」这一种改法；删件/补洞/改贴图/改 UV/改拓扑/加物件**一条都没量**",
                       "★ **不核人改得对不对**：位移是闸自己给的 +0.5 m，只为造一个可测的差，不反映真实修模",
                       "★ **只证链路通，不证渲染对**：贴图有没有跟着错位、新旧片接缝裂不裂，不在射程内",
                       "★ **看不见节点变换型的改动**：位移若只作为节点 matrix 留在出件里（顶点不动），顶点包围盒尺子读成「没动」",
                       "★ **不复核 `导回` 写进真 `_archive/` 的留档**：闸把留档重定向到临时目录（`--archive-dir`）",
                       "★ **不判源件自己是不是对的**：源瓦片被改坏也会照它比 ⇒「一致」只说明没走样",
                       "★ **不判回切件与源件的锚定/树形**：那是 `J-10.10-06` 的射程，两者不许互相顶替"] + blind_note)
    return rc


def _dump_run():
    os.makedirs(OUTDIR, exist_ok=True)
    with open(os.path.join(OUTDIR, GID + ".run.txt"), "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(_LOG) + "\n")


def _skip(reason, errs=None):
    log("\n" + MARK)
    log("%s 总判 : **量不到**（不是通过）—— %s" % (GID, reason))
    _dump_run()
    _write_json(RC_NOGAUGE, skip_reason=reason, errors=errs or [])
    return RC_NOGAUGE


def _fail(reason, errs=None):
    log("★ " + reason)
    log("\n" + MARK)
    log("%s 总判 : FAIL —— %s" % (GID, reason))
    _dump_run()
    _write_json(RC_FAIL, fail_reason=reason, errors=errs or [])
    return RC_FAIL


if __name__ == "__main__":
    raise SystemExit(main())
