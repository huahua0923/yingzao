# -*- coding: utf-8 -*-
r"""给「图上比模型多一层且多的那层是 D1/J11/H 这类非数字层号」的楼补层（只读报告；
`--apply` 才落盘）。

起因（用户原话）
----------------
「水上图书馆，f0其实是两层」。查下去不是"两层"而是**图上最底下那层压根没进模型**：
砚湖图书馆(c001) 的图把 6 个平面**沿 Y 摞着画**（D1 在最下，往上 1~5），
而 profile 的 `floor_ys` 只有 5 个（1~5）。`floor_of` 取"与层中心最近"，
**没有下界** ⇒ D1 那层的墙全部被并进 F0 —— 交付的 F0 于是是「D1 平面 + 1 层平面」
两片叠在一起的东西，而不是任何一层。

为什么不是「ROOM_RE 写死 \d{1,2}」的问题
----------------------------------------
`backend/checks/__init__.py` 的 B4 记的是房号正则把 `D1` 吃掉了。那条也对，
但它管的是**房间**；这里量的是**楼层归属**，两者独立。本工具只补层，
不动正则。

判据（都从图上量，不写死常数）
------------------------------
  ① 取本栋 `x_range` 内的墙折线质心；
  ② 按 Y 做一维聚类，得到平面上实际画了几坨；
  ③ 坨数 > `len(floor_ys)` ⇒ 有层没进模型；把**多出来的那几坨**按各自外接框中心
     补进 floor_ys（插在正确的位置：按 y 升序排）。
  ④ 自检：补完之后，每一坨图的 y 中心都必须落在**离自己最近**的那个层中心上
     （即"每坨图都归到了自己的层"），否则报出来不落盘。

★ 为什么同时删 `floor_y_bands`
  `floor_of` 里 `floor_y_bands` 的优先级**高于** `floor_ys`，但 `load_profile`
  **从不读它**（全仓 grep 为 0）—— 是一份**死配置**。层号一旦改动，
  这份死配置就成了"同一件事的第二种写法"，将来谁把加载器接上，低优先的那份
  会静默改行为（memory: dual-representation-shadowed-control）。要么写对，要么删掉；
  这里**删掉**并留 _note 说明，因为 floor_ys 才是实际生效的那份。

用法（只认位置参数；本仓惯例不认 --help）：
  python _scratch/_add_d1_floor.py c001
  python _scratch/_add_d1_floor.py c001 --apply
"""
import collections
import json
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "_scratch"), str(ROOT / "backend")]
sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

BDIR = ROOT / "data" / "buildings"

# 一维聚类的断开阈值（毫米）：两层平面的中心间距远大于此。取 15m —— 图纸把
# 同栋的相邻平面摞得最近的实测也在 100m 以上（c001 各层间距 ~122m），
# 15m 只会把"同一层里被拆成两半的图"分开，而那种情况本来就该被看见。
CLUSTER_GAP_MM = 15000.0


def wall_centres(msp, p) -> list[float]:
    """x_range 内的墙折线质心 y（毫米）。按本栋 classifier 取墙。"""
    p = type(p)(**{**p.__dict__, "floor_ys": None, "floor_plans": None,
                   "floor_y_bands": None})
    if getattr(p, "classifier", "lwpolyline") == "line":
        from recognizer.classify_line import classify_line
        walls, _, _, _ = classify_line(msp, p)
    else:
        from recognizer.classify import classify
        walls, _, _, _ = classify(msp, p)
    return [sum(float(q[1]) for q in s) / len(s) for s in walls]


def cluster(ys: list[float]) -> list[list[float]]:
    """一维聚类：排序后相邻差 > CLUSTER_GAP_MM 就断开。"""
    out, cur = [], []
    for y in sorted(ys):
        if cur and y - cur[-1] > CLUSTER_GAP_MM:
            out.append(cur)
            cur = []
        cur.append(y)
    if cur:
        out.append(cur)
    return out


