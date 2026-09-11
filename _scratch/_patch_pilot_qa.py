# -*- coding: utf-8 -*-
"""修 _pilot_frozen_fix.qa(): 汇总行状态是 PASS/FAIL/CAUTION 三者之一,
旧代码只认 PASS/FAIL, 于是 c103 的 CAUTION 行被丢 -> 基线 ERROR 解析成 None,
门禁把「CAUTION -> ERROR=45 的真回归」误报成「None -> 45」而回滚原因说不清。
同时改成按 parts[0]==name 且 len>=5 认汇总行(避开 'c103 (6 层):' 表头)。

用法: python _patch_pilot_qa.py
"""
import io, sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

P = r"D:\gym3d\_pilot_frozen_fix.py"
OLD = '''    line, err_n = "", None
    for ln in (r.stdout or "").splitlines():
        if ln.strip().startswith(name) and ("PASS" in ln or "FAIL" in ln):
            line = ln.strip()
            parts = ln.split()
            for i, p in enumerate(parts):
                if p == name and i + 2 < len(parts):
                    try:
                        err_n = int(parts[i + 2])
                    except ValueError:
                        pass
    return r.returncode, err_n, line'''

NEW = '''    line, err_n = "", None
    for ln in (r.stdout or "").splitlines():
        parts = ln.split()
        # 汇总行固定 5 列: <楼> <层数> <ERROR> <WARN> <状态>, 状态是 PASS/FAIL/CAUTION
        # 三者之一(旧代码只认 PASS/FAIL, 把 CAUTION 楼整行丢掉 -> 基线 None)。
        # 表头 'c103 (6 层):' split 后只有 3 段, 天然被 len>=5 挡掉。
        if len(parts) >= 5 and parts[0] == name:
            try:
                err_n = int(parts[2])
            except ValueError:
                continue
            line = ln.strip()
    return r.returncode, err_n, line'''

s = io.open(P, encoding="utf-8", newline="").read()
nl = "\r\n" if "\r\n" in s else "\n"
if NEW.replace("\n", nl) in s:
    print("已经修过, 跳过")
    sys.exit(0)
o = OLD.replace("\n", nl)
n = NEW.replace("\n", nl)
if o not in s:
    print("!! 没找到目标片段, 未修改")
    sys.exit(1)
s2 = s.replace(o, n, 1)
assert ("\r\n" in s2) == (nl == "\r\n"), "换行风格被改写"
io.open(P, "w", encoding="utf-8", newline="").write(s2)
print("OK 已修 qa() 解析器 (换行 %s)" % ("CRLF" if nl == "\r\n" else "LF"))

import ast
ast.parse(io.open(P, encoding="utf-8").read())
print("AST OK")
