# -*- coding: utf-8 -*-
"""把控制台元数据冻结成静态产物 data/_meta/console_meta.json。

为什么必须冻结（Phase 1 关键交付）
--------------------------------
`/api/meta` 是控制台首屏第一个请求，而 `console_meta.spec_defaults()` 在调用期
`import build_standard_glb` → 拖进 trimesh / numpy / mapbox_earcut / shapely。
服务器 venv 刻意**不装**这些重依赖（「只服务」模式的依赖层防线），于是：

    compute=1 的开发机   → 实时求值没问题
    compute=0 的服务器   → 不冻结必然 500，前端白屏

所以在本机（唯一有全套依赖的地方）把这份元数据求值一次、落成 JSON，
服务器只读文件。`specDefaults` 仍是**从建模层问出来的**，不是复制一份，
不会漂移 —— 冻结的是「快照」，不是「副本」。

构建期门禁
----------
**升级为致命的只有「结构性」那几类**：规格键对不上、可跑阶段缺 argv、
specDefaults 是空占位、冻结那份与活那份的键不一致、selfCheck 没带上。
结构性不合格的产物不该被发到服务器。

`console_meta.self_check()` 的那些**信息性告警**（死键 / 潜伏 / 非识别通道）
**只印、不拦** —— 它们在**生产代码里本来就是非致命的**，而且被有意设计成
「进了 `/api/meta`、在页面上给用户看」的一栏数据（见
`console_meta.self_check_report` 的 docstring），不是构建失败。

★ 2026-10-02 实测：改前第 1 步把 self_check 的**全部**告警并进 problems ⇒
  只要有一条死键就永远写不出产物。而产物里**连 selfCheck 这一栏都没有**
  （它冻结于那一栏上线之前）⇒ 这道闸从上线起**一次都没放行过**，服务器一直
  跑 2026-09-11 的载荷，C6「冻结载荷的出身」因此长期 gap。
  「产物不合格就别发」这个好意图，被过宽的作用域变成了「合格的产物也永远
  发不出去」（本仓铁律 162：闸的作用域在动作到达之前不可见）。

用法
----
    python freeze_meta.py            # 生成/刷新 data/_meta/console_meta.json
    python freeze_meta.py --check    # 只校验，不写文件（CI/提交前用）
"""
import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone

DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(DIR, "backend"))            # paths.py
sys.path.insert(0, os.path.join(DIR, "backend", "web"))     # console_meta.py
sys.path.insert(0, os.path.join(DIR, "backend", "modeling"))  # build_standard_glb（spec_defaults 用）
sys.path.insert(0, DIR)                                     # 仓库根
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from paths import DATA  # noqa: E402

OUT = DATA / "_meta" / "console_meta.json"
SOURCE = os.path.join(DIR, "backend", "web", "console_meta.py")

# 建模层消费但不属于 SPEC_GROUPS 的键（self_check 的口径，见 console_meta.py:330）
EXTRA_REAL_KEYS = {"style", "roofType"}


def build_payload():
    """求值出与 GET /api/meta 的 data 字段完全一致的对象。

    ★ 「完全一致」这句话以前**没有人量过**：两边各手抄一份 6 键字典，
      漏一个字段是不报错的 —— 页面上「本来就没有」与「这份没带」同形（铁律 16）。
      现在 `gate()` 里有一条判据拿 `META_PAYLOAD_KEYS`（声明的唯一出处）逐键核。
    """
    import console_meta

    return {
        "profile": console_meta.PROFILE_GROUPS,
        "spec": console_meta.SPEC_GROUPS,
        "styleKeys": console_meta.STYLE_KEYS,
        "pipeline": console_meta.PIPELINE,
        "specDefaults": console_meta.spec_defaults(),
        "runnable": console_meta.runnable_ids(),
        # ★ 用**不缓存**的 `self_check_report()`：这一趟就是「此刻」，
        #   冻结进产物的读数必须带自己的时刻与来路（`stamp_self_check` 盖章），
        #   读这份 JSON 的人才知道它有多旧。计数器恒为 1（本进程只算这一次）。
        "selfCheck": console_meta.stamp_self_check(
            console_meta.self_check_report(),
            "构建期冻结（freeze_meta.py 跑的那一趟，此后不再变）", 1),
    }


