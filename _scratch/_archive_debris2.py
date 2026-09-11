# -*- coding: utf-8 -*-
r"""第三遍：归档 root / data / backend 三处的调试碎片（脚本、图片、文本、临时目录）。

与 _archive_root.py / _archive_debris.py 同一套约定：只移动不删除，哈希入清单，可一键还原。

**三重安全闸**（过不了就中止，绝不猜）：
  1. 待归档的 .py —— 被 backend/ 或根目录保留脚本**真实 import** 的不动
  2. 待归档的 .glb/.json/.png/.html —— 被 frontend/*.html 或 backend/**/*.py **按名引用**的不动
  3. 明确不碰：data/buildings/*/.orig（数据回滚备份）、data/*.glb（交付/前端引用）、
     _qa/（体检基线证据）、archive/ blender/ render_c103/（历史整目录）

用法: python _scratch/_archive_debris2.py [--apply]
"""
import os, sys, json, glob, shutil, hashlib, re, time

sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

ROOT = r"D:\gym3d"
SCRATCH = os.path.join(ROOT, "_scratch")
MANIFEST = os.path.join(SCRATCH, "_MANIFEST_DEBRIS2.json")

# 扫描引用时要跳过的目录
SKIP_DIRS = {".orig", "_tmp", "__pycache__", "node_modules", ".git", "_scratch",
             "archive", "blender", "render_c103", "dxf_plan", "dxf_plan_recog"}

# 引用闸拦下、确认保留在原位的项（相对 ROOT）
EXCLUDE = {
    "data/_verify_floors",   # backend/verify_recognizer.py 读它做楼层复验
    "_tmp_c019_door",        # _run_c019_tmp.py（保留的根脚本）的落盘目录
}

# —— 规则：(相对 ROOT 的目录, 目标子路径, 匹配函数) ——
RULES = [
    # 根目录
    ("", "probe-out/root",        lambda n: n in {"_c006_rooms.json", "_c057profile.json",
                                                  "_dorm_census.tsv", "_idx.tsv"}),
    ("", "backups",               lambda n: n.endswith("_stairtread")),
    # data/
    ("data", "probe-out/data",    lambda n: n.endswith(".py") and n.startswith(("_check_", "_diag_",
                                                  "_dump_", "_render_", "_verify_"))),
    ("data", "probe-out/data",    lambda n: n.endswith(".txt") and n.startswith("_")),
    ("data", "probe-out/data",    lambda n: n in {"_isolated_door.glb", "_lihua_check_top_small.jpg"}),
    ("data", "probe-out/data",    lambda n: n == "_verify_floors"),
    # backend/
    ("backend", "probe-out/backend", lambda n: n.endswith(".png") and n.startswith("_")),
    ("backend", "probe-out/backend", lambda n: n.endswith(".txt") and n.startswith("_vision")),
    ("backend", "probe-out/backend", lambda n: n == "_verify_v2.py"),
    # backend/web/
    ("backend/web", "backups",    lambda n: ".orig" in n),
    # 根目录临时目录
    ("", "tmp",                   lambda n: n.startswith("_tmp_")),
]


