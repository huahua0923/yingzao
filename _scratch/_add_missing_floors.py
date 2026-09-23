# -*- coding: utf-8 -*-
r"""「图上画了几层」vs「profile 声明了几层」——数坨比对，差几层就报几层（只读报告；
`--apply` 才落盘）。

与 _scratch/_add_d1_floor.py 的关系
----------------------------------
那个只找**最低层下方**多出来的坨（c001 的 D1 在最底下，够用）。实测不够：
c081 是「1 坨都没缺在下方」的情况 —— 它的 3 个平面摞在同一个 band 里，
而 floor_ys 只有 1 个（band 中心），于是**上方**的层同样没进模型。
本工具把判据generalize成：**把 x_range 内所有墙折线质心按 Y 一维聚类，
坨数 vs len(floor_ys)**，多几坨就报几坨，并把每坨的中心补成一层。

判据（都从图上量，不写死常数）
------------------------------
  ① 取本栋 `x_range` 内的墙折线质心 y；
  ② 按 Y 一维聚类（断开阈值 CLUSTER_GAP_MM，见下）；
  ③ 坨数 != len(floor_ys) ⇒ 层没对齐；坨数 > 声明数 = **有层没进模型**；
     坨数 < 声明数 = 声明了图上是空的（另一种伤，同样要报）；
  ④ 自检：补完之后，**每一条墙**都必须落在离自己最近的层中心 0.75×层距以内
     （即"每条墙都归到了自己的层"），否则报出来**不落盘**。

★ `floor_y_bands` 同样要删 —— 见 _add_d1_floor.py 的长注释：
  它优先级高于 floor_ys 而 load_profile 从不读（死配置），
  层号一改它就成"同一件事的第二种写法"。

用法（只认位置参数；本仓惯例不认 --help）：
  python _scratch/_add_missing_floors.py c081 c053 c115      # 只报告
  python _scratch/_add_missing_floors.py c081 --apply        # 落盘
"""
import json
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "_scratch"), str(ROOT / "backend")]
sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

BDIR = ROOT / "data" / "buildings"

# 一维聚类的断开阈值（毫米）。同栋相邻平面实测间距在 100m 以上，
# 15m 只会把"同一层里被拆成两半的图"分开 —— 而那种情况本来就该被看见。
CLUSTER_GAP_MM = 15000.0

# 一坨墙少于这么多条就不当一层（图签、详图、零星线）
MIN_WALLS_PER_BLOB = 20


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
    if not names:
        print("用法: _add_missing_floors.py <楼> [...]  [--apply]  （本仓惯例：不认 --help）")
        return
    import ezdxf
    from run_building import load_profile

    n_need = 0
    for nm in names:
        pf = BDIR / nm / "profile.json"
        raw = json.loads(pf.read_text(encoding="utf-8"))
        p = load_profile(nm)
        ys_old = [float(v) for v in (p.floor_ys or [])]
        print("=" * 96)
        print("【%s】%s" % (nm, raw.get("title")))
        print("  现有 floor_ys(%d 个)：%s" % (len(ys_old), ["%.0f" % v for v in ys_old]))
        print("  profile 的 floor_y_bands：%s"
              % ("有 %d 个（**加载器从不读**，死配置）" % len(raw["floor_y_bands"])
                 if raw.get("floor_y_bands") else "无"))
        if not ys_old:
            print("  ⚠ 本楼没有 floor_ys —— 不是「按 Y 摞图」的体裁，本工具不适用，跳过")
            continue

        doc = ezdxf.readfile(p.dxf, encoding="utf-8")
        cy = wall_centres(doc.modelspace(), p)
        cl = cluster(cy)
        blobs = [c for c in cl if len(c) >= MIN_WALLS_PER_BLOB]
        small = [c for c in cl if len(c) < MIN_WALLS_PER_BLOB]
        print("  x_range 内墙 %d 条 → 聚成 %d 坨（其中 %d 坨 ≥%d 条算一层，%d 坨太少忽略）"
              % (len(cy), len(cl), len(blobs), MIN_WALLS_PER_BLOB, len(small)))
        for c in blobs:
            print("     坨：%4d 条墙  y[%9.0f, %9.0f]  中心 %9.0f"
                  % (len(c), min(c), max(c), (min(c) + max(c)) / 2.0))

        if len(blobs) == len(ys_old):
            print("  ✓ 坨数 == floor_ys 条数（%d）—— 层数一致，本工具无需补" % len(blobs))
            continue
        n_need += 1
        print("  ⚠ 坨数 %d != floor_ys %d" % (len(blobs), len(ys_old)))

        ys_new = sorted(round((min(c) + max(c)) / 2.0) for c in blobs)
        step = ((max(ys_new) - min(ys_new)) / max(1, len(ys_new) - 1)) if len(ys_new) > 1 else 0.0
        print("  ⇒ 新 floor_ys(%d 个)：%s   层距 %.0f" % (len(ys_new), ys_new, step))

        # 自检：每条墙都归到离自己最近的层中心（容差 0.75×层距）
        tol = step * 0.75 if step else float("inf")
        bad = 0
        for y in cy:
            j = min(range(len(ys_new)), key=lambda i: abs(y - ys_new[i]))
            if abs(y - ys_new[j]) > tol:
                bad += 1
        tag = "通过" if bad == 0 else "⚠ 先看清楚再落盘"
        print("  ✓ 自检：%d 条墙中 %d 条归不到任何层中心 %.0f 以内（%s）" % (len(cy), bad, tol, tag))

        if not apply:
            print("  （只报告。加 --apply 才落盘）")
            continue
        if bad:
            print("  ✗ 自检没过，拒绝落盘 —— 先查清那些墙是什么")
            continue
        bak = pf.with_name(pf.name + ".bak-floors-%s" % time.strftime("%Y%m%d_%H%M%S"))
        shutil.copy2(pf, bak)
        raw["floor_ys"] = [float(v) for v in ys_new]
        dropped = raw.pop("floor_y_bands", None)
        raw["_note_floor_ys"] = (
            "%s 由 _scratch/_add_missing_floors.py 补层：图上平面按 Y 摞着画，"
            "聚成 %d 坨而 profile 只声明了 %d 层 ⇒ 多出来的层没进模型。"
            "按每坨中心补进 floor_ys。同时删掉 floor_y_bands（%s）——"
            "该键优先级更高但 load_profile 从不读它（死配置）。"
            % (time.strftime("%Y-%m-%d"), len(blobs), len(ys_old),
               "原有 %d 个，已删" % len(dropped) if dropped else "本就没有")
        )
        tmp = pf.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(raw, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(pf)
        print("  ✅ 已写 %s（备份 %s）" % (pf, bak.name))

    print("\n合计：%d 栋层数与图不一致" % n_need)


if __name__ == "__main__":
    main()
