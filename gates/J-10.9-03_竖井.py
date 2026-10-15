# -*- coding: utf-8 -*-
r"""判据 J-10.9-03：挂 `LIFT` / 「电梯井」这个名字的东西，判词必须**印在脸上**，不许静默绿。

★ 用户 2026-10-15 报「**电梯生成的也不是不对**」。查完的结论是：这三个**不是客运电梯井**
  —— 1 层核心筒墙上闭合矩形只有 1389.4×1853.0、1008.0×1646.9×2，**1008 mm 的净宽任何客运梯都装不下**；
  且 12 层共 1099 条文字**无一条含「梯」或「井」**。⇒ `LIFT` 是**误命名**，已改叫 `SHAFT`/「竖井」。
  **判词进 `参数.json::竖井/判定`，并逐行写进件的读数里。** 本闸就核「这个判词有没有被说出来」。

判据
 ① 参照件同趟：`对照.json` 生成时刻/磁盘时刻不许早于 `contours/1层.json` 磁盘时刻 − 600 s。
 ② 行内恒等式（精度写在读数里 ⇒ 判据按同一精度写）：`净宽 × 净高` 四舍五入到 **3 位小数**
    必须逐字等于 `净面积_m2`。★ 这条只到 ±0.0005 m²（±500 mm²）—— 声明在盲区里，不假装它细。
 ③ **逐层**多重集相等：每一层的 (净宽, 净高) 多重集必须**逐字**等于 `参数.json::竖井/净空实测.值`
    的多重集。不是「集合包含」——★ 包含会漏掉「同一层里两个矩形被并成一个」和「少了一个」；
    多重集相等才核得住参数表那句「1 层实测；**12 层逐层同位**」。
 ④ 判词逐行一致：每行 `判定` 必须**逐字**等于 `参数.json::竖井/判定.值`。件里出现任何一行
    别的判词 ⇒ 红（这是「不许静默绿」那一条：判词是数据，不是注释）。
 ④b 判词与留空**互锁**（两条声明不许自相矛盾）：
    · 判定 = 「本套图无客运电梯井」 ⇒ `国标下限.值` 与 `层门洞.值` **必须都是 null**
      （没有井却填着井道尺寸/层门洞 = 声明自己打自己）；
    · 判定 ≠ 无井 ⇒ `国标下限.值` **不许是 null**（说有井却拿不出任何档位 = 建不了）。
    ★ 这两条读的是**参数表内部**，与 ④ 读件的那条**不同源**：④ 红是「件与表不一致」，
      ④b 红是「表与表不一致」，两条要能分开指认。
 ⑤ echo：每行 `壁厚_mm` == `井壁厚.值`、`壁厚源` == `井壁厚.标注`，且 壁厚 落在 `井壁厚.区间` 内。
 ⑥ 层覆盖与「没缩没」：12 层每层竖井个数相同（件里 36 行 ⇒ 每层 3）；`缩没了` 不许有 True
    —— 「缩没了」= 井被墙吃掉、这一格**没建出来**，不能与「建出来了且合规」同形。
 ⑦ 判词不静默：**原句**「本套图无客运电梯井」必须出现在日志里；件里出现的判词集合、
    每层个数、净空多重集写进 json。

量具
 `构件库/对照.json::竖井`（逐层逐个一行，`build3d.lift_polys` 现算）；`构件库/参数.json::构件.竖井`；
 层名单取自 `06_su/contours/*层.json` 的文件名。

量具盲区（★先声明，再判）
 · **「无客运电梯井」这条判词不是本闸算出来的。** 它出自两把互不同源的尺子（① 形状：1 层核心筒墙上
   闭合矩形尺寸；② 命名：12 层 1099 条文字里无「梯」/「井」）。本闸只核「件逐行写着它」
   +「它与两条留空自洽」，**那两把尺子本身本闸一概核不到**。
 · 净面积只存 **3 位小数** ⇒ ② 的分辨力是 ±0.0005 m²（±500 mm²）。
 · 不核 z 向：井壁的起止标高、是否贯到顶、底坑/顶层、层门洞所在的标高 —— 行里只有平面净尺寸，全盲。
 · 壁厚 150 是**假设**值：本闸核「件与参数表一致」，**不是**「150 mm 是对的」。
 · 不核源图：本闸只比「件 vs 参数表」，源图那一侧是 `J-10.8-00` 的活。

正对照（每条必须**因该因**而红；`新增 N 条` 是相对 C1 基线的**差集**，铁律 183）
 C1 真件                —— 基线
 C2 一行净宽改 999、净面积**同步改** —— ③ 红（不在净空实测多重集里；同步改是为了隔离 ③，不同步会连 ② 一起响）
 C3 一行净面积改 9.999   —— ② 红
 C4 一行判定改「有电梯井」—— ④ 红（④b 不动：它读参数表）
 C5 参数.json 不在       —— SKIP(rc=4)，另起一个**真进程**验 rc
 C6 生成时刻改旧         —— ① 红
 C7 参数判定改成「有客运电梯井」而 `国标下限` 仍 null —— ④b 红（**证明互锁不是空的**）

三态：rc=0 PASS ／ rc=1 FAIL ／ rc=4 SKIP（对照.json / 参数.json / contours 不在）
"""
import glob
import json
import os
import subprocess
import sys
from collections import Counter
from datetime import datetime

sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = r"D:\项目\cdut3d"
CONTOURS = os.path.join(ROOT, "rebuild", "06_su", "contours")
PARAM = os.path.join(ROOT, "rebuild", "构件库", "参数.json")
DUIZHAO = os.path.join(ROOT, "rebuild", "构件库", "对照.json")
OUTD = os.path.join(HERE, "_out")
OUT = os.path.join(OUTD, "J-10.9-03.run.txt")

NO_LIFT = "本套图无客运电梯井"
BLIND = [
    "「无客运电梯井」这条判词不是本闸算出来的：它出自「形状」与「命名」两把互不同源的尺子，"
    "本闸只核「件逐行写着它」+「它与两条留空自洽」，那两把尺子本身核不到",
    "净面积只存 3 位小数 ⇒ 「净宽×净高 == 净面积」只到 ±0.0005 m²（±500 mm²）",
    "不核 z 向：井壁起止标高、是否贯到顶、底坑/顶层、层门洞标高，全盲（行里只有平面净尺寸）",
    "壁厚 150 是假设值：本闸核「件与参数表一致」，不是「150 mm 是对的」",
    "只比「件 vs 参数表」，源图那一侧不在本闸",
]
FRESH_SLACK_S = 600

_LOG = []


def log(s):
    _LOG.append(s)
    print(s)


