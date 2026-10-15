# -*- coding: utf-8 -*-
"""A0 命令行串链骨架 —— 每个外部软件一个**探针**（headless 入口 → 产出文件 → 记退出码）。

用户令：「**通过命令行把本地的软件串起来，自动运行**」（§7.9.4 / §9.2 A0）。
本模块只做一件事：**按四条判据把「可无人值守地串进链」这件事量出来**——
① 有 headless 入口；② 输入输出都是文件；③ **退出码可判**；④ ★ 每步带超时。

★★ 本模块的**核心一条**（来自 §7.9.4 烟测的实测教训）：
**链路层只认产出物，不认退出码**。`accoreconsole.exe` 实测「脚本层失败一律退 0」、
「括号不闭合会挂死永不返回」⇒ 若拿 rc 当判据，会把一半失败当成功往下走。
所以本模块把 **rc==0 / rc!=0 / 超时 / 没产出物** 分成**四个互不合并的状态**（铁律 199 三态不许合并的加强版）。

状态表（`run_step` 的返回）：
  OK          产出物存在且内容含凭据 且 rc==0   —— ★ 唯一算「过」的状态
  FAIL_RC     rc != 0
  TIMEOUT     被超时杀掉（**与 FAIL_RC 分开报**：「崩了」与「没量到」不许同形）
  NO_ARTIFACT ★ rc==0 却没产出物（或产出物不含凭据）—— **静默成功**，最危险的一类
  SKIP        exe 不在盘上（前置缺件，不算失败）
  PENDING     需要工程 / 影像 / 许可证输入，本步**不假装跑过**（诚实占位）

★ 判别力怎么证明：**每个工具都喂一对（好输入 / 坏输入）**，两条必须**可分**
（好=OK 且 坏!=OK）。分不开的工具 ⇒ 判为**不可判**，踢出链。
"""
from __future__ import annotations

import glob
import json
import os
import subprocess
import sys
import time

OK = "OK"
FAIL_RC = "FAIL_RC"
TIMEOUT = "TIMEOUT"
NO_ARTIFACT = "NO_ARTIFACT"
SKIP = "SKIP"
PENDING = "PENDING"

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS_JSON = os.path.join(HERE, "tools.json")


def load_tools(path: str = TOOLS_JSON) -> list:
    with open(path, encoding="utf-8") as f:
        return json.load(f)["tools"]


def _expand(argv, outdir):
    return [str(a).replace("{out}", outdir) for a in argv]


def _artifact_ok(spec, outdir) -> tuple:
    """产出物是不是真的产出来了。返回 (exists, path)。★ 产出物=唯一真值。"""
    art = spec["artifact"].replace("{out}", outdir)
    if spec.get("glob"):
        hits = sorted(glob.glob(art))
        return (len(hits) > 0, hits[0] if hits else art)
    return (os.path.exists(art), art)