def payload_key_mismatch(payload):
    """核 `build_payload()` 与活的那份（`meta_source._live()`）是不是同一组键。

    判据来源是 `meta_source.META_PAYLOAD_KEYS` —— **声明**，不是把活那份跑一遍
    （跑 `_live()` 要拖进建模层、还要读 96 栋的 profile.json，构建期再跑一遍纯浪费；
      而且要核的是「键集」，不是「值」）。

    ★ 为什么值得一条判据：这两份载荷各手抄一遍，**漏键不报错**；
      而它们服务的是同一张页面（开发机走活的、服务器走冻结），
      差异只在**部署到服务器之后**才显现 —— 那正是最不容易当场发现的场合。
    """
    try:
        sys.path.insert(0, os.path.join(DIR, "backend"))
        from api.services.meta_source import META_PAYLOAD_KEYS
    except Exception as exc:  # noqa: BLE001 — 核不了就要说出来，不许静默放行
        return ["无法读取 META_PAYLOAD_KEYS（%s: %s）⇒ **键集一致性这一条没跑**，"
                "不是「两份一致」" % (type(exc).__name__, exc)]
    got, want = tuple(payload), tuple(META_PAYLOAD_KEYS)
    if got == want:
        return []
    miss = [k for k in want if k not in got]
    extra = [k for k in got if k not in want]
    return ["build_payload() 的顶层键与 meta_source.META_PAYLOAD_KEYS 不一致："
            "缺 %s、多 %s（顺序也核，实际 %s / 声明 %s）"
            % (miss or "无", extra or "无", got, want)]


def gate(payload):
    """构建期门禁：返回问题清单（空 = 合格）。"""
    problems = []

    # 1) 信息性告警：**只印，不拦**（理由见模块 docstring 的「构建期门禁」一节）
    #    ★ 结构性那几类在下面 3)/4)/5)/6) 各自**独立复核**（注释写着「避免它被改松」），
    #      所以去掉这里的致命化，不会让任何结构性问题溜过去 —— 它们照样印出来。
    import console_meta
    for _w in console_meta.self_check():
        print("  [告警·不拦] %s" % _w)

    # 2) specDefaults 必须是「从建模层问出来的」真字典，不能是空占位
    defaults = payload.get("specDefaults")
    if not isinstance(defaults, dict) or not defaults:
        problems.append("specDefaults 不是非空字典 —— 建模层默认值没求出来")
        return problems

    # 3) 逐字段硬校验（self_check 走的是同一口径，这里独立复核，避免它被改松）
    real = set(defaults) | EXTRA_REAL_KEYS
    for group in payload.get("spec", []):
        for field in group.get("fields", []):
            key = field.get("k")
            if key not in real:
                problems.append(
                    "规格键 %r 不在 build_standard_glb 消费列表里" % key)

    # 4) 可跑阶段必须有 args 模板，否则前端点不动
    for stage in payload.get("pipeline", []):
        if stage.get("runnable") and stage.get("scope") == "single" and not stage.get("args"):
            problems.append("阶段 %s 标为可跑但没有 args 模板" % stage.get("id"))

    # 5) 冻结这份与活的那份必须是同一组键（漏一个字段是不报错的，见 build_payload 的 docstring）
    problems.extend(payload_key_mismatch(payload))

    # 6) selfCheck 必须真的**带**着、且是「已读」那一档 ——
    #    缺了它页面上「这个键改了生不生效」就没得看，而屏幕上与「一切正常」同形。
    sc = payload.get("selfCheck")
    if not isinstance(sc, dict):
        problems.append("payload 里没有 selfCheck ⇒ 控制台看不到「哪些键改了不生效」")
    elif sc.get("规格键", {}).get("状态") != "已读":
        problems.append("selfCheck.规格键.状态 = %r（不是「已读」）—— 这一栏没量到，"
                        "而它在页面上与「规格键都合规」同形"
                        % sc.get("规格键", {}).get("状态"))

    return problems


