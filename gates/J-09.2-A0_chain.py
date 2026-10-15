# -*- coding: utf-8 -*-
"""闸 2：A0 命令行串链骨架的**交付件复算**（独立于 chain.py 自报）。

量的是**交付件本身**（§10.0.1-1）：probe 真跑出来的**磁盘产出物**，不是 chain.py 的自我描述。
所以本脚本**自己按 tools.json 的路径去磁盘上核**每一件的存在与内容，再与 `chain_run.json`
里记的状态**两个独立读数对比**（对不上就要报，不许以自报为准）。

★ 正对照（缺一 ⇒ 判据没分辨力，等于没写）——用**四个假探针**证明四态真的**分得开**：
  C1 `好假件`   rc=0 + 产出物      ⇒ 必须 OK
  C2 `撒谎件`   rc=0 + **无产出物** ⇒ 必须 NO_ARTIFACT（★ 这是 accoreconsole「脚本层失败一律退 0」的现场版）
  C3 `挂死件`   **永不返回**        ⇒ 必须 TIMEOUT（且**不**并成 FAIL_RC）
  C4 `失败件`   rc≠0               ⇒ 必须 FAIL_RC
  四态必须**两两不同**；若 C1..C4 有任意两个同态 ⇒ 尺子没有分辨力 ⇒ FAIL。

★ 量具盲区（声明）：
  1) 只认「产出物存在 + 含凭据串」；对**产出物内容正确性**（如 STL 几何对不对）**全盲**，
     那是 A1/§10.1 建模判据的活，不是串链骨架的活；
  2) `pending` 项（SketchUp/RCNode/RSNode/UE/图新地球5）**本判据不给结论** —— 三种原因
     各不相同：待补工程输入／只有 GUI ⇒ 已踢出链／**入口可用但进不了本骨架**（SketchUp）。
     ⇒ 原因逐条写在 `chain/tools.json` 的 `pending` 字段里，**「没量」与「量到否」不许同形**；
  3) 只覆盖 tools.json 里登记的件；**未登记的工具本判据看不见**（「清单里没有」≠「世上没有」）；
  4) 磁盘这一侧**只读不重跑**：它核的是「台账记 OK 的那一轮，产物还在不在」，
     证明不了**此刻重跑一次**还会 OK（可重复性以 §10.0.3 **闸 3 独立复现**来管，本闸不越权）。
"""
import glob
import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8")

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CHAIN = os.path.join(ROOT, "chain")
sys.path.insert(0, CHAIN)

import chain  # noqa: E402

PY = sys.executable
FAKE_DIR = os.path.join(HERE, "_out", "_a0_fakes")
LEDGER = os.path.join(CHAIN, "_out", "chain_run.json")


def _fake(name, code, timeout=20):
    """造一个假探针：用 python 当「工具」，argv 里塞要执行的代码。"""
    return {"name": name, "exe": PY,
            "argv": ["-c", code],
            "artifact": "{out}/%s.txt" % name, "contains": "cdut3d-ok",
            "bad_argv": ["-c", "import sys;sys.exit(9)"],
            "timeout": timeout}


def positive_controls():
    """四个假件 ⇒ 四态必须两两不同。返回 (状态字典, 违例列表)。"""
    os.makedirs(FAKE_DIR, exist_ok=True)
    good = _fake("c1_good", "open(r'{out}/c1_good.txt','w').write('cdut3d-ok')")
    liar = _fake("c2_liar", "pass")                       # rc=0，什么都不写
    hang = _fake("c3_hang", "import time;time.sleep(120)", timeout=4)
    fail = _fake("c4_fail", "import sys;sys.exit(5)")
    states = {}
    for label, spec in (("C1_好假件", good), ("C2_撒谎件", liar),
                        ("C3_挂死件", hang), ("C4_失败件", fail)):
        d = os.path.join(FAKE_DIR, spec["name"])
        os.makedirs(d, exist_ok=True)
        r = chain.run_step(spec, d, spec["timeout"])
        states[label] = r["state"]
    bad = []
    want = {"C1_好假件": chain.OK, "C2_撒谎件": chain.NO_ARTIFACT,
            "C3_挂死件": chain.TIMEOUT, "C4_失败件": chain.FAIL_RC}
    for k, exp in want.items():
        if states[k] != exp:
            bad.append(("控制件状态不符", k, "期望 %s 实得 %s" % (exp, states[k])))
    if len(set(states.values())) != 4:
        bad.append(("四态不可分", str(states)))
    return states, bad


