# -*- coding: utf-8 -*-
"""keep_courtyard_holes 分支收窄改动的 A/B 量具（只读产物；只有 `before` 会备份）。

量什么
------
交付 `floors/floorN.json` 的 `outline` 多边形面积 / 图纸建筑面积表那一格。
**与 `_slab_vs_truth_fleet.py` 用同一把尺**（同一处读法、同一处 off-by-one：
模型 F0 ↔ 图纸标签 "1"），否则改前改后的数不可比。

为什么要有对照组
----------------
改动是「只给楼板分支留内环，墙梳分支一律不留」。对**没开这个开关**的楼，
`getattr(p,"keep_courtyard_holes",False)` 本来就是 False，行为必须**一个字节都不变**
—— 若对照组的数动了，说明改错了地方，而不是"它本来就有问题"。
对照组就是这次改动的**刑具**（memory: verifier-needs-its-own-falsifier）。

三组：
  · 待修 c002/c003         —— 该变好
  · 回字形 c054/c072/c073  —— 开关本来就是给它们的，**不许变坏**
  · 对照 c006/c019         —— 没这个键，**必须逐位不变**

用法（只认位置参数，本仓惯例：不认 --help）：
  python _scratch/_kch_ab.py before c002 c003 c054 c072 c073 c006 c019
  python _scratch/_kch_ab.py after  c002 c003 c054 c072 c073 c006 c019
  python _scratch/_kch_ab.py cmp
"""
import json
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "_scratch"), str(ROOT / "backend")]
sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

from shapely.geometry import Polygon                       # noqa: E402
from checks.floor_levels import read_area_rows, own_prefix  # noqa: E402

BDIR = ROOT / "data" / "buildings"
BAK = ROOT / "_scratch" / "_bak_kch"
SNAP = ROOT / "_scratch"


def outline_area(d: dict) -> float:
    """交付轮廓面积。★ 与 _slab_vs_truth_fleet.py 逐字一致 —— 两把尺子不一样就白比。"""
    o = d.get("outline") or []
    return Polygon([tuple(q) for q in o]).area if len(o) >= 3 else 0.0


def truth_of(nm: str) -> dict:
    dxf = (json.loads((BDIR / nm / "profile.json").read_text(encoding="utf-8"))
           or {}).get("dxf")
    if not dxf or not Path(dxf).exists():
        return {}
    pre = own_prefix(nm)
    try:
        rows = read_area_rows(Path(dxf))
    except Exception as ex:                                # noqa: BLE001
        print("  %s 面积表读不出：%s" % (nm, ex))
        return {}
    return {str(r["label"]): r for r in rows
            if str(r.get("sheet", "")).upper().startswith(pre.upper())}


def measure(nm: str, truth: dict) -> list[dict]:
    out = []
    fdir = BDIR / nm / "floors"
    for fj in sorted(fdir.glob("floor*.json")):
        try:
            F = int(fj.stem.replace("floor", ""))
        except ValueError:
            continue
        d = json.loads(fj.read_text(encoding="utf-8"))
        a1 = outline_area(d)
        t = truth.get(str(F + 1))                # ★ off-by-one：模型 F0 ↔ 标签 "1"
        a3 = (t or {}).get("m2") or 0.0
        out.append({"floor": F, "area": round(a1, 1),
                    "truth": float(a3), "label": (t or {}).get("label"),
                    "ratio": round(a1 / a3, 3) if a3 > 0 else None,
                    "parts": len(d.get("outline_parts") or []),
                    "rooms": len(d.get("rooms") or []),
                    "walls": len(d.get("walls") or [])})
    return out


def backup(nm: str) -> None:
    """★ 覆盖交付件前先留档（memory: backup-before-overwriting-deliverable）。
    data/** 无版本历史且写盘是原子的 —— 写下去就回不来。"""
    src = BDIR / nm
    dst = BAK / time.strftime("%Y%m%d_%H%M%S") / nm
    dst.mkdir(parents=True, exist_ok=True)
    if (src / "floors").is_dir():
        shutil.copytree(src / "floors", dst / "floors")
    for f in src.glob("profile.json*"):
        shutil.copy2(f, dst / f.name)
    for f in src.glob("rooms.json"):
        shutil.copy2(f, dst / f.name)
    for f in src.glob("*.glb"):
        shutil.copy2(f, dst / f.name)
    print("  已留档 → %s" % dst)