def source_hash():
    with open(SOURCE, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def summarize(payload, old):
    """新旧对比：只报键级差异，不打整份 JSON（产物 15 KB 左右，也别刷屏）。"""
    if not old:
        print("  对比: 无旧产物，这是首次冻结")
        return
    for key in ("profile", "spec", "pipeline", "runnable"):
        a, b = old.get(key), payload.get(key)
        if a != b:
            print("  对比: %s 有变化" % key)
    a, b = old.get("specDefaults") or {}, payload.get("specDefaults") or {}
    if a != b:
        added = sorted(set(b) - set(a))
        removed = sorted(set(a) - set(b))
        changed = sorted(k for k in set(a) & set(b) if a[k] != b[k])
        if added:
            print("  对比: specDefaults 新增 %s" % ", ".join(added))
        if removed:
            print("  对比: specDefaults 移除 %s" % ", ".join(removed))
        if changed:
            print("  对比: specDefaults 改值 %s" % ", ".join(changed))
        if not (added or removed or changed):
            print("  对比: specDefaults 键序有变化（值相同）")
    if a == b or (not a and not b):
        print("  对比: specDefaults 无变化")
    # selfCheck 不进上面那个「逐键相等」的对比：它每次冻结都会因为「量于」而不同，
    # 那样对比永远报「有变化」，而这个判据会被学会忽略（铁律 47）。
    # 拿它真正会变的那一项来比 —— **告警条数**。
    n_old = (old.get("selfCheck") or {}).get("告警条数")
    n_new = (payload.get("selfCheck") or {}).get("告警条数")
    if n_old is None:
        print("  对比: selfCheck 旧产物没有这一栏（说明旧产物早于本栏上线）")
    elif n_old != n_new:
        print("  对比: selfCheck 告警条数 %s → %s" % (n_old, n_new))
    else:
        print("  对比: selfCheck 告警条数无变化（%s 条）" % n_new)


def main():
    ap = argparse.ArgumentParser(description="冻结控制台元数据")
    ap.add_argument("--check", action="store_true",
                    help="只校验现有产物与当前源码是否一致，不写文件")
    args = ap.parse_args()

    print("冻结控制台元数据 -> %s" % OUT)
    payload = build_payload()

    problems = gate(payload)
    if problems:
        print("\n门禁未通过，共 %d 条：" % len(problems))
        for p in problems:
            print("  ✗ %s" % p)
        return 1
    print("  门禁: 通过（规格键 %d 个 / 阶段 %d 个 / 可跑 %d 个）"
          % (len(payload["specDefaults"]), len(payload["pipeline"]),
             len(payload["runnable"])))

    old = None
    if OUT.exists():
        try:
            old = json.loads(OUT.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            print("  警告: 旧产物读取失败（%s），按首次冻结处理" % exc)
    summarize(payload, old)

    digest = source_hash()
    if args.check:
        if not old:
            print("\n--check: 产物不存在，需先跑一次 freeze_meta.py")
            return 1
        if old.get("_frozen", {}).get("sourceSha256") != digest:
            print("\n--check: 产物已过期（console_meta.py 改过），请重跑 freeze_meta.py")
            return 1
        print("\n--check: 产物与当前源码一致")
        return 0

    payload["_frozen"] = {
        "generatedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": "backend/web/console_meta.py",
        "sourceSha256": digest,
        "specDefaultKeys": len(payload["specDefaults"]),
        "note": "本文件由 freeze_meta.py 生成，服务器只读；改了 console_meta.py 要重跑。",
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=False)
    with open(OUT, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text + "\n")

    size = os.path.getsize(OUT)
    print("  已写入: %d 字节（%.1f KB）" % (size, size / 1024))
    return 0


if __name__ == "__main__":
    sys.exit(main())
