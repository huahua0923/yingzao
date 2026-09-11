# -*- coding: utf-8 -*-
"""给 _pilot_frozen_fix.py 加 --bak <名字>: 每次实验一个独立回滚点。

原实现固定备份到 before_frozen_fix/, 且已存在就不覆盖 —— 目的是保住「最初冻结态」。
但多变量实验时(先开 pair_curved 成功, 再试 outline_unify), 第二刀若失败会一路回滚到
最初的冻结态, 把第一刀的收益也抹掉。加 --bak 让每次实验有自己的回滚点。
"""
import io, ast

P = r"D:\gym3d\_pilot_frozen_fix.py"
s = io.open(P, encoding="utf-8", newline="").read()

A_OLD = '''def backup(name):
    d = os.path.join(ROOT, name)
    bak = os.path.join(d, ".orig", BAKNAME)'''
A_NEW = '''def backup(name, bkname=None):
    d = os.path.join(ROOT, name)
    bak = os.path.join(d, ".orig", bkname or BAKNAME)'''

B_OLD = '''    print("===== %s =====" % name)
    bak, msg = backup(name)'''
B_NEW = '''    bkname = BAKNAME
    for i, a in enumerate(argv):
        if a == "--bak":
            bkname = argv[i + 1]
    print("===== %s =====" % name)
    bak, msg = backup(name, bkname)'''

for tag, old, new in (("A", A_OLD, A_NEW), ("B", B_OLD, B_NEW)):
    assert old in s, "锚点%s未找到" % tag
    s = s.replace(old, new, 1)

# 用法注释补一行
s = s.replace('    python _pilot_frozen_fix.py c009 --set pair_curved=true --set outline_unify=false',
              '    python _pilot_frozen_fix.py c009 --set pair_curved=true --set outline_unify=false\n'
              '    python _pilot_frozen_fix.py c009 --bak before_unify_off --set outline_unify=false', 1)

io.open(P, "w", encoding="utf-8", newline="").write(s)
assert "\r" not in io.open(P, encoding="utf-8", newline="").read()
ast.parse(io.open(P, encoding="utf-8").read())
print("已加 --bak; CRLF=0; AST OK")
