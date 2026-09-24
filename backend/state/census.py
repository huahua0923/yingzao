# -*- coding: utf-8 -*-
"""全库口径的唯一计算者 —— 「现在是什么状态」只许从这里取数。

**为什么需要这个文件。** 同一个「全库几层」，仓库里同时存在**六个**答案，
而它们**全都是正确的测量** —— 每一个都是对**它自己那把量具**而言精确正确的数，
分歧只来自六个没说出口的定义：

    456   `buildings/<栋>/floors/floorN.json`              ← 交付（服务端也是这个）
     12   `c057/floors.orig_<时间戳>/floorN.json`           ← 快照，名字带 .orig_ 后缀
   1946   路径**组件**含 `.orig` 的那些 `floorN.json`        ← 真备份层
   2414   456 + 12 + 1946（逐项加得起来 ✓）                  ← 全部
    468   456 + 12（=`glob.glob` 语义下的 `floor*.json` 总数） ← 侦察员报的，没撒谎
    642   456 + 186（`pathlib` 语义下、父目录**恰好叫** `floors` 的那些）

README 360 ／ `index.json` 441 or 437 是另外两个更旧的副本。

**⇒ 642 和 468 都不是算错的，是「问错了问题」**（`642` 把 186 个备份层当成交付层，
因为它按「父目录名 == `floors`」找，而备份的内层目录恰好也叫 `floors`）。
分辨它们不需要更小心，只需要**把口径写下来** —— 这正是本文件存在的全部理由。
我一开始把 642 钉成「真值」、又反过来怀疑 468，两头都错；错的从来不是数，是**没记下量法**。

⇒ **教训不是「要更小心」。** 是两条，都写进代码里了：

  **① 口径必须写成可执行的定义串，不能是一句自然语言。**
     本文件每个数都带 `def`（人话定义）+ `how`（机械做法），并且能由机器复算：

         python -u backend/state/census.py                        现算 + 写 state.json
         python -u backend/state/census.py --print                只打印
         python -u backend/state/census.py --compare <基线.json>  逐项对比，不同则退出码 1

  **② ★ 用「正向的形状匹配」，不要用「反向的排除规则」。**
     那个 642 的错法就是排除规则写窄了：「路径组件 == `.orig` 即排除」——
     而快照目录的命名有**三种**约定，排除规则得逐个枚举，漏一个就错：
         `c006/.orig/before_slabunion_…/`      路径组件是 `.orig`      —— 顶层
         `c057/floors.orig_20260909_160037/`   `.orig_` 是**文件名后缀** —— 顶层
         `…/.orig/<标签>/floors.before_wallthin/`  `before_` 前缀，连 orig 都没有
                                               —— **嵌在 `.orig/` 里**，不在顶层
     ⇒ 本文件改成只认**一个形状**：`buildings/<栋>/floors/floorN.json`。
       形状匹配枚举的是「我要什么」，排除规则枚举的是「我不要什么」——
       后者永远追不上命名习惯的变化。**同类问题一律照此办理。**

口径纪律（**改本文件前先读这段**）：

  1. 交付层 = **正向形状匹配**（见 ②），不写排除规则。
  2. 快照目录**必须能被数出来**，不许"反正排除了就不管"——`snapshot_dirs` 就是这笔账。
  3. **一个事实有多个来源时，全部登记**，不许挑一个当唯一答案把别的藏起来。
     分歧本身就是答案，C1 判据拿它报红。
  4. **不许在这文件里写死任何数字。** 全部现算。
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")))
from paths import DATA, ROOT  # noqa: E402

#: ★ 手写。改了**分组 / 形状 / 量纲 / 门槛**就 +1 —— 跟语义走，不跟行数走。
#: 机械的那一半（本文件 sha256 前 12 位）在产物里，人忘改版本号时它还在。
CRITERION_VERSION = 2

BUILDINGS = DATA / "buildings"
STATE_PATH = DATA / "_meta" / "state.json"
ORIG = ".orig"


# ── 基础设施 ──────────────────────────────────────────────────────────

def _atomic_json(path: Path, payload: dict) -> None:
    """tmp + os.replace。直写会截成 0 字节（memory: atomic-artifact-write）。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=1)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _self_sha12() -> str:
    """本文件自己的 sha256 前 12 位 —— 产物要能说出是哪把尺子量的。"""
    try:
        return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()[:12]
    except OSError:
        return "unavailable"


