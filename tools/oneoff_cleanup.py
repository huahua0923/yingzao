# -*- coding: utf-8 -*-
"""一次性整理（2026-10-20）：把过程文件归档/清掉。

用法：
  python -I -X utf8 tools/oneoff_cleanup.py plan     # 只量，不动
  python -I -X utf8 tools/oneoff_cleanup.py zip      # 把 _archive 打成 zip
  python -I -X utf8 tools/oneoff_cleanup.py verify   # CRC + 抽样 sha256 比对
  python -I -X utf8 tools/oneoff_cleanup.py delete   # 仅当 verify 通过才删；
                                                     # DIRS 里没备份的目录一律拒绝，
                                                     # 确有第二份才加 --i-have-a-copy

★ 规矩：zip 没过 verify，delete 一律拒绝。
"""
import argparse
import hashlib
import json
import os
import random
import shutil
import sys
import time
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ARCHIVE = os.path.join(ROOT, "_archive")
ZIP = os.path.join(ROOT, "_archive_bak_2026-10-20.zip")
STAMP = os.path.join(ROOT, "_cleanup_verified_2026-10-20.json")
MANIFEST = os.path.join(ROOT, "_cleanup_manifest_2026-10-20.json")

# 用户 2026-10-20 弹窗勾选的四类；先删这些（_archive 走 zip→verify→删）
DIRS = [
    "_freecad_probe", "_deliver", "pipeline/_try",
    "_edit", "_drill", "_回切_按栋",
    "rebuild/c103", "rebuild/c104", "rebuild/c105",
]
JUNK_DIRS = ("__pycache__",)


def walk(path):
    out = []
    for base, dirs, files in os.walk(path):
        for f in files:
            out.append(os.path.join(base, f))
    return out


def size_of(path):
    n = 0
    for f in walk(path):
        try:
            n += os.path.getsize(f)
        except OSError:
            pass
    return n


def human(n):
    for unit in ("B", "K", "M", "G", "T"):
        if n < 1024 or unit == "T":
            return "%.1f %s" % (n, unit)
        n /= 1024.0


def sha256(path, chunk=1 << 20):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            b = f.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def cmd_plan():
    rows = []
    for d in DIRS:
        p = os.path.join(ROOT, d)
        if os.path.isdir(p):
            rows.append({"path": d, "files": len(walk(p)), "bytes": size_of(p)})
        else:
            rows.append({"path": d, "files": 0, "bytes": 0, "missing": True})
    if os.path.isdir(ARCHIVE):
        rows.append({"path": "_archive", "files": len(walk(ARCHIVE)),
                     "bytes": size_of(ARCHIVE)})
    for r in rows:
        print("%-22s %7d 文件 %10s" % (r["path"], r["files"], human(r["bytes"])))
    print("合计 %s" % human(sum(r["bytes"] for r in rows)))
    with open(MANIFEST, "w", encoding="utf-8", newline="\n") as f:
        json.dump(rows, f, ensure_ascii=False, indent=1)
    print("清单写到", MANIFEST)
    return 0


def cmd_zip():
    if not os.path.isdir(ARCHIVE):
        print("没有 _archive，跳过")
        return 0
    if os.path.exists(ZIP):
        print("zip 已存在，先 verify 再决定：", ZIP)
        return 0
    t0 = time.time()
    n = 0
    with zipfile.ZipFile(ZIP, "w", zipfile.ZIP_DEFLATED, compresslevel=1) as z:
        for base, dirs, files in os.walk(ARCHIVE):
            rel = os.path.relpath(base, ROOT).replace("\\", "/")
            z.write(base, rel + "/")
            for f in files:
                z.write(os.path.join(base, f), rel + "/" + f)
                n += 1
                if n % 500 == 0:
                    print("  已打包 %d 个文件（%.0f s）" % (n, time.time() - t0), flush=True)
    print("打包完成：%d 个文件，zip %s，用时 %.0f s"
          % (n, human(os.path.getsize(ZIP)), time.time() - t0))
    return 0


