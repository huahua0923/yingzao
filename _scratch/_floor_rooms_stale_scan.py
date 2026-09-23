# -*- coding: utf-8 -*-
"""扫全库：**楼层快照里的房间数，是否落在 rooms.json 后面**（只读）。

为什么要有这把尺
----------------
`floors/floorN.json` 的 `rooms[]` 是**写盘那一刻**的快照，不是视图 —— rooms.json
后补时它不会自己更新（memory: floor-json-rooms-are-snapshot）。后果是**沉默**的：
3D 查看器点不到房间、识别结果图少画房间，而两边文件都"格式正确、没有报错"。
2026-09-24 凌晨实测 c001/c002/c003 **三栋全都没回填**，而当时的提交说明里写着
"已跑 backfill_floor_rooms" —— 说明**"我跑过"这句话本身不是量具**。

判据（按层，不按整栋）
--------------------
对每层 F：`floors` 的条数 < `rooms.json` 里 floor==F 的条数 ⇒ 该层**落后**。
两边相等 ⇒ 齐。floors 比 rooms.json 还多 ⇒ 也不对（另报 `floors_more`，那是
重复注入那类老伤，`_dedupe_by_id` 该收拾的）。

★ 不报"少了多少间"以外的推断：少 0 间不等于房间对，只等于**两边条数一致**。
  非空条数一致的层不再往下看 —— 那是 `backfill` 的活干完了，不是"房间抽对了"。

用法：
  python _scratch/_floor_rooms_stale_scan.py            # 全库
  python _scratch/_floor_rooms_stale_scan.py c001 c002  # 指定栋
输出：_scratch/_floor_rooms_stale.json
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
BDIR = ROOT / "data" / "buildings"
OUT = ROOT / "_scratch" / "_floor_rooms_stale.json"


def scan(name: str) -> dict:
    b = BDIR / name
    rp = b / "rooms.json"
    fdir = b / "floors"
    if not rp.exists() or not fdir.is_dir():
        return {"skip": "无 rooms.json 或无 floors/"}
    try:
        rooms = json.loads(rp.read_text(encoding="utf-8"))
    except Exception as ex:                                   # noqa: BLE001
        return {"skip": "rooms.json 读不出：%s" % ex}
    want = {}
    for r in rooms:
        if "floor" in r:
            want[r["floor"]] = want.get(r["floor"], 0) + 1

    have, behind, more = {}, [], []
    for fj in sorted(fdir.glob("floor*.json")):
        try:
            F = int(fj.stem.replace("floor", ""))
        except ValueError:
            continue
        try:
            d = json.loads(fj.read_text(encoding="utf-8"))
        except Exception as ex:                               # noqa: BLE001
            print("  ⚠ %s/%s 读不出：%s" % (name, fj.name, ex))
            continue
        n = len(d.get("rooms") or [])
        have[F] = n
        w = want.get(F, 0)
        if n < w:
            behind.append({"floor": F, "floors": n, "ledger": w, "gap": w - n})
        elif n > w:
            more.append({"floor": F, "floors": n, "ledger": w, "extra": n - w})
    return {
        "ledger_total": len(rooms),
        "floors_total": sum(have.values()),
        "have": have, "want": want,
        "behind": behind, "floors_more": more,
        "behind_gap": sum(x["gap"] for x in behind),
    }


def main() -> None:
    names = [a for a in sys.argv[1:] if not a.startswith("-")]
    if not names:
        names = sorted(p.name for p in BDIR.iterdir() if p.is_dir())
    res, n_stale = {}, 0
    for nm in names:
        r = scan(nm)
        if not r or r.get("skip"):
            continue
        res[nm] = r
        if r["behind"] or r["floors_more"]:
            n_stale += 1
            print("【%s】台账 %d 间 / 楼层 %d 间  落后 %d 层（缺 %d 间）%s"
                  % (nm, r["ledger_total"], r["floors_total"], len(r["behind"]),
                     r["behind_gap"],
                     "  ⚠ 楼层多出 %d 层" % len(r["floors_more"]) if r["floors_more"] else ""))
            for x in r["behind"]:
                print("     F%-2d 楼层 %3d / 台账 %3d  缺 %d" % (x["floor"], x["floors"], x["ledger"], x["gap"]))
            for x in r["floors_more"]:
                print("     F%-2d 楼层 %3d / 台账 %3d  ⚠ 多 %d" % (x["floor"], x["floors"], x["ledger"], x["extra"]))
    print("\n合计：扫 %d 栋，落后或多出的 %d 栋" % (len(res), n_stale))
    OUT.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    print("明细已写 %s" % OUT)


if __name__ == "__main__":
    main()
