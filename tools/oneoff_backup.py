# -*- coding: utf-8 -*-
"""一次性：把活代码打成一个 zip，供目录重构后回退。手动跑，无调用方。"""
import os
import sys
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ZIP = os.path.join(ROOT, "_code_bak_2026-10-20.zip")
DIRS = ["pipeline", "gates", "tools", "workbench", "demo", "rebuild/tools"]
EXT = (".py", ".js", ".mjs", ".html")


def main():
    n = 0
    with zipfile.ZipFile(ZIP, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for d in DIRS:
            for base, _ds, fs in os.walk(os.path.join(ROOT, d)):
                if "vendor" in base.replace("\\", "/").split("/"):
                    continue
                for f in fs:
                    if f.endswith(EXT):
                        p = os.path.join(base, f)
                        z.write(p, os.path.relpath(p, ROOT))
                        n += 1
        for f in os.listdir(ROOT):
            if f.endswith(".py"):
                z.write(os.path.join(ROOT, f), f)
                n += 1
    print("备份 %d 个文件，%d 字节" % (n, os.path.getsize(ZIP)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
