# -*- coding: utf-8 -*-
"""纯文本尺子（第 3 把外部量具）：只按行首读 OBJ，不 import 任何三维库。

★ 为什么还要有它：`Blender` 与 `three.js` 是**另外两套内核/另一门语言**的实现，
但它们都得把件**解析进内存**才量得到。这一把只数行，用来判两件事：
  ① 文件本身有没有被改坏（行数守恒）；
  ② 两个大工具读出来的数，**基础事实**（顶点数 v、包围盒）对不对得上。

★★ 三把尺子读的是**同一份文件**。这一点是硬要求（铁律 174/196）：
  拿 Blender 读 OBJ 的数去比 three.js 读 GLB 的数，是**换主语** ——
  两个件的三角化方式天生不同，数不一样**证明不了**任何东西。
  同一个量有两个估计器时，必须按**身份**（同一个文件、同一个下标）比，不许按数值像不像比。

用法:
    python -I obj_text_metrics.py <模型.obj> [--scale 25.4]
输出: 单行 `OBJTEXT {json}`（前缀是给调用方切分的，免得跟别的输出混）。
"""
import io
import json
import re
import sys

# 组名形状（2026-10-15 实测 3549 条全中，零例外）:
#     g Mesh41 G_1__DOOR Model
#     g Mesh1  __1__DOOR Model      ← 首批少了 G_ 前缀，是同一族的写法
# 捕获组: 1=层号 2=类名
GROUP_RE = re.compile(r"^(?:G_)?_*(\d+)__([A-Za-z_]+)$")


def parse_group(name: str):
    """'Mesh41 G_1__DOOR Model' -> (1, 'DOOR')；认不出返回 (None, None)。"""
    parts = name.split()
    if len(parts) < 2:
        return None, None
    m = GROUP_RE.match(parts[1])
    return (int(m.group(1)), m.group(2)) if m else (None, None)


def metrics(path: str, scale: float = 1.0) -> dict:
    mn = [None, None, None]
    mx = [None, None, None]
    n_v = n_vt = n_vn = n_f = n_g = 0
    layers, classes, unparsed = set(), set(), 0

    with io.open(path, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            if line.startswith("v "):
                n_v += 1
                p = line.split()
                for i in range(3):
                    x = float(p[1 + i]) * scale
                    if mn[i] is None or x < mn[i]:
                        mn[i] = x
                    if mx[i] is None or x > mx[i]:
                        mx[i] = x
            elif line.startswith("vt "):
                n_vt += 1
            elif line.startswith("vn "):
                n_vn += 1
            elif line.startswith("f "):
                n_f += 1
            elif line.startswith("g "):
                n_g += 1
                lay, cls = parse_group(line.strip()[2:])
                if lay is None:
                    unparsed += 1
                else:
                    layers.add(lay)
                    classes.add(cls)

    size = [None if mn[i] is None else mx[i] - mn[i] for i in range(3)]
    return {
        "path": path,
        "scale": scale,
        "n_v": n_v,
        "n_vt": n_vt,
        "n_vn": n_vn,
        "n_f": n_f,
        "n_g": n_g,
        "bbox_min": mn,
        "bbox_max": mx,
        "size": size,
        "layers": sorted(layers),
        "classes": sorted(classes),
        "groups_unparsed": unparsed,
    }


def main() -> int:
    argv = list(sys.argv[1:])
    if not argv:
        sys.stderr.write("用法: python -I obj_text_metrics.py <模型.obj> [--scale 25.4]\n")
        return 2
    path = argv[0]
    scale = 1.0
    if "--scale" in argv:
        scale = float(argv[argv.index("--scale") + 1])
    out = metrics(path, scale)
    sys.stdout.write("OBJTEXT " + json.dumps(out, ensure_ascii=False) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
