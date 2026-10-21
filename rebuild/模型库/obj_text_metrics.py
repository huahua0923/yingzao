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
# ★ 2026-10-17：类名允许**尾部数字**（SU 给重名组追加流水号）。
#   原式 `([A-Za-z_]+)` 遇到 `G_1__WALL88` 直接**不匹配** ⇒ 归成 (None,None)，
#   量出来的「未识别组」是 0 而不是几千（铁律 158：量具对它认不出的形状是静默的）。
GROUP_RE = re.compile(r"^(?:G_)?_*(\d+)__([A-Za-z_][A-Za-z0-9_]*)$")

# ★ 2026-10-20：第二种形状 —— FreeCAD 那条链（`contours_to_fc.py`）导出的 OBJ 用对象行：
#     o floor0__WALL      o B1__LINTEL      o floor10__ROOF_ROOM
#   交付路径 2026-10-17 已换成 FreeCAD（见 `rebuild/06_su/流程.md` 头），模型库的「好件」
#   必须跟着**交付件**走（`c006_fc.obj`），否则它量的是退路件 SU（`c006_su.obj`），
#   两头都不是同一个主语（铁律 196）。
#   ⇒ `g` 与 `o` 是同一件东西的两种写法：**只数一种**（`g` 优先），两边都数会双计。
OBJ_RE = re.compile(r"^([A-Za-z0-9_]*)__([A-Za-z_][A-Za-z0-9_]*)$")


def parse_obj_name(name: str):
    """`floor0__WALL` -> ('floor0', 'WALL')；认不出返回 (None, None)。

    层号用字符串（`B1` / `floor0`），不像 SU 那样是整数 —— 本尺子只把类名当判据，
    层号原样带出去备查；调用方要整数时自己解析。
    """
    m = OBJ_RE.match(name.strip())
    if not m:
        return None, None
    lay, cls = m.group(1), m.group(2)
    if cls not in STDS:
        base = cls.rstrip("0123456789")
        if base in STDS:
            cls = base
    return lay, cls

# ★ 2026-10-17 块级隔离后，SU 给**重名组**追加流水号 ⇒ `G_1__WALL88`。
#   流水号不是类名。只有「去掉尾部数字后正好命中标准类」才剥
#   （标准类里没有以数字结尾的，所以不会误伤）。
#   ★ 这份名单与 `gates/J-10.9-07_类闭合.py::STDS` 同一口径；类名漂了，
#     正对照（坏_没有门头墙）会先红 —— 不会静默放过。
# ★★ 2026-10-19 补 `ROOF_ROOM`（出屋面楼梯间+电梯机房），与
#   `gates/J-10.9-07_类闭合.py::STDS` 同步 —— 两边漂开会让「未识别组」静默多出几千。
STDS = ("WALL", "COL", "LIFT", "SLAB", "DOOR", "STAIR",
        "LINTEL", "PARAPET", "ROOF_STAIR", "ROOF_STEP", "ROOF", "ROOF_ROOM")


def parse_group(name: str):
    """'Mesh41 G_1__DOOR Model' -> (1, 'DOOR')；认不出返回 (None, None)。"""
    parts = name.split()
    if len(parts) < 2:
        return None, None
    m = GROUP_RE.match(parts[1])
    if not m:
        return None, None
    lay, cls = int(m.group(1)), m.group(2)
    if cls not in STDS:
        base = cls.rstrip("0123456789")
        if base in STDS:
            cls = base
    return lay, cls


def metrics(path: str, scale: float = 1.0) -> dict:
    mn = [None, None, None]
    mx = [None, None, None]
    n_v = n_vt = n_vn = n_f = 0
    n_g_grp = n_g_obj = 0
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
                n_g_grp += 1
                lay, cls = parse_group(line.strip()[2:])
                if lay is None:
                    unparsed += 1
                else:
                    layers.add(lay)
                    classes.add(cls)
            elif line.startswith("o "):
                # ★ FreeCAD 那条链的写法；`g` 优先（一个文件只数一种，否则双计）
                n_g_obj += 1
                lay, cls = parse_obj_name(line.strip()[2:])
                if cls is None:
                    unparsed += 1
                else:
                    layers.add(lay)
                    classes.add(cls)

    both_shapes = bool(n_g_grp and n_g_obj)
    n_g = n_g_grp if n_g_grp else n_g_obj

    size = [None if mn[i] is None else mx[i] - mn[i] for i in range(3)]
    return {
        "path": path,
        "scale": scale,
        "n_v": n_v,
        "n_vt": n_vt,
        "n_vn": n_vn,
        "n_f": n_f,
        "n_g": n_g,
        "n_g_grp": n_g_grp,
        "n_g_obj": n_g_obj,
        "group_shapes_both": both_shapes,
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