def _walk(root: Path):
    for dirpath, _dirnames, filenames in os.walk(root):
        for fn in filenames:
            yield Path(dirpath) / fn


def _is_floor_json(p: Path) -> bool:
    return p.suffix == ".json" and p.name.startswith("floor")


def _building_dirs() -> list[Path]:
    if not BUILDINGS.is_dir():
        return []
    return sorted((p for p in BUILDINGS.iterdir() if p.is_dir()), key=lambda p: p.name)


def _load_json_list(path: Path):
    try:
        with path.open(encoding="utf-8") as fh:
            obj = json.load(fh)
    except (OSError, ValueError):
        return None
    return obj if isinstance(obj, list) else None


def _delivered_floors(b: Path) -> list[Path]:
    """★ 交付层：**只认 `buildings/<栋>/floors/floorN.json` 这一个形状**。

    正向匹配，不写排除规则 —— 原因见文件头 ②。
    """
    d = b / "floors"
    if not d.is_dir():
        return []
    return sorted(p for p in d.glob("floor*.json") if p.is_file())


def _snapshot_dirs(b: Path) -> list[Path]:
    """一栋楼里的**快照目录** —— 中间产物，必须数得出来，不许"排除了就不管"。

    已见三种命名约定（写在这里，一是让第四种出现时能被看见，二是别让注释骗人）：
        `.orig/`                    路径组件 —— 顶层，本函数看得见
        `floors.orig_<时间戳>/`      后缀带 `.orig_` —— 顶层，本函数看得见
        `floors.before_<标签>/`      前缀 `before_` —— **嵌在 `.orig/<标签>/` 里**，
                                   本函数看不见它，靠 `_walk` 计入 `orig_json_files`
    ⇒ 判据刻意放宽成「名字以 `floors.` 开头，或以 `.` 开头」——
      这样**第四种命名也会落进来**（落在快照账上，而不是消失）。
    """
    if not b.is_dir():
        return []
    out = [p for p in b.iterdir()
           if p.is_dir() and (p.name.startswith("floors.") or p.name.startswith("."))]
    return sorted(out)


def _count_rooms_in_floor_files(floor_files: list[Path]) -> int | None:
    """各层交付 `floorN.json` 里 `rooms` 数组长度之和（「全库几间房」的第二个口径）。

    读不动任何一份就返回 None —— **「量不到」不许冒充 0**。
    """
    total = 0
    for p in floor_files:
        try:
            with p.open(encoding="utf-8") as fh:
                obj = json.load(fh)
        except (OSError, ValueError):
            return None
        rooms = obj.get("rooms") if isinstance(obj, dict) else None
        if not isinstance(rooms, list):
            return None
        total += len(rooms)
    return total


# ── 口径 ──────────────────────────────────────────────────────────────

