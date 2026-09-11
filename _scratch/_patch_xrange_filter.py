# -*- coding: utf-8 -*-
"""把「X 区间裁剪」补进两个只读体检脚本, 与 classify._in_x_range 同口径。

根因: 识别器在 classify 里用 `_in_x_range` 过滤实体(实体 X 包围盒中心必须落在
floor_plans 各层 X 区间并集 / x_range 内), 但我的两个体检脚本直接把整张图纸的
墙层实体都算进来了。c009 有 1500m 开外的墙层内容、c006 有层间夹缝内容, 全被算成
「域外弧墙/轮廓不匹配」, 会得出假结论。

改法(纯只读脚本, 不改任何数据):
  A. _curve_delivered_check.py : curve_points_mm 里逐实体按 X 中心裁剪。
  B. _diag_frozen_outline.py   : wall_content_points 里同样裁剪; 并修打印格式串
     (原先把 (min_x,min_y,w,h) 按 "%.1f x %.1f @(%.1f,%.1f)" 打印, 标签与值错位)。
保留 LF, 改前备份到 .orig_patch/。
"""
import os, shutil, sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = r"D:\gym3d"
BAK = os.path.join(ROOT, ".orig_patch")

HELPER = '''

def _ent_cx(e):
    """实体 X 包围盒中心(mm); 取不到返回 None。与 classify._in_x_range 同口径。"""
    t = e.dxftype()
    try:
        if t == "LINE":
            xs = [float(e.dxf.start.x), float(e.dxf.end.x)]
        elif t == "ARC":
            xs = [float(q[0]) for q in e.flattening(50.0)]
        elif t == "LWPOLYLINE":
            xs = [float(q[0]) for q in e.get_points("xyseb")]
        elif t == "POLYLINE":
            xs = [float(v.dxf.location.x) for v in e.vertices]
        else:
            return None
    except Exception:  # noqa: BLE001
        return None
    return (min(xs) + max(xs)) / 2.0 if xs else None
'''

FILES = {
    "_curve_delivered_check.py": [
        # 1) 顶部 import 裁剪函数
        ("from backend.recognizer.classify import _seg_radius, CURVE_MIN_R",
         "from backend.recognizer.classify import _seg_radius, CURVE_MIN_R\n"
         "from backend.recognizer.profile import in_floor_x_range"),
        # 2) 插入 helper
        ("def curve_points_mm(p):", HELPER.strip() + "\n\n\ndef curve_points_mm(p):"),
        # 3) ARC 分支前裁剪
        ('        t = e.dxftype()\n        if t == "ARC":\n'
         '            if e.dxf.radius < CURVE_MIN_R * 1000.0:',
         '        t = e.dxftype()\n'
         '        _cx = _ent_cx(e)\n'
         '        if _cx is not None and not in_floor_x_range(p, _cx):\n'
         '            continue          # 识别器看不到的远场/夹缝内容, 不算分母\n'
         '        if t == "ARC":\n'
         '            if e.dxf.radius < CURVE_MIN_R * 1000.0:'),
    ],
    "_diag_frozen_outline.py": [
        ("from backend.recognizer.profile import floor_of, to_local",
         "from backend.recognizer.profile import floor_of, to_local, in_floor_x_range"),
        ("def wall_content_points(p):", HELPER.strip() + "\n\n\ndef wall_content_points(p):"),
        ('        if e.dxf.layer != p.wall_layer:\n            continue\n        t = e.dxftype()\n        try:',
         '        if e.dxf.layer != p.wall_layer:\n            continue\n'
         '        _cx = _ent_cx(e)\n'
         '        if _cx is not None and not in_floor_x_range(p, _cx):\n'
         '            continue          # 与 classify._in_x_range 同口径\n'
         '        t = e.dxftype()\n        try:'),
        # 修正打印: (min_x, min_y, w, h) 显式命名
        ('        f1 = "%.1f x %.1f @(%.1f,%.1f)" % cb if cb else "-"\n'
         '        f2 = "%.1f x %.1f @(%.1f,%.1f)" % ob if ob else "-"',
         '        f1 = ("宽%.1f x 高%.1f @(%.1f,%.1f)" % (cb[2], cb[3], cb[0], cb[1])) if cb else "-"\n'
         '        f2 = ("宽%.1f x 高%.1f @(%.1f,%.1f)" % (ob[2], ob[3], ob[0], ob[1])) if ob else "-"'),
    ],
}


def patch(fn, subs):
    path = os.path.join(ROOT, fn)
    src = open(path, encoding="utf-8", newline="").read()
    if "已套X区间裁剪" in src:
        return "%s: 已打过, 跳过" % fn
    assert "\r" not in src, "%s 含 CRLF, 拒绝改" % fn
    for old, new in subs:
        if old not in src:
            return "%s: 未找到锚点 -> %s" % (fn, old[:60].replace("\n", "\\n"))
        src = src.replace(old, new, 1)
    src = src.replace("# -*- coding: utf-8 -*-",
                      "# -*- coding: utf-8 -*-\n# 已套X区间裁剪(与 classify._in_x_range 同口径)", 1)
    os.makedirs(BAK, exist_ok=True)
    b = os.path.join(BAK, fn + ".before_xrange")
    if not os.path.exists(b):
        shutil.copy2(path, b)
    open(path, "w", encoding="utf-8", newline="").write(src)
    assert "\r" not in open(path, encoding="utf-8", newline="").read()
    return "%s: 已改 (CRLF=0)" % fn


for fn, subs in FILES.items():
    print(patch(fn, subs))
