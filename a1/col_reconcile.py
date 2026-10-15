# -*- coding: utf-8 -*-
"""对账：`建出柱的栋 39/92` 与方案里写的「柱覆盖 41/105」差的那 2 栋是谁？

两个分母不是一回事，混着写就会印出一个**像结论的数**（铁律 174：同名的两个量必须死掉一个）：
  A) 有柱层/能建出柱的**文件数**（分母 105，全库）
  B) 其中**几何闸 OK**（进得了打分）的文件数（分母 92）
差 = 有柱但没进打分的文件（NO_GRID / 其它失败态）。本脚本把它们点名列出来。
"""
import collections
import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
sys.path.insert(0, str(Path(__file__).parent))
import cols as COLS       # noqa: E402
import ezdxf              # noqa: E402

SRC = Path(r"D:\项目\gym3d\材料\dxf_output")
SWEEP = Path(r"D:\项目\cdut3d\a1\_out\wall_sweep4.json")


def main():
    rows = json.loads(SWEEP.read_text(encoding="utf-8"))["rows"]
    state = {r["dxf"]: r for r in rows}
    have, ok_have, nogrid_have = [], [], []
    for f in sorted(SRC.glob("*.dxf")):
        doc = ezdxf.readfile(str(f))
        polys, lh, hits = COLS.load_cols_from_msp(doc.modelspace())
        if not polys:
            continue
        have.append(f.name)
        st = state.get(f.name, {}).get("state", "?")
        if st == "OK" and state[f.name].get("n_col", 0) > 0:
            ok_have.append(f.name)
        else:
            nogrid_have.append((f.name, st, len(polys)))
    print("有柱的文件（ALL polys 非空）: %d" % len(have))
    print("  其中 sweep4 状态 OK 且 n_col>0 : %d   ← 「建出柱的栋 39/92」的分子" % len(ok_have))
    print("  其中没进打分或 n_col=0        : %d" % len(nogrid_have))
    for n, st, k in nogrid_have:
        print("      %-38s %-10s 柱块 %d" % (n[:38], st, k))
    print("\n⇒ 41 与 39 的分母不同：41 是**全库有柱的文件数**（分母 105），39 是**其中状态 OK 的**（分母 92）。")
    return 0


sys.exit(main())
