# -*- coding: utf-8 -*-
"""检查引擎的数据源 —— 注册表 / 逐栋产物 / 陈旧判据 / 跑一次并回读。

引擎在 `backend/checks/`（它自己就是「判据长在系统里」的产物：纯函数、无智能体也能跑）。
本模块是它在 HTTP 层的那一层——**只读产物、只调命令，不重写任何判据**。

## 读路径：只读产物，绝不现场算

逐栋产物落在 `data/_meta/checks/building-<楼>.json`（`runner.py` 原子写）。
读路径**不现跑**：A 层虽只读产物（秒级），但 B 层要 ezdxf/shapely + 读源 DXF、
逐栋起子进程，几十分钟的事，HTTP 请求等不起；而且只服务模式（服务器 venv 里
没有 ezdxf）现跑会直接 ImportError，逼着服务器装全套重依赖 —— 那条依赖层防线
（见 settings.py 的硬要求）就废了。

## 三态：产物不存在 / 陈旧 / 新鲜

「产物在不在」不等于「它的结论此刻还成不成立」。本项目反复栽在「汇总里看不出
没量过」（memory: gauge-coverage-invisible-in-summary），所以这里把三态分开报，
并且**把陈旧判据写进响应正文**（`staleness.criterion`），让人能自己复核 ——
后台不该替人下一个说不清来历的结论。

## 跑完必须回读产物

「命令返回 0」和「产物被写出来了」是两件事（CLAUDE.md 铁律 17 / 20），
所以 `run()` 跑完一定把产物读回来核对（`generated_unix` 不早于本次开始时刻、
`scope` 就是这一栋）。对不上就如实报失败，绝不回 200。

★ 另有一条极易读反的：**runner.py 的退出码 1 表示「有 GAP」，不是「运行失败」**
  （`main()` 用退出码表达结论：0 = 无 GAP，1 = 有 GAP，2 = 没有可检查的楼）。
  把 1 当失败报，会把「检查到缺陷」说成「检查没跑成」，正好说反。
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

from ..responses import ApiError, bad_request
from . import artifacts as A

# 产物目录：data/_meta/checks/（与 runner.py 的 OUT_REL 同一处）
CHECKS_SUBDIR = ("_meta", "checks")
# 判据源码目录：它比产物新 ⇒ 判据可能改过，旧结论未必还成立
ENGINE_SUBDIR = ("backend", "checks")

# 超时。★ 刻意**不**复用 cfg.job_timeout_s（7200s）：那是建模管道单阶段的时限，
# 拿它当 HTTP 请求的时限等于让一个请求挂两小时。这里按层给两档，
# 超时**真的终止子进程**并如实回 504 —— HTTP 请求不是作业队列，宁可报错不假装。
_LAYER_A_TIMEOUT_S = 300
_LAYER_B_TIMEOUT_S = 1800

# 回读核验时给时钟/落盘留的余量（generated_unix 是跑完那一刻写的，
# 理论上 ≥ 开始时刻；留 1 秒防止同秒内的比较误判）。
_FRESH_EPS_S = 1.0

# 陈旧判据的原文 —— 写进响应，调用方不必去读源码。
_CRITERION = (
    "比较「产物的生成时刻（generated_unix）」与「它据以算出的每一个输入的 mtime」："
    "只要有任一输入比产物新，就判 stale（产物是拿旧输入算的）。"
    "再比一遍判据源码（backend/checks/*.py）的 mtime：晚于产物 ⇒ 判据可能改过，"
    "旧结论未必还成立，单列为 engine_newer。"
    "能证明什么：能证明「陈旧」。证明不了什么：证明不了「新鲜 = 正确」——"
    "mtime 没动而内容变了（备份还原、带时间戳的拷贝、改完又改回去）判不出来，"
    "这正是 A5 拒绝用 mtime 判 GLB 陈旧的原因（memory: delivery-glb-content-staleness）。"
    "所以 fresh 的含义只是「没有任何输入比它新」，不等于「它此刻一定对」。"
    "产物里没有 generated_unix 时判不了年份 ⇒ 一律按陈旧处理，不给绿灯。"
)

_TIER_LABELS = {
    "A": "A 层：只要标准库（服务器上也能跑）",
    "B": "B 层：要 ezdxf/shapely 与源 DXF，逐栋起子进程",
}

# B 层的重依赖：只探测它的**存在**，绝不 import（见 dependencies()）
_HEAVY_DEPS = ("shapely", "ezdxf")

# 响应里回给调用方的 finding 字段白名单（**不回整个对象**，同 artifacts._PROFILE_OMIT 那条规矩）
_FINDING_KEYS = ("check", "title", "status", "detail", "floor", "measure",
                 "evidence", "blocked_by")
_REPORT_KEYS = ("scope", "verdict", "counts", "deliverable", "blockers",
                "findings", "meta", "generated_unix", "generated_iso", "heavy")

# 单飞锁：本进程同时只允许一个检查作业。
_RUN_LOCK = threading.Lock()
_RUN_STATE: dict[str, Any] = {}


# ── 懒加载引擎 ────────────────────────────────────────────────────────

def _engine():
    """把检查引擎 import 进来 —— **函数内 import，不是模块级**。

    两条理由：① 只服务模式下万一 `backend/checks/` 不在或坏了，倒下的应当是
    `/api/checks` 这几条路由，而不是整个 API 起不来；② 别在 API 进程启动时
    就把引擎的依赖面拉进来（引擎自己会拉起子进程跑 qa_structural，那是重活）。
    仓库根塞进 sys.path 是 runner.py 自己的做法（它没有 backend/__init__.py）。
    """
    root = str(Path(__file__).resolve().parents[3])
    if root not in sys.path:
        sys.path.insert(0, root)
    from backend.checks import CHECK_REGISTRY, layout, sources
    return CHECK_REGISTRY, layout, sources


# ── 注册表与本机可跑性 ────────────────────────────────────────────────

def dependencies(cfg) -> dict:
    """B 层在这台机器上跑不跑得动 —— 只**探测**，不 import。

    ★ 用标准库的 `importlib.util.find_spec`（只找位置，不执行模块）而不是真 import：
      本服务是只读优先的，把 ezdxf 拉进 API 进程就等于把那条依赖层防线拆了。
    ★ 而 find_spec **只证明「找得到」**，不证明「import 得成」—— 本仓有过
      预编译二进制与服务器 libstdc++ 不匹配的先例（memory: server-native-module-glibcxx）。
      所以真正的裁判是 B 层自己报的 UNAVAILABLE，不是这里的布尔值。
    """
    def _has(mod: str) -> bool:
        try:
            return importlib.util.find_spec(mod) is not None
        except (ImportError, ValueError):
            return False

    deps = {m: _has(m) for m in _HEAVY_DEPS}
    return {
        "heavy_deps": deps,
        "heavy_ready": all(deps.values()) and cfg.compute and bool(cfg.dxf_dir),
        "compute": cfg.compute,
        "dxf_dir_configured": bool(cfg.dxf_dir),
        "method": "importlib.util.find_spec（不做真实 import：只服务模式不许把 ezdxf 拉进本进程）",
        "caveat": "find_spec 只证明找得到，不证明 import 得成（本仓有过预编译二进制与 "
                  "libstdc++ 不匹配的先例）。真裁判是 B 层自己报的 UNAVAILABLE。",
    }


def registry(cfg) -> dict:
    """这台机器能跑哪几条检查。**直接取 CHECK_REGISTRY，这里不另留一份清单。**

    顺序就按注册表的书写顺序（源码里本来就是 A 层在前、B 层在后）——
    另写一个排序函数就是同一个判断的第二份实现（memory:
    one-judgement-many-implementations）。
    """
    check_registry, _layout, _sources = _engine()
    deps = dependencies(cfg)
    checks = []
    for cid, meta in check_registry.items():
        title, tier, per_building, why = meta
        blocked = _blocked_reason(cfg, deps, tier)
        checks.append({
            "id": cid,
            "title": title,
            "tier": tier,
            "tier_label": _TIER_LABELS.get(tier, tier),
            "per_building": bool(per_building),
            "why": why,
            "heavy_required": tier == "B",
            "runnable_today": blocked is None,
            "blocked_by": blocked,
        })
    return {
        "checks": checks,
        "dependencies": deps,
        "read": {
            "endpoint": "GET /api/checks/{building}",
            "states": ["fresh", "stale"],
            "missing": "产物不存在时回 404 check_artifact_missing"
                       "（与「没有这栋楼」的 not_found 是两个码，别混）",
        },
        "run": {
            "endpoint": "POST /api/checks/{building}/run",
            "mode": "同步 + 超时（本仓没有作业队列，不假装有）",
            "layer_a_timeout_s": _LAYER_A_TIMEOUT_S,
            "layer_b_timeout_s": _LAYER_B_TIMEOUT_S,
            "concurrency": "单飞：已有作业在跑时**立刻回 409 check_running**，"
                           "不排队、不静默等待 ——「正在跑」是要报出来的状态，不是可以藏起来的等待",
            "on_timeout": "超时**真的终止子进程**，产物不会写成；端点回 504 并明说产物没写出来",
        },
    }


def _blocked_reason(cfg, deps: dict, tier: str) -> str | None:
    """这条检查今天跑不动的话，卡在哪。A 层永远 None（只要标准库）。"""
    if tier != "B":
        return None
    missing = sorted(m for m, ok in deps["heavy_deps"].items() if not ok)
    if missing:
        return "本机找不到 %s" % "、".join(missing)
    if not cfg.compute:
        return "本进程 compute=0（只读）：B 层要起子进程、要写产物"
    if not cfg.dxf_dir:
        return "未配置 GYM3D_DXF_DIR：B 层要读源 DXF"
    return None


# ── 产物路径 ──────────────────────────────────────────────────────────

def artifact_name(name: str) -> str:
    return "building-%s.json" % name


def artifact_dir(cfg) -> Path:
    """**读侧**的产物目录：跟随 GYM3D_DATA_DIR（与其余所有路由一致）。"""
    return cfg.resolved_data_dir.joinpath(*CHECKS_SUBDIR)


def runner_artifact_path(cfg, name: str) -> Path:
    """**写侧**的产物路径 —— runner.py 里 `DATA_DIR` 是**写死的** `<仓库根>/data`，
    不走 settings。所以「跑完落在哪」只有这一处是真话，回读必须按它读。
    """
    return cfg.root.joinpath("data", *CHECKS_SUBDIR, artifact_name(name))


def config_mismatch(cfg) -> bool:
    """读写侧目录是否分了叉（配了 GYM3D_DATA_DIR 且不是 <根>/data 就会分叉）。

    分叉时：POST 跑完写的是 A 处，GET 读的是 B 处 —— 两边都不报错，只是互相看不见。
    这正是本仓「两处写同一个数，一致证明不了它对」那一族（铁律 18），所以要说出来。
    """
    return cfg.resolved_data_dir.resolve() != (cfg.root / "data").resolve()


# ── 产物清单 ──────────────────────────────────────────────────────────

# artifact_name 的模板。用占位符**反推**前后缀，而不是在这里把
# "building-" / ".json" 再写一遍 —— 两处各写一份，改了一处就是静默错配（铁律 18）。
_NAME_PROBE = "__NAME__"


def artifact_name_inverse(filename: str) -> str | None:
    """`building-c113.json` → `c113`；认不出来的返回 None（**不猜**）。"""
    probe = artifact_name(_NAME_PROBE)
    pre, _, suf = probe.partition(_NAME_PROBE)
    if not filename.startswith(pre) or not filename.endswith(suf):
        return None
    inner = filename[len(pre):len(filename) - len(suf)]
    return inner or None


def manifest(cfg) -> dict:
    """哪几栋楼**已经有**检查产物。

    存在的理由只有一个：调用方要能先知道"该问谁"，而不是对全库逐栋撞一次
    404。本仓实测 95 栋里只有个位数有产物 —— 逐栋去问等于往浏览器 console
    里灌几十条 404 红字，而红字多了就会训练人忽略真错误。

    ★ 读的是 `artifact_dir(cfg)` —— 与 `read_artifact` **同一个目录**。
      这里若另走一条路径推导，清单就会和实际 GET 的可见范围分叉：清单说"有"、
      GET 回 404，或者反过来。分叉不报错，只是两句话对不上（铁律 18）。
    """
    d = artifact_dir(cfg)
    have: list[str] = []
    other: list[str] = []
    fleet_file = fleet_artifact_name()
    has_fleet = False
    if d.is_dir():
        for p in sorted(d.iterdir()):
            if not p.is_file():
                continue
            if p.name.startswith("."):     # 原子写的中间件/编辑器临时文件
                continue
            if p.name == fleet_file:
                # ★ 这一份**单独说**，不混进"认不出来的文件"里 —— 系统认识它，
                #   把它列进 unrecognized 会读成"有个谁也不知道是什么的文件"。
                has_fleet = True
                continue
            name = artifact_name_inverse(p.name)
            (have if name else other).append(name or p.name)
    have.sort()
    return {
        "buildings": have,
        "count": len(have),
        # 全库级那一份在不在。它覆盖全库，分母与逐栋那份**不一样**，要分开说。
        "fleet": has_fleet,
        "fleet_file": fleet_file,
        # 真认不出来的文件名**列出来**，不静默丢 —— 本仓的"默默扔掉"都是这么来的
        # （outline.py 静默回退、vectorize 静默算 0 个，都是这一族）。
        "unrecognized": other,
        "dir": "/".join(("data", *CHECKS_SUBDIR)),
        # 读写侧分叉时说清楚：清单读的是 B 处，而 POST 跑完写的是 A 处。
        "config_mismatch": config_mismatch(cfg),
    }


# ── 读产物 ────────────────────────────────────────────────────────────

# 全库级产物的 scope 名。runner.py 落盘写的是 `"%s.json" % scope`，scope 取 "fleet"
# —— 所以这里**从同一个词拼出来**，不在两处各写一遍 "fleet.json"（铁律 18）。
FLEET_SCOPE = "fleet"


def fleet_artifact_name() -> str:
    return "%s.json" % FLEET_SCOPE


def _load_checked(cfg, p: Path, want_scope: str, what: str,
                  how_to_make_it: str) -> tuple[dict, os.stat_result]:
    """读一份检查产物并把三种失败分开报：不在 / 读不了 / 内容是别人的。

    ★ 三种必须分开（本仓反复栽的那条「量具坏了和被测量对象是空的长得一样」）：
      · 文件不在        ⇒ 404 check_artifact_missing（"还没跑过"）
      · 文件在但读不了  ⇒ 500 check_artifact_corrupt（"跑了但产物坏了"）
      · scope 对不上    ⇒ 500 check_artifact_mismatch（拷贝/改名留下的错件）
    """
    if not p.is_file():
        detail: dict[str, Any] = {
            "artifact_file": p.name,
            "expected_dir": "/".join(("data", *CHECKS_SUBDIR)),
            "how_to_make_it": how_to_make_it,
        }
        if config_mismatch(cfg):
            detail["config_mismatch"] = (
                "本进程的 data 目录被配成了 %s，而检查产物默认落在 <仓库根>/data —— "
                "两处不一致时，跑出来的产物这个 GET 看不见" % cfg.resolved_data_dir.name)
        raise ApiError(404, "check_artifact_missing",
                       "%s还没有检查报告产物：%s" % (what, p.name), detail)
    payload = A.read_json(p)
    if not isinstance(payload, dict):
        raise ApiError(500, "check_artifact_corrupt",
                       "检查产物不是对象：%s" % p.name, {"file": p.name})
    scope = payload.get("scope")
    if scope != want_scope:
        # 文件名对得上但内容是别的（拷贝/改名留下的）⇒ 明确报，不冒充。
        raise ApiError(500, "check_artifact_mismatch",
                       "产物里的 scope 与文件名不符：%r（应为 %r）" % (scope, want_scope),
                       {"file": p.name, "scope": scope, "expected_scope": want_scope})
    return payload, p.stat()


def read_artifact(cfg, name: str) -> tuple[dict, os.stat_result]:
    """读一栋楼的检查产物。产物不存在 ⇒ 404 check_artifact_missing —— 这个码
    与「没有这栋楼」（not_found）分开，调用方才分得清「这栋楼没有报告」
    和「压根没有这栋楼」。
    """
    return _load_checked(
        cfg, artifact_dir(cfg) / artifact_name(name),
        "building:%s" % name, name,
        "POST /api/checks/%s/run？heavy=false 只跑 A 层；"
        "要 B 层加 heavy=true（本机需 ezdxf/shapely + 源 DXF）" % name)


def read_fleet(cfg) -> tuple[dict, os.stat_result]:
    """读**全库级**产物（fleet.json）—— 这是检查引擎对整个库的那一次结论。

    ★ 为什么单栋墙之外还要有这一份：墙是按楼各取一次产物再数出来的，**分母是
      "有产物的那几栋"**；而 fleet.json 的分母是**全库**。两个分母不同的数摆在
      同一屏上，若不明说各自的分母，就会被读成同一个数（本仓栽过多次）。
    ★ 它是 runner.py 跑 `len(names) > 1` 那条路时落盘的；逐栋跑**不会**生成它。
    """
    return _load_checked(
        cfg, artifact_dir(cfg) / fleet_artifact_name(),
        FLEET_SCOPE, "全库",
        "python -m backend.checks.runner（不传楼号即全库；不传 --heavy 只跑 A 层）")


def public_report(payload: dict) -> dict:
    """白名单投影 —— **不回整个对象**（同 artifacts._PROFILE_OMIT 的规矩）。

    ★ 关于「报告里带楼栋编号与房间号」：产物里**没有坐标**（几何不进证据，
      B1 的 pos 是 null），房间号本来就是这份报告要说的事。
      B3 的证据里夹着图纸文字摘录（面积 / 名称），而那正是
      `/api/buildings/{name}/rooms` 那条路由回的同一份抽取结果的另一种写法 ——
      两条路由**同一把门禁**（本仓没有「模块白名单」这一层，都只是 SettingsDep）。
      所以这里不是新开一条读取面：要按号取名字，走 rooms 那条。
      这里做的是**只挑已知字段**，不是把产物原样透传（防产物被塞了别的东西）。
    ★ `by_floor` 不在这里回：它和 `findings` 是同一批内容，只是按层重排，
      调用方按 finding.floor 自己分一次就是（省一半字节，且不会两份不一致）。
    """
    rep = {k: payload[k] for k in _REPORT_KEYS if k in payload}
    rep["findings"] = [{k: f[k] for k in _FINDING_KEYS if k in f}
                       for f in (payload.get("findings") or [])]
    return rep


def omitted_fields() -> list[dict]:
    return [{"field": "by_floor",
             "why": "与 findings 同内容，只是按层重排；调用方按 finding.floor 自行分组"}]


# ── 陈旧判据 ──────────────────────────────────────────────────────────

def _iso(ts: float | None) -> str | None:
    if ts is None:
        return None
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts))


def _row(path: Path, rel: str, label: str, **extra) -> dict:
    """一个输入文件的指纹。**只回相对路径**：回绝对路径等于把本机目录结构写进响应
    （artifacts._PROFILE_OMIT 丢掉 profile 里的 dxf / out_dir 就是这个道理）。"""
    try:
        st = path.stat()
    except OSError:
        return {"label": label, "file": rel, "exists": False, "mtime": None,
                "mtime_iso": None, **extra}
    return {"label": label, "file": rel, "exists": True, "mtime": st.st_mtime,
            "mtime_iso": _iso(st.st_mtime), "bytes": st.st_size, **extra}


def _inputs(cfg, name: str) -> list[dict]:
    """这份产物据以算出来的输入清单 —— 陈旧判据的被比较对象。

    就是引擎真正读的那几份：本栋的 profile / rooms / spec / 逐层 floors，
    加 A2/A7 的裁判（`data/_meta/area_audit_detail.json`，引擎自己产出的图纸明细），
    以及 B 层要读的源 DXF（只在 profile 里记着、只在本机有）。
    """
    _, layout, sources = _engine()
    dd = cfg.resolved_data_dir
    bdir = dd / "buildings" / name
    out = [
        _row(bdir / "profile.json", "buildings/%s/profile.json" % name, "识别参数 profile.json"),
        _row(bdir / "rooms.json", "buildings/%s/rooms.json" % name, "房间台账 rooms.json"),
        _row(bdir / "spec.json", "buildings/%s/spec.json" % name, "建模规格 spec.json"),
    ]

    # 逐层几何：最多十几份，压成一行（回 100 行文件清单只会把真正的差异淹掉）。
    floors = [(F, p) for F, p in layout.floor_files(dd, name) if p.is_file()]
    if floors:
        newest_F, newest_p = max(floors, key=lambda kv: kv[1].stat().st_mtime)
        st = newest_p.stat()
        out.append({"label": "交付逐层几何", "file": "buildings/%s/floors/floor*.json" % name,
                    "exists": True, "count": len(floors),
                    "newest_file": newest_p.name, "newest_floor": newest_F,
                    "mtime": st.st_mtime, "mtime_iso": _iso(st.st_mtime)})
    else:
        out.append({"label": "交付逐层几何",
                    "file": "buildings/%s/floors/floor*.json" % name,
                    "exists": False, "count": 0, "mtime": None, "mtime_iso": None})

    # 引擎自产的外部裁判（A2 的图纸房间数、A7 的图纸建筑面积都取自它）。
    # ★ 路径问引擎自己（sources.detail_path），不在这里再拼一份 —— 两份路径
    #   迟早会有一份跟不上（memory: one-judgement-many-implementations）。
    detail = sources.detail_path(dd)
    out.append(_row(detail, "data/_meta/" + detail.name, "图纸逐层明细（A2/A7 的裁判）"))

    # 源 DXF：路径在 profile 里，只本机有。★ 只回文件名，不回路径。
    try:
        prof = json.loads((bdir / "profile.json").read_text(encoding="utf-8"))
        raw = prof.get("dxf") if isinstance(prof, dict) else None
    except (OSError, ValueError):
        raw = None
    if raw:
        p = Path(raw)
        out.append(_row(p, p.name, "源 DXF（B 层读）"))
    return out


def _engine_files(cfg) -> list[dict]:
    """判据源码的 mtime —— 改了判据，旧结论未必还成立。
    ★ 这条是有来历的：只按输入指纹去重会让「判据变了但结论不更新」（memory:
      cache-key-must-cover-the-judge）。所以判据自己也要进比较。
    """
    d = cfg.root.joinpath(*ENGINE_SUBDIR)
    if not d.is_dir():
        return []
    return [{"file": "%s/%s" % ("/".join(ENGINE_SUBDIR), p.name),
             "mtime": p.stat().st_mtime, "mtime_iso": _iso(p.stat().st_mtime)}
            for p in sorted(d.glob("*.py")) if p.is_file()]


def staleness(cfg, name: str, payload: dict, stat: os.stat_result) -> dict:
    """产物是三态里的哪一态，以及**凭什么这么判**。"""
    gen = payload.get("generated_unix")
    gen_ok = isinstance(gen, (int, float))
    inputs = _inputs(cfg, name)
    engine = _engine_files(cfg)

    newer = [r for r in inputs if gen_ok and r["mtime"] is not None and r["mtime"] > gen]
    eng_newer = [r for r in engine if gen_ok and r["mtime"] > gen]
    missing = [r for r in inputs if not r["exists"]]

    reasons: list[dict] = []
    if not gen_ok:
        reasons.append({"kind": "no_timestamp",
                        "why": "产物里没有可用的 generated_unix —— 判不出它是何时算的，"
                               "按陈旧处理（不给绿灯）"})
    for r in newer:
        reasons.append({"kind": "input_newer",
                        "why": "输入 %s 比产物新 %s" % (r["file"], _age(gen, r["mtime"]))})
    for r in eng_newer:
        reasons.append({"kind": "engine_newer",
                        "why": "判据源码 %s 比产物新 %s —— 判据改过，旧结论未必还成立"
                               % (r["file"], _age(gen, r["mtime"]))})

    warnings: list[dict] = []
    if missing:
        warnings.append({
            "kind": "input_missing",
            "why": "有输入当前不在盘上：%s。产物可能是它还在的时候算的，也可能是它缺失时"
                   "算的 —— 这一条判据当时到底量到了什么，看报告里对应的 unavailable 结论"
                   % "、".join(r["file"] for r in missing),
        })
    if not payload.get("heavy"):
        warnings.append({
            "kind": "layer_a_only",
            "why": "这份产物只跑了 A 层（heavy=false），B 层那一轮**没跑**"
                   "（报告里对应的是 unavailable，不是 pass）。要 B 层结论得 POST …/run？heavy=true",
        })
    if config_mismatch(cfg):
        warnings.append({
            "kind": "config_mismatch",
            "why": "本进程的 data 目录（%s）与检查产物的默认落盘处（<仓库根>/data）不是一处："
                   "跑出来的新产物这个 GET 可能看不见" % cfg.resolved_data_dir.name,
        })

    return {
        "state": "stale" if reasons else "fresh",
        "criterion": _CRITERION,
        "report_generated_unix": gen if gen_ok else None,
        "report_generated_iso": payload.get("generated_iso"),
        "artifact_mtime_iso": _iso(stat.st_mtime),
        "inputs": inputs,
        "engine": {
            "dir": "/".join(ENGINE_SUBDIR),
            "files": len(engine),
            "newer_than_report": [r["file"] for r in eng_newer],
            "note": "判据源码改了 ⇒ 这份产物是旧判据算的。注意：git checkout / 重新克隆会把 "
                    "所有文件 mtime 刷成当前时刻，那种情况下这一栏会集体报新，属于已知噪声。",
        },
        "reasons": reasons,
        "warnings": warnings,
    }


def _age(ref: float, ts: float) -> str:
    d = ts - ref
    if d < 90:
        return "%.0f 秒" % d
    if d < 5400:
        return "%.1f 分钟" % (d / 60.0)
    if d < 172800:
        return "%.1f 小时" % (d / 3600.0)
    return "%.1f 天" % (d / 86400.0)


# ── 跑一次（写操作，已过 compute 门禁）────────────────────────────────

def run(cfg, name: str, heavy: bool = False) -> dict:
    """跑一次并**回读产物**确认它真的被写出来了。

    单飞：本进程同时只允许一个检查作业，第二个请求**立刻回 409**，不排队。
    （本仓 PM2 是 instances:1，所以这把进程内的锁就是全局的；哪天真起了多实例，
      它只挡得住一半 —— 那时要换跨进程的锁，别让它悄悄失效。）
    """
    if name.startswith("-"):
        # ★ runner.py 用 sys.argv 手解析，`-` 开头的**位置参数会被它当成开关**
        #   （CLAUDE.md 铁律 9：--help 被当楼名或忽略 / 未知开关直接退出）。
        #   BuildingName 的 pattern 允许短横线开头，所以这里再挡一道。
        raise bad_request("楼号不许以短横线开头（会被命令行解析成开关）：%r" % name,
                          building=name)

    if not _RUN_LOCK.acquire(blocking=False):
        info = dict(_RUN_STATE)
        raise ApiError(409, "check_running",
                       "已有一个检查作业在跑（%s），本端点不排队、不静默等待"
                       % info.get("building"),
                       {"running": info, "hint": "稍后重试；或直接看它跑完后 GET 产物"})
    try:
        return _run_locked(cfg, name, heavy)
    finally:
        _RUN_STATE.clear()
        _RUN_LOCK.release()


def _run_locked(cfg, name: str, heavy: bool) -> dict:
    _engine()   # 先确认引擎 import 得动：坏在这里就报得清楚，别等子进程吐 stderr
    script = cfg.root.joinpath(*ENGINE_SUBDIR) / "runner.py"
    if not script.is_file():
        raise ApiError(500, "checks_engine_missing",
                       "找不到检查引擎入口：%s" % "/".join(ENGINE_SUBDIR + ("runner.py",)))

    layer = "A+B" if heavy else "A"
    timeout_s = _LAYER_B_TIMEOUT_S if heavy else _LAYER_A_TIMEOUT_S
    started = time.time()
    _RUN_STATE.update({"building": name, "layer": layer, "heavy": heavy,
                       "started_unix": started, "started_iso": _iso(started)})

    out_path = runner_artifact_path(cfg, name)     # 写侧路径（runner 里 data 是写死的）
    before = _mtime_ns(out_path)

    argv = [sys.executable, "-u", str(script), name, "--quiet"]
    if heavy:
        argv.append("--heavy")
    env = dict(os.environ, PYTHONIOENCODING="utf-8")   # 不然中文日志变糊字（memory: gbk-mangled-log-units）
    try:
        # capture_output 由 communicate() 抽干，不会出「管道写满卡死」那种死锁
        # （CLAUDE.md 铁律 14）。encoding=utf-8 同上。
        p = subprocess.run(argv, cwd=str(cfg.root), env=env, timeout=timeout_s,
                           capture_output=True, encoding="utf-8", errors="replace")
    except subprocess.TimeoutExpired as ex:
        raise ApiError(504, "check_timeout",
                       "检查超时（%ds，%s 层）——子进程已被终止，**产物没有写成**。"
                       "要跑完请用命令行：python -u backend/checks/runner.py %s%s"
                       % (timeout_s, layer, name, " --heavy" if heavy else ""),
                       {"building": name, "layer": layer, "timeout_s": timeout_s,
                        "killed": True, "artifact_written": False,
                        "stdout_tail": _tail(ex.stdout), "stderr_tail": _tail(ex.stderr),
                        "note": "被终止的是 runner 子进程；B 层还会再起一层孙进程"
                                "（qa_structural 等），极端情况下它可能仍在收尾"}) from None
    duration = time.time() - started

    # ── 回读：以**产物**为准，「命令返回 0」不作数 ──────────────────
    verified, payload = _verify(out_path, name, started, before)
    if not verified:
        raise ApiError(500, "artifact_not_confirmed",
                       "命令跑完了，但产物没能被确认写成 —— 不当成功报",
                       {"building": name, "exit_code": p.returncode,
                        "artifact_file": out_path.name,
                        "artifact_exists": out_path.is_file(),
                        "artifact_mtime_before_iso": _iso(_ns_to_s(before)),
                        "artifact_mtime_after_iso": _iso(_mtime_s(out_path)),
                        "artifact_scope": (payload or {}).get("scope"),
                        "artifact_generated_iso": (payload or {}).get("generated_iso"),
                        "stdout_tail": _tail(p.stdout), "stderr_tail": _tail(p.stderr)})

    warnings: list[dict] = []
    if p.returncode not in (0, 1):
        warnings.append({
            "kind": "odd_exit_code",
            "why": "退出码 %d 不在 {0,1} 里（0 = 无 GAP，1 = 有 GAP），但产物已按本次运行写回 —— "
                   "两处不一致，先别拿退出码当结论" % p.returncode,
        })
    if config_mismatch(cfg):
        warnings.append({
            "kind": "config_mismatch",
            "why": "产物写到了 <仓库根>/data，而本进程读侧配的是 %s —— 这个 POST 回的是刚写的产物，"
                   "但随后的 GET 可能看不见它" % cfg.resolved_data_dir.name,
        })

    return {
        "building": name,
        "layer": layer,
        "heavy": heavy,
        "exit_code": p.returncode,
        "exit_code_meaning": ("0 = 未发现 GAP（不是「一切正常」，看结论里的 unavailable）"
                              if p.returncode == 0
                              else "1 = **检查到 GAP** —— 注意这不是运行失败，"
                                   "引擎用退出码表达结论"),
        "duration_s": round(duration, 2),
        "timeout_s": timeout_s,
        "artifact": {
            "file": out_path.name,
            "bytes": out_path.stat().st_size,
            "mtime_before_iso": _iso(_ns_to_s(before)),
            "mtime_after_iso": _iso(_mtime_s(out_path)),
            "rewritten_by_this_run": before != _mtime_ns(out_path),
            "generated_iso": payload.get("generated_iso"),
            "generated_unix": payload.get("generated_unix"),
        },
        "verified": {
            "ok": True,
            "method": "回读产物并核对：generated_unix ≥ 本次开始时刻、scope == building:<楼号>",
            "scope": payload.get("scope"),
        },
        "report": public_report(payload),
        "staleness": staleness(cfg, name, payload, out_path.stat()),
        "warnings": warnings,
    }


def _verify(out_path: Path, name: str, started: float,
            before: int | None) -> tuple[bool, dict | None]:
    """产物真的被这次运行写出来了吗。

    看三样，缺一不可：文件在、scope 就是这栋、generated_unix 不早于本次开始时刻。
    只用「文件在」不够（上一轮的旧产物也在）；只用退出码也不够（见模块头的说明）。
    """
    if not out_path.is_file():
        return False, None
    try:
        payload = json.loads(out_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False, None
    if not isinstance(payload, dict):
        return False, None
    gen = payload.get("generated_unix")
    if not isinstance(gen, (int, float)):
        return False, payload
    if payload.get("scope") != "building:%s" % name:
        return False, payload
    if gen < started - _FRESH_EPS_S:
        return False, payload
    return True, payload


def _mtime_ns(p: Path) -> int | None:
    try:
        return p.stat().st_mtime_ns
    except OSError:
        return None


def _mtime_s(p: Path) -> float | None:
    try:
        return p.stat().st_mtime
    except OSError:
        return None


def _ns_to_s(ns: int | None) -> float | None:
    return None if ns is None else ns / 1e9


def _tail(s: Any, n: int = 2000) -> str:
    """子进程输出的尾巴。中文经 utf-8 解码后按**字符**截 —— 不按字节，
    免得把一个汉字劈成两半（屏幕上就是乱码）。"""
    if not s:
        return ""
    # subprocess.run 传了 encoding 时是 str；但它被 timeout 打断的那条路上
    # 拿到的可能是原始 bytes，bytes 进 JSON 会直接炸 —— 这里收口成 str。
    if isinstance(s, (bytes, bytearray)):
        s = bytes(s).decode("utf-8", "replace")
    return str(s)[-n:]