def run_step(spec: dict, outdir: str, timeout: int) -> dict:
    """跑一次探针。spec: {exe, argv, artifact, [from:str="file"|"stdout"], [contains], [userdata]}"""
    exe = spec["exe"]
    if not os.path.isfile(exe):
        return {"state": SKIP, "rc": None, "secs": 0.0, "detail": "exe 不在盘上", "exe": exe}
    argv = [exe] + _expand(spec["argv"], outdir)

    # ★ 约定 3：脚本写法（每条命令一行、括号同行闭合）由 setup 落盘，本层不拼 shell 串
    for rel, content in spec.get("setup", {}).items():
        p = os.path.join(outdir, rel)
        os.makedirs(os.path.dirname(p) or outdir, exist_ok=True)
        with open(p, "wb") as f:
            f.write(content.replace("{out}", outdir.replace("\\", "/")).encode("utf-8"))

    t0 = time.time()
    try:
        p = subprocess.run(argv, cwd=outdir, capture_output=True, timeout=timeout)
        rc, timed_out, out = p.returncode, False, p.stdout
    except subprocess.TimeoutExpired:
        # ★ 超时单独成态；**不**并进 FAIL_RC
        return {"state": TIMEOUT, "rc": None, "secs": round(time.time() - t0, 1),
                "detail": "超时 %ds 被终止" % timeout, "exe": exe}
    secs = round(time.time() - t0, 1)

    if spec.get("from") == "stdout":
        art = spec["artifact"].replace("{out}", outdir)
        os.makedirs(os.path.dirname(art) or outdir, exist_ok=True)
        with open(art, "wb") as f:
            f.write(out or b"")

    exists, art = _artifact_ok(spec, outdir)
    contains = spec.get("contains")
    has_receipt = True
    if exists and contains:
        with open(art, "rb") as f:
            has_receipt = contains.encode("utf-8") in f.read()

    if rc != 0:
        state = FAIL_RC
    elif not exists:
        state = NO_ARTIFACT          # ★ rc=0 但没产出物 ⇒ 静默成功，不算过
    elif not has_receipt:
        state = NO_ARTIFACT          # 产出物不含凭据 ⇒ 等同没产出
    else:
        state = OK
    err = ((p.stderr or b"")[:400]).decode("utf-8", "replace")
    return {"state": state, "rc": rc, "secs": secs, "artifact": art, "exe": exe, "stderr": err}


def probe(spec: dict, base: str) -> dict:
    """一个工具跑一对（好 / 坏），并判它**可分不可分**。

    ★★ 好坏两次必须在**各自的目录**里跑：否则好跑留下的产出物会把坏跑的结果盖住
    （首轮实测：blender 的坏输入被判成 OK，就是被上一轮的 out.blend 顶出来的假绿）。
    """
    base = os.path.abspath(base)
    if spec.get("pending"):
        return {"name": spec["name"], "good": {"state": PENDING, "detail": spec["pending"]},
                "bad": None, "discriminates": None, "verdict": PENDING}
    good_dir = os.path.join(base, "good")
    bad_dir = os.path.join(base, "bad")
    os.makedirs(good_dir, exist_ok=True)
    os.makedirs(bad_dir, exist_ok=True)
    good = run_step(spec, good_dir, spec.get("timeout", 180))
    bad_spec = dict(spec)
    bad_spec["argv"] = spec["bad_argv"]
    bad_spec.pop("from", None)          # 坏输入一律看它自己产不产东西
    bad_spec.pop("contains", None)
    bad_spec["artifact"] = spec.get("bad_artifact", spec["artifact"])
    bad = run_step(bad_spec, bad_dir, spec.get("timeout", 180))
    discriminates = (good["state"] == OK) and (bad["state"] != OK)
    verdict = OK if discriminates else ("NO_DISCRIMINATION" if good["state"] == OK else good["state"])
    return {"name": spec["name"], "good": good, "bad": bad,
            "discriminates": discriminates, "verdict": verdict}


def run_all(outdir: str, tools_path: str = TOOLS_JSON) -> dict:
    outdir = os.path.abspath(outdir)
    os.makedirs(outdir, exist_ok=True)
    rows = []
    for spec in load_tools(tools_path):
        r = probe(spec, os.path.join(outdir, spec["name"]))
        rows.append(r)
    summary = {}
    for r in rows:
        summary[r["verdict"]] = summary.get(r["verdict"], 0) + 1
    return {"rows": rows, "summary": summary, "outdir": outdir}


def main(argv):
    sys.stdout.reconfigure(encoding="utf-8")
    outdir = argv[1] if len(argv) > 1 else os.path.join(HERE, "_out", "run")
    res = run_all(outdir)
    for r in res["rows"]:
        g, b = r["good"], r["bad"]
        bstate = (b or {}).get("state", "-")
        print("%-18s 好=%-12s 坏=%-12s 可分=%s" %
              (r["name"], g["state"], bstate, r["discriminates"]))
    print("\n汇总:", res["summary"])
    os.makedirs(os.path.join(HERE, "_out"), exist_ok=True)
    with open(os.path.join(HERE, "_out", "chain_run.json"), "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=1)
    print("台账 →", os.path.join(HERE, "_out", "chain_run.json"))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
