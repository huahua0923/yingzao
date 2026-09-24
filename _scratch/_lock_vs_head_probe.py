# -*- coding: utf-8 -*-
"""探针：evidence-lock 的基线是「工作区」的，还是「HEAD」的？

⑥ 陈旧判据比的是 锁 ↔ 工作区。而 git 提交的是 HEAD。
两者不是一回事 ⇒ **锁可能记着一份从未提交过的内容**，
于是「本机 ⑥ 绿」和「新克隆出来 ⑥ 绿」是两件不同的事。
"""
import hashlib
import io
import json
import subprocess

lock = json.load(io.open("kb/evidence-lock.json", encoding="utf-8"))
files = lock["files"]


def sha12(b):
    return hashlib.sha256(b).hexdigest()[:12]


rows = []
for name, want in files.items():
    try:
        cur = sha12(io.open(name, "rb").read())
    except OSError as e:
        rows.append((name, want, "<读不到: %s>" % e, ""))
        continue
    head = subprocess.run(["git", "show", "HEAD:" + name], capture_output=True).stdout
    rows.append((name, want, cur, sha12(head) if head else "<HEAD 里没有>"))

same_wt = sum(1 for _, w, c, _h in rows if w == c)
same_hd = sum(1 for _, w, _c, h in rows if w == h)
print("锁里共 %d 个文件" % len(rows))
print("锁 == 工作区：%d（这就是本机 ⑥ 绿的原因）" % same_wt)
print("锁 == HEAD  ：%d  ⇒ **剩下 %d 个在新克隆出来时 ⑥ 会红**" % (same_hd, len(rows) - same_hd))
print()
for name, w, c, h in sorted(rows):
    if w != h:
        print("  %-46s 锁=%s 工作区=%s HEAD=%s" % (name, w, c, h))