def _load_ledger(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def check_deliverables(tools, ledger_path=None, root=None):
    """★ 交付件复算：自己上磁盘核产出物，不信 chain_run.json 的自报。

    ★★ 参照物作用域（铁律 192）：产出物根目录取自**台账自己记的 outdir**，不硬编码。
    硬编码的话，换目录跑一次链，磁盘上**上一轮**的旧产物会配着**这一轮**的新自报一起绿。
    ★ 台账缺失 ⇒ 直接记违例：「没量到」不许当「没问题」。
    """
    ledger_path = ledger_path or LEDGER
    if not os.path.isfile(ledger_path):
        return [], [("台账缺失", ledger_path, "无台账时本判据拒绝给结论")], {}
    payload = _load_ledger(ledger_path)
    self_report = {row["name"]: row for row in payload.get("rows", [])}
    root = root or payload.get("outdir") or os.path.join(CHAIN, "_out", "run")
    rows, bad = [], []
    for spec in tools:
        name = spec["name"]
        if spec.get("pending"):
            # ★ 判词不许把几种 pending 混成一句（铁律 199 的同形禁令）：
            #   「待补工程/影像输入」（RCNode/RSNode/UE）与「只有 GUI ⇒ 已踢出链」（图新地球5）
            #   是**两回事**，SketchUp 又是**第三种**（它入口可用，只是**不能进本骨架** ——
            #   单实例静默接手 + 无无头模式，见 tools.json 的 pending 字段）。
            #   ⇒ 这里只报「不给结论」，具体是哪种原因去 tools.json 读，**不替它下结论**。
            rows.append((name, chain.PENDING, "-", "本判据不给结论（原因见 tools.json 的 pending 字段）"))
            continue
        # 独立核：好输入的产出物在不在、含不含凭据（★ 好跑在 <name>/good/ 子目录）
        outdir = os.path.abspath(os.path.join(root, name, "good"))
        art = spec["artifact"].replace("{out}", outdir)
        hits = sorted(glob.glob(art)) if spec.get("glob") else ([art] if os.path.exists(art) else [])
        exists = bool(hits)
        has = True
        if exists and spec.get("contains"):
            with open(hits[0], "rb") as f:
                has = spec["contains"].encode("utf-8") in f.read()
        disk_ok = exists and has
        rep = self_report.get(name, {})
        rep_state = (rep.get("good") or {}).get("state", "?")
        agree = (disk_ok and rep_state == chain.OK) or ((not disk_ok) and rep_state != chain.OK)
        if not agree:
            bad.append(("自报与磁盘不符", name, "磁盘产出=%s 自报=%s" % (disk_ok, rep_state)))
        note = ("  ← " + spec["note"][:64]) if spec.get("note") else ""
        rows.append((name, rep_state, "产出物=%s" % ("有" if disk_ok else "无"),
                     "可分=%s%s" % (rep.get("discriminates"), note)))
    return rows, bad, payload


def control_recheck(tools, ledger_path, root):
    """★ 复算判据**自己的正对照**：篡改一行自报，它必须报「不符」。

    只有证明它会红，才谈得上它的绿有意义（§10.0.1-4）。返回 (被篡改的名字, 报红了吗)。
    """
    payload = _load_ledger(ledger_path)
    flipped = None
    for r in payload.get("rows", []):
        g = r.get("good") or {}
        if g.get("state") == chain.OK:
            g["state"] = chain.FAIL_RC          # 磁盘上产出物还在 ⇒ 自报改反必然对不上
            flipped = r["name"]
            break
    if flipped is None:
        return None, False
    tmp = os.path.join(HERE, "_out", "_a0_tamper.json")
    os.makedirs(os.path.dirname(tmp), exist_ok=True)
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False)
    _, bad_t, _ = check_deliverables(tools, tmp, root)
    return flipped, any(b[0] == "自报与磁盘不符" and b[1] == flipped for b in bad_t)


