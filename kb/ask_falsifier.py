# -*- coding: utf-8 -*-
"""kb/ask_falsifier.py —— `ask.py --selftest` 的**阳性对照**。

为什么需要单独一个文件：`--selftest` 报绿本身不构成证据 —— 一条永远绿的判据
和一条真的判据在屏幕上一模一样。这里把图谱**改坏五处**（改的是 kb.json 的**内存副本**，
不落盘、不动真文件），要求每次 `--selftest` 都红、且红在**正确的那一处**。

实测抓到的两件事（都不是猜的）：

  · 只删「漏墙」这一个别名的注入**不会红** —— 该家族还有 6 个别名含「漏墙」
    （`build_kb.py` 把 symptoms/causes/fixes 的 `what` 原文也当别名）。
    ⇒ 结论有两个：① 这个家族对单个别名缺失是**冗余**的（好事，属实测）；
      ② 「改坏了却不红」既可能是判据哑、也可能是**注入太弱**，两者要分开。
  · 「登记一条会写盘的命令」当场红：`--run` 的白名单在 ask.py 这一层也拦了一道。

用法：python -u kb/ask_falsifier.py      （退出码 0 = 五处对照全红在正确的一处）
"""
import copy
import io
import json
import os
import sys

KB_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(KB_DIR)
sys.path.insert(0, KB_DIR)
sys.path.insert(0, ROOT)
import ask  # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE = json.loads(io.open(os.path.join(KB_DIR, "kb.json"), encoding="utf-8").read())


def run(kb, label):
    ask.load_kb = lambda *a, **k: kb          # load_kb() 的默认参在 def 时绑定，只能换函数
    buf, old = io.StringIO(), sys.stdout
    sys.stdout = buf
    try:
        code = ask.selftest()
    finally:
        sys.stdout = old
    txt = buf.getvalue().strip()
    print("── %s\n   exit=%s\n%s" % (label, code, "\n".join("   " + l for l in txt.splitlines())))
    return code, txt


def main():
    print("=== 基线（未改动，应当绿）===")
    base_code, _ = run(copy.deepcopy(BASE), "基线")
    if base_code != 0:
        print("!! 基线就红 ⇒ 后面的对照没有意义（先把 --selftest 修绿）")
        return 1

    cases = []

    kb = copy.deepcopy(BASE)
    gone = [k for k, v in kb["index"]["alias"].items()
            if "漏墙" in k and "pb:missing-wall-blob" in v]
    for k in gone:
        del kb["index"]["alias"][k]
    cases.append((kb, "抽光含「漏墙」的别名（%d 个）—— 单删一个不会红" % len(gone), "漏墙"))

    kb = copy.deepcopy(BASE)
    kb["index"]["alias"]["漏墙"] = ["pb:missing-wall"]
    cases.append((kb, "把「漏墙」指向不存在的家族", "missing-wall"))

    kb = copy.deepcopy(BASE)
    kb["playbook"]["floor-misalign"]["runs"] = []
    kb["playbook"]["floor-misalign"]["unverified"] = []
    cases.append((kb, "家族既无可跑判据、又不声明无锚点", "floor-misalign"))

    kb = copy.deepcopy(BASE)
    for k in ("进行中", "快照", "终值", "进度数", "跑着呢", "中途", "pending", "还没跑完"):
        kb["index"]["alias"].pop(k, None)
    cases.append((kb, "抽掉「只有人记着」那条陷阱的全部别名", "unverified"))

    kb = copy.deepcopy(BASE)
    kb["playbook"]["floor-misalign"]["runs"] = [
        {"cmd": "python -u rm -rf data", "writes": "无", "expect": "无", "read": "无",
         "evidence": "qa_structural.py:check_building"}]
    cases.append((kb, "登记一条会写盘的命令", "白名单"))

    kb = copy.deepcopy(BASE)
    kb["playbook"]["floor-misalign"]["runs"] = [
        {"cmd": "python -u qa_structural.py c057; del /q data\\*", "writes": "_qa/c057_qa.txt",
         "expect": "无", "read": "无", "evidence": "qa_structural.py:check_building"}]
    cases.append((kb, "登记一条带 shell 元字符的命令（前缀合法，注入在后面）", "argv"))

    # ── 图那一层：改的不是 ask.py，是**产物**（kb.json 的内存副本）──────────
    #    「多跳能到别的家族」这句话的**唯一**依据就是产物里的 `graph.out`。
    #    把某个家族的出边抽掉，它就该红 —— 不然「多跳」可能只是别名表自己绕出来的。
    kb = copy.deepcopy(BASE)
    gone_e = kb["graph"]["out"].pop("pb:floor-misalign", [])
    cases.append((kb, "抽掉 floor-misalign 的全部出边（%d 条）—— 两跳就断了" % len(gone_e),
                  "T14"))

    kb = copy.deepcopy(BASE)
    del kb["graph"]
    cases.append((kb, "整个 graph 一节删掉（旧产物的形状）", "T15"))

    bad = 0
    for kb, label, must_say in cases:
        code, txt = run(kb, label)
        if code == 0:
            print("   ✗ 改坏了它却报绿 —— 这条刑具是哑的")
            bad += 1
        elif must_say not in txt:
            print("   ✗ 红了，但没指名 %r —— 红在别处等于没抓到这一处" % must_say)
            bad += 1
        else:
            print("   ✓ 红且指名 %s" % must_say)

    print("\n=== 结论 ===")
    if bad:
        print("阳性对照 %d/%d 失败 ⇒ ask.py --selftest 不可信" % (bad, len(cases)))
        return 1
    print("阳性对照 %d/%d 全过：%d 处改坏各自红在正确的一处；基线绿。"
          % (len(cases), len(cases), len(cases)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
