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
`console_meta.self_check()` 在生产代码里是**非致命**的（只打印告警）。
这个脚本把它前移到构建期并**升级为致命**：规格键对不上、可跑阶段缺 argv
都直接非零退出。产物不合格就不该被发到服务器。

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
    """求值出与 GET /api/meta 的 data 字段完全一致的对象。"""
    import console_meta

    return {
        "profile": console_meta.PROFILE_GROUPS,
        "spec": console_meta.SPEC_GROUPS,
        "styleKeys": console_meta.STYLE_KEYS,
        "pipeline": console_meta.PIPELINE,
        "specDefaults": console_meta.spec_defaults(),
        "runnable": console_meta.runnable_ids(),
    }


def gate(payload):
    """构建期门禁：返回问题清单（空 = 合格）。"""
    problems = []

    # 1) 生产环境的非致命告警，在这里升级为致命
    import console_meta
    problems.extend(console_meta.self_check())

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