def main() -> None:
    apply = "--apply" in sys.argv
    names = [a for a in sys.argv[1:] if not a.startswith("--")]
    import ezdxf
    from run_building import load_profile

    for nm in names:
        pf = BDIR / nm / "profile.json"
        raw = json.loads(pf.read_text(encoding="utf-8"))
        p = load_profile(nm)
        ys_old = [float(v) for v in (p.floor_ys or [])]
        print("=" * 96)
        print("【%s】%s" % (nm, raw.get("title")))
        print("  现有 floor_ys(%d 个)：%s" % (len(ys_old), ["%.0f" % v for v in ys_old]))
        print("  profile 里的 floor_y_bands：%s"
              % ("有 %d 个（**加载器从不读**，死配置）" % len(raw["floor_y_bands"])
                 if raw.get("floor_y_bands") else "无"))

        doc = ezdxf.readfile(p.dxf, encoding="utf-8")
        cy_all = wall_centres(doc.modelspace(), p)
        # 只留 y 在 [最低层 - 半个层距, 最高层 + 半个层距] 之外的**下方**坨
        if not ys_old:
            print("  本楼没有 floor_ys，跳过（本工具只处理『按 Y 摞图』的体裁）")
            continue
        lo, hi = min(ys_old), max(ys_old)
        step = (hi - lo) / max(1, len(ys_old) - 1)
        # 下方：低于最低层中心半个层距以外的墙，都是"没有归属层"的
        below = [y for y in cy_all if y < lo - step * 0.5]
        cl = cluster(below)
        print("  图纸 x_range 内墙 %d 条；最低层中心 %.0f，层距 %.0f" % (len(cy_all), lo, step))
        print("  落在最低层下方半步以外的墙 %d 条，聚成 %d 坨" % (len(below), len(cl)))
        if not cl:
            print("  ✓ 没有多余的坨 —— 本楼层数与图一致，不需要补")
            continue
        newc = []
        for c in cl:
            n = len(c)
            if n < 20:
                print("    跳过一坨 %d 条墙（太少，疑似图签/详图/零星线）：y %.0f~%.0f"
                      % (n, min(c), max(c)))
                continue
            newc.append(round((min(c) + max(c)) / 2.0))
            print("    补一坨：%d 条墙  y[%.0f, %.0f]  中心 %.0f"
                  % (n, min(c), max(c), (min(c) + max(c)) / 2.0))
        if not newc:
            print("  → 没有够格的坨，不落盘")
            continue
        ys_new = sorted(set([round(v) for v in ys_old] + newc))
        print("  ⇒ 新 floor_ys(%d 个)：%s" % (len(ys_new), ["%.0f" % v for v in ys_new]))

        # 自检：每坨墙都归到离自己最近的那个层中心
        bad = 0
        for y in cy_all:
            j = min(range(len(ys_new)), key=lambda i: abs(y - ys_new[i]))
            # 允许在本层图的外接框内摆动：层距的一半当作容差
            if abs(y - ys_new[j]) > step * 0.75:
                bad += 1
        print("  ✓ 自检：%d 条墙中 %d 条归不到任何层中心半步以内（%s）"
              % (len(cy_all), bad, "通过" if bad == 0 else "⚠ 先看清楚再落盘"))

        if not apply:
            print("  （只报告。加 --apply 才落盘）")
            continue
        bak = pf.with_name(pf.name + ".bak-d1-%s" % time.strftime("%Y%m%d_%H%M%S"))
        shutil.copy2(pf, bak)
        raw["floor_ys"] = [float(v) for v in ys_new]
        dropped = raw.pop("floor_y_bands", None)
        raw["_note_floor_ys"] = (
            "%s 由 _scratch/_add_d1_floor.py 补层：图上平面按 Y 摞着画，"
            "最下面那一坨（中心 y=%.0f）在 profile 里**没有对应层**，"
            "而 floor_of 取最近层中心、没有下界 ⇒ 它的墙被并进 F0。"
            "补进 floor_ys 后每坨图各归其层。"
            "同时删掉 floor_y_bands（%s）—— 该键优先级更高但"
            "load_profile 从不读它（死配置），留着就是同一件事两份写法。"
            % (time.strftime("%Y-%m-%d"), newc[0],
               "原有 %d 个，已删" % len(dropped) if dropped else "本就没有")
        )
        tmp = pf.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(raw, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(pf)
        print("  ✅ 已写 %s（备份 %s）" % (pf, bak.name))


if __name__ == "__main__":
    main()
