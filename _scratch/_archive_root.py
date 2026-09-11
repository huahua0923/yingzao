# -*- coding: utf-8 -*-
r"""把根目录的一次性脚本归档进 _scratch/（只移动，不删除，可一键还原）。

判据：脚本是不是「管线/生产/门禁/回归资产」。
  - 是 -> 留在 D:\gym3d 根目录（KEEP）
  - 不是 -> 移进 D:\gym3d\_scratch\（一次性探针/补丁/单栋修复/建档期工具）

安全：
  - **只移动，绝不删除**；移动前写 SHA256 清单 _scratch/_MANIFEST.json
  - 生成 _scratch/_unarchive.py，随时一键还原回根目录
  - 移动前校验：KEEP 集合必须覆盖所有「被 backend/ 或其他 KEEP 脚本真实 import 的」脚本

用法: python _scratch/_archive_root.py            # 干跑，只报告
      python _scratch/_archive_root.py --apply    # 真移动
"""
import os, sys, json, shutil, hashlib, time, re, glob

sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

ROOT = r"D:\gym3d"
SCRATCH = os.path.join(ROOT, "_scratch")
MANIFEST = os.path.join(SCRATCH, "_MANIFEST.json")

# —— 保留在根目录的「管线/生产/门禁/回归资产」———————————————
# 判据不是"看起来重要"，而是：被 backend/ 或其他保留脚本真实 import，或属于交付链固定环节。
KEEP = {
    # 管线入口
    "run_building",          # 单栋管道；backend/web/run_step.py 真 import
    "run_batch",             # 批量管道（用户铁律：不许跑，但脚本保留）
    "convert_dwg_to_dxf",    # DWG->DXF，管线第一步
    "build_index",           # 生成 data/buildings/index.json，网页选择器消费
    "qa_structural",         # 结构体检不变量门禁（只读，不可改不可移）
    # 内墙重建（生产）
    "_wall_thin_batch",
    "_wall_thin_force",
    # 图纸渲染三件套（生产；彼此真 import）
    "_dxf_cad_render",       # 源图纸所有者；_dxf_audit 真 import
    "_dxf_compare_render",   # 真 import _dxf_png_batch
    "_dxf_png_batch",        # 识别叠加图
    # 审计
    "_dxf_audit",
    "_dxf_audit_report",     # 真 import _dxf_audit
    "_sweep_modeling",       # 全仓缺陷扫描（回归用）
    # 门洞工具箱（待推广到其他楼）
    "_door_punch_apply",
    "_run_c019_tmp",         # 被 _door_punch_apply 报错信息引用
    "_probe_c019_thin_dryrun",
    "_probe_doorbox_equiv",  # _door_boxes 等价性单测
    # 工具与单测
    "_glb_only",             # 不重跑 recognize 只重出 GLB
    "_test_curve_pair",
}

# 归档后按用途分组写进 README（纯导航，不影响文件位置——scratch 内脚本互相 import，必须同一目录）
GROUPS = [
    ("probe/ 探针（只读诊断，一次性）", lambda n: n.startswith("_probe_")),
    ("patch/ 补丁与试点（已应用，历史）", lambda n: n.startswith("_patch_") or n.startswith("_pilot_")),
    ("bybuilding/ 单栋专项修复", lambda n: re.match(r"_(c0\d\d|trim_)", n) is not None),
    ("onetime/ 一次性数据修复", lambda n: n in {
        "_columns_fix_zerovol", "_stairs_fix_giants", "_stairs_redetect", "_fix_uniform",
        "_doors_rebuild", "_regen_windows", "_rooms_batch_write", "_rooms_batch_dry",
        "_trim_c103_f0"}),
    ("census/ 普查与审计（只读）", lambda n: n.startswith(("_stairs_", "_rooms_census", "_wall_verify",
        "_walls_profile", "_curve_", "_diag_", "_doors_displace", "_door_symbol", "_sweep"))),
    ("render/ 被取代的渲染", lambda n: n in {"render_floor_pngs", "compare_floors", "wall_plan",
        "_dxf_plan_ascii", "_overlay_region"}),
    ("profiling/ 建档期工具", lambda n: n in {
        "pipeline", "gather_dwg", "inspect_building", "detect_all", "detect_floors", "detect_layout",
        "diag_apartments", "recon_apartments", "recon_teaching", "batch_profiles", "add_style",
        "check_alignment", "check_complex"}),
]


