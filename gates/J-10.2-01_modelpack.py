# -*- coding: utf-8 -*-
"""判据 J-10.2-01 —— 模型包装载口（出口门：装一个**质检不过**的包必须被拒）。

判据（§10.1/§10.2）：没有质检报告的包装不上；质检不过的包装不上；件被动过装不上。
量具（写明）：tools/modelpack.py validate()；单位=原因条数；阈值=0（合格包必须 0 条硬伤）。
量具盲区（声明）：
  · 只按扩展名 / 目录名粗筛**原始影像**；识别不出一份「改名叫 .bin 的原片」 ⇒ 权威是 manifest
    的 `no_raw_imagery` 声明，扩展名只是兜底（见 modelpack.validate 注释）。
  · 只校验 manifest **列出的**件；对包内**没登记**的文件（除影像外）不判 ⇒ 不告发「夹带私货」。
正对照（必配）：① 合格包 ⇒ **放行**；② 质检 level=FAIL ⇒ **拒**；③ 正对照未触发 ⇒ **拒**；
  ④ 件被改一个字节 ⇒ **拒**；⑤ 塞一张 .jpg ⇒ **拒**；⑥ 抽掉质检报告 ⇒ **拒**；
  ⑦ 抽掉精细度声明 lod ⇒ **拒**；⑧ lod 缺键 ⇒ **拒**；
  ⑨ **质检件被同长度换字节** ⇒ **拒**（只可能由 `QC_SHA` 抓到 —— 尺寸不变、内容检查也全过）。
  九条里**任一条不按预期** ⇒ 判据没有分辨力，作废。
三态：OK / FAIL / SKIP。
"""
from __future__ import annotations

import json
import os
import shutil
import sys

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, r"D:\项目\cdut3d\tools")
from modelpack import build, validate, QC_SCHEMA, SCHEMA  # noqa: E402

BLD = "c006"
SRC = os.path.join(r"D:\项目\gym3d\gym3d\data\buildings", BLD)
ROOT = os.path.join(r"C:\Users\Administrator\_scratch", "_gate_modelpack")
OUTDIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_out")
_LOG = []


def log(*a):
    s = " ".join(str(x) for x in a)
    print(s)
    _LOG.append(s)


# ★ 为什么落 json（2026-10-14 用户明令；口径照抄同目录 J-10.2-02）：
#   台账页 demo/sys.html（生成器 tools/build_sys_page.py）对每条判据取**三路互相独立
#   的读数**：① `gates/_out/<编号>.json` 的 `pass` ② run.txt 的 `rc=` ③ run.txt 的判词行。
#   本闸原先**只落 run.txt、不落 json** ⇒ 页上这条只有两路、「字段·顶层字段」一节是空的。
#   ★ 这里**只把已经算出来的数写出去**，判据的比较/阈值/遍历一个都不动，rc 原样透传。
#   ★ 键名与 J-10.2-02 对齐（pass/rc/…/blind），落盘严格 JSON：不许裸 NaN/Infinity
#     （tools/lint_json_strict.py 是页面读 json 的前置守卫，见铁律 123）。
def _write_json(rc, **kv):
    d = {"pass": rc == 0, "rc": rc}
    d.update(kv)
    os.makedirs(OUTDIR, exist_ok=True)
    p = os.path.join(OUTDIR, "J-10.2-01.json")
    with open(p, "w", encoding="utf-8") as f:      # indent=1、ensure_ascii=False，与仓内一致
        json.dump(d, f, ensure_ascii=False, indent=1)
    print("  写出:", p)


def good_qc():
    # ★ QC 数值取自方案 §7.10 已实测的 c006 方法数（出处 libs3d\c006\c006_v8_walls_score8_lift.json）：
    #   本判据量的是**装载口有没有分辨力**，不是这次有没有真算出这个 IoU。
    return {
        "schema": QC_SCHEMA, "building": BLD, "level": "WARN",
        "gauge": {"name": "同口径 IoU", "value": 0.9883, "threshold": 0.95, "unit": "ratio"},
        "positive_control": {"fired": True, "perturbation": "墙厚2倍假件",
                             "value": 0.689, "expect": "掉到 ~0.69"},
        "blind_spots": ["只比墙体栅格；对门窗柱全盲"],
        "records": [{"floor": i} for i in range(11)],
    }


