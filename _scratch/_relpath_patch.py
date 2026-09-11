# -*- coding: utf-8 -*-
"""把 backend/ 下剩余的绝对路径字面量换成从 __file__ 推导的相对路径。

范围只含「机械替换」的几类（vision 临时脚本、extract 一次性脚本），
每个文件替换后都会 py_compile 校验语法。跑完用 grep 复验零命中。
"""
import os
import py_compile
import re
import sys

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

VISION_BOOTSTRAP = '''import os
import sys

sys.path.insert(0, os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")))    # backend/
from paths import DATA  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))          # backend/vision
'''

EXTRACT_BOOTSTRAP = '''sys.path.insert(0, os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")))    # backend/
from paths import ensure_sys_path  # noqa: E402

ensure_sys_path()                    # 仓库根：run_building.py 等入口在这
'''


def patch_vision(rel):
    path = os.path.join(ROOT, rel)
    text = open(path, encoding="utf-8", newline="").read()
    old = 'import sys\nsys.path.insert(0, r"D:\\gym3d\\backend\\vision")\n'
    if old not in text:
        return f"  跳过（找不到锚点）：{rel}"
    text = text.replace(old, VISION_BOOTSTRAP, 1)
    # 图片路径：r"D:\gym3d\data\xxx.png" → DATA / "xxx.png"
    text = re.sub(r'r"D:\\gym3d\\data\\([^"]+)"', r'DATA / "\1"', text)
    open(path, "w", encoding="utf-8", newline="").write(text)
    py_compile.compile(path, doraise=True)
    return f"  已改：{rel}"


def patch_extract(rel, bootstrap=True):
    path = os.path.join(ROOT, rel)
    text = open(path, encoding="utf-8", newline="").read()
    if bootstrap:
        old = 'sys.path.insert(0, r"D:\\gym3d\\backend")\nsys.path.insert(0, r"D:\\gym3d")\n'
        if old not in text:
            return f"  跳过（找不到锚点）：{rel}"
        if not re.search(r"^import os$", text, re.M):
            text = re.sub(r"^(import [a-z_]+\n)", r"import os\n\1", text, count=1, flags=re.M)
        text = text.replace(old, EXTRACT_BOOTSTRAP, 1)
    else:
        old = 'DATA = r"D:\\gym3d\\data\\buildings"'
        if old not in text:
            return f"  跳过（找不到锚点）：{rel}"
        if not re.search(r"^import os$", text, re.M):
            text = re.sub(r"^(import [a-z_]+\n)", r"import os\n\1", text, count=1, flags=re.M)
        text = text.replace(
            old,
            'sys.path.insert(0, os.path.normpath(\n'
            '    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")))  # 仓库根\n'
            'from paths import BUILDINGS  # noqa: E402\n\n'
            'DATA = str(BUILDINGS)',
            1,
        )
    open(path, "w", encoding="utf-8", newline="").write(text)
    py_compile.compile(path, doraise=True)
    return f"  已改：{rel}"


TARGETS = [
    (patch_vision, "backend/vision/check_closeup.py"),
    (patch_vision, "backend/vision/check_doors.py"),
    (patch_vision, "backend/vision/check_now.py"),
    (patch_extract, "backend/extract/extract_rooms_c006.py"),
    (patch_extract, "backend/extract/extract_rooms_generic.py"),
    (lambda r: patch_extract(r, bootstrap=False), "backend/extract/backfill_floor_rooms.py"),
]

for fn, rel in TARGETS:
    print(fn(rel))

sys.exit(0)