def sha(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for c in iter(lambda: f.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()


def collect_sources():
    """返回所有被引用的文本源（frontend html + backend py + 根保留脚本）。"""
    srcs = []
    for pat in ("frontend/*.html", "backend/**/*.py", "*.py"):
        for p in glob.glob(os.path.join(ROOT, pat), recursive=True):
            if any(("/%s/" % d) in p.replace("\\", "/") or p.endswith(os.sep + d)
                   for d in SKIP_DIRS):
                continue
            h = os.path.basename(p)
            if h.startswith("_archive_debris2"):
                continue
            srcs.append(p)
    return srcs


def main():
    ap = "--apply" in sys.argv

    # —— 收集计划 ——
    plan = []  # (相对根目录的源路径, 目标子路径)
    for sub, dest, pred in RULES:
        d = os.path.join(ROOT, sub) if sub else ROOT
        for p in sorted(glob.glob(os.path.join(d, "*"))):
            if os.path.basename(p) in {".orig"}:
                continue
            if pred(os.path.basename(p)) and os.path.relpath(p, ROOT).replace("\\", "/").replace("/", os.sep) not in {
                    e.replace("/", os.sep) for e in EXCLUDE}:
                plan.append((p, dest))

    if not plan:
        print("无待归档碎片。")
        return 0

    # —— 闸 1 & 2：引用扫描 ——
    srcs = collect_sources()
    texts = {}
    for s in srcs:
        try:
            texts[s] = open(s, encoding="utf-8", errors="replace").read()
        except Exception:
            pass

    blocked = []
    for p, _ in plan:
        n = os.path.basename(p)
        stem = os.path.splitext(n)[0]
        hits = []
        for s, t in texts.items():
            if os.path.abspath(s) == os.path.abspath(p):
                continue
            rel = os.path.relpath(s, ROOT)
            if n.endswith(".py"):
                # 只认真 import
                if re.search(r"^\s*(?:import\s+%s\b|from\s+%s\s+import)" % (re.escape(stem), re.escape(stem)),
                             t, re.M):
                    hits.append(rel)
            else:
                # 非 py：按文件名整体出现即算引用
                if n in t and not rel.startswith("_scratch"):
                    hits.append(rel)
        if hits:
            blocked.append((os.path.relpath(p, ROOT), sorted(set(hits))[:3]))

    print("待归档 %d 项；引用扫描 %d 个文本源。" % (len(plan), len(texts)))
    if blocked:
        print("\n!! 中止：以下项被引用，不能归档：")
        for rel, hits in blocked:
            print("   %-46s <- %s" % (rel, ", ".join(hits)))
        return 2
    print("三重安全闸通过（无真实 import / 无按名引用）。\n")

    bydest = {}
    for p, dest in plan:
        bydest.setdefault(dest, []).append(os.path.relpath(p, ROOT))
    for dest in sorted(bydest):
        print("  -> _scratch/%-22s %2d 项" % (dest, len(bydest[dest])))

    if not ap:
        print("\n（干跑。加 --apply 真移动）")
        return 0

    # —— 执行 ——
    items = []
    for p, dest in plan:
        dd = os.path.join(SCRATCH, *dest.split("/"))
        os.makedirs(dd, exist_ok=True)
        n = os.path.basename(p)
        dst = os.path.join(dd, n)
        if os.path.exists(dst):
            print("   跳过(已存在): %s" % n)
            continue
        if os.path.isdir(p):
            shutil.move(p, dst)
            items.append(dict(name=n, dest=dest, isdir=True, src=p, dst=dst))
            continue
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
    write_unarchive()
    print("\n移动 %d 项；清单 -> %s" % (len(items), MANIFEST))
    print("还原 -> python _scratch/_unarchive.py [--apply]")
    return 0


def write_unarchive():
    """重生成 _unarchive.py：读 **全部** 清单，一个入口还原所有批次。"""
    open(os.path.join(SCRATCH, "_unarchive.py"), "w", encoding="utf-8").write('''# -*- coding: utf-8 -*-
"""按 _scratch/_MANIFEST*.json 把归档文件全部还原回原位。默认干跑，--apply 真移。

覆盖三批：_MANIFEST.json(根脚本) / _MANIFEST_DEBRIS.json(根碎片) / _MANIFEST_DEBRIS2.json(data·backend碎片)
"""
import os, sys, json, glob, shutil
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
D = os.path.dirname(os.path.abspath(__file__))
ap = "--apply" in sys.argv
tot = done = miss = 0
for mf in sorted(glob.glob(os.path.join(D, "_MANIFEST*.json"))):
    M = json.load(open(mf, encoding="utf-8"))
    items = M.get("moved", [])
    print("\\n== %s (%d) ==" % (os.path.basename(mf), len(items)))
    for it in items:
        tot += 1
        if not os.path.exists(it["dst"]):
            print("  缺失: %s" % it["name"]); miss += 1; continue
        if os.path.exists(it["src"]):
            print("  已存在(不覆盖): %s" % it["name"]); continue
        if ap:
            os.makedirs(os.path.dirname(it["src"]), exist_ok=True)
            shutil.move(it["dst"], it["src"]); done += 1
print("\\n%s %d / %d（缺失 %d）" % ("已还原" if ap else "待还原", done if ap else tot - miss, tot, miss))
''')


if __name__ == "__main__":
    sys.exit(main())