def main():
    tools = chain.load_tools()
    print("tools.json 件数 :", len(tools),
          "(可跑 %d / pending %d)" % (sum(1 for t in tools if not t.get("pending")),
                                      sum(1 for t in tools if t.get("pending"))))

    print("\n---- 正对照（四个假探针，四态必须两两不同）----")
    states, bad = positive_controls()
    for k, v in states.items():
        print("  %-10s → %s" % (k, v))

    print("\n---- 交付件复算（磁盘产出物 vs 自报台账）----")
    rows, bad2, payload = check_deliverables(tools)
    for name, state, art, extra in rows:
        print("  %-16s %-14s %-10s %s" % (name, state, art, extra))
    bad.extend(bad2)

    print("\n---- 复算判据的正对照（篡改一行自报，必须报「不符」）----")
    root = payload.get("outdir") or os.path.join(CHAIN, "_out", "run")
    flipped, caught = control_recheck(tools, LEDGER, root)
    print("  篡改 [%s] 的自报状态 → 判据报不符 = %s" % (flipped, caught))
    if not caught:
        bad.append(("正对照失败", "复算判据对篡改无分辨力（只会盖章）"))

    # ★ 踢出判据：GUI-only 的「图新地球5」必须被判出、且**不在可跑集**里
    gui = [t for t in tools if t["name"] == "图新地球5"]
    if not gui or not gui[0].get("pending"):
        bad.append(("踢出判据失效", "图新地球5 未被标 pending/踢出"))

    # ★ 非空断言：可跑的件不许为 0（空集合的绿不算绿）
    runnable = [t for t in tools if not t.get("pending")]
    if not runnable:
        bad.append(("非空断言失败", "可跑件为 0"))

    # 可跑件里，真 OK 的占比（判词用，不设阈值，如实报）
    ok = [r for r in rows if r[1] == chain.OK]
    print("\n可跑件 %d，其中 probe 判 OK %d，pending %d" %
          (len(runnable), len(ok), len([r for r in rows if r[1] == chain.PENDING])))

    rc = 0
    if bad:
        print("\n!! FAIL", len(bad))
        for b in bad:
            print("  " + "  ".join(str(x) for x in b))
        rc = 1
    else:
        print("\nJ-09.2-A0 总判 : PASS（四态可分 + 磁盘产出与自报一致 + GUI-only 已踢出）")

    # ★ 为什么落 json：本闸原先**只落 run.txt** ⇒ 台账页 demo/sys.html 对它只有两路读数
    #   （run.txt 里的 `rc=` 与判词行）；2026-10-14 补上 `gates/_out/J-09.2-A0.json`，
    #   让页面对每条判据取的三路读数里第三路（json 里的 `pass`）也齐。
    # ★ 只把**本闸已经算出来的**那几个量原样写出去，不新算、不改判定、不改退出码。
    _write_json(rc,
                tools_total=len(tools),
                runnable=len(runnable),
                pending=len([t for t in tools if t.get("pending")]),
                ok=len(ok),
                n_bad=len(bad),
                bad=["  ".join(str(x) for x in b) for b in bad],
                states=states,                                   # 四个假探针的四态（正对照）
                tamper={"flipped": flipped, "caught": caught})   # 复算判据的正对照
    return rc


def _write_json(rc, **kv):
    """★ 把本闸已算出的读数落 `gates/_out/J-09.2-A0.json`（默认路径写死，无命令行开关）。

    为什么单开这个模块级小函数：本闸**没有 argparse**、`main()` 多处直接 `return`，
    所以在 `main()` 里把 rc 汇到一个出口后调它，改动最小、判定逻辑一字不动。
    ★ 盲区照抄 docstring 里**已经声明**的四条（有几条写几条，不默认它没有）。
    写盘按铁律 079：字节层 `open(..., "w", encoding="utf-8")`，别用文本模式写别的文件。
    """
    path = os.path.join(HERE, "_out", "J-09.2-A0.json")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    payload = {"pass": rc == 0, "rc": rc}
    payload.update(kv)
    payload["blind"] = [
        "只认「产出物存在 + 含凭据串」；对产出物内容正确性（如 STL 几何对不对）全盲",
        "pending 项（RCNode/RSNode/UE/图新地球5）本判据不给结论；「没量」不许与「量到否」同形",
        "只覆盖 tools.json 里登记的件；未登记的工具本判据看不见（「清单里没有」≠「世上没有」）",
        "磁盘侧只读不重跑：核的是「台账记 OK 的那一轮产物还在不在」，证明不了此刻重跑仍 OK",
    ]
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=1)
    print("  写出:", path)


sys.exit(main())
