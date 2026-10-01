# -*- coding: utf-8 -*-
"""「同一个房号在图上被标注了两次」—— B6 的读数层（单一实现，B6 与 `_scratch/_b6_probe.py` 共用）。

## 这条判据为什么必须存在

2026-09-29 量 c011（银杏体育馆）：图上 F0 的平面被画了**两遍** ——
主图在左列（x≈1356933，`D1`/`F0`/`F1`/`F2`/`F3` 五份叠在 Y 上），右列又单独画了一张
**首层平面图**（x≈1536870），两列相隔 **180000 mm**（整）。而 profile 的
`x_range=[1266870,1626870]`（360 m 宽）**把两列都收了进来** ⇒ 四处症状、一个根因：

  · F0 的墙折回图面跨两列（层内相差 90000 mm）；
  · 交付的 F0 `outline`/`rooms` 取自**右列**、F1/F2/F3 取自**左列** ⇒
    结构不变量 **I8** 报「F1/F2/F3 几何中心距 F0 偏移 180.8 / 181.8 / 180.0 m」；
  · **I1/I10** 报「F0 柱在自身轮廓外 **179.7 m**」61/61（轮廓取自右列、柱取自两列）；
  · **缺陷 A**（`11-01-22`/`11-01-23` 没用途）也是它 —— 那两条错层文本
    （`书记办公室`/`资料室`）正是**右列独有**，左列同位置在正确的 `8房间用途` 层；
  · F0 的房号在图上共 44 条 = 右列 23（21 号 + 那 2 条）+ 左列 21，**逐号同名**。

⇒ 而**图上「同一个号被标了两次」是这个根因唯一的直接指纹**：左右两列各 21 个房号、
逐号同名，墙 373 / 373 条、宽度都 ~61 m。四条既有不变量报的是**后果**，
本条报的是**成因**。

## 判据的量法（数什么、阈值从哪来）

对**模型收进来的范围**（`in_floor_x_range`）内、被抽取器判成房号的每一条标注，
按归一化后的号分组。**两个条件缺一不可**：

  ① 重复的两处落在**同一个层带**里（`floor_of` 给同一个 F）。跨层的同名是**另一件事**
     —— 房号里嵌了层号，c006 的 `6-A-02-06` 就出现在相邻两层（距/层带 0.97）。
  ② 同层内两处的最大间距 > `offset`（层带高度，`profile.json` 里**本栋的数**，不手打）。

为什么阈值取「层带高度」：同一层内**同一个房间**的两处标注相距不可能超过一个层带
（房间尺度远小于层带高度）；只有「两份平面」才跨得到这个量级。
c011 实测 180000 ÷ 130118 = **1.38**；对照组最危险的一个是 c006 的 0.97，
★★ 那一栋是靠条件 ① 排除的，**不是靠 ② 的余量** —— 别拿掉 ①。

★ 之所以**只看 `x_range` 之内**：本条量的是「**模型会收进来什么**」，不是「图上有什么」。
  右列本来就该被排除 —— 排除它正是修法本身。所以修完本条应当转绿。
  落在 `x_range` 之外的重复另计一档证据（**打印条数，不参与判定**）——
  滤行必须能被看见，不许静默。

## outcome 三档（`near` 是 2026-09-29 收窄 `x_range` 之后才长出来的一档）

| outcome | 条件 | 是什么 |
|---|---|---|
| `dup` | 同层重复 **且** 同层最大间距 > `offset` | 整层在图上被画了两份（c011 的 180 m） |
| `near` | 同层重复，但最大间距 ≤ `offset` | 同层两个位置共用一个号：一间标两遍，或两个不同房间重号 |
| `ok` | 同层没有重号 | 正常 |

**为什么 `near` 该单独成档而不是并进 `ok`**：c011 收窄 `x_range` 后剩的那一条 ——
`11-04-01` 在 F3 层内相距 **50060 mm**（层带 130118，比 0.38），两处各自带着自己的
用途与储藏室（一簇 `11-04-01/11-04-02/运动处方实验室`，另一簇 `11-04-01/11-04-04/
设备控制室`，邻号一缺 `-03`）⇒ **两个不同房间共用一个号**，而**房号在一层内必须唯一**。
它够不到「两份平面」那个量级，所以不进 `dup`；但它也不是「没问题」，所以不进 `ok`。
**阈值（`offset`）不变** —— 分档只让第二类被看见，不改第一类的判法。

★ 跨层同名（`6-A-02-06` 那种）既不是 `dup` 也不是 `near`，是**第三种现象**：房号里嵌了
  层号。它在 `n_dups_cross_floor` 里单独报，**不参与任何判定** —— 早先它被并进 `n_dups`
  一起当「同层重复」的数印出去，那是挂错了量。

## 排序：含数字的优先（否则标题永远是垃圾）

`dups` 按 `(含数字, 同层间距)` 排。**这一维不是修饰，是必需的**：2026-09-29 全库冒烟
实测 c114 的同层重号有三个 —— 真房号 `114-05-04`（7100 mm）＋ 两个**无数字**的
`天台`（38910 mm）、`花坛`（13520 mm）。只按距离排，`worst` 就是 `天台`，
而 `天台` **根本不是房号**（它在房号层上，是抽取器把风景构件判成了 number）。
⇒ `same_floor[0]`（= `worst_same_floor`）在有含数字候选时一定是含数字的那个。

不含数字的那些进 `n_dups_same_floor_nonnum` / `worst_nonnum`，**另列一档并指给 J-A**
（「房号层上出现了不合房号式的文本」）—— 本条不判它们，但**必须把它们数出来**，
否则「同层重号 3 个」里的 2 个会永远匿名。

## 三个哨兵（同一个病，一天之内犯了三次）

「不适用」不许用 `0` 或 `None` 去冒充「量到零 / 量到了」—— 三处的实际后果：

| 哨兵 | 读起来像 | 真相 | 后果 |
|---|---|---|---|
| 跨层同名的 `dx/dy/dist/ratio` 停在初始值 `0.0` | 「两处重合」 | 同层间距这个量**不存在** | c006 那两条印 `Δy=0.0`，真实位移 130508.8 |
| `same = None` 兼作「没找到同层对」 | 「找到了一层，层号 None」 | `floor_of` **合法地**会返回 `None`（两条都在层带之外） | `d["dist"] > offset` 抛 TypeError ⇒ 全库普查里 **c046 报 CRASH** |
| 挑最优时用 `max(ax,ay) > max(fx,fy)`（严格 `>`） | 以为「这条同层重号是跨层的那种」 | 同层两条标注落在**同一个点**上时 `max(ax,ay) == 0.0`，与初始值**相等** ⇒ 严格 `>` 永不成立 | 同上，c046 **第二次报 CRASH**（前一处修完才露出来） |

⇒ 修法：`不适用` 落 `None`；「找没找到」落**独立的 `found` 标志位**；挑最优的条件写成
`if not found or …`（**初始值不是哨兵，是待覆盖的占位**）。`floor is None` 另配
`floor_known=False`，判词要把「同在**未归属**那一桶」说出来。

★ 判据自己的教训：同一族缺陷**修一处只露出下一处**，所以改完必须**重跑全库**，
不能只跑改点 —— c046 的两处就是这么先后露出来的。
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

__all__ = ["diagnose", "norm_number"]

# 归一化只做「同一个号的不同写法算同一个号」：去空白、全角连字符折半角、大写。
_FULLWIDTH = {"－": "-", "—": "-", "–": "-", "　": " ", " ": " "}


def norm_number(t: str) -> str:
    s = str(t or "")
    for a, b in _FULLWIDTH.items():
        s = s.replace(a, b)
    return re.sub(r"\s+", "", s).upper()


def shape_of(t: str) -> str:
    """形状签名：数字串→`#`、字母串→`A`、汉字与符号原样。

    `11-04-01`→`#-#-#`　`6-A-05-00`→`#-A-#-#`　`64.00M`→`#.#A`　`天台`→`天台`

    这是**读数**，不是判据 —— 判据只用到 `has_digit` 那一半。
    """
    s = re.sub(r"\d+", "#", str(t or ""))
    return re.sub(r"[A-Za-z]+", "A", s)


def has_digit(t: str) -> bool:
    """房号**必须**含数字 —— 这是**定义**，不是阈值。

    实测（2026-09-29 解剖 `near` 那一档）：房号层上混着 `天台`/`花坛` 这种**风景/屋面
    构件名**（c114 各 2 条），它们完全没有数字。把它们算进「同层重号」会让判词的标题
    被垃圾抢走 —— c114 那个 `天台` 相距 38910 mm，比真房号 `114-05-04` 的 7100 mm
    还大，而排序按距离 ⇒ 垃圾排在真房号前面。所以分档时**含数字的优先**；
    不含数字的另列一档，并指给 J-A（「房号层上出现了不合房号式的文本」）。
    """
    return any(ch.isdigit() for ch in str(t or ""))


def _prep_imports(data_dir, name):
    """取抽取器当尺子 —— 与 B3 同一条纪律：**路径不对就不量**，不另抄一份读法。

    返回 (EX, CTBL, prof_module, err)。err 非空即量不到。
    """
    root = Path(data_dir).resolve().parent
    for pth in (root, root / "backend", root / "backend" / "extract"):
        if str(pth) not in sys.path:
            sys.path.insert(0, str(pth))
    try:
        import extract_rooms_generic as EX
    except Exception as ex:                                   # noqa: BLE001
        return None, None, None, "取不到房间抽取器：%s: %s" % (type(ex).__name__, ex)
    want = root / "backend" / "extract" / "extract_rooms_generic.py"
    got = Path(getattr(EX, "__file__", "") or "")
    if got and os.path.normcase(str(want)) != os.path.normcase(str(got)):
        return None, None, None, ("import 到的不是这一个：想读 %s，实际 %s —— 尺子拿错了，不量"
                                  % (want, got))
    try:
        import config_table as CTBL
    except Exception as ex:                                   # noqa: BLE001
        return None, None, None, "取不到 config_table：%s: %s" % (type(ex).__name__, ex)
    try:
        from recognizer.profile import in_floor_x_range, floor_of, RANGE_TOL_MM
    except Exception as ex:                                   # noqa: BLE001
        return None, None, None, "取不到坐标口径 recognizer.profile：%s: %s" % (type(ex).__name__, ex)
    return EX, CTBL, (in_floor_x_range, floor_of, RANGE_TOL_MM), None


def _dxf_doc(EX, dxf_path):
    import ezdxf
    return ezdxf.readfile(str(dxf_path), encoding=EX.ENCODING).modelspace()


def diagnose(data_dir, name: str, x_range_override=None) -> dict:
    """一条结论 + 全部证据。调用方（B6 / 探针）负责翻译成 Finding。

    outcome ∈ {ok, near, dup, unreadable, no_labels}

    `x_range_override`：**只给反事实输入用**（铁律 82）。缺陷修好之后，真档案里已经
    **没有**那个输入了（c011 的 `x_range` 已收窄）⇒ 以「缺陷还在」为前提的验证据
    再也验不了「判据仍有分辨力」。唯一老实的办法是把**当时那份档案的那个数**喂回来
    （值从备份里读，不许手打）。语义上它只替换 `in_floor_x_range` 的 `x_range` 分支，
    容差 `RANGE_TOL_MM` 逐字照抄 ⇒ 对**没有 `floor_plans`** 的楼逐位等价；
    对**有 `floor_plans`** 的楼这份覆写不忠实（那一支优先），故直接拒量而不是给个错答案。
    """
    base = {"name": name}
    EX, CTBL, coords, err = _prep_imports(data_dir, name)
    if err:
        return {**base, "outcome": "unreadable", "why": err}
    in_range, floor_of, range_tol = coords

    prof_path = Path(data_dir) / "buildings" / name / "profile.json"
    try:
        prof = json.loads(prof_path.read_text(encoding="utf-8"))
    except Exception as ex:                                   # noqa: BLE001
        return {**base, "outcome": "unreadable", "why": "profile.json 读不了：%s" % ex}
    dxf = Path(str(prof.get("dxf") or ""))
    if not dxf.is_file():
        return {**base, "outcome": "unreadable", "why": "源 DXF 不在：%s" % dxf,
                "dxf": str(dxf)}

    try:
        p = EX.load_profile(name)
    except Exception as ex:                                   # noqa: BLE001
        return {**base, "outcome": "unreadable", "why": "load_profile 失败：%s: %s"
                % (type(ex).__name__, ex), "dxf": str(dxf)}

    offset = float(getattr(p, "offset", 0) or 0)
    xr = list(getattr(p, "x_range", None) or prof.get("x_range") or [])

    # ── 反事实输入的口子（只有传了才生效；默认路径逐位不变）────────────────
    if x_range_override is not None:
        if getattr(p, "floor_plans", None):
            return {**base, "outcome": "unreadable", "dxf": str(dxf), "x_range": xr,
                    "why": ("本条覆写只替换 x_range 那一支，而本栋有 floor_plans"
                            "（in_floor_x_range 优先用它）⇒ 覆写不忠实，拒量而不是给个错答案")}
        ov = [float(v) for v in x_range_override]

        def in_range(_p, x, _ov=ov, _tol=range_tol):
            return _ov[0] - _tol <= x <= _ov[1] + _tol
        xr = list(ov)

    try:
        msp = _dxf_doc(EX, dxf)
        role_map = EX.layer_role_map(msp)
        # ★ 与 B3 同款：走 `config/buildings.json`（`config_table`），**不许**直接读
        #   `EX.LAYER_ROLE_OVERRIDE` —— 否则用户一改配置，产物按新配置、本检查按旧表，
        #   两边分叉而不出声（「一个判断两份实现」）。
        role_map.update(CTBL.layer_role_override(name))
        labels = EX.read_labels(msp, role_map, CTBL.purpose_drop_area_like(name))
    except Exception as ex:                                   # noqa: BLE001
        return {**base, "outcome": "unreadable", "why": "读图失败：%s: %s"
                % (type(ex).__name__, ex), "dxf": str(dxf)}

    nums = labels.get("number") or []
    if not nums:
        return {**base, "outcome": "no_labels", "dxf": str(dxf),
                "why": "图上一条房号标注都没读到（层名语义变了？）—— 不猜"}

    # ── 分箱：模型收进来的 / 被图幅滤掉的（每条记下它归到哪一层）──────────
    groups: dict[str, list[tuple[float, float, object]]] = {}
    n_out = 0
    for x, y, t in nums:
        if not in_range(p, x):
            n_out += 1
            continue
        groups.setdefault(norm_number(t), []).append((float(x), float(y), floor_of(p, x, y)))

    if offset <= 0:
        return {**base, "outcome": "unreadable", "dxf": str(dxf), "x_range": xr,
                "why": "profile 的 offset 不是正数（%r）—— 阈值没有来源，不量" % offset}

    dups = []
    for num, pts in sorted(groups.items()):
        if len(pts) < 2:
            continue
        # ★ 判据的两个条件，缺一不可：
        #   ① 重复的两处必须落在**同一个层带**里。跨层的同名是**另一件事** ——
        #      c006 的 `6-A-02-06` 就出现在相邻两层（Δy=130508.8，距/层带 **0.97**，
        #      差 0.03 就会误报，余量只有 3%）。加上这一条，它被**整个排除**，
        #      判据的分辨余量不再靠那 3% 撑着。
        #   ② 同层内两处的最大间距 > `offset`。
        per_floor: dict[object, list[tuple[float, float]]] = {}
        for x, y, F in pts:
            per_floor.setdefault(F, []).append((x, y))

        def _span(q):
            return (max(abs(a[0] - b[0]) for a in q for b in q),
                    max(abs(a[1] - b[1]) for a in q for b in q))

        fx = fy = 0.0
        same = None
        # ★★ 「有没有同层对」必须用**独立的标志位**，不能拿 `same is None` 去代表 ——
        #    `floor_of` 本来就**合法地会返回 None**（两条标注都落在所有层带之外，实测
        #    c046 就是：`n_same_floor>=2` 却 `same is None` ⇒ `dist` 成了 None ⇒
        #    `d["dist"] > offset` 抛 TypeError，全库普查里它报 CRASH）。
        #    一个 `None` 担「没找到」与「层未知」两个意思 = 铁律 146 那一族的第二处
        #    （上一处是 `dx=0.0` 当哨兵）。
        found = False
        for F, q in per_floor.items():
            if len(q) < 2:
                continue
            ax, ay = _span(q)
            # ★★ 选中条件里必须有 `not found` 这一支：`max(ax,ay)` 可以**合法地等于 0.0**
            #    （同一层里两条标注落在**同一点**上），而初始的 `max(fx,fy)` 也是 0.0
            #    ⇒ 严格 `>` 永远不成立 ⇒ `found` 一直是 False ⇒ 一条**真的同层**重号
            #    拿到了 `dist=None`，读起来像跨层。c046 就是这么崩的（同一族的第三处：
            #    前两处是 `dx=0.0` 当哨兵、`same is None` 担两个意思）。初始值当哨兵，
            #    第三次付账 —— 铁律 19 那一族的落点。
            if not found or max(ax, ay) > max(fx, fy):
                fx, fy, same, found = ax, ay, F, True
        # ★★ 跨层同名那一档：同层间距这个量**不存在**，所以 `dx/dy/dist/ratio` 必须是
        #    **None，不是 0.0**。先前它们停在初始值 0.0 ⇒ 打印出来读作「两处重合」
        #    （实测 2026-09-29：c006 的 `6-A-02-06` 印 `Δx=0.0 Δy=0.0 距/层带=0.0000`，
        #    真相是它那两条分属相邻两层，Δy 实际 130508.8）。哨兵值当读数 = 铁律 146
        #    的配套那一半：`None`（不适用）与 `0`（量到零）在屏幕上必须长得不一样。
        #    跨层那种另有 `dist_all`（全体两两最大间距，中性地量位移，不判）。
        has_sf = found
        ax_all, ay_all = _span([(x, y) for x, y, _F in pts])
        dups.append({"number": num, "n": len(pts),
                     # 形状与「含不含数字」进证据：判词不许被 `天台` 这种抢标题
                     "shape": shape_of(num), "numeric": has_digit(num),
                     "n_same_floor": max((len(q) for q in per_floor.values()), default=0),
                     "floor": same,
                     # `floor is None` 的含义是「这两条都不属于任何层带」（不是「没找到」）
                     "floor_known": same is not None,
                     "dx": fx if has_sf else None, "dy": fy if has_sf else None,
                     "dist": max(fx, fy) if has_sf else None,
                     "ratio": (max(fx, fy) / offset) if has_sf else None,
                     "dx_all": ax_all, "dy_all": ay_all,
                     "dist_all": max(ax_all, ay_all),
                     "xs": sorted(set(round(q[0], 1) for q in pts)),
                     "ys": sorted(set(round(q[1], 1) for q in pts))})
    # 排序：**含数字的优先**（房号是它本分），再按同层间距降序，跨层同名沉底。
    # ★ 第一维为什么必须有：c114 的 `天台`（无数字）相距 38910 mm，压过真房号
    #   `114-05-04` 的 7100 mm ⇒ 只按距离排，标题永远是垃圾。
    #   跨层那条 `dist` 是 None，不能进取负号，用 -1.0 占位让它落在本组末尾。
    dups.sort(key=lambda d: (0 if d["numeric"] else 1,
                             -(d["dist"] if d["dist"] is not None else -1.0)))
    # ★★★ 「同层」与「同名」是**两个量**，必须分开数 —— 2026-09-29 读回自己写的判词时抓到。
    #   `dups` 装的是**所有**在幅内出现 ≥2 次的号，**含跨层同名**（房号里嵌层号，
    #   c006 的 `6-A-02-06` 就出现在相邻两层）。而本条的命题是「**同一层**被画了两份」。
    #   先前那句通过判词印的是 `n_dups`（含跨层），却配了一句「同层内间距都不超过层带
    #   高度」——对 c006 是**假的**：它 n_dups=1、那一条的 dist=130508.8，比同一句里
    #   印出来的 offset 130118 还大。判词挂在了错的量上（铁律 44/146：挂错/数反了
    #   照样把「好话」印出来）。⇒ 分成三档，每档只说自己那个量的事。
    same_floor = [d for d in dups if d["n_same_floor"] >= 2]
    over = [d for d in same_floor if d["dist"] > offset]
    cross = [d for d in dups if d["n_same_floor"] < 2]     # 跨层同名：另一种现象，只报不判
    # 「不含数字」的同层重号：**不是房号式文本**（`天台`/`花坛`/`走道` 那种），
    # 是抽取器把别的东西判成了房号 —— 归 J-A 管，本条只把它数出来、印出来。
    nonnum = [d for d in same_floor if not d["numeric"]]
    shapes = {}
    for _k, _v in groups.items():
        shapes[shape_of(_k)] = shapes.get(shape_of(_k), 0) + len(_v)

    ev = {"dxf": str(dxf), "x_range": xr, "offset": offset, "shapes": shapes,
          "n_number_labels": len(nums), "n_in_frame": sum(len(v) for v in groups.values()),
          "n_out_of_frame": n_out, "n_distinct": len(groups),
          "dups": dups[:12], "n_dups": len(dups),
          "n_dups_same_floor": len(same_floor), "n_dups_cross_floor": len(cross),
          "n_dups_same_floor_nonnum": len(nonnum),
          "worst_nonnum": nonnum[0] if nonnum else None,
          "n_dups_over": len(over),
          # `worst` 保名不改义：**同层**最大的那个；同层一个都没有时才是跨层里最大的
          # （按 dist_all，而不是那条 0.0）—— 免得 `worst` 在两种情形下指两个量。
          "worst": (same_floor[0] if same_floor else
                    (max(cross, key=lambda d: d["dist_all"]) if cross else None)),
          # 本条的判词只能用**同层**那一侧的数（`same_floor` 已按 dist 降序，取 [0] 即最大）
          "worst_same_floor": same_floor[0] if same_floor else None}
    # outcome 三档：dup = 同层且间距 > offset（整层画了两份）；near = 同层有重号但间距更小
    # （一间标两遍 / 两个房间共用一个号）；ok = 同层无重号。
    out = "dup" if over else ("near" if same_floor else "ok")
    return {**base, **ev, "outcome": out}
