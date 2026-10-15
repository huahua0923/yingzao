# -*- coding: utf-8 -*-
r"""修模**工程模板**与**一键导回** —— 「编辑器」的人机接口（★ 不是网页网格编辑器）。

【判据】本件把「编辑器」这半件**能量出来的两件事**量出来，其余如实声明为盲区：

  A. `造` —— 工程模板**真的能重开**：
     ① Blender headless 造出的 `_work/修模工程/<块>.blend`，**重开**后逐片的
        `(顶点数, 面数)` 与主件 `_edit/<块>/<块>.glb` **逐片相等**；
     ② 贴图数 > 0（不许把纹理弄丢，丢了人就看不到真实外观）；
     ③ `.blend` 自带出处：场景自定义属性里存着主件**路径 + sha256**，
        另有文本块写着同一对值 ⇒ 件换手之后仍然知道它是从哪个件来的。
     ★ 判据只核「重开后几何/贴图**还在**」，**不核**「人改得对不对」—— 那是人的事。

  B. `导回` —— 编辑**真能回到主件**（不回读＝改的是内存不是件）：
     ① 用户的导出件 `_work/修模工程/<块>.导出.glb` 落进 `_edit/<块>/<块>.glb`；
     ② 落盘 sha256 **必须逐位等于**导出件 sha256（**原样搬运**，不二次加工）；
     ③ 几何名集合与主件**完全一致**（少一片＝静默丢件，多一片＝来了个不认识的东西）；
     ④ **落盘前先留档**旧主件（cdut3d 无 git ⇒ `_archive/` 是唯一回退依据）；
     ⑤ 每片顶点数/面数 **> 0**（空片是「看着有、其实没有」）。
     ★ ③ 是**结构性守卫**，**不是**「几何没被改」—— 人就是要改几何的。

【量具】单位与出处：
  · 顶点/面数 ＝ **trimesh 5.1 读件**（主件侧）＋ **Blender 5.2 重开 `.blend` 自报**（模板侧）——
    ★ 两条路**不同源**（铁律 187：基线与期望值必须来自两次不同读数），不是拿 Blender 比 Blender。
  · 焊接容差 `DIGITS` **从 `tools/weld_vertices.py` import**（铁律 174：同一个量只许一个来源）。
  · 时刻一律 ISO-8601 UTC；写盘一律**字节层**（铁律 79）。

【量具盲区】—— 这把尺子**对下面几类东西全盲**，别把绿读成「编辑器做好了」：
  1. **不核人改得对不对**：删错面、把楼削平、纹理拉伸，本件一律看不见（那是人的判断）。
  2. **不核纹理内容**：只数贴图**张数** > 0，不看像素、不看 UV 有没有被 Blender 改写（只核它还在）。
  3. **不核 Blender 与 trimesh 的约定差**：两边都报「顶点数」，但这个数在「焊/未焊」两种形态下
     **本来就不同**（实测 2026-10-15：Blender 导出会把点按 UV 缝重新拆开，2131 → 6922）。
     ⇒ 只有**同形态**的两个数才可比；跨形态直接比会得出「件坏了」的假红。
     ★★ **本件第一版就栽在这里**：`1323 对 1322`，看着像「Blender 弄丢了一个点」，其实是
     拿**未焊的 src** 比**焊过的 rt**。诊断读数（`_scratch/_rt_diff.py`，另一把尺子）：
     两侧 raw 各自 unique 位置都是 **1323**、**两侧都焊**后都是 **1322** 且集合**逐位相等**。
     ⇒ 修正：往返比较**两侧都进同一形态**（都焊），并补一条**伪证器**（挪 1 mm 必须报不等），
     否则「都焊」只是把假红换成**恒绿**（铁律 183：同形状换函数会再犯）。
  4. **不核「导出件是不是这一次导的」**：只看文件在不在、名字对不对。人拿上次的旧导出件来导回，
     本件**看不出来**（时间戳不给结论，因为人可能真是先导后导回）。
  5. **不核回切**：导回只到主件；主件 → 瓦片那一段由 `J-10.10-01` 与 `editable_to_tiles.py` 管。
  6. `--with-rt` 的往返自检**只跑主件未编辑的那一条路**（模板原样导出→焊→比）；
     人**改过**之后再往返会怎样，本件不给结论。
  7. ★★ **`导回` 的「← 改过」标记只认 (顶点数, 面数)，看不见坐标改动**。
     实测（`_scratch/_gauge_discrim.py`，把三个坏件喂给本件**自己的** `piece_counts`/`diff_counts`）：
     未改 ⇒ 不亮（✓）；**删 1 个面** ⇒ 指名亮、面 −1（✓ 有分辨力）；**整片挪 5 mm** ⇒ **不亮**。
     ⇒ 反过来说死：**「没标改过」绝不等于「没改」**。要判坐标改动只能用**位置集合**那条尺子，
     而那条只在**未编辑往返**（`--with-rt`）里成立。**不许**把这条标记当「改动清单」用。

【正对照】—— 每条判据都配一条「故意弄坏必须响」的读数（跑 `--with-rt` 时印出）：
  · C1 **缺片**：把重开读到的片删掉一个再喂给同一个比较函数 ⇒ 必须报「缺片」（证明 A① 不是恒绿）。
  · C2 **值改一个**：把某片面数 +1 ⇒ 必须报「面数不等」。
  · C3 **无导出件**：`导回` 时导出件不在 ⇒ 必须判 rc=4「没量到」，**不许**静默当成功。
  · C4 **坏导出件**：把导出件的几何名改掉一个 ⇒ 必须**指名**报出是哪一个（不是只说「不一致」）。
  · C5 **未编辑往返**：模板原样导出 → 两侧**都按 `DIGITS` 焊** → 与主件比
    「面数逐片相等」＋「位置集合逐位相等」（★ 两条独立，不许合成一条）。
  · C6 **往返尺子的伪证器**：把焊后 rt 的**一个顶点挪 1 mm** ⇒ 位置集合必须**不再相等**
    （不做这条，「都焊」就可能只是把假红换成恒绿）。
  · C7 **导回那把尺子的分辨力**：① 未改的件**不许**亮；② **删 1 个面必须指名亮**；
    ③ **整片挪 5 mm ⇒ 实测不亮** —— 这条**不是**「判据通过」，是**盲区 7** 的实测依据。

用法（★ 都是单行，Windows 终端可直接粘）：
  python tools/repair_project.py 状态
  python tools/repair_project.py 造 --blocks Tile_+003_+005 --with-rt
  python tools/repair_project.py 导回 --blocks Tile_+003_+005
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time

import numpy as np

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "tools"))

STAGES = {
    "edit": os.path.join(REPO, "_edit"),
    "repair": os.path.join(REPO, "_repair"),
    "clean": os.path.join(REPO, "_clean"),
    "flatten": os.path.join(REPO, "_flatten"),
    # ★ 步 4：`_drill/` 是**按楼栋**切的（步 3 产物），目录形状与 `_edit/` **逐字同形**
    #   （`<stage>/<名>/<名>.glb`）⇒ 「编辑器」不必为它另写一套，加一个 stage 就够（KISS/DRY）。
    #   ★ 块名在 drill 档就是**栋号** `bldg_<16hex>`（可指名——这是步 3 的全部意义）。
    "drill": os.path.join(REPO, "_drill"),
}

# ★ `--stage-dir` 覆盖（默认 None＝用 STAGES）。存在的唯一理由：**判据要在临时目录上跑同一条链**，
#   证明「工具真能跑」而**不碰交付件**（铁律 192：判据的参照物不许与交付件同源，且评测不许改被测件）。
_STAGE_ROOT = None


def stage_root(stage: str) -> str:
    return _STAGE_ROOT or STAGES[stage]
WORK = os.path.join(REPO, "_work", "修模工程")
ARCHIVE = os.path.join(REPO, "_archive")

# ★ `--archive-dir` 覆盖（默认 None＝用 `ARCHIVE`）：与 `--stage-dir`/`--work-dir` **同一件理由**。
#   导回**必先留档**（无 git ⇒ 唯一回退依据），档名带时间戳 ⇒ **每跑一次就在 `_archive/` 新长一个目录**。
#   评测（判据）会反复跑这条链 ⇒ 不重定向就会往只有人看的回退目录里**堆废档**，
#   而废档与真档**同名同形**，日后真要回退时**分不出哪份是那次修复前的**（铁律 197）。
#   ★ 代价照实说：重定向后，判据**不覆盖**「留档写到真 `_archive/`」这一步（见闸的盲区表）。
_ARCHIVE_ROOT = None


def archive_root() -> str:
    return _ARCHIVE_ROOT or ARCHIVE

# ★ `--work-dir` 覆盖（默认 None＝用 `WORK`）：与 `--stage-dir` **成对**用。
#   否则「造/导回」会往真 `_work/修模工程/` 里写名字相同的中间件（`.blend` / `导出.glb` 按块名命名），
#   等于**评测时改到了别人的工作目录** —— 那种污染不报错，只在下次人打开模板时以「怎么是这栋」现形。
_WORK_ROOT = None


def work_root() -> str:
    return _WORK_ROOT or WORK
BLENDER = "C:/Program Files/Blender Foundation/Blender 5.2/blender.exe"

# ★ 焊接触点容差**只许有一个来源**（铁律 174）：从焊接那一刀 import，本件不写第二个数。
from weld_vertices import DIGITS, weld_one                         # noqa: E402

RC_PASS, RC_FAIL, RC_NOGAUGE = 0, 1, 4

_MARK = "===== 判词 ====="


def log(*a):
    print(" ".join(str(x) for x in a))


def utc_now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def stamp() -> str:
    return datetime.datetime.now().strftime("%Y%m%d-%H%M%S")


def sha256_file(p: str) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for c in iter(lambda: f.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()


# ---------------------------------------------------------------- 只读读数

def piece_counts(path: str, weld: bool = False) -> dict:
    """trimesh 读件 ⇒ `{几何名: {"n_v":…, "n_f":…}}`。★ 这是**主件侧**的独立读数。

    `weld=True` 时先按 `DIGITS` 焊再数。★ 为什么要这个开关：Blender 导出会按 UV 缝**重拆点**
    ⇒ 两侧的**未焊**顶点数**本来就不同**（实测 2131 对 6922），拿它判「改没改」**恒为真**
    ⇒ 那个标记没有分辨力。**要判「改没改」必须两侧同形态（都焊）**；未焊读数只作参考。
    """
    import trimesh
    sc = trimesh.load(path, force="scene")
    out = {}
    for k, g in sc.geometry.items():
        if weld:
            g, _ = weld_one(g, DIGITS)
        out[k] = {"n_v": int(len(g.vertices)), "n_f": int(len(g.faces))}
    return out


def glb_images(path: str) -> int:
    """glTF JSON 块里 `images` 的条数（不解析二进制块）。"""
    import struct
    with open(path, "rb") as f:
        f.read(12)
        n = struct.unpack("<I", f.read(4))[0]
        f.seek(20)
        j = json.loads(f.read(n).decode("utf-8"))
    return len(j.get("images", []))


# ---------------------------------------------------------------- 结构守卫

def name_set_guard(got: dict, want: dict) -> list:
    """几何名集合必须**完全一致**。★ 返回的每条都要**指名**（「不一致」不算判词）。"""
    errs = []
    for m in sorted(set(want) - set(got)):
        errs.append("缺片：主件有 `%s`，导出件里没有" % m)
    for e in sorted(set(got) - set(want)):
        errs.append("多片：导出件里多出 `%s`，主件里没有" % e)
    for k in sorted(set(got) & set(want)):
        if got[k]["n_v"] <= 0 or got[k]["n_f"] <= 0:
            errs.append("空片：`%s` 顶点 %d 面 %d（看着有、其实没有）"
                        % (k, got[k]["n_v"], got[k]["n_f"]))
    return errs


def diff_counts(got: dict, want: dict) -> list:
    """逐片比 `(顶点数, 面数)`。★ 这是**报告**，不是合格线 —— 人就是要改几何的。"""
    rows = []
    for k in sorted(set(got) & set(want)):
        dv = got[k]["n_v"] - want[k]["n_v"]
        df = got[k]["n_f"] - want[k]["n_f"]
        rows.append({"piece": k, "n_v": got[k]["n_v"], "n_f": got[k]["n_f"],
                     "d_v": dv, "d_f": df, "changed": bool(dv or df)})
    return rows


# ---------------------------------------------------------------- Blender 端脚本

_BLEND_SCRIPT = r'''# -*- coding: utf-8 -*-
"""由 `tools/repair_project.py` 生成并驱动 —— Blender 端：装主件、落出处、存 .blend。"""
import bpy

SRC = r"@SRC@"
OUT = r"@OUT@"
BLOCK = "@BLOCK@"
STAGE = "@STAGE@"
SRC_SHA = "@SRC_SHA@"
EXPORT = r"@EXPORT@"

README = """cdut3d 修模工程 —— @BLOCK@（来源阶段：@STAGE@）

