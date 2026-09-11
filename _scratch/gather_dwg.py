# -*- coding: utf-8 -*-
"""归集已知 DWG 到统一输入文件夹（MD5 去重）。

可 import 的 `gather(sources, dest_dir)` 供 pipeline 调用。
新增一栋楼只需在 KNOWN_SOURCES 加一条路径。
"""
import os
import sys
import shutil
import hashlib

DEFAULT_SRC_DIR = r"D:\dwg_source"

# 已知 CAD 源文件位置（新增一栋楼就加一条）
KNOWN_SOURCES = [
    r"D:\dwg_source\C006-第六教学楼（逸夫楼）.dwg",
    r"D:\dwg_source\C108-网安楼.dwg",
    r"D:\校庆\校庆材料\C005-理化楼.dwg",
    r"D:\校庆\城东体育公园综合运动场馆-建筑.dwg",
    r"D:\校庆\校庆材料\城东体育公园综合运动场馆-建筑.dwg",
]


def gather(sources, dest_dir):
    """把 sources 里的 DWG 去重复制到 dest_dir。

    返回 (复制数, 去重数, 缺失数)。重复文件（MD5 相同）跳过。
    """
    os.makedirs(dest_dir, exist_ok=True)
    seen = {}  # md5 -> 源路径
    copied = dup = missing = 0
    for f in sources:
        if not os.path.exists(f):
            print("缺失:", f)
            missing += 1
            continue
        with open(f, "rb") as fp:
            h = hashlib.md5(fp.read()).hexdigest()
        dst = os.path.join(dest_dir, os.path.basename(f))
        if h in seen:
            print("重复(跳过):", os.path.basename(f), "== 与", os.path.basename(seen[h]))
            dup += 1
            continue
        seen[h] = f
        if os.path.abspath(f) == os.path.abspath(dst):
            print("已在目标(跳过):", os.path.basename(f))
            continue
        shutil.copy2(f, dst)
        copied += 1
        print("已复制:", os.path.basename(f), round(os.path.getsize(f) / 1024, 0), "KB")
    return copied, dup, missing


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    print("=== 归集 DWG 到", DEFAULT_SRC_DIR, "===")
    c, d, m = gather(KNOWN_SOURCES, DEFAULT_SRC_DIR)
    print(f"\n汇总: 复制 {c} / 去重 {d} / 缺失 {m}")
    print("\n=== D:\\dwg_source 内容 ===")
    for n in sorted(os.listdir(DEFAULT_SRC_DIR)):
        p = os.path.join(DEFAULT_SRC_DIR, n)
        print(n, round(os.path.getsize(p) / 1024, 0), "KB")


if __name__ == "__main__":
    main()