def good_lod():
    # ★ 精细度声明：等级串抄标准正本（技术文件—12），本判据量的是**装载口认不认这个字段**，
    #   不是这次等级名对不对。四个键必须齐（规范 模型包格式-v1.md §2.1）。
    return {"schema": "cdut3d-lod/1",
            "standard": {"name": "城市三维模型（LOD1.3 级）快速构建技术规定（试行）",
                         "id": "技术文件—12", "issued": "2023-09", "tier": "国家级"},
            "level": ">=LOD1.3",
            "relation": "超出适用范围：本包为构件级白模，精细度高于 LOD1.3 棱柱体",
            "citations": {"external": "CH/T 9024-2014", "national_check": "GB/T 18316-2008",
                          "process": "两级检查+一级验收+成果核验；本包现处自检层"}}


def artifacts():
    return [
        {"role": "model", "src": os.path.join(SRC, "c006-building.glb"), "rel": "model/c006-building.glb"},
        {"role": "ledger", "src": os.path.join(SRC, "c006-audit.json"), "rel": "ledger/c006-audit.json"},
        {"role": "meta", "src": os.path.join(SRC, "spec.json"), "rel": "meta/spec.json"},
    ]


def reasons_of(v):
    return {c for c, _ in v["reasons"]}


def main():
    os.makedirs(OUTDIR, exist_ok=True)
    if os.path.isdir(ROOT):
        shutil.rmtree(ROOT)
    os.makedirs(ROOT)
    good = os.path.join(ROOT, "pkg_good")
    log("建合格包（真 c006 件：GLB 28MB + audit + spec）…")
    build(BLD, good, artifacts(), good_qc(), created_at="2026-10-12T00:00:00+08:00", lod=good_lod())
    v = validate(good)
    log("  合格包 validate →", "放行 ok" if v["ok"] else "★被拒: %s" % v["reasons"], v["counts"])

    cases = []  # (名, 期望原因码集合, 构造目录)

    # ② 质检 level=FAIL（模拟 2× 墙假件：IoU 掉到 0.689）
    d = os.path.join(ROOT, "pkg_qc_fail"); shutil.copytree(good, d)
    qp = os.path.join(d, "qc", "c006-qc.json")
    q = json.load(open(qp, encoding="utf-8"))
    q["level"] = "FAIL"; q["gauge"]["value"] = 0.689
    json.dump(q, open(qp, "w", encoding="utf-8"), ensure_ascii=False)
    cases.append(("QC level=FAIL", {"QC_LEVEL_FAIL", "QC_BELOW_THRESHOLD"}, d))

    # ③ 正对照未触发
    d = os.path.join(ROOT, "pkg_no_ctrl"); shutil.copytree(good, d)
    qp = os.path.join(d, "qc", "c006-qc.json")
    q = json.load(open(qp, encoding="utf-8")); q["positive_control"]["fired"] = False
    json.dump(q, open(qp, "w", encoding="utf-8"), ensure_ascii=False)
    cases.append(("正对照未触发", {"QC_NO_POSITIVE_CONTROL"}, d))

    # ④ 件被改一个字节
    d = os.path.join(ROOT, "pkg_tamper"); shutil.copytree(good, d)
    with open(os.path.join(d, "ledger", "c006-audit.json"), "ab") as f:
        f.write(b" ")                      # 追加一个空格 ⇒ 尺寸变、sha 变
    cases.append(("件被改一字节", {"ARTIFACT_SIZE", "ARTIFACT_SHA"}, d))

    # ⑤ 塞一张 .jpg（原始影像）
    d = os.path.join(ROOT, "pkg_rawimg"); shutil.copytree(good, d)
    os.makedirs(os.path.join(d, "raw"), exist_ok=True)
    with open(os.path.join(d, "raw", "DJI_0001.jpg"), "wb") as f:
        f.write(b"\xff\xd8\xff")
    cases.append(("塞一张原片 .jpg", {"RAW_IMAGERY_PRESENT"}, d))

    # ⑥ 抽掉质检报告
    d = os.path.join(ROOT, "pkg_no_qc"); shutil.copytree(good, d)
    m = json.load(open(os.path.join(d, "manifest.json"), encoding="utf-8"))
    m.pop("qc", None)
    json.dump(m, open(os.path.join(d, "manifest.json"), "w", encoding="utf-8"), ensure_ascii=False)
    cases.append(("抽掉质检报告", {"NO_QC_REPORT"}, d))

    # ⑦ 抽掉精细度声明 lod（← 规范加严后，没声明的包装不上）
    d = os.path.join(ROOT, "pkg_no_lod"); shutil.copytree(good, d)
    m = json.load(open(os.path.join(d, "manifest.json"), encoding="utf-8"))
    m.pop("lod", None)
    json.dump(m, open(os.path.join(d, "manifest.json"), "w", encoding="utf-8"), ensure_ascii=False)
    cases.append(("抽掉 lod 声明", {"LOD_MISSING"}, d))

    # ⑧ lod 缺键（citations 被挖空）
    d = os.path.join(ROOT, "pkg_lod_bad"); shutil.copytree(good, d)
    m = json.load(open(os.path.join(d, "manifest.json"), encoding="utf-8"))
    m["lod"].pop("citations", None)
    json.dump(m, open(os.path.join(d, "manifest.json"), "w", encoding="utf-8"), ensure_ascii=False)
    cases.append(("lod 缺 citations", {"LOD_BAD"}, d))

    # ⑨ ★ 质检件被**同长度**改掉（改的还不是 validate 看的字段）⇒ 尺寸不变、内容检查全过，
    #    **只有指纹**能抓。★ 2026-10-12 加：原 manifest.qc 只记 path/schema/level，包里质检
    #    **不在 package_sha256 之内** ⇒ 这一条在「加钉」之前是**绿**的（铁律 137：名单漏主体则永远绿）。
    d = os.path.join(ROOT, "pkg_qc_swap"); shutil.copytree(good, d)
    qp = os.path.join(d, "qc", "c006-qc.json")
    raw = open(qp, "rb").read()
    assert b'"c006"' in raw, "构造失败：质检件里没有可同长替换的串"
    n = raw.count(b'"c006"')
    open(qp, "wb").write(raw.replace(b'"c006"', b'"c007"'))
    cases.append(("质检件同长换字节 x%d" % n, {"QC_SHA"}, d))

    ok = v["ok"]
    log("\n---- 正对照（每一条都必须按预期变红）----")
    case_recs = []                       # ★ 只加：把每条正对照的实测读数收下来落 json（判定逻辑不动）
    for name, expect, path in cases:
        rv = validate(path)
        got = reasons_of(rv)
        fired = (not rv["ok"]) and bool(expect & got)
        ok = ok and fired
        log("  %-16s → %s  期望⊆%s 实得%s" % (
            name, "✔拒" if not rv["ok"] else "★放行了", sorted(expect), sorted(got)))
        if not fired:
            log("     ★该拒没拒/原因码不符")
        case_recs.append({"case": name, "expect": sorted(expect), "got": sorted(got),
                          "rejected": not rv["ok"], "fired": fired})

    log("\n===== 判词 =====")
    log("合格包放行 且 %d 条坏件全被拒 :" % len(cases), "PASS" if ok else "FAIL")
    log("J-10.2-01 总判 :", "PASS" if ok else "FAIL")

    with open(os.path.join(OUTDIR, "J-10.2-01.run.txt"), "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(_LOG) + "\n")

    # ★ rc 与改前**逐位相同**：仍是 `0 if ok else 1`，只是先记账再返回。
    rc = 0 if ok else 1
    _write_json(rc,
                good_pack_ok=v["ok"], good_counts=v["counts"],
                n_expected=len(cases),
                n_rejected=sum(1 for r in case_recs if r["rejected"]),
                n_fired=sum(1 for r in case_recs if r["fired"]),
                cases=case_recs,
                blind=["只按扩展名/目录名粗筛原始影像：识别不出「改名叫 .bin 的原片」"
                       "⇒ 权威是 manifest 的 no_raw_imagery 声明，扩展名只是兜底",
                       "只校验 manifest 列出的件；对包内没登记的文件（除影像外）不判"
                       "⇒ 不告发「夹带私货」"])
    return rc


sys.exit(main())
