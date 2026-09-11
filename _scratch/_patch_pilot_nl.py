# -*- coding: utf-8 -*-
"""让 _pilot_frozen_fix.set_key 自适应换行风格(解冻楼里 c009/c103/c104 的 profile.json 是 CRLF,
c006 是 LF)。原实现会 assert 拒改 CRLF, 等于这三栋没法动。"""
import io

P = r"D:\gym3d\_pilot_frozen_fix.py"
s = io.open(P, encoding="utf-8", newline="").read()

A_OLD = '''    s = open(P, encoding="utf-8", newline="").read()
    assert "\\r" not in s, "%s 含 CRLF" % P
    val = {"true"'''
A_NEW = '''    s = open(P, encoding="utf-8", newline="").read()
    # 解冻楼 profile.json 行尾不一(c041/c072/c073/c006 是 LF, c009/c103/c104 是 CRLF)。
    # 按原文件风格写回, 避免为改一行把整文件行尾翻掉。
    nl = "\\r\\n" if "\\r\\n" in s else "\\n"
    val = {"true"'''

B_OLD = '''        s2 = j + sep + '\\n  "%s": %s\\n}\\n' % (key, val)'''
B_NEW = '''        s2 = j + sep + nl + '  "%s": %s' % (key, val) + nl + "}" + nl'''

C_OLD = '''    open(P, "w", encoding="utf-8", newline="").write(s2)
    assert "\\r" not in open(P, encoding="utf-8", newline="").read()
    return "%s %s=%s" % (act, key, val)'''
C_NEW = '''    open(P, "w", encoding="utf-8", newline="").write(s2)
    r2 = open(P, encoding="utf-8", newline="").read()
    assert ("\\r\\n" in r2) == (nl == "\\r\\n"), "换行风格被改写"
    return "%s %s=%s (换行%s)" % (act, key, val, "CRLF" if nl == "\\r\\n" else "LF")'''

for tag, old, new in (("A", A_OLD, A_NEW), ("B", B_OLD, B_NEW), ("C", C_OLD, C_NEW)):
    assert old in s, "锚点%s未找到" % tag
    s = s.replace(old, new, 1)

io.open(P, "w", encoding="utf-8", newline="").write(s)
assert "\r" not in io.open(P, encoding="utf-8", newline="").read()
import ast
ast.parse(io.open(P, encoding="utf-8").read())
print("已改 set_key 为换行自适应; CRLF=0; AST OK")