def compute() -> dict:
    bdirs = _building_dirs()
    per_building: dict[str, dict] = {}

    delivered: list[Path] = []
    under_orig: list[Path] = []
    suffix_orig: list[Path] = []
    snapdir_names: dict[str, int] = {}

    with_profile = with_rooms = rooms_total = 0
    with_recog = with_fast = 0
    orig_files = 0
    orig_bytes = 0

    for b in bdirs:
        rec: dict = {"name": b.name}

        prof = b / "profile.json"
        rec["has_profile"] = prof.is_file()
        with_profile += 1 if rec["has_profile"] else 0

        rooms = _load_json_list(b / "rooms.json")
        rec["rooms_in_rooms_json"] = len(rooms) if rooms is not None else None
        if rooms:
            with_rooms += 1
            rooms_total += len(rooms)

        d = _delivered_floors(b)
        rec["floors_delivered"] = len(d)
        delivered.extend(d)

        # 快照目录：逐个点名入账（这是「中间产物」的主账）
        snaps = _snapshot_dirs(b)
        rec["snapshot_dirs"] = {p.name: sum(1 for _ in _walk(p)) for p in snaps}
        for p in snaps:
            snapdir_names[p.name] = snapdir_names.get(p.name, 0) + 1
            for f in _walk(p):
                if f.suffix == ".json":
                    orig_files += 1
                try:
                    orig_bytes += f.stat().st_size
                except OSError:
                    pass
                if _is_floor_json(f):
                    # `.orig` 是路径组件 ⇒ 真备份层；`floors.orig_*` 只是后缀 ⇒ 另一档
                    if ORIG in p.parts:
                        under_orig.append(f)
                    else:
                        suffix_orig.append(f)

        rec["glb"] = [p.name for p in sorted(b.glob("*.glb"))]

        drec = b / "dxf_plan_recog"
        dfast = b / "dxf_plan_fast"
        rec["has_dxf_plan_recog"] = drec.is_dir() and any(drec.iterdir())
        rec["has_dxf_plan_fast"] = dfast.is_dir() and any(dfast.iterdir())
        with_recog += 1 if rec["has_dxf_plan_recog"] else 0
        with_fast += 1 if rec["has_dxf_plan_fast"] else 0

        per_building[b.name] = rec

    glb_in_buildings = [p for b in bdirs for p in sorted(b.glob("*.glb"))]
    glb_root = sorted(DATA.glob("*.glb"))
    lihua_floors = sorted((DATA / "floors").glob("floor*.json")) \
        if (DATA / "floors").is_dir() else []
    lihua_verify = sorted((DATA / "_verify_floors").glob("floor*.json")) \
        if (DATA / "_verify_floors").is_dir() else []

    n_deliv = len(delivered)
    n_under = len(under_orig)
    n_suffix = len(suffix_orig)

    def num(value, definition, how):
        return {"value": value, "def": definition, "how": how}

    counts = {
        "buildings_dirs": num(
            len(bdirs),
            "data/buildings/ 下的一级子目录数（含分片楼 f1/f2）",
            "iterdir + is_dir"),
        "with_profile": num(
            with_profile, "其中有 profile.json 的栋数", "is_file(profile.json)"),
        "with_rooms_nonempty": num(
            with_rooms, "其中 rooms.json 存在且数组非空的栋数",
            "json.load → isinstance(list) → len>0"),

        # ── 层：四档分开数，四档相加必须等于 floors_all（不一致就是又混口径了）──
        "floors_delivered": num(
            n_deliv,
            "★交付层：只认 buildings/<栋>/floors/floorN.json 这一个形状（正向匹配，不写排除规则）",
            "is_dir(floors) → glob(floor*.json)"),
        "floors_snapshot_orig_suffix": num(
            n_suffix,
            "★快照但**不带** .orig 路径组件：c057/floors.orig_<时间戳>/（`.orig_` 是文件名后缀）——上一版判据漏掉的就是这批",
            "snapshot_dirs 里 floor*.json，且路径无 .orig 组件"),
        "floors_under_orig_component": num(
            n_under,
            "备份层：路径**组件**含 .orig 的 floor*.json（含 .orig/<标签>/floors.before_*/ 各式）",
            "snapshot_dirs 里 floor*.json，且路径有 .orig 组件"),
        "floors_all_in_buildings": num(
            n_deliv + n_suffix + n_under,
            "上面三档之和 = data/buildings 下全部 floor*.json",
            "相加"),
        "floors_lihua_top_level": num(
            len(lihua_floors), "理化楼基线层：data/floors/floorN.json（不在 buildings/ 下）",
            "glob"),
        "floors_lihua_verify_copy": num(
            len(lihua_verify),
            "data/_verify_floors/floorN.json —— 与上一项是同一栋的两份副本",
            "glob"),

        "glb_delivered_in_buildings": num(
            len(glb_in_buildings), "buildings/<栋>/*.glb（本栋目录下）", "glob(*.glb)"),
        "glb_at_data_root": num(
            len(glb_root), "data/ 顶层的 *.glb（理化楼 + j6 两个）", "DATA.glob(*.glb)"),
        "glb_all": num(
            len(glb_in_buildings) + len(glb_root), "上面两项之和", "相加"),

        "rooms_total": num(
            rooms_total,
            "逐栋 rooms.json 的条目数之和（不含 lihua，它在 data/ 顶层）",
            "json.load → len"),
        "rooms_total_from_floors": num(
            _count_rooms_in_floor_files(delivered),
            "★第二个口径：各层交付 floorN.json 内 rooms 数组长度之和；量不到为 null",
            "逐份 floor*.json → len(obj['rooms'])"),

        "with_dxf_plan_recog": num(
            with_recog, "有非空 dxf_plan_recog/ 的栋数（识别后叠图）", "is_dir + 非空"),
        "with_dxf_plan_fast": num(
            with_fast, "有非空 dxf_plan_fast/ 的栋数", "is_dir + 非空"),

        # ── 中间产物的账 ──
        "snapshot_dirs": num(
            sum(snapdir_names.values()),
            "快照目录总数（.orig/ 与 floors.* 各式）—— 中间产物的主账",
            "iterdir + 名字以 'floors.' 或 '.' 开头"),
        "snapshot_dir_kinds": num(
            len(snapdir_names),
            "快照目录的**命名种类数**；出现第四种命名时这个数会变，用来发现新约定",
            "set(dirname) → len"),
        "orig_json_files": num(
            orig_files, "快照目录里的 .json 文件总数", "walk + 后缀 .json"),
        "orig_bytes": num(
            orig_bytes, "快照目录占用的字节数", "逐文件 stat().st_size 求和"),
    }

    return {
        "built_at": None,          # 由 main 填，让 compute() 本身是纯函数
        "criterion_version": CRITERION_VERSION,
        "source_sha256_12": _self_sha12(),
        "root": str(ROOT),
        "counts": counts,
        "snapshot_dir_names": dict(sorted(snapdir_names.items(),
                                         key=lambda kv: -kv[1])),
        "per_building": per_building,
    }


