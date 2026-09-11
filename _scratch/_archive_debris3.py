# -*- coding: utf-8 -*-
r"""第四遍：归档「理化楼/六教时代」的遗留目录、一次性产物与死代码。

与前三批同一套约定：只移动不删除，哈希入清单，可一键还原（_unarchive.py 读全部清单）。

**判据（唯一）**：不被**存活代码**真实引用。
存活代码 = frontend/*.html + backend/{web,db,recognizer,nav}/ + backend/modeling/build_standard_glb|glb_common
          + backend/extract/{extract_rooms_generic,extract_rooms_c006,backfill_floor_rooms}
          + 根目录保留的 19 个脚本。
**legacy 建模器不算存活源**——它们自己就是要归档的对象，互相引用不构成存活证据。

明确不碰：data/buildings/（48 栋主数据）、data/floors + rooms.json + spec.json + adjacency.json
（serve_rooms/building.html 在用）、data/j6-walls.glb（render_j6.html 在用）、_qa/（体检基线）、blender/（渲染能力）。

用法: python _scratch/_archive_debris3.py [--apply]
"""
import os, sys, json, glob, shutil, hashlib, re, time

sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
ROOT = r"D:\gym3d"
SCRATCH = os.path.join(ROOT, "_scratch")
MANIFEST = os.path.join(SCRATCH, "_MANIFEST_DEBRIS3.json")

# —— 存活代码（引用检查的唯一权威）——
LIVE = [
    "frontend/*.html",
    "backend/web/*.py", "backend/db/*.py", "backend/recognizer/*.py", "backend/nav/*.py",
    "backend/modeling/build_standard_glb.py", "backend/modeling/glb_common.py",
    "backend/extract/extract_rooms_generic.py", "backend/extract/extract_rooms_c006.py",
    "backend/extract/backfill_floor_rooms.py",
]
# 根目录保留脚本（管线/生产/门禁/回归资产）
LIVE_ROOT = ["run_building", "run_batch", "convert_dwg_to_dxf", "build_index", "qa_structural",
             "_wall_thin_batch", "_wall_thin_force", "_dxf_cad_render", "_dxf_compare_render",
             "_dxf_png_batch", "_dxf_audit", "_dxf_audit_report", "_sweep_modeling",
             "_door_punch_apply", "_run_c019_tmp", "_probe_c019_thin_dryrun",
             "_probe_doorbox_equiv", "_glb_only", "_test_curve_pair"]

# —— 待归档候选：(相对 ROOT 路径, 目标子路径) ——
CANDIDATES = [
    # 整目录
    ("archive",                                "legacy/"),
    ("render_c103",                            "legacy/"),
    ("_al_check",                              "legacy/"),
    ("backend/extract",                        "legacy/backend_extract"),   # 见下方逐文件白名单
    ("backend/modeling",                        "legacy/backend_modeling"),  # 见下方逐文件白名单
    # 过期文档
    ("PLAN.md",                                "legacy/"),
    # 死数据（根 spec.json；data/ 的理化楼时代产物）
    ("spec.json",                              "legacy/"),
    ("data/gymnasium.glb",                     "legacy/data"),
    ("data/j6-dbg.glb",                        "legacy/data"),
    ("data/j6-deci03.glb",                     "legacy/data"),
    ("data/cad_model.json",                    "legacy/data"),
    ("data/geometry.json",                     "legacy/data"),
    ("data/outline_v2.json",                   "legacy/data"),
    ("data/adjacency_v1_backup.json",          "legacy/data"),
    ("data/preview.html",                      "legacy/data"),
    ("data/nav_grid_f0.png",                   "legacy/data"),
    ("data/lihua-geometry.json",               "legacy/data"),
]

# 逐文件白名单：目录候选里**必须留在原地**的（存活）
KEEP_IN_DIR = {
    "backend/extract": {"extract_rooms_generic.py", "extract_rooms_c006.py", "backfill_floor_rooms.py"},
    "backend/modeling": {"build_standard_glb.py", "glb_common.py"},
}
# data/ 下按前缀整批归档的理化楼时代产物
DATA_GLOB = ["data/lihua*", "data/path_0*"]

# 前缀命中但**存活**的例外（相对 ROOT）：
#   data/lihua-building.glb —— run_step.py:107-109「注册表楼（理化楼）」分支的落盘目标，是活产物
KEEP_ABS = {"data/lihua-building.glb"}

# 已逐行人工核对为「无引用」的例外（自动匹配必然假阳性）：
#   根 spec.json —— serve_rooms.py:8,88 与 build_standard_glb.py:99 引用的都是
#   data/spec.json（DATA 相对路径），无一指向仓库根；散文里出现的 "spec.json" 不是引用。
#   目标在 data/ 的 index.json / rooms.json / floors/ 等均已单独保留，未被本批触及。
VERIFIED_DEAD = {"spec.json"}