def sha(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main():
    apply_ = "--apply" in sys.argv
    os.makedirs(SCRATCH, exist_ok=True)

    all_root = sorted(os.path.basename(p) for p in glob.glob(os.path.join(ROOT, "*.py")))
    move = [n[:-3] for n in all_root if n[:-3] not in KEEP]
    keep = [n[:-3] for n in all_root if n[:-3] in KEEP]

    # —— 安全校验：KEEP 必须覆盖所有被 backend/ 真实 import 的根脚本 ——
    back = []
    for r, d, fs in os.walk(os.path.join(ROOT, "backend")):
        if any(x in r for x in (".orig", "_tmp", "__pycache__", "node_modules")):
            continue
        for f in fs:
            if f.endswith(".py"):
                back.append(os.path.join(r, f))
    missing = set()
    for s in back:
        try:
            t = open(s, encoding="utf-8", errors="replace").read()
        except Exception:
            continue
        for c in move:
            # 只认真 import，不认注释/文档串里的提及
            if re.search(r"^\s*(?:import\s+%s\b|from\s+%s\s+import)" % (re.escape(c), re.escape(c)),
                         t, re.M):
                missing.add((c, os.path.relpath(s, ROOT)))
    if missing:
        print("!! 中止：以下待归档脚本被 backend/ 真实 import，必须先加入 KEEP：")
        for c, s in sorted(missing):
            print("   %s  <-  %s" % (c, s))
        return 2

    print("根目录 .py  %d 个  ->  保留 %d / 归档 %d" % (len(all_root), len(keep), len(move)))
    print("\n保留在根目录（%d）：" % len(keep))
    for k in keep:
        print("   %s" % k)
    if not apply_:
        print("\n（干跑。加 --apply 真移动）")
        return 0

    ts = time.strftime("%Y%m%d_%H%M%S")
    items = []
    for c in move:
        src = os.path.join(ROOT, c + ".py")
        dst = os.path.join(SCRATCH, c + ".py")
        if os.path.exists(dst):
            print("   跳过(scratch 已存在同名): %s" % c)
            continue
        rec = dict(name=c, size=os.path.getsize(src), sha256=sha(src),
                   mtime=time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(os.path.getmtime(src))),
                   src=src, dst=dst)
        shutil.move(src, dst)
        # 移动后校验哈希一致，不一致立刻移回
        if sha(dst) != rec["sha256"]:
            shutil.move(dst, src)
            print("   !! 哈希不符已回滚: %s" % c)
            continue
        items.append(rec)

    json.dump(dict(ts=ts, root=ROOT, scratch=SCRATCH, moved=items),
              open(MANIFEST, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    write_unarchive()
    write_readme(items)
    print("\n移动 %d 个 -> %s" % (len(items), SCRATCH))
    print("清单 -> %s" % MANIFEST)
    print("还原 -> python _scratch/_unarchive.py [--apply]")
    return 0


def write_unarchive():
    open(os.path.join(SCRATCH, "_unarchive.py"), "w", encoding="utf-8").write('''# -*- coding: utf-8 -*-
"""按 _MANIFEST.json 把归档脚本还原回根目录。默认干跑，--apply 真移。"""
import os, sys, json, shutil, hashlib
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
D = os.path.dirname(os.path.abspath(__file__))
M = json.load(open(os.path.join(D, "_MANIFEST.json"), encoding="utf-8"))
ap = "--apply" in sys.argv
n = 0
for it in M["moved"]:
    if not os.path.exists(it["dst"]):
        print("  缺失: %s" % it["name"]); continue
    if os.path.exists(it["src"]):
        print("  已存在(不覆盖): %s" % it["name"]); continue
    print("  %s  %s" % ("还原" if ap else "将还原", it["name"]))
    if ap:
        shutil.move(it["dst"], it["src"]); n += 1
print("\\n%s %d / %d" % ("已还原" if ap else "待还原", n if ap else len(M["moved"]), len(M["moved"])))
''')


def write_readme(items):
    names = {it["name"] for it in items}
    used = set()
    L = ["# _scratch —— 根目录一次性脚本归档", "",
         "**用法**：`python _scratch/_unarchive.py --apply` 一键还原回根目录。",
         "存档时间：`%s`，共 %d 个脚本；清单（含 SHA256）见 `_MANIFEST.json`。" % (
             time.strftime("%Y-%m-%d %H:%M"), len(items)), "",
         "## 根目录为什么只留这些", "",
         "留下的都是**管线/生产/门禁/回归资产**（被 `backend/` 或其他保留脚本真实 import，",
         "或属于交付链固定环节）。其余全部是一次性产物：跑过一次、结论已固化进数据或记忆。",
         "它们仍然**有用**——出问题时是最快的取证入口——所以只归档不删除。", "",
         "## 分组导航", ""]
    for title, pred in GROUPS:
        hit = sorted(n for n in names if pred(n) and n not in used)
        used |= set(hit)
        if not hit:
            continue
        L.append("### %s（%d）" % (title, len(hit)))
        L.append("")
        for n in hit:
            L.append("- `%s.py`" % n)
        L.append("")
    rest = sorted(names - used)
    if rest:
        L += ["### 其他（%d）" % len(rest), ""] + ["- `%s.py`" % n for n in rest] + [""]
    open(os.path.join(SCRATCH, "README.md"), "w", encoding="utf-8").write("\n".join(L))


if __name__ == "__main__":
    sys.exit(main())