# ── 命令行（本仓惯例：手解析 sys.argv，不用 argparse）──────────────────

USAGE = """用法：
  python -u backend/state/census.py                  现算并写 data/_meta/state.json
  python -u backend/state/census.py --print          只打印到 stdout，不落盘
  python -u backend/state/census.py --compare <基线> 与基线逐项对比（不同则退出码 1）
  python -u backend/state/census.py --selftest       ①…⑤ 自检（含两条刑具）
"""

_KNOWN = ("--print", "--compare", "--selftest")


def selftest() -> int:
    """两把尺子对一次 + 两条刑具。

    ★ 为什么必须有这个。本文件的 456/12/1946/2414 是**逐栋 walk** 算的；
      而历史上同一个问题出现过 468、642 两个"也对"的答案 —— 它们不是算错的，
      是**别的尺子**量的。判据自己不会喊，所以这里把三把尺子摆在一起对质。

    两个 API 的行为**相反**（实测，Python 3.x）：
        pathlib.Path.glob('**/...')  **进** `.orig/` 这种点目录
        glob.glob('**/...')          **不进**
    ⇒ 任何人顺手把本文件里的 walk 换成 `glob.glob`，交付口径会当场少 1946
      而**不报任何错**。刑具 ③④ 就是钉住这件事的。
    """
    st = compute()
    c = st["counts"]

    def v(k: str):
        return c[k]["value"]

    import glob as _glob

    all_pathlib = len(list(BUILDINGS.glob("**/floor*.json")))
    all_globglob = len(_glob.glob(str(BUILDINGS / "**" / "floor*.json"),
                                  recursive=True))
    deliv_glob = len(list(BUILDINGS.glob("*/floors/floor*.json")))
    by_parent_name = len(list(BUILDINGS.glob("**/floors/floor*.json")))
    kinds = st["snapshot_dir_names"]

    checks = [
        ("① pathlib 全量 == 三档之和",
         all_pathlib == v("floors_all_in_buildings"),
         "%d == %d" % (all_pathlib, v("floors_all_in_buildings"))),
        ("② 交付层 == */floors/floor*.json 单次 glob",
         deliv_glob == v("floors_delivered"),
         "%d == %d" % (deliv_glob, v("floors_delivered"))),
        ("③ ★刑具：两个 glob API 在点目录上必须相反，且本文件站「进」的那边",
         all_pathlib != all_globglob
         and v("floors_all_in_buildings") == all_pathlib,
         "pathlib=%d  glob.glob=%d  差=%d（.orig 里的）"
         % (all_pathlib, all_globglob, all_pathlib - all_globglob)),
        ("④ ★刑具：按「父目录名叫 floors」的错口径必须 != 交付口径",
         by_parent_name != v("floors_delivered"),
         "错口径=%d  交付=%d  多出 %d（被吞进来的备份）"
         % (by_parent_name, v("floors_delivered"),
            by_parent_name - v("floors_delivered"))),
        ("⑤ 快照目录命名种类 <= 3（出现第四种约定要人看）",
         len(kinds) <= 3,
         "kinds=%d  %s" % (len(kinds), sorted(kinds)[:6])),
    ]

    ok = True
    for name, good, detail in checks:
        print("%s %-44s %s" % ("OK  " if good else "FAIL", name, detail))
        ok = ok and good
    print("\n--selftest %s" % ("全过 ①…⑤" if ok else "★ 有未通过项"))
    return 0 if ok else 1


