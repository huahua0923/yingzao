# -*- coding: utf-8 -*-
r"""第二遍：把根目录的「运行噪音」归档进 _scratch/（日志/探针输出/调试图/代码备份）。

与 _archive_root.py 同一套安全约定：只移动不删除，哈希入清单，可一键还原。
**绝不会碰** data/buildings/*/.orig —— 那是数据回滚备份，是数据不是噪音。

用法: python _scratch/_archive_debris.py [--apply]
"""
import os, sys, json, glob, shutil, hashlib, time

sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

ROOT = r"D:\gym3d"
SCRATCH = os.path.join(ROOT, "_scratch")
MANIFEST = os.path.join(SCRATCH, "_MANIFEST_DEBRIS.json")

# (目标子目录, 匹配函数)  —— 按顺序匹配，先命中先算
RULES = [
    ("logs",       lambda n: n.endswith(".log")),
    ("probe-out",  lambda n: n.endswith(".txt") and n.startswith("_")),
    ("probe-out",  lambda n: n.startswith("_ov_") and n.endswith(".png")),
    ("probe-out",  lambda n: n.startswith(("debug_", "c041_overlay")) and n.endswith((".png", ".jpg"))),
    ("backups",    lambda n: ".bak" in n or n.endswith((".orig", ".orig2"))),
]

# 白名单：这些虽命中规则但必须留在根目录
KEEP = set()


def sha(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for c in iter(lambda: f.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()


def main():
    ap = "--apply" in sys.argv
    plan = []
    for p in sorted(glob.glob(os.path.join(ROOT, "*"))):
        if not os.path.isfile(p):
            continue
        n = os.path.basename(p)
        if n in KEEP:
            continue
        for sub, pred in RULES:
            if pred(n):
                plan.append((n, sub))
                break

    bysub = {}
    for n, sub in plan:
        bysub.setdefault(sub, []).append(n)
    print("根目录噪音文件 %d 个：" % len(plan))
    for sub, ns in sorted(bysub.items()):
        print("  -> _scratch/%-10s %2d 个: %s" % (sub, len(ns), ", ".join(ns[:6]) + ("..." if len(ns) > 6 else "")))
    if not ap:
        print("\n（干跑。加 --apply 真移动）")
        return 0

    items = []
    for n, sub in plan:
        d = os.path.join(SCRATCH, sub)
        os.makedirs(d, exist_ok=True)
        src = os.path.join(ROOT, n)
        dst = os.path.join(d, n)
        if os.path.exists(dst):
            print("   跳过(同名已存在): %s" % n)
            continue
        rec = dict(name=n, sub=sub, size=os.path.getsize(src), sha256=sha(src), src=src, dst=dst)
        shutil.move(src, dst)
        if sha(dst) != rec["sha256"]:
            shutil.move(dst, src)
            print("   !! 哈希不符已回滚: %s" % n)
            continue
        items.append(rec)

    old = {}
    if os.path.exists(MANIFEST):
        old = json.load(open(MANIFEST, encoding="utf-8"))
    prev = old.get("moved", [])
    json.dump(dict(ts=time.strftime("%Y%m%d_%H%M%S"), moved=prev + items),
              open(MANIFEST, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("\n移动 %d 个 -> _scratch/{logs,probe-out,backups}/" % len(items))
    print("清单 -> %s" % MANIFEST)
    return 0


if __name__ == "__main__":
    sys.exit(main())
