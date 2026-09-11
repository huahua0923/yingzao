# -*- coding: utf-8 -*-
"""按行删掉 profile.json 里的某个顶层键(保留原换行风格与原文件其余字节)。

用法: python _patch_del_key.py <楼名> <键名>

为什么按行删而不是 json.load/dump: dump 会重排/重格式化整个文件(浮点写成 469675.0 之类),
可能引入无关 diff。按行删只动那一行, 并用 json.loads 校验结果仍合法。
"""
import io, json, os, sys, shutil

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
name, key = sys.argv[1], sys.argv[2]
P = os.path.join(r"D:\gym3d\data\buildings", name, "profile.json")
s = io.open(P, encoding="utf-8", newline="").read()
nl = "\r\n" if "\r\n" in s else "\n"
lines = s.split(nl)

hit, content = [], []
for i, ln in enumerate(lines):
    t = ln.strip()
    body = t.rstrip(",").strip()
    if body in ('"%s": true' % key, '"%s": false' % key) or body.startswith('"%s":' % key):
        if not t.startswith("//") and i not in hit:
            hit.append(i)
            content.append(i)
            continue
    lines[i] = ln

if not hit:
    print("没找到 %s, 未修改" % key)
    sys.exit(0)

# 删掉命中行; 若它原本带尾逗号且删后成了最后一个键, 需去掉前一个键的尾逗号
stripped = [ln for i, ln in enumerate(lines) if i not in set(hit)]
txt = nl.join(stripped)
try:
    json.loads(txt)
except Exception as e:
    print("!! 直接删导致 JSON 非法(%s), 尝试修尾逗号" % e)
    fixed, changed = [], False
    for i, ln in enumerate(stripped):
        if ln.strip() and ln.strip() != "}" and not changed:
            nxt = next((x for x in stripped[i + 1:] if x.strip()), "")
            if nxt.strip().startswith("}") and ln.rstrip().endswith(","):
                fixed.append(ln.rstrip()[:-1])
                changed = True
                continue
        fixed.append(ln)
    txt = nl.join(fixed)
    json.loads(txt)   # 再不过就直接抛, 不写盘
    print("   尾逗号已修")

assert ("\r\n" in txt) == (nl == "\r\n"), "换行风格被改写"
bk = P + ".delkey_bak"
if not os.path.exists(bk):
    shutil.copy2(P, bk)
io.open(P, "w", encoding="utf-8", newline="").write(txt)
cfg = json.loads(io.open(P, encoding="utf-8").read())
print("OK 已删 %s.%s ; 剩余顶层键: %s" % (name, key, sorted(cfg.keys())))
print("   备份: %s" % bk)
