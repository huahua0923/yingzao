# -*- coding: utf-8 -*-
"""A1 找**外部量**：图上的 `DIMENSION`（人写的实测尺寸）能不能当「不来自 `4.2墙体` 的独立读数」。

思路：一栋楼的**总尺寸**（图纸上标注的最大跨度）是制图人**量/写**出来的，**不由我的墙线配对规则派生**。
⇒ 若模型墙的包围盒跨度 ≈ 标注总尺寸，就是一次**跨来源**的对账（这是 IoU 那种自洽量给不了的）。

本尺量：每份 DXF 的 ① DIMENSION 条数与 ② 沿 X / 沿 Y 的**最大标注跨度**
               ③ 模型墙的包围盒跨度（用 `generic_wall.load` + `wire` 建出来的墙线范围）
               ④ 两者之比。

用法: python probe_dims.py <dxf> [...]

★ 量具盲区（必须声明）：
  ① 只认 `DIMENSION` 实体；**尺寸被炸成 LINE+TEXT** 的图 ⇒ 全盲（报 0）。
  ② `actual_measurement` 是 ezdxf 按**定义点**算的，**文字被手动改写过**（图上写着另一个数）时，
     本尺读的是定义点、**不是那个手写数** ⇒ 与「图上写的数」可能不一致。
  ③ 取「最大值」当总尺寸：若总尺寸被拆成两段标注（或最大值是个斜向尺寸）⇒ 会取错。
  ④ 墙包围盒跨**全楼所有图幅**；若图幅间有大间隙，跨度会把间隙算进去 ⇒ 只在**同一图幅内**比才准
     （本尺先给全楼粗值，看清了再收到图幅内）。
"""
import sys
import os
import collections

sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
import ezdxf

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)


def probe(path):
    doc = ezdxf.readfile(path)
    msp = doc.modelspace()
    dims = []
    for e in msp:
        if e.dxftype() != "DIMENSION":
            continue
        try:
            m = float(e.get_measurement())
        except Exception:
            continue
        if not (m == m) or m <= 0:      # 去 NaN
            continue
        try:
            ang = float(e.dxf.angle) % 180.0
        except Exception:
            ang = 0.0
        dims.append((m, ang, e.dxf.layer))
    hx = max((m for m, a, _ in dims if a < 5 or a > 175), default=0.0)
    hy = max((m for m, a, _ in dims if 85 < a < 95), default=0.0)
    return {"dxf": os.path.basename(path), "n_dim": len(dims),
            "max_x": hx, "max_y": hy,
            "layers": dict(collections.Counter(l for _, _, l in dims).most_common(5)),
            "top": sorted((round(m) for m, _, _ in dims), reverse=True)[:8]}


def main():
    if len(sys.argv) < 2:
        print(__doc__); return 2
    for p in sys.argv[1:]:
        if not os.path.isfile(p):
            print("MISSING:", p); continue
        r = probe(p)
        print("\n===== %s =====" % r["dxf"])
        print("  DIMENSION 条数 : %d" % r["n_dim"])
        print("  层分布         :", r["layers"])
        print("  最大跨度 X/Y   : %.0f / %.0f mm" % (r["max_x"], r["max_y"]))
        print("  最大的几条尺寸 :", r["top"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