【这是什么】倾斜摄影成果的可编辑主件。改完**必须导出**，改动才回得去。
【三刀在哪做】★ 前两把与第三把**都在命令行**（tools/ 下，改完并 `导回` 之后再跑，不在此 .blend 内）：
     python tools/weld_vertices.py  --blocks <块>     焊点：洞 450->17（容差 0.1 mm，实测算出）
     python tools/drop_floaters.py  --blocks <块>     删退化面与悬浮物（阈值由面积空档算出）
     python tools/flatten_ground.py --blocks <块> --sel-file <声明.json>   只压**显式给定**的地面
   ★ 本 .blend **不预置任何自动修模** —— 计划 §4.2 定死：程序化预修模不做（那几刀最容易错，
     用户到手还得重改）。★ 要在 Blender 里**手工补洞**，就在 Edit Mode 里：
     A 全选 -> Ctrl+F -> Grid Fill，或 Mesh 菜单 -> Clean Up -> Fill Holes（按需调 Max Sides）。
     ★ 手工补洞**没有程序化判据**：本仓只保证你导出的件**结构**没坏（片数/名字），
     「补得对不对」是人的判断，不在任何判据的射程内。
【怎么交】在 Text Editor 里打开 `一键导出.py` 并 Run Script（或 Alt+P），
          它会写到 @EXPORT@ —— 那就是本工具 `导回` 要读的件。