def cmd_verify():
    if not os.path.exists(ZIP):
        print("没有 zip，不能验")
        return 2
    bad = []
    with zipfile.ZipFile(ZIP) as z:
        first = z.testzip()          # 逐条 CRC
        files = [i.filename for i in z.infolist() if not i.filename.endswith("/")]
        random.seed(20261020)
        sample = random.sample(files, min(50, len(files)))
        mism = []
        for name in sample:
            src = os.path.join(ROOT, name)
            if not os.path.isfile(src):
                mism.append({"missing_src": name})
                continue
            with z.open(name) as fh:
                h = hashlib.sha256()
                while True:
                    b = fh.read(1 << 20)
                    if not b:
                        break
                    h.update(b)
            if h.hexdigest() != sha256(src):
                mism.append({"sha_mismatch": name})
        print("CRC: %s" % ("通过" if not first else "坏：%s" % first))
        print("抽样 %d 个，sha256 不符 %d 个" % (len(sample), len(mism)))
        ok = (not first) and (not mism)
        if ok:
            with open(STAMP, "w", encoding="utf-8", newline="\n") as f:
                json.dump({"zip": os.path.basename(ZIP), "sample": len(sample),
                           "at": time.strftime("%Y-%m-%dT%H:%M:%S")}, f,
                          ensure_ascii=False, indent=1)
            print("验证通过 →", STAMP)
        else:
            print(json.dumps(bad + mism, ensure_ascii=False)[:800])
        return 0 if ok else 3


def cmd_delete(made_copy=False):
    # ★★ 2026-10-20 的账：`_archive` 有 zip + verify 才删，而 `DIRS` 里另外九个目录
    #    是**裸 rmtree**——`_edit` 367 MB、`_drill` 203 MB、`_回切_按栋` 200 MB、
    #    `rebuild/c103~c105` 约 1.8 GB，删完盘上再没有第二份
    #    （`_archive_bak_*.zip` 顶层只有 `_archive/`，17738 条里含 `_edit` 的 0 条）。
    #    ⇒ 从那以后：**没有自带备份的目录一律拒绝**；要删得先自己搬出去，
    #      并显式带 `--i-have-a-copy` 说明「这个我有第二份」。
    pending = [d for d in DIRS if os.path.isdir(os.path.join(ROOT, d))]
    if pending and not made_copy:
        print("★ 拒绝：下面这些目录**删了就没有第二份**（此脚本不打包它们）：")
        for d in pending:
            print("   %-18s %s" % (d, human(size_of(os.path.join(ROOT, d)))))
        print("  ⇒ 先自行拷贝/打包，再带 --i-have-a-copy 重跑；_archive 的删除不受影响。")
        return 4
    if os.path.isdir(ARCHIVE):
        if not os.path.exists(STAMP):
            print("★ 拒绝：_archive 还没通过 verify，不删")
            return 4
        shutil.rmtree(ARCHIVE)
        print("已删 _archive（zip 保留：%s）" % os.path.basename(ZIP))
    freed = 0
    for d in DIRS:
        p = os.path.join(ROOT, d)
        if os.path.isdir(p):
            freed += size_of(p)
            shutil.rmtree(p)
            print("已删", d)
    for base, dirs, files in os.walk(ROOT):
        for name in list(dirs):
            if name in JUNK_DIRS:
                shutil.rmtree(os.path.join(base, name), ignore_errors=True)
                dirs.remove(name)
    logs = 0
    for base, dirs, files in os.walk(ROOT):
        for f in files:
            if f.endswith((".log", ".bak", ".tmp")):
                try:
                    os.remove(os.path.join(base, f))
                    logs += 1
                except OSError:
                    pass
    print("清掉缓存目录与 %d 个日志/备份文件" % logs)
    print("本轮目录释放 %s" % human(freed))
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["plan", "zip", "verify", "delete"])
    ap.add_argument("--i-have-a-copy", action="store_true",
                    help="确认 DIRS 里那些目录我另有第二份，才允许真删")
    a = ap.parse_args(argv)
    if a.mode == "delete":
        return cmd_delete(made_copy=a.i_have_a_copy)
    return {"plan": cmd_plan, "zip": cmd_zip, "verify": cmd_verify}[a.mode]()


if __name__ == "__main__":
    sys.exit(main())