def main() -> None:
    phase = sys.argv[1] if len(sys.argv) > 1 else "cmp"
    names = [a for a in sys.argv[2:] if not a.startswith("--")]

    if phase == "cmp":
        # ★ 必须**按时间**排，不能按文件名 —— 第一版用 sorted()，于是
        #   `_kch_after.json` 排在 `_kch_before.json` **前面**（a<b 字典序），
        #   两份快照被当成"前一份=after、后一份=before"，**每个箭头都反了**：
        #   真正变大的 c002 (758.7→1112.3) 打成了"[变小]"。这跟 c072 那次回归
        #   差点混在一起 —— 一个把方向搞反的量具，比没有量具更坏。
        #   所以：显式给路径优先，其次按 mtime。
        args = [a for a in sys.argv[2:] if a.endswith(".json")]
        if len(args) >= 2:
            pa, pb = Path(args[0]), Path(args[1])
        else:
            snaps = sorted(SNAP.glob("_kch_*.json"), key=lambda p: p.stat().st_mtime)
            if len(snaps) < 2:
                print("只有 %d 份快照，比不了：%s" % (len(snaps), [s.name for s in snaps]))
                return
            pa, pb = snaps[-2], snaps[-1]
        a = json.loads(pa.read_text(encoding="utf-8"))
        b = json.loads(pb.read_text(encoding="utf-8"))
        print("按时间：前 = %s   →   后 = %s\n" % (pa.name, pb.name))
        n_same = n_diff = 0
        for nm in sorted(set(a) | set(b)):
            fa = {r["floor"]: r for r in a.get(nm, [])}
            fb = {r["floor"]: r for r in b.get(nm, [])}
            if not fa or not fb:
                print("【%s】一边缺数据：%d 层 vs %d 层" % (nm, len(fa), len(fb)))
                continue
            if set(fa) != set(fb):
                print("【%s】⚠ 层集合变了：%s → %s" % (nm, sorted(fa), sorted(fb)))
            for F in sorted(set(fa) & set(fb)):
                ra, rb = fa[F], fb[F]
                d = rb["area"] - ra["area"]
                tag = "同" if abs(d) < 1e-6 else ("变大" if d > 0 else "变小")
                if abs(d) < 1e-6:
                    n_same += 1
                else:
                    n_diff += 1
                print("  %-7s F%-2d %8.1f → %8.1f  (%+9.1f)  比值 %.2f → %.2f  [%s]"
                      % (nm, F, ra["area"], rb["area"], d,
                         ra["ratio"] if ra["ratio"] else 0,
                         rb["ratio"] if rb["ratio"] else 0, tag))
        print("\n合计：不变 %d 层 / 变了 %d 层" % (n_same, n_diff))
        return

    snap = {}
    print("=" * 92)
    print("阶段 %s：%s" % (phase, " ".join(names)))
    print("=" * 92)
    for nm in names:
        pj = BDIR / nm / "profile.json"
        if not pj.exists():
            print("【%s】没有 profile.json，跳过" % nm); continue
        kch = json.loads(pj.read_text(encoding="utf-8")).get(
            "keep_courtyard_holes", "__无此键__")
        if phase == "before":
            backup(nm)
        truth = truth_of(nm)
        rows = measure(nm, truth)
        snap[nm] = rows
        print("\n【%s】keep_courtyard_holes=%s  图上层标签 %d 个 %s   模型 %d 层"
              % (nm, kch, len(truth), sorted(truth), len(rows)))
        for r in rows:
            print("   F%-2d 轮廓%9.1f  图纸%9.1f  比值 %-6s  环%3d 房%4d 墙%4d"
                  % (r["floor"], r["area"], r["truth"],
                     ("%.2f" % r["ratio"]) if r["ratio"] else "N/A",
                     r["parts"], r["rooms"], r["walls"]))

    outp = SNAP / ("_kch_%s.json" % phase)
    outp.write_text(json.dumps(snap, ensure_ascii=False, indent=1), encoding="utf-8")
    print("\n快照已写 %s" % outp)


if __name__ == "__main__":
    main()
