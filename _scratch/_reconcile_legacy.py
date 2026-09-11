# -*- coding: utf-8 -*-
r"""对账：把 _scratch/legacy/ 下**已移走但没进清单**的文件补进 _MANIFEST_DEBRIS3.json。

背景：_archive_debris3.py 第一次 --apply 崩在重复项上（写清单之前），129 个文件已移入
legacy/ 却无记录；第二次重跑时源已不存在，expand() 跳过它们，清单只记了后 14 个。
本脚本按 legacy/ 的目录结构反推原始路径，补齐记录，保证 _unarchive.py 能全部还原。

默认干跑，--apply 才写清单。
"""
import os, sys, json, hashlib

sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
ROOT = r"D:\gym3d"
SCRATCH = os.path.join(ROOT, "_scratch")
LEGACY = os.path.join(SCRATCH, "legacy")
MANIFEST = os.path.join(SCRATCH, "_MANIFEST_DEBRIS3.json")

# legacy/ 下的子目录名 -> 它原来的父目录（相对 ROOT）
BACK = {
    "extract":   "backend/extract",
    "modeling":  "backend/modeling",
    "_al_check": "_al_check",
    "archive":   "archive",
    "data":      "data",
    "render_c103": "render_c103",
}


def sha(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for c in iter(lambda: f.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()


def main():
    ap = "--apply" in sys.argv
    man = json.load(open(MANIFEST, encoding="utf-8")) if os.path.exists(MANIFEST) else {"moved": []}
    known = {os.path.normcase(os.path.normpath(it["dst"])) for it in man["moved"]}

    add = []
    for r, ds, fs in os.walk(LEGACY):
        for f in fs:
            dst = os.path.join(r, f)
            if os.path.normcase(os.path.normpath(dst)) in known:
                continue
            rel = os.path.relpath(dst, LEGACY).replace("\\", "/")
            if "/" in rel:
                head, tail = rel.split("/", 1)
                parent = BACK.get(head)
                if parent is None:
                    print("  !! 未知分组，跳过: %s" % rel)
                    continue
                src = os.path.join(ROOT, *parent.split("/"), *tail.split("/"))
            else:
                src = os.path.join(ROOT, rel)      # legacy/ 根下的散文件（PLAN.md / spec.json）
            add.append(dict(name=f, dest="legacy/...", size=os.path.getsize(dst),
                            sha256=sha(dst), src=src, dst=dst, reconciled=True))

    print("已记录 %d 项；需补记 %d 项。" % (len(man["moved"]), len(add)))
    if add:
        for it in add[:5]:
            print("   %s  <-  %s" % (os.path.relpath(it["dst"], ROOT), os.path.relpath(it["src"], ROOT)))
        if len(add) > 5:
            print("   ... 另 %d 项" % (len(add) - 5))
    if not ap:
        print("\n（干跑。加 --apply 写清单）")
        return 0

    # 校验：src 不应已存在（否则说明还原点被占用，写进去会覆盖）
    clash = [it for it in add if os.path.exists(it["src"])]
    if clash:
        print("!! 中止：%d 个还原目标已存在，先人工处理：" % len(clash))
        for it in clash[:5]:
            print("   %s" % it["src"])
        return 2

    man["moved"] += add
    json.dump(man, open(MANIFEST, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("\n补齐后清单共 %d 项 -> %s" % (len(man["moved"]), MANIFEST))
    return 0


if __name__ == "__main__":
    sys.exit(main())