【纪律】① 不许改**几何名**（那是回填的钥匙，改了就认不出是哪一片）。
        ② 导出格式 GLB、Y-up 保持默认 ON（脚本已写好，别手改）。
        ③ 改完先自己看一眼：Text Editor 里的 `自检.py` 会印出逐片顶点/面数。
"""

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=SRC)

sc = bpy.context.scene
sc.unit_settings.system = "METRIC"
sc.unit_settings.scale_length = 1.0
sc.name = "修模·" + BLOCK
sc["cdut3d_block"] = BLOCK
sc["cdut3d_stage"] = STAGE
sc["cdut3d_source_path"] = SRC
sc["cdut3d_source_sha256"] = SRC_SHA
sc["cdut3d_export_to"] = EXPORT
sc["cdut3d_note"] = "本 .blend 由 tools/repair_project.py 生成；几何名不许改。"

# 出处也写成一个**文本块**（件换手后仍能看到，不只藏在自定义属性里）
bpy.data.texts.new("README·纪律").from_string(README)
bpy.data.texts.new("一键导出.py").from_string(
    "import bpy\n"
    "bpy.ops.export_scene.gltf(filepath=r\"%s\", export_format=\"GLB\", export_yup=True)\n"
    "print(\"导出 →\", r\"%s\")\n" % (EXPORT, EXPORT))
bpy.data.texts.new("自检.py").from_string(
    "import bpy\n"
    "for o in bpy.data.objects:\n"
    "    if o.type == \"MESH\":\n"
    "        print(\"PIECE\", o.name, len(o.data.vertices), len(o.data.polygons))\n")

# 相机/太阳：只为「F12 能出图」，不参与任何判据
ms = [o for o in bpy.data.objects if o.type == "MESH"]
lo = [min(min((o.matrix_world @ v.co)[i] for v in o.data.vertices) for o in ms) for i in range(3)]
hi = [max(max((o.matrix_world @ v.co)[i] for v in o.data.vertices) for o in ms) for i in range(3)]
ctr = [(lo[i] + hi[i]) / 2.0 for i in range(3)]
rad = max(hi[i] - lo[i] for i in range(3)) or 1.0
cam_d = bpy.data.cameras.new("相机")
cam = bpy.data.objects.new("相机", cam_d)
cam.location = (ctr[0] + rad * 1.2, ctr[1] - rad * 1.6, ctr[2] + rad * 1.1)
bpy.context.collection.objects.link(cam)
sc.camera = cam
sun_d = bpy.data.lights.new("太阳", type="SUN")
sun_d.energy = 3.0
sun = bpy.data.objects.new("太阳", sun_d)
sun.location = (ctr[0] + rad, ctr[1] - rad, ctr[2] + rad * 2)
sun.rotation_euler = (0.6, 0.2, 0.5)
bpy.context.collection.objects.link(sun)

bpy.ops.wm.save_as_mainfile(filepath=OUT)
print("SAVED", OUT)
'''


_REOPEN_SCRIPT = r'''# -*- coding: utf-8 -*-
"""由 `tools/repair_project.py` 生成并驱动 —— **重开** `.blend` 自报逐片读数。"""
import bpy, json
res = {"props": {}, "texts": [], "pieces": {}}
sc = bpy.context.scene
for k in ("cdut3d_block", "cdut3d_stage", "cdut3d_source_path", "cdut3d_source_sha256"):
    res["props"][k] = str(sc.get(k, ""))
res["texts"] = sorted(t.name for t in bpy.data.texts)
for o in bpy.data.objects:
    if o.type == "MESH":
        res["pieces"][o.name] = {"n_v": len(o.data.vertices), "n_f": len(o.data.polygons)}
print("REOPEN_JSON " + json.dumps(res, ensure_ascii=False))
'''


def _run_blender(args: list, timeout: int) -> tuple:
    """跑 Blender headless ⇒ `(rc, 输出, 秒)`。★ rc=None 表示**崩了/超时**，与「没量到」分开报。"""
    t0 = time.time()
    try:
        p = subprocess.run([BLENDER] + args, capture_output=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return None, "超时 %ds 被终止" % timeout, round(time.time() - t0, 1)
    out = (p.stdout or b"").decode("utf-8", "replace") + (p.stderr or b"").decode("utf-8", "replace")
    return p.returncode, out, round(time.time() - t0, 1)


def _write_text(path: str, text: str):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "wb") as f:                    # ★ 字节层（铁律 79）
        f.write(text.encode("utf-8"))


# ---------------------------------------------------------------- 子命令

def stage_glb(stage: str, block: str) -> str:
    return os.path.join(stage_root(stage), block, block + ".glb")


def index_drift(stage: str, block: str) -> dict:
    r"""★ **台账漂移守卫** —— 导回之后，`<stage>/_index.json` 里记的那个块**已经过期了**。

    为什么必须查：`_drill/_index.json` 里逐栋记着 `bytes` / `sha256` / `n_f` / `area_m2`，
    而**判据与页面读的是那份台账**（`J-10.10-05` 读 `blocks[]`）。人改完一栋并导回之后，
    台账**一个字都没变** —— 它不会自己发现自己过期（本仓旧账：「链一重跑 PPT 就静默过期」）。
    ⇒ 本函数把「漂移」**印出来**（不是拦下来），并给出**正确的下一步**。

    ★★ 这条警告里最重要的一句：**别用 `drill_reality.py` 去刷台账**。
       它是**从 `_edit/` 重新切一遍** ⇒ 会**把人刚导回的改动整个丢掉**（而且不报错）。
    """
    root = stage_root(stage)
    idx = os.path.join(root, "_index.json")
    rec = {"index": idx, "exists": os.path.isfile(idx), "recorded": None,
           "actual_bytes": None, "actual_sha256": None, "bytes_match": None, "sha_match": None}
    if not rec["exists"]:
        return rec                      # ★ 没台账 ≠ 漂移（「没量到」与「不符」是两件事，铁律 199）
    try:
        with open(idx, "r", encoding="utf-8") as f:
            d = json.load(f)
    except (OSError, ValueError) as e:
        rec["unreadable"] = repr(e)
        return rec
    ent = None
    for k in ("blocks", "results"):     # `_drill` 用 blocks[]（键名 `fid`）；`_回切_*` 用 results[]（键名 `block`）
        for it in (d.get(k) or []):
            if it.get("fid") == block or it.get("block") == block:
                ent = it
                break
        if ent:
            break
    if ent is None:
        rec["not_in_index"] = True      # 台账里根本没这一条 ⇒ 不是漂移，是**另一回事**
        return rec
    rec["recorded"] = {k: ent.get(k) for k in ("bytes", "sha256", "n_f", "area_m2") if k in ent}
    p = stage_glb(stage, block)
    if not os.path.isfile(p):
        return rec
    rec["actual_bytes"] = os.path.getsize(p)
    rec["actual_sha256"] = sha256_file(p)
    rec["bytes_match"] = rec["recorded"].get("bytes") == rec["actual_bytes"]
    rec["sha_match"] = rec["recorded"].get("sha256") == rec["actual_sha256"]
    rec["drifted"] = not (rec["bytes_match"] and rec["sha_match"])
    return rec


def export_path(block: str) -> str:
    return os.path.join(work_root(),block + ".导出.glb")


def cmd_status(a) -> int:
    src_dir = stage_root(a.stage)
    if not os.path.isdir(src_dir):
        log("★ 量不到阶段目录：%s" % src_dir)
        return RC_NOGAUGE
    blocks = a.blocks or sorted(os.listdir(src_dir))
    blocks = [b for b in blocks if os.path.isdir(os.path.join(src_dir, b))]
    if not blocks:
        log("★ 量不到：`%s` 下一个块都没有 ⇒ 判不了（不是「都过了」）" % src_dir)
        return RC_NOGAUGE
    log("阶段目录（现算，不读任何台账）：")
    for name, d in STAGES.items():
        log("  %-8s %s" % (name, d if os.path.isdir(d) else "（不在）"))
    log("")
    for b in blocks:
        cells = []
        for name in STAGES:
            p = stage_glb(name, b)
            cells.append("%s=%s" % (name, ("%.1fMB" % (os.path.getsize(p) / 1e6))
                                    if os.path.isfile(p) else "无"))
        ex = export_path(b)
        log("  %-18s %s | 导出件=%s" % (b, "  ".join(cells),
                                       ("有 %.1fMB" % (os.path.getsize(ex) / 1e6))
                                       if os.path.isfile(ex) else "无"))
    log("")
    log("工作目录:", work_root())
    return RC_PASS


def cmd_make(a) -> int:
    block = a.blocks[0]
    src = stage_glb(a.stage, block)
    if not os.path.isfile(src):
        log("★ 量不到主件：%s" % src)
        return RC_NOGAUGE
    os.makedirs(work_root(), exist_ok=True)
    src_sha = sha256_file(src)
    want = piece_counts(src)
    n_img = glb_images(src)
    blend = os.path.join(work_root(),block + ".blend")
    ex = export_path(block)

    script = (_BLEND_SCRIPT.replace("@SRC@", src).replace("@OUT@", blend)
              .replace("@BLOCK@", block).replace("@STAGE@", a.stage)
              .replace("@SRC_SHA@", src_sha).replace("@EXPORT@", ex))
    sp = os.path.join(work_root(),"_造模板.py")
    _write_text(sp, script)
    rc, out, secs = _run_blender(["-b", "-P", sp], a.timeout)
    log("造模板：Blender rc=%s 用时 %ss" % (rc, secs))
    if rc is None:
        log("★ 崩了/超时：%s" % out.strip()[:300])
        return RC_FAIL
    if rc != 0 or not os.path.isfile(blend):
        log("★ 没造出 .blend（rc=%s）" % rc)
        log(out.strip()[-600:])
        return RC_FAIL

    # ---- 判据 A①②③：**重开** .blend 自报，与主件侧独立读数逐片比 ----
    rp = os.path.join(work_root(),"_重开读数.py")
    _write_text(rp, _REOPEN_SCRIPT)
    rc2, out2, secs2 = _run_blender(["-b", blend, "-P", rp], a.timeout)
    log("重开：Blender rc=%s 用时 %ss" % (rc2, secs2))
    got = {}
    for line in out2.splitlines():
        if line.startswith("REOPEN_JSON "):
            got = json.loads(line[len("REOPEN_JSON "):])
    if not got:
        log("★ 重开没读到读数 ⇒ 判不了（不是「模板没问题」）")
        log(out2.strip()[-600:])
        return RC_NOGAUGE
    pieces = got["pieces"]
    errs = name_set_guard(pieces, want)
    rows = diff_counts(pieces, want)
    for r in rows:
        if r["changed"]:
            errs.append("重开后 `%s` 的读数与主件不等：%d/%d 对 %d/%d"
                        % (r["piece"], r["n_v"], r["n_f"],
                           want[r["piece"]]["n_v"], want[r["piece"]]["n_f"]))
    # ★ 正对照：删一片 / 改一个数，同一个比较函数必须响（否则上面那条「相等」是恒绿）
    c1 = bool(name_set_guard(dict(list(pieces.items())[1:]), want)) if len(pieces) > 1 else None
    c2 = None
    if rows:
        fake = {k: dict(v) for k, v in pieces.items()}
        fake[rows[0]["piece"]]["n_f"] += 1
        c2 = bool([r for r in diff_counts(fake, want) if r["changed"]])
    prop_ok = (got["props"].get("cdut3d_source_sha256") == src_sha
               and os.path.normcase(got["props"].get("cdut3d_source_path", "")) == os.path.normcase(src))
    text_ok = "README·纪律" in got["texts"] and "一键导出.py" in got["texts"]

    log("")
    log("主件 %s ｜ %.0f KB ｜ sha256 %s…" % (os.path.basename(src), os.path.getsize(src) / 1e3,
                                            src_sha[:16]))
    log("主件侧读数（trimesh）：%d 片，面数 %s" % (len(want), [want[k]["n_f"] for k in sorted(want)]))
    log("模板侧读数（Blender 重开）：%d 片，面数 %s" % (len(pieces),
                                                [pieces[k]["n_f"] for k in sorted(pieces)]))
    log("贴图张数 %d（>0 为合格）｜出处属性 %s ｜出处文本块 %s" % (n_img, prop_ok, text_ok))
    log("正对照：删一片必须报缺片 = %s ｜ 面数 +1 必须报不等 = %s" % (c1, c2))
    if not n_img:
        errs.append("贴图张数为 0")
    if not prop_ok:
        errs.append("场景自定义属性里的出处与主件不符（件丢了「我是从哪来的」）")
    if not text_ok:
        errs.append("文本块缺 README·纪律 或 一键导出.py")

    rt = roundtrip_check(src, want) if a.with_rt else None
    if rt is not None:
        log("")
        log("未编辑往返自检（模板原样导出 → 两侧都按 DIGITS=%d 焊 → 与主件比）：" % DIGITS)
        if rt.get("err"):
            log("  ★ 没量到：%s（「崩了」与「没量到」不许同形）" % rt["err"])
            errs.append("未编辑往返自检没量到：%s" % rt["err"])
        else:
            for r in rt["rows"]:
                log("   %-30s 面 %5d/%5d 相等=%-5s ｜ 位置集合 %5d/%5d 逐位相等=%-5s ｜ 挪1mm必报=%s"
                    % (r["piece"], r["n_f_src"], r["n_f_rt"], r["face_exact"],
                       r["n_pos_src"], r["n_pos_rt"], r["pos_bitwise_same"],
                       r.get("falsifier_1mm_caught")))
            log("  面数逐片相等=%s ｜ 位置集合逐位相等=%s ｜ C6 伪证器全中=%s"
                % (rt["face_exact_all"], rt["pos_bitwise_all"], rt["falsifier_caught_all"]))
            if not rt["face_exact_all"]:
                errs.append("未编辑往返：面数不是逐片相等")
            if not rt["pos_bitwise_all"]:
                errs.append("未编辑往返：位置集合不是逐位相等")
            if not rt["falsifier_caught_all"]:
                errs.append("未编辑往返：C6 伪证器没响 ⇒ 上面那两条绿不可信（尺子恒绿）")

    _write_work_json(block, "造", {"block": block, "stage": a.stage, "src": src,
                                   "src_sha256": src_sha, "blend": blend,
                                   "n_images": n_img,
                                   "pieces_source": want, "pieces_blend": pieces,
                                   "source_props_ok": prop_ok, "texts": got["texts"],
                                   "controls": {"C1_缺片必报": c1, "C2_面数改动必报": c2},
                                   "roundtrip": rt, "errs": errs, "at": utc_now()})
    log("")
    log(_MARK)
    if errs:
        for e in errs:
            log("  违规：" + e)
        log("修模工程·造 %s : FAIL" % block)
        return RC_FAIL
    log("修模工程·造 %s : PASS（重开后 %d 片逐片相等 ｜ 贴图 %d 张 ｜ 出处自带）"
        % (block, len(pieces), n_img))
    return RC_PASS


def roundtrip_check(src: str, want: dict):
    """★ C5 未编辑往返：模板**原样导出** → 按 `DIGITS` 焊 → 与主件比两条独立判据。

    ★ 为什么要焊：实测（2026-10-15）Blender 导出会按 UV 缝**重新拆点**（1322 → 6919 顶点），
      面表却逐位不变。⇒ 「顶点数」在**焊/未焊两种形态下本来就不同**，跨形态直接比会假红。
      焊回的容差**从 `weld_vertices.DIGITS` import**（铁律 174）。
    """
    import trimesh
    from weld_vertices import weld_one
    blend = [os.path.join(work_root(),f) for f in os.listdir(WORK) if f.endswith(".blend")]
    if not blend:
        return {"err": "找不到 .blend（先跑 `造`）"}
    rt_glb = os.path.join(work_root(),"_往返自检.glb")
    sp = os.path.join(work_root(),"_往返自检.py")
    _write_text(sp, "import bpy\n"
                    "bpy.ops.export_scene.gltf(filepath=r\"%s\", export_format=\"GLB\","
                    " export_yup=True)\nprint(\"RT_EXPORTED\")\n" % rt_glb)
    rc, out, secs = _run_blender(["-b", blend[0], "-P", sp], 300)
    if rc != 0 or not os.path.isfile(rt_glb):
        return {"err": "原样导出没成（rc=%s）" % rc, "secs": secs}
    A = trimesh.load(src, force="scene")
    B = trimesh.load(rt_glb, force="scene")
    rows, allf, alls = [], True, True
    falsifier = []                      # ★ C6：挪 1 mm 后**必须**不再相等
    for k in sorted(want):
        if k not in B.geometry:
            rows.append({"piece": k, "err": "导出件里没有这一片"})
            allf = alls = False
            continue
        # ★★ 两侧**都进同一形态**（都焊）—— 第一版拿未焊 src 比焊过 rt ⇒ 1323 对 1322 假红。
        ws, _ = weld_one(A.geometry[k], DIGITS)
        wt, _rd = weld_one(B.geometry[k], DIGITS)
        fa = np.asarray(ws.faces)
        fw = np.asarray(wt.faces)
        sa = set(map(tuple, np.asarray(ws.vertices, float).tolist()))
        sw = set(map(tuple, np.asarray(wt.vertices, float).tolist()))
        okf, oks = bool(fa.shape == fw.shape), bool(sa == sw)
        allf, alls = allf and okf, alls and oks
        # C6 伪证器：把焊后 rt 的第一个顶点在 x 上挪 1 mm，集合必须不再等于 sa
        mv = wt.copy()
        vv = np.asarray(mv.vertices, float).copy()
        vv[0][0] += 1.0
        mv.vertices = vv
        caught = not bool(set(map(tuple, np.asarray(mv.vertices, float).tolist())) == sa)
        falsifier.append(caught)
        rows.append({"piece": k, "n_f_src": int(fa.shape[0]), "n_f_rt": int(fw.shape[0]),
                     "face_exact": okf, "n_pos_src": len(sa), "n_pos_rt": len(sw),
                     "pos_bitwise_same": oks, "falsifier_1mm_caught": caught})
    return {"rt_glb": rt_glb, "rows": rows,
            "face_exact_all": allf, "pos_bitwise_all": alls,
            "falsifier_caught_all": bool(falsifier) and all(falsifier), "secs": secs}


def cmd_import(a) -> int:
    """`导回` —— 把人的导出件**原样**装回主件（先留档、逐位核、结构守卫）。"""
    block = a.blocks[0]
    ex = export_path(block)
    master = stage_glb(a.stage, block)
    if not os.path.isfile(ex):
        # ★ C3：不导出 ⇒ 「改动必须消失」。这里判 **rc=4 没量到**，不许静默当成功。
        log("★ 没量到导出件：%s" % ex)
        log("   （在 Blender 里 Run `一键导出.py`，或手工导到上面这个路径）")
        return RC_NOGAUGE
    if not os.path.isfile(master):
        log("★ 没量到主件：%s" % master)
        return RC_NOGAUGE

    want_raw = piece_counts(master)
    got_raw = piece_counts(ex)
    errs = name_set_guard(got_raw, want_raw)
    # ★ 「改没改」必须**两侧同形态**（都焊）：未焊顶点数跨形态不可比（实测 2131 对 6922），
    #   拿它判会**恒为「改过」** ⇒ 那个标记没有分辨力（铁律 183：同形状的错会换个函数再犯）。
    want = piece_counts(master, weld=True)
    got = piece_counts(ex, weld=True)
    rows = diff_counts(got, want)

    # ★ C4 正对照：把导出件的一个几何名改掉 ⇒ 上面的守卫必须**指名**报出
    c4 = None
    if got:
        k0 = sorted(got)[0]
        fake = dict(got)
        fake["%s_改坏了" % k0] = fake.pop(k0)
        c4 = name_set_guard(fake, want)
        log("正对照 C4（把 `%s` 改名，同一个守卫必须响）：%s" % (k0, c4[0] if c4 else "**没响！判据失灵**"))
    if errs:
        log(_MARK)
        for e in errs:
            log("  违规：" + e)
        log("修模工程·导回 %s : FAIL（结构守卫不许过）" % block)
        return RC_FAIL

    # 留档（★ 无 git ⇒ 唯一回退依据）
    d = os.path.join(archive_root(), "%s-主件导回留档-%s" % (block, stamp()))
    os.makedirs(d, exist_ok=True)
    old_sha = sha256_file(master)
    shutil.copyfile(master, os.path.join(d, block + ".glb.before"))
    shutil.copyfile(ex, master)                       # ★ 逐位搬运，不做任何加工
    new_sha = sha256_file(master)
    ex_sha = sha256_file(ex)
    same_bytes = bool(new_sha == ex_sha)

    log("导出件 %s ｜ %.0f KB ｜ sha256 %s…" % (os.path.basename(ex),
                                              os.path.getsize(ex) / 1e3, ex_sha[:16]))
    log("主件   %s ｜ 旧 sha256 %s… → 新 %s…" % (os.path.basename(master), old_sha[:16], new_sha[:16]))
    log("逐位原样搬运：%s ｜ 留档 %s" % (same_bytes, d))
    log("逐片读数（「改过」按**焊后同形态**判；未焊顶点数只作参考，跨形态不可比）：")
    for r in rows:
        k = r["piece"]
        log("   %-30s 未焊顶点 %6d → %6d ｜ 焊后 顶点 %6d → %6d (%+d)  面 %6d → %6d (%+d)%s"
            % (k, want_raw[k]["n_v"], got_raw[k]["n_v"],
               want[k]["n_v"], r["n_v"], r["d_v"],
               want[k]["n_f"], r["n_f"], r["d_f"], "  ← 改过" if r["changed"] else ""))
    log("")
    log("下一步（改动要走到瓦片，必须往下跑；★ 都是单行命令）：")
    if a.stage == "drill":
        # ★ drill 档的下一跳**只有一条**：直接回切。跑 `drill_reality.py` 会把这一改**整个丢掉**。
        log("   python tools/editable_to_tiles.py --edit _drill --out _回切_按栋 --all")
        log("   ★★ **不要** 用 `python tools/drill_reality.py` 去「刷新」—— 它是从 `_edit/` 重切一遍，")
        log("      会把人刚导回的改动**整个丢掉**，而且**不报错**。")
    else:
        log("   python tools/weld_vertices.py --blocks %s" % block)
        log("   python tools/drop_floaters.py --blocks %s" % block)
        log("   python tools/flatten_ground.py --blocks %s --sel-file <你的声明文件.json>" % block)
        log("   python tools/editable_to_tiles.py --blocks %s" % block)

    drift = index_drift(a.stage, block)
    if drift.get("drifted"):
        log("")
        log("★ **台账已过期**：`%s` 里这一块记的读数与盘上的件**对不上了**（它不会自己发现）"
            % os.path.basename(drift["index"]))
        log("   台账记 bytes=%s sha256=%s…"
            % (drift["recorded"].get("bytes"), str(drift["recorded"].get("sha256"))[:16]))
        log("   盘上现算 bytes=%s sha256=%s…"
            % (drift["actual_bytes"], str(drift["actual_sha256"])[:16]))
        log("   ⇒ 读那份台账的判据/页面（`J-10.10-05`、挑栋页）此刻印的是**旧数**。")
    elif drift.get("exists") and drift.get("not_in_index"):
        log("")
        log("★ 台账里**没有** `%s` 这一条 ⇒ 本件量不到漂移（不是「没漂」）" % block)

    _write_work_json(block, "导回", {"block": block, "stage": a.stage,
                                    "export": ex, "export_sha256": ex_sha,
                                    "master": master, "old_sha256": old_sha, "new_sha256": new_sha,
                                    "bytewise_same": same_bytes, "archive": d,
                                    "pieces_master_raw": want_raw, "pieces_export_raw": got_raw,
                                    "diff_basis": "welded(DIGITS=%d)" % DIGITS,
                                    "pieces_master": want, "pieces_export": got,
                                    "diff": rows, "controls": {"C4_改名必指名": c4},
                                    "index_drift": drift,
                                    "errs": errs, "at": utc_now()})
    log("")
    log(_MARK)
    if not same_bytes:
        log("  违规：落盘后 sha256 与导出件不等 ⇒ 搬运被二次加工过")
        log("修模工程·导回 %s : FAIL" % block)
        return RC_FAIL
    log("修模工程·导回 %s : PASS（%d 片结构一致 ｜ 落盘与导出件逐位相同 ｜ 旧件已留档）"
        % (block, len(got)))
    return RC_PASS


def _write_work_json(block: str, kind: str, payload: dict):
    os.makedirs(work_root(), exist_ok=True)
    p = os.path.join(work_root(),"%s.%s.json" % (block, kind))
    payload["tool"] = "tools/repair_project.py"
    with open(p, "wb") as f:                            # ★ 字节层（铁律 79）
        f.write(json.dumps(payload, ensure_ascii=False, indent=1, sort_keys=False).encode("utf-8"))
    log("台账 →", p)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="修模工程模板与一键导回（编辑器的人机接口）")
    ap.add_argument("cmd", choices=["状态", "造", "导回"])
    ap.add_argument("--blocks", nargs="*", default=None, help="块名（不给=全部/报错）")
    ap.add_argument("--stage", default="edit", choices=sorted(STAGES),
                    help="主件取自哪个阶段目录（默认 edit＝主件；drill＝按楼栋）")
    ap.add_argument("--stage-dir", default=None,
                    help="★ 覆盖阶段目录（判据用：在**临时目录**上跑同一条链，不碰交付件）")
    ap.add_argument("--with-rt", action="store_true",
                    help="造模板时附带跑「未编辑往返」自检（多一次 Blender）")
    ap.add_argument("--timeout", type=int, default=600)
    ap.add_argument("--work-dir", default=None,
                    help="★ 覆盖工作目录（默认 `_work/修模工程`）；与 --stage-dir 成对，用于隔离评测")
    ap.add_argument("--archive-dir", default=None,
                    help="★ 覆盖留档目录（默认 `_archive`）；防反复评测往人的回退目录里堆废档")
    a = ap.parse_args(argv)
    global _STAGE_ROOT, _WORK_ROOT, _ARCHIVE_ROOT
    if a.stage_dir:
        _STAGE_ROOT = os.path.abspath(a.stage_dir)
    if a.work_dir:
        _WORK_ROOT = os.path.abspath(a.work_dir)
    if a.archive_dir:
        _ARCHIVE_ROOT = os.path.abspath(a.archive_dir)
    if not os.path.isfile(os.path.join(REPO, "tools", "weld_vertices.py")):
        log("★ 焊接那一刀不在 ⇒ 往返自检没法用同一个容差（铁律 174）")
        return RC_NOGAUGE
    if not os.path.isfile(BLENDER):
        log("★ 量不到 Blender：%s" % BLENDER)
        return RC_NOGAUGE
    if a.cmd == "状态":
        return cmd_status(a)
    if not a.blocks:
        log("★ `%s` 必须点名 --blocks（不许默认动全部主件）" % a.cmd)
        return RC_NOGAUGE
    if a.cmd == "造":
        return cmd_make(a)
    return cmd_import(a)


if __name__ == "__main__":
    sys.exit(main())