def _print_table(state: dict) -> None:
    print("criterion_version=%s  source_sha256_12=%s  built_at=%s"
          % (state["criterion_version"], state["source_sha256_12"],
             state["built_at"]))
    print("%-28s %10s  %s" % ("口径", "值", "定义"))
    for k, v in state["counts"].items():
        val = "n/a" if v["value"] is None else str(v["value"])
        print("%-28s %10s  %s" % (k, val, v["def"]))


def _compare(base_path: Path, fresh: dict) -> int:
    """与基线逐项对比。★「搬完口径没变」这句话只有这里能证。"""
    try:
        with base_path.open(encoding="utf-8") as fh:
            base = json.load(fh)
    except (OSError, ValueError) as exc:
        print("读不到基线 %s：%s" % (base_path, exc))
        return 2
    b, f = base.get("counts", {}), fresh["counts"]
    diffs = []
    for k in sorted(set(b) | set(f)):
        bv = b.get(k, {}).get("value", "<缺>")
        fv = f.get(k, {}).get("value", "<缺>")
        if bv != fv:
            diffs.append((k, bv, fv))
    print("基线 %s  (criterion_version=%s, sha=%s)"
          % (base_path.name, base.get("criterion_version"),
             base.get("source_sha256_12")))
    print("现算 criterion_version=%s, sha=%s"
          % (fresh["criterion_version"], fresh["source_sha256_12"]))
    if not diffs:
        print("逐项相同：%d 项全部一致" % len(f))
        return 0
    print("★ 有 %d 项不同：" % len(diffs))
    print("  %-28s %10s %10s" % ("口径", "基线", "现算"))
    for k, bv, fv in diffs:
        print("  %-28s %10s %10s" % (k, bv, fv))
    return 1


def main(argv: list[str]) -> int:
    import datetime

    args = argv[1:]
    unknown = [a for a in args if a.startswith("-") and a not in _KNOWN]
    if unknown:
        print("不认识的参数：%s\n%s" % (" ".join(unknown), USAGE))
        return 2

    state = compute()
    state["built_at"] = datetime.datetime.now().isoformat(timespec="seconds")

    if "--selftest" in args:
        return selftest()


    if "--compare" in args:
        i = args.index("--compare")
        if i + 1 >= len(args):
            print("--compare 后面要给基线文件路径\n%s" % USAGE)
            return 2
        return _compare(Path(args[i + 1]), state)

    if "--print" in args:
        print(json.dumps({"counts": state["counts"]}, ensure_ascii=False, indent=1))
        return 0

    _atomic_json(STATE_PATH, state)
    _print_table(state)
    print("\n已写 %s" % STATE_PATH)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
