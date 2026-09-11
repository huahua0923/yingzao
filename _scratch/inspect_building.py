# -*- coding: utf-8 -*-
"""单栋侦查：图层结构 + 墙层 Y 聚类(楼层/OFFSET) + 范围(中心/尺寸)。

可 import 的 `inspect_building(tag, path)` 返回报告文本，供 pipeline 调用。
命令行: python inspect_building.py <tag> <dxf路径>
"""
import sys
import os
import ezdxf
from collections import Counter

DEFAULT_OUT_DIR = r"D:\dwg_source"  # 侦查报告落盘目录


def inspect_building(tag, path):
    """侦查一栋楼，返回报告文本（图层数/每层实体构成/墙层 Y 聚类→楼层数+OFFSET）。"""
    lines = []
    lines.append("=" * 70)
    lines.append("建筑: " + tag)
    lines.append("文件: " + path + f"  ({os.path.getsize(path) / 1048576:.1f} MB)")
    doc = ezdxf.readfile(path)
    lines.append("DXF 版本: " + str(doc.dxfversion))
    msp = doc.modelspace()

    lc = Counter()
    lt = {}
    wall_y = []       # 墙层所有顶点 Y(mm)
    all_x = []
    all_y = []
    for e in msp:
        t = e.dxftype()
        lay = e.dxf.layer if hasattr(e.dxf, "layer") else "(none)"
        lc[lay] += 1
        lt.setdefault(lay, Counter())[t] += 1
        if t == "LWPOLYLINE":
            try:
                pts = [tuple(p[:2]) for p in e.get_points()]
            except Exception:
                continue
            for x, y in pts:
                all_x.append(x)
                all_y.append(y)
            if "墙" in lay:
                for x, y in pts:
                    wall_y.append(y)

    lines.append("图层数: %d" % len(lc))
    for lay, c in lc.most_common():
        ts = "+".join(f"{t}:{n}" for t, n in lt[lay].most_common())
        lines.append("  [%5d] %r -> %s" % (c, lay, ts))

    lines.append("")
    if all_x:
        lines.append(
            "全部LWPOLYLINE顶点 X范围: [%.0f, %.0f]  宽 %.0f mm (%.0f m)"
            % (min(all_x), max(all_x), max(all_x) - min(all_x), (max(all_x) - min(all_x)) / 1000)
        )
        lines.append(
            "全部LWPOLYLINE顶点 Y范围: [%.0f, %.0f]  高 %.0f mm (%.0f m)"
            % (min(all_y), max(all_y), max(all_y) - min(all_y), (max(all_y) - min(all_y)) / 1000)
        )
        lines.append(
            "中心 CX=(min+max)/2=%.0f  CY=%.0f"
            % ((min(all_x) + max(all_x)) / 2, (min(all_y) + max(all_y)) / 2)
        )

    # 墙层 Y 聚类 → 楼层数 + OFFSET（间距 >5000mm 视为不同楼层）
    if wall_y:
        wy = sorted(set(round(y) for y in wall_y))
        clusters = []
        cur = [wy[0]]
        for y in wy[1:]:
            if y - cur[-1] > 5000:
                clusters.append(cur)
                cur = [y]
            else:
                cur.append(y)
        clusters.append(cur)
        centers = [sum(c) / len(c) for c in clusters]
        gaps = [round(centers[i + 1] - centers[i]) for i in range(len(centers) - 1)]
        lines.append("")
        lines.append("墙层顶点 Y 聚类: %d 组 (≈ 层数)" % len(clusters))
        lines.append("  各组中心 Y(mm): %s" % [round(c) for c in centers])
        lines.append("  相邻间距(mm): %s" % gaps)
        if gaps:
            lines.append("  推断 OFFSET(层间距): %d mm" % round(sum(gaps) / len(gaps)))
        # 每层墙段 X 范围（判断各层是否同尺寸）
        c_sets = [set(c) for c in clusters]
        for ci, cset in enumerate(c_sets):
            xs = [all_x[k] for k in range(len(all_x)) if round(all_y[k]) in cset]
            if xs:
                lines.append(
                    "  第 %d 层: Y中心=%.0f  X范围[%.0f,%.0f] 宽%.0f mm"
                    % (ci, centers[ci], min(xs), max(xs), max(xs) - min(xs))
                )
    return "\n".join(lines)


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if len(sys.argv) < 3:
        print("用法: python inspect_building.py <tag> <dxf路径>")
        sys.exit(2)
    tag, path = sys.argv[1], sys.argv[2]
    text = inspect_building(tag, path)
    print(text)
    out_txt = os.path.join(DEFAULT_OUT_DIR, tag + "_inspect.txt")
    with open(out_txt, "w", encoding="utf-8") as f:
        f.write(text + "\n")
    print("\n报告已写: " + out_txt)


if __name__ == "__main__":
    main()