def sha(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for c in iter(lambda: f.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()


def live_texts():
    ps = []
    for pat in LIVE:
        ps += glob.glob(os.path.join(ROOT, pat))
    for n in LIVE_ROOT:
        p = os.path.join(ROOT, n + ".py")
        if os.path.exists(p):
            ps.append(p)
    out = {}
    for p in ps:
        try:
            out[p] = open(p, encoding="utf-8", errors="replace").read()
        except Exception:
            pass
    return out


def expand():
    """把候选展开成 (绝对路径, 目标子路径) 列表。"""
    items = []
    for rel, dest in CANDIDATES:
        p = os.path.join(ROOT, rel)
        if not os.path.exists(p):
            continue
        if os.path.isdir(p):
            keep = KEEP_IN_DIR.get(rel.replace("\\", "/"), set())
            for f in sorted(os.listdir(p)):
                if f in keep or f == "__pycache__":
                    continue
                items.append((os.path.join(p, f), "legacy/" + os.path.basename(rel)))
        else:
            items.append((p, dest))
    for g in DATA_GLOB:
        d = os.path.dirname(g)
        base = os.path.basename(g)
        for p in sorted(glob.glob(os.path.join(ROOT, g))):
            if os.path.basename(p) == "lihua_twin":
                continue
            if os.path.relpath(p, ROOT).replace("\\", "/") in KEEP_ABS:
                continue
            items.append((p, "legacy/data"))
    # 去重（必须 normpath：glob 通配段保留 '/' 而 os.path.join 用 '\'，直接比字符串会漏）
    seen, out = set(), []
    for p, d in items:
        k = os.path.normcase(os.path.normpath(p))
        if k in seen:
            continue
        seen.add(k)
        out.append((p, d))
    return out


def main():
    ap = "--apply" in sys.argv
    plan = expand()
    texts = live_texts()

    blocked = []
    for p, _ in plan:
        n = os.path.basename(p)
        stem = os.path.splitext(n)[0]
        isdir = os.path.isdir(p)
        # 目录名太通用（data/html/img），只按「路径限定」匹配；文件名按词边界匹配，
        # 否则根 spec.json 会被 data/spec.json 这种同名字符串误判为被引用。
        rel_c = os.path.relpath(p, ROOT).replace("\\", "/")
        pat = re.compile(r"(?<![\w/\\.\-])%s" % re.escape(n)) if not isdir else None
        # 目录按**完整相对路径**匹配（archive/data），不按 basename（data 是通用词）
        dirpat = re.compile(r"(?<![\w\-.])%s[/\\]" % re.escape(rel_c)) if isdir else None
        hits = []
        if rel_c in VERIFIED_DEAD:
            continue
        for s, t in texts.items():
            if os.path.abspath(s).startswith(os.path.abspath(p)):
                continue
            rel = os.path.relpath(s, ROOT)
            if n.endswith(".py"):
                if re.search(r"^\s*(?:import\s+%s\b|from\s+%s\s+import)" % (re.escape(stem), re.escape(stem)),
                             t, re.M):
                    hits.append(rel)
            elif isdir and dirpat.search(t):
                hits.append(rel)
            elif not isdir and pat.search(t):
                hits.append(rel)
        if hits:
            blocked.append((os.path.relpath(p, ROOT), sorted(set(hits))[:2]))

    print("候选 %d 项；存活源 %d 个。" % (len(plan), len(texts)))
    if blocked:
        print("\n!! 中止：以下被存活代码引用，不能归档：")
        for rel, hits in blocked:
            print("   %-44s <- %s" % (rel, ", ".join(hits)))
        return 2
    print("引用闸通过（存活代码零引用）。\n")

    bydest = {}
    for p, d in plan:
        bydest.setdefault(d, []).append(os.path.relpath(p, ROOT))
    for d in sorted(bydest):
        print("  -> _scratch/%-24s %2d 项" % (d, len(bydest[d])))
    if not ap:
        print("\n（干跑。加 --apply 真移动）")
        return 0

    items = []
    for p, dest in plan:
        dd = os.path.join(SCRATCH, *dest.split("/"))
        os.makedirs(dd, exist_ok=True)
        n = os.path.basename(p)
        dst = os.path.join(dd, n)
        # 续跑容错：源已不在但目标在 → 上一次中断时移过去的，先补记清单（按目标哈希）
        if not os.path.exists(p) and os.path.exists(dst):
            if os.path.isdir(dst):
                items.append(dict(name=n, dest=dest, isdir=True, src=p, dst=dst, resumed=True))
            else:
                items.append(dict(name=n, dest=dest, size=os.path.getsize(dst), sha256=sha(dst),
                                  src=p, dst=dst, resumed=True))
            continue
        if os.path.isdir(p):
            shutil.move(p, dst)
            items.append(dict(name=n, dest=dest, isdir=True, src=p, dst=dst))
            continue
        if os.path.exists(dst):   # 与新移入的同名文件冲突，加哈希后缀
            dst = os.path.join(dd, "%s_%s" % (n, hashlib.md5(p.encode()).hexdigest()[:6]))
        rec = dict(name=n, dest=dest, size=os.path.getsize(p), sha256=sha(p), src=p, dst=dst)
        shutil.move(p, dst)
        if sha(dst) != rec["sha256"]:
            shutil.move(dst, p)
            print("   !! 哈希不符已回滚: %s" % n)
            continue
        items.append(rec)

    old = json.load(open(MANIFEST, encoding="utf-8")) if os.path.exists(MANIFEST) else {"moved": []}
    json.dump(dict(ts=time.strftime("%Y%m%d_%H%M%S"), moved=old.get("moved", []) + items),
              open(MANIFEST, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("\n移动 %d 项；清单 -> %s" % (len(items), MANIFEST))
    print("还原 -> python _scratch/_unarchive.py [--apply]")
    return 0


if __name__ == "__main__":
    sys.exit(main())