def write(path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as fh:
        fh.write(("\n".join(_LOG) + "\n").encode("utf-8").replace(b"\r\n", b"\n"))


def json_path(out_txt):
    if out_txt == OUT:
        return os.path.join(OUTD, "J-10.9-03.json")
    if out_txt.endswith(".run.txt"):
        return out_txt[:-len(".run.txt")] + ".json"
    return os.path.splitext(out_txt)[0] + ".json"


def finish(rc, out, readings):
    p = json_path(out)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as fh:
        json.dump({"pass": rc == 0, "rc": rc, **readings, "blind": BLIND},
                  fh, ensure_ascii=False, indent=1)
    log("  rc=%d" % rc)
    log("  写出: %s" % p)
    write(out)
    return rc


def judge(rows, par, layers, fr):
    fs = []
    S = par["构件"]["竖井"]
    verdict = S["判定"]["值"]

    if not fr["是否新"]:
        fs.append("① 对照.json（生成时刻 %s、mtime %s）比 contours（%s）旧 —— 参照件停在上一趟"
                  % (fr["对照生成时刻"], fr["对照_mtime"], fr["contours_mtime"]))

    # ② 行内恒等式（按读数自己的 3 位精度）
    for r in rows:
        want = round(r["净宽_mm"] * r["净高_mm"] / 1e6, 3)
        if abs(want - r["净面积_m2"]) > 1e-9:
            fs.append("② %s %.1f×%.1f = %.3f m² ≠ 读数 净面积_m2=%.3f"
                      % (r["层"], r["净宽_mm"], r["净高_mm"], want, r["净面积_m2"]))

    # ③ 逐层多重集 == 参数 净空实测 多重集
    want_ms = Counter((round(w, 1), round(h, 1)) for w, h in S["净空实测"]["值"])
    per = {}
    for r in rows:
        per.setdefault(r["层"], []).append((round(r["净宽_mm"], 1), round(r["净高_mm"], 1)))
    for lay in layers:
        got = Counter(per.get(lay, []))
        if got != want_ms:
            fs.append("③ %s 净空多重集与参数.json::竖井/净空实测 不相等：缺 %s／多 %s"
                      "（该层读到 %d 个，参数声明 %d 个）"
                      % (lay, dict(want_ms - got) or "—", dict(got - want_ms) or "—",
                         sum(got.values()), sum(want_ms.values())))

    # ④ 判词逐行一致
    for r in rows:
        if r["判定"] != verdict:
            fs.append("④ %s 判定＝%r，参数.json::竖井/判定.值＝%r —— 判词不一致（判词是数据，不许静默）"
                      % (r["层"], r["判定"], verdict))

    # ④b 判词与留空互锁（读参数表内部，与 ④ 不同源）
    gl, dm = S["国标下限"]["值"], S["层门洞"]["值"]
    if verdict == NO_LIFT:
        if gl is not None:
            fs.append("④b 判定＝「%s」却说 `国标下限.值＝%r` —— 没有井却填着井道尺寸，两条声明自相矛盾"
                      % (verdict, gl))
        if dm is not None:
            fs.append("④b 判定＝「%s」却说 `层门洞.值＝%r` —— 没有井却填着层门洞，两条声明自相矛盾"
                      % (verdict, dm))
    elif gl is None:
        fs.append("④b 判定＝%r（不是说无井）而 `国标下限.值` 是 null —— 说有井却拿不出档位，建不了"
                  % verdict)

    # ⑤ echo：壁厚/壁厚源 + 区间
    wl, wh = S["井壁厚"]["区间"]
    for r in rows:
        if r["壁厚_mm"] != S["井壁厚"]["值"]:
            fs.append("⑤ %s 壁厚_mm=%r，而 参数.json::竖井/井壁厚.值=%r —— 件与参数表脱钩"
                      % (r["层"], r["壁厚_mm"], S["井壁厚"]["值"]))
        if r["壁厚源"] != S["井壁厚"]["标注"]:
            fs.append("⑤ %s 壁厚源=%r，而 井壁厚.标注=%r —— 来源标注脱钩"
                      % (r["层"], r["壁厚源"], S["井壁厚"]["标注"]))
        if not (wl <= r["壁厚_mm"] <= wh):
            fs.append("⑤ %s 壁厚_mm=%r 落在 井壁厚.区间 [%s, %s] 之外"
                      % (r["层"], r["壁厚_mm"], wl, wh))

    # ⑥ 层覆盖 + 层间个数 + 缩没了
    for lay in layers:
        if lay not in per:
            fs.append("⑥ %s 一行竖井读数都没有 —— 这一层的竖井**没量到**（不与「建出来了」同形）" % lay)
    for lay in per:
        if lay not in layers:
            fs.append("⑥ %s 有竖井读数，但 contours/ 里没有这一层" % lay)
    cnt = {k: len(v) for k, v in per.items()}
    if cnt:
        hi = max(cnt.values())
        for lay in sorted(cnt):
            if cnt[lay] != hi:
                fs.append("⑥ %s 竖井 %d 个，而最多的层有 %d 个 —— 层与层个数不等"
                          % (lay, cnt[lay], hi))
    for r in rows:
        if r["缩没了"]:
            fs.append("⑥ %s 的竖井 缩没了=True —— 井被墙吃掉、这一格没建出来（**不是**合规）" % r["层"])

    return fs, {
        "行数": len(rows), "层数": len(per), "件里判词集合": sorted({r["判定"] for r in rows}),
        "参数判词": verdict, "每层竖井数": cnt, "净空多重集_参数": [list(k) for k in want_ms],
        "国标下限_值": gl, "层门洞_值": dm, "层门洞_净高下限_值": S["层门洞_净高下限"]["值"],
        "壁厚_值": S["井壁厚"]["值"], "壁厚_标注": S["井壁厚"]["标注"],
        "缩没了_行": sum(1 for r in rows if r["缩没了"]),
    }


def main():
    global DUIZHAO, PARAM, CONTOURS
    argv = sys.argv[1:]
    out = argv[argv.index("--out") + 1] if "--out" in argv else OUT
    for flag, tgt in (("--duizhao", "DUIZHAO"), ("--param", "PARAM"), ("--contours", "CONTOURS")):
        if flag in argv:
            globals()[tgt] = argv[argv.index(flag) + 1]

    _LOG.clear()
    log("J-10.9-03 · 挂 LIFT/「电梯井」的东西，判词必须在脸上（对照 %s）" % DUIZHAO)

    files = sorted(glob.glob(os.path.join(CONTOURS, "*层.json")))
    lack = [p for p in (DUIZHAO, PARAM) if not os.path.exists(p)] + ([] if files else [CONTOURS])
    if lack:
        log("★ 没量到：缺 %d 件 —— %s ⇒ SKIP(rc=4)"
            % (len(lack), [os.path.basename(m) for m in lack]))
        return finish(4, out, {"n_missing": len(lack),
                               "missing": [os.path.basename(m) for m in lack]})

    dz = json.load(open(DUIZHAO, "r", encoding="utf-8"))
    par = json.load(open(PARAM, "r", encoding="utf-8"))
    rows = dz["竖井"]
    layers = [os.path.basename(p)[:-5] for p in files]
    t_dz, t_c = os.path.getmtime(DUIZHAO), os.path.getmtime(os.path.join(CONTOURS, "1层.json"))
    fr = {"是否新": (t_dz + FRESH_SLACK_S) >= t_c,
          "对照生成时刻": str(dz.get("生成时刻") or ""),
          "对照_mtime": datetime.fromtimestamp(t_dz).strftime("%Y-%m-%d %H:%M:%S"),
          "contours_mtime": datetime.fromtimestamp(t_c).strftime("%Y-%m-%d %H:%M:%S")}
    log("  ① 对照生成时刻 %s ｜ 对照 mtime %s ｜ contours mtime %s ⇒ %s"
        % (fr["对照生成时刻"], fr["对照_mtime"], fr["contours_mtime"],
           "同趟" if fr["是否新"] else "★参照件停在上一趟"))
    log("  读数 %d 行 ｜ contours %d 层 ｜ 参数.json「竖井」%d 条"
        % (len(rows), len(files), len(par["构件"]["竖井"])))
    log("-" * 78)

    base, head = judge(rows, par, layers, fr)
    log("  ⑦ 判词 : **%s**" % head["参数判词"])
    log("     件里判词集合 %s ｜ 每层竖井数 %s ｜ 缩没了 %d 行"
        % (head["件里判词集合"], head["每层竖井数"], head["缩没了_行"]))
    log("     净空多重集（参数声明，逐层必须相同）%s ｜ 国标下限.值=%r ｜ 层门洞.值=%r"
        % (head["净空多重集_参数"], head["国标下限_值"], head["层门洞_值"]))
    log("C1 真件 ⇒ 违反 %d 条" % len(base))
    for x in base:
        log("    " + x)
    bad = list(base)

    def ctl(name, fs_, want):
        new = [x for x in fs_ if x not in base]
        got = sorted({x.split(" ")[0] for x in new})
        ok = bool(new) and got == sorted(want)
        log("  对照 %-22s → %s（新增 %d 条，要 %s，实得 %s）"
            % (name, "✔红" if ok else "✘没红/红错因", len(new), "".join(want), "".join(got) or "—"))
        if not ok:
            bad.append("对照 %s 没按预期红（要 %s，实得 %s，新增 %d 条）"
                       % (name, "".join(want), "".join(got) or "无", len(new)))

    r2 = json.loads(json.dumps(rows))
    # ★ 净宽与净面积**同步改**：只改一个会同时踩到 ②（恒等式）与 ③（多重集），
    #   那条对照就分不开「哪把尺子响了」。同步改之后 ② 自洽，剩下的红只能是 ③。
    r2[0]["净宽_mm"] = 999.0
    r2[0]["净面积_m2"] = round(999.0 * r2[0]["净高_mm"] / 1e6, 3)
    ctl("C2 净宽+面积同步改", judge(r2, par, layers, fr)[0], ["③"])
    r3 = json.loads(json.dumps(rows))
    r3[0]["净面积_m2"] = 9.999
    ctl("C3 净面积改 9.999", judge(r3, par, layers, fr)[0], ["②"])
    r4 = json.loads(json.dumps(rows))
    r4[0]["判定"] = "有电梯井"
    ctl("C4 一行判定改有井", judge(r4, par, layers, fr)[0], ["④"])
    p7 = json.loads(json.dumps(par))
    p7["构件"]["竖井"]["判定"]["值"] = "有客运电梯井"
    ctl("C7 参数判定改有井", judge(rows, p7, layers, fr)[0], ["④", "④b"])
    fr6 = dict(fr)
    fr6["是否新"] = False
    ctl("C6 参照件改旧", judge(rows, par, layers, fr6)[0], ["①"])

    tmp = os.path.join(OUTD, "_shaft_skip_probe.txt")
    env = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    r = subprocess.run([sys.executable, os.path.abspath(__file__),
                        "--param", os.path.join(ROOT, "rebuild", "构件库", "_no_such.json"),
                        "--out", tmp], cwd=ROOT, capture_output=True, env=env)
    log("  对照 %-22s → %s（rc=%d，要 4）"
        % ("C5 参数.json 不在", "✔" if r.returncode == 4 else "✘", r.returncode))
    if r.returncode != 4:
        bad.append("对照 C5 参数.json 不在时没 SKIP（rc=%d，要 4）" % r.returncode)

    log("-" * 78)
    log("J-10.9-03 总判 : %s" % ("PASS" if not bad else "FAIL（%d 条）" % len(bad)))
    for x in bad:
        log("  ✗ " + x)

    readings = dict(head)
    readings.update(fr)
    readings["n_violations"] = len(bad)
    return finish(0 if not bad else 1, out, readings)


if __name__ == "__main__":
    sys.exit(main())
