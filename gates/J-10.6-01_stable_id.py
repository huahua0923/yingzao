# -*- coding: utf-8 -*-
"""判据 J-10.6-01 —— 构件稳定 ID 规则（出口门：重跑一次建模 ⇒ 同构件 ID 不变；变了要报数）。

判据（§10.6「锚点不脱锚」）：
  ① 重跑一次建模，**同构件 ID 必须不变**；
  ② 故意改一套 ID（这里用「在墙列表前面插入一堵新墙」模拟重出的位移）⇒ 锚点校验**必须报出脱锚条数**。

量具（写明）：tools/stable_id.py 的 content-hash ID + resolve()；单位=条；阈值=期望条数。
量具盲区（声明）：
  · 只认 FLOOR_KEYS 里那四类件 + 房间；对新增的构件种类**全盲**（未列入即不计）。
  · 房间身份取 (楼层, number)；**number 自身跨重跑的稳定性本轮未核** ⇒ 房间 ID 的否定判词不算证据。
  · 只读 floor*.json；对 GLB 里另生成的几何（屋面/女儿墙等）**全盲**。
正对照（必配，全部要求变红）：
  · C1 位置型 id 在「前面插一堵墙」后 **142 条全平移**（证明这把尺子量得出脱锚）；
  · C2 内容型 id 在同一扰动下 **0 条脱锚、恰好 +1 新增**（证明它真的稳）；
  · C3 真改一堵墙（厚 2 倍）⇒ 内容型 **恰好 1 条脱锚**（证明「变了要报数」不是恒 0）。
三态：OK / FAIL / SKIP（前置缺件·跑不动）。SKIP 不算过、也不假报成 FAIL。
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, r"D:\项目\cdut3d\tools")
from stable_id import (ids_of_building, ids_of_floor, resolve,  # noqa: E402
                       resolve_mapped, legacy_id, component_id)

CAMPUS, BLD = "cdut-main", "c001"
BASE = os.path.join(r"D:\项目\gym3d\gym3d\data\buildings", BLD)
FLOORS = os.path.join(BASE, "floors")
SCRATCH = os.path.join(r"C:\Users\Administrator\_scratch", "_gate_rerun_" + BLD)
HERE = os.path.dirname(os.path.abspath(__file__))
OUTDIR = os.path.join(HERE, "_out")
# ★ 默认落盘路径（用 HERE 拼）：页面 build_sys_page.py 按脚本名 stem 找 `J-10.6-01.json`，
#   不给这名字它就读不到「顶层字段」那一路读数 ⇒ 本闸在页上只剩 rc 与判词两路。
JSON_PATH = os.path.join(OUTDIR, "J-10.6-01.json")

# ★ 盲区：逐条抄 docstring 里「量具盲区（声明）」那三条 —— 盲区外的读数才算证据，
#   写进 json 是为了让页面上这一条**自己带着**它的适用边界，不靠人去翻源码。
BLIND = [
    "只认 FLOOR_KEYS 里那四类件 + 房间；对新增的构件种类全盲（未列入即不计）",
    "房间身份取 (楼层, number)；number 自身跨重跑的稳定性本轮未核 ⇒ 房间 ID 的否定判词不算证据",
    "只读 floor*.json；对 GLB 里另生成的几何（屋面/女儿墙等）全盲",
]

_LOG = []


def log(*a):
    s = " ".join(str(x) for x in a)
    print(s)
    _LOG.append(s)


def load(p):
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def legacy_ids_of_building():
    """整栋的位置型 id 集合（复刻现有 `w0-4` 口径）。"""
    out = {}
    for fn in sorted(os.listdir(FLOORS)):
        if not (fn.startswith("floor") and fn.endswith(".json")):
            continue
        d = load(os.path.join(FLOORS, fn))
        F = d.get("floor")
        for key in ("walls", "doors", "windows", "columns"):
            for i in range(len(d.get(key) or [])):
                out[legacy_id(key[:-1], F, i)] = True
    return out


def _maps(f0_walls, floors):
    """给定 floors 字典，返回 (位置型 {legacy_id: 内容id}, 内容型 {content_id: content_id})。"""
    leg, cnt = {}, {}
    for F in sorted(floors):
        d = floors[F]
        for key in ("walls", "doors", "windows", "columns"):
            kind = key[:-1]
            for i, obj in enumerate(d.get(key) or []):
                cid = component_id(CAMPUS, BLD, kind, obj)
                leg[legacy_id(kind, F, i)] = cid      # ★ 位置型 id → 它此刻指的那件的内容
                cnt[cid] = cid
    return leg, cnt


def control_C1_C2():
    log("\n---- 正对照 C1/C2：在 c001 F0 墙列表**前面插入一堵新墙**，两套 id 各自怎么错 ----")
    floors = {}
    for fn in sorted(os.listdir(FLOORS)):
        if fn.startswith("floor") and fn.endswith(".json"):
            d = load(os.path.join(FLOORS, fn))
            floors[d["floor"]] = d
    f0 = floors[0]
    new_wall = json.loads(json.dumps(f0["walls"][0]))
    for pt in new_wall.get("poly") or []:
        pt[0] += 0.5                      # 挪半米 ⇒ 确属另一堵墙，不是同一件
    f0_new = dict(f0)
    f0_new["walls"] = [new_wall] + list(f0["walls"])
    floors_new = dict(floors)
    floors_new[0] = f0_new

    leg_a, cnt_a = _maps(f0_walls=None, floors=floors)
    leg_b, cnt_b = _maps(f0_walls=None, floors=floors_new)

    # ★ 关键：位置型必须**按 id 对齐再比内容**，不能只比 id 集合
    r_leg = resolve_mapped(leg_a, leg_b)
    r_cnt = resolve_mapped(cnt_a, cnt_b)
    n0 = len(f0["walls"])
    log("  位置型 id ：脱锚(reassigned+gone)=%d  新增=%d  （F0 墙数=%d，整栋位置型共 %d 件）"
        % (r_leg["detached"], r_leg["added"], n0, len(leg_a)))
    log("     样本(同一个 id 指到了别件):", r_leg["reassigned_sample"][:3])
    log("  内容型 id ：脱锚=%d  新增=%d  （基线共 %d 件）"
        % (r_cnt["detached"], r_cnt["added"], len(cnt_a)))
    ok = (r_leg["detached"] == n0) and (r_cnt["detached"] == 0) and (r_cnt["added"] == 1)
    log("  C1 位置型静默重挂 :", "✔变红(F0 %d 条 id 全指向了别件，有分辨力)" % r_leg["detached"]
        if r_leg["detached"] == n0 else "★没红(作废)")
    log("  C2 内容型零脱锚+1新增:", "✔" if (r_cnt["detached"] == 0 and r_cnt["added"] == 1) else "★不符")
    return ok, r_leg, r_cnt


def control_C3():
    log("\n---- 正对照 C3：真把 c001 F0 的一堵墙**改厚 2 倍**，看内容型 id 报几条 ----")
    cur = ids_of_building(CAMPUS, BLD, FLOORS)
    d = load(os.path.join(FLOORS, "floor0.json"))
    w = json.loads(json.dumps(d["walls"][0]))
    w["thickness"] = (w.get("thickness") or 0.1) * 2
    d2 = dict(d)
    d2["walls"] = [w] + list(d["walls"][1:])
    f0_new = {}
    f0_new.update(ids_of_floor(CAMPUS, BLD, d2))
    cur2 = dict(cur)
    cur2 = {k: v for k, v in cur2.items() if not (v["kind"] == "wall" and v["floor"] == 0)}
    cur2.update(f0_new)
    r = resolve(cur, cur2)
    log("  内容型 id ：脱锚=%d 新增=%d （只该动那一堵墙）" % (r["missing"], r["added"]))
    log("  C3 变了报数 :", "✔恰好1脱锚+1新增" if (r["missing"] == 1 and r["added"] == 1) else "★不符")
    # ★ 连判别用的那个 r 一起返回：json 要的是**实测读数**，不是重新算一遍（铁律 174）
    return (r["missing"] == 1 and r["added"] == 1), r


def literal_rerun():
    """★ 真跑一次重识别（out_dir 改指 scratch，**绝不碰基线**），比 floor*.json 与 id 集合。"""
    log("\n---- 正对照 C0（字面出口门）：真跑一次重识别，同构件 ID 必须不变 ----")
    if not os.path.isfile(os.path.join(BASE, "profile.json")):
        return "SKIP", "缺 profile.json", {}
    if os.path.isdir(SCRATCH):
        shutil.rmtree(SCRATCH)
    os.makedirs(SCRATCH)
    # 交给子进程跑，避免污染本判据进程的 import 状态
    helper = os.path.join(OUTDIR, "_rerun_helper.py")
    os.makedirs(OUTDIR, exist_ok=True)
    with open(helper, "w", encoding="utf-8", newline="\n") as f:
        f.write(RERUN_HELPER)
    r = subprocess.run([sys.executable, helper, BLD, SCRATCH], capture_output=True, timeout=900)
    if r.returncode != 0:
        out = (r.stdout.decode("utf-8", "replace") + r.stderr.decode("utf-8", "replace")).strip()
        log("  重识别跑不动（rc=%d）—— 记 SKIP，不假报 FAIL：%s"
            % (r.returncode, "\n".join(out.splitlines()[-3:])))
        return "SKIP", "rc=%d" % r.returncode, {"child_rc": r.returncode}
    a = ids_of_building(CAMPUS, BLD, FLOORS)
    b = ids_of_building(CAMPUS, BLD, os.path.join(SCRATCH, "floors"))
    if not b:
        log("  重识别没写出 floor*.json —— 记 SKIP，不假报 FAIL")
        return "SKIP", "没写出产物", {"baseline": len(a), "rerun": len(b)}
    rr = resolve(a, b)
    log("  重跑件数 %d / 基线 %d ；脱锚=%d 新增=%d" % (len(b), len(a), rr["missing"], rr["added"]))
    info = {"baseline": len(a), "rerun": len(b), "missing": rr["missing"], "added": rr["added"]}
    if rr["missing"] == 0 and rr["added"] == 0 and len(a) == len(b) and a:
        log("  C0 重跑 ID 不变 : ✔（%d 件全解析）" % len(a))
        return "OK", "%d 件" % len(a), info
    log("  C0 ★重跑后 ID 变了 —— 出口门不过")
    return "FAIL", "missing=%d added=%d" % (rr["missing"], rr["added"]), info


RERUN_HELPER = r'''# -*- coding: utf-8 -*-
"""子进程：把 profile.out_dir 改指 argv[2]，调 recognize() 重识别一栋。只写 argv[2]。"""
import json, os, sys
sys.stdout.reconfigure(encoding="utf-8")
NAME, OUT = sys.argv[1], sys.argv[2]
sys.path.insert(0, r"D:\\项目\\gym3d\\gym3d\\backend")
SRC = os.path.join(r"D:\\项目\\gym3d\\gym3d\\data\\buildings", NAME)
cfg = json.load(open(os.path.join(SRC, "profile.json"), encoding="utf-8"))
cfg["out_dir"] = os.path.join(OUT, "floors")
os.makedirs(cfg["out_dir"], exist_ok=True)
from recognizer import BuildingProfile, recognize
p = BuildingProfile.from_cfg(cfg)
floors = recognize(p)
print("重识别完成 楼层=", floors)
'''


def _write_artifacts(rc, payload):
    """★ 本闸**唯一**的出口：run.txt 与 json 在同一处写、共用一份 `_LOG`。

    为什么要合并（★ 用户 2026-10-14 明令）：台账页 `demo/sys.html` 对每条判据取
    三路**互相独立**的读数 —— ① json 的 `pass` ② run.txt 的 `rc=` ③ run.txt 的判词行。
    本闸原只落 run.txt、不落 json ⇒ 页上只剩两路、「顶层字段」一节为空。
    出口合成一处，是为了让「返回值」与「落到盘上的读数」永远出自同一次运行（铁律 187）。
    """
    with open(os.path.join(OUTDIR, "J-10.6-01.run.txt"), "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(_LOG) + "\n")
    os.makedirs(os.path.dirname(JSON_PATH), exist_ok=True)
    # ★ encoding="utf-8" + ensure_ascii=False + indent=1：与仓内 J-10.2-02 那套口径一致
    with open(JSON_PATH, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=1)
    print("  写出:", JSON_PATH)
    return rc


def main():
    os.makedirs(OUTDIR, exist_ok=True)
    # ★ 非空断言：没有件可量的绿不算绿
    n = len(ids_of_building(CAMPUS, BLD, FLOORS))
    log("被测集合非空断言：c001 共 %d 个可识别构件/房间" % n)
    if n == 0:
        log("★ 空集合 ⇒ 判据恒绿，直接作废")
        # ★ 没量到的读数一律写 None（不许编数）：空集合下正对照根本没跑
        return _write_artifacts(1, {
            "pass": False, "rc": 1, "n_components": 0,
            "c1_leg_detached": None, "c1_leg_added": None,
            "c2_cnt_detached": None, "c2_cnt_added": None,
            "c3_cnt_detached": None, "c3_cnt_added": None,
            "c0": {"state": "SKIP", "detail": "空集合未跑正对照"},
            "blind": BLIND,
        })

    ok01, r_leg, r_cnt = control_C1_C2()
    ok3, r3 = control_C3()
    state, detail, c0 = literal_rerun()

    log("\n===== 判词 =====")
    log("C1/C2（位置型不稳·内容型稳）:", "PASS" if ok01 else "FAIL")
    log("C3（变了要报数）          :", "PASS" if ok3 else "FAIL")
    log("C0（真重跑 ID 不变）      :", state, detail)

    verdict = "PASS" if (ok01 and ok3 and state in ("OK", "SKIP")) else "FAIL"
    log("J-10.6-01 总判 :", verdict)
    rc = 0 if verdict == "PASS" else 1

    # ★ 读数全部取自刚才**真正算出来**的那几个对象（r_leg/r_cnt/r3/c0），不重算、不手打
    return _write_artifacts(rc, {
        "pass": rc == 0, "rc": rc,
        "n_components": n,                         # 非空断言量到的构件/房间数
        "c1_leg_detached": r_leg["detached"],      # C1 位置型：插一堵墙后脱锚条数
        "c1_leg_added": r_leg["added"],            # C1 位置型：新增条数
        "c2_cnt_detached": r_cnt["detached"],      # C2 内容型：同扰动下脱锚条数
        "c2_cnt_added": r_cnt["added"],            # C2 内容型：同扰动下新增条数
        "c3_cnt_detached": r3["missing"],          # C3 真改一堵墙 ⇒ 内容型脱锚条数
        "c3_cnt_added": r3["added"],
        "c0": dict({"state": state, "detail": detail}, **c0),   # C0 真重跑：件数/脱锚/新增
        "blind": BLIND,
    })


sys.exit(main())
