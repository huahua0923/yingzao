# -*- coding: utf-8 -*-
"""把立面渲染 PNG 变成 ASCII 剪影，检查楼层是否笔直堆叠。

用法: python _ascii_facade.py <png> [--cols 110] [--rows 44]
判读: '#'=建筑占用；'.'=天空。行=高度采样，列=水平。
楼层若对齐 → 连续若干行的左右边缘平齐、上下是竖直边；
若错位 → 逐行左右边界左右跳动（墙/板 突进突出）。
"""
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import numpy as np
from PIL import Image

def main():
    args = sys.argv[1:]
    path = args[0]
    cols = 112
    rows = 46
    if "--cols" in args:
        cols = int(args[args.index("--cols") + 1])
    if "--rows" in args:
        rows = int(args[args.index("--rows") + 1])

    im = np.asarray(Image.open(path).convert("RGB")).astype(int)
    H, W, _ = im.shape
    bg = im[3, 3].astype(int)
    dist = np.abs(im - bg).sum(axis=2)
    mask = dist > 60
    colany = mask.any(axis=1)
    ys = np.where(colany)[0]
    if len(ys) == 0:
        print("no building found")
        return
    y0, y1 = int(ys.min()), int(ys.max())
    step = max(1, (y1 - y0) // rows)
    samp = np.arange(y0, y1 + 1, step)
    # 建采样列索引
    xsamp = (np.arange(cols) * W // cols).clip(0, W - 1)
    print(f"{path}  img={W}x{H}  building rows y[{y0}..{y1}] step={step}px")
    for i, y in enumerate(samp):
        row = mask[y]
        occ = row[xsamp]
        # 找左右实体极值（连续#边界），不依赖内部
        line = "".join("#" if o else "." for o in occ)
        print(f"{i:3d} {line}")

if __name__ == "__main__":
    main()
