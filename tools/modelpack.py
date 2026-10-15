# -*- coding: utf-8 -*-
"""模型包 —— 两个平台之间**唯一**的接缝（规范见 规范/模型包格式-v1.md）。

本地建模平台产出「模型包」→ 上传 → 服务器装载。包内四样：**模型 + 料账 + 质检报告 + 元数据**。
★ 包里**没有原始影像**（§6.1 边界纪律 4）。★ **没有质检报告、或质检不过**的包**装不上**（§10.1/§10.2）。

本模块两个口：
  build()    把一个楼栋目录的产物打成模型包（清单 manifest.json 用**字节层**写盘）；
  validate() 装载前校验：任一硬条件不满足即拒绝，并给出**可数的原因码**。
validate 是本步的**交付件** —— 它的分辨力由 gates/J-10.2-01 的正对照证明（塞坏件必须装不上）。
"""
from __future__ import annotations

import hashlib
import json
import os

SCHEMA = "cdut3d-modelpack/1"
QC_SCHEMA = "cdut3d-qc/1"

# ★ 原片 / 相机原始格式（粗筛；权威是 manifest 的 `no_raw_imagery` 声明 + 每件 role，
#   扩展名只是**兜底**，见 validate 的「盲区」注释）。
RAW_CAMERA_EXT = {".cr2", ".cr3", ".nef", ".dng", ".arw", ".raf", ".orf", ".rw2", ".pef", ".srw"}
RAW_IMAGE_EXT = {".jpg", ".jpeg", ".tif", ".tiff", ".heic", ".bmp"}

_ALLOWED_QC_LEVEL = {"PASS", "OK", "WARN"}


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _dump_bytes(path: str, obj) -> None:
    """★ 字节层写盘：utf-8 + LF，绝不让文本模式把行尾翻成 CRLF（铁律 79）。"""
    data = json.dumps(obj, ensure_ascii=False, indent=1).encode("utf-8")
    data = data.replace(b"\r\n", b"\n")
    with open(path, "wb") as f:
        f.write(data)


def build(building: str, out_pkg: str, artifacts: list, qc: dict,
          campus_id: str = "cdut-main", created_at: str = "", lod: dict = None) -> str:
    """artifacts: [{"role","src","rel"}]，src 是磁盘文件、rel 是包内相对路径。

    lod: 模型精细度声明（标准族 / 等级 / 与本包的适用关系 / 引用口径）。
         ★ 必须是**从标准正本抄来的**，不许自造等级名 —— 见 规范/模型包格式-v1.md §2.1。
    """
    os.makedirs(out_pkg, exist_ok=True)
    listed = []
    for a in artifacts:
        rel = a["rel"].replace("\\", "/")
        dst = os.path.join(out_pkg, rel.replace("/", os.sep))
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        # 拷贝用字节层
        with open(a["src"], "rb") as fin, open(dst, "wb") as fout:
            fout.write(fin.read())
        listed.append({"role": a["role"], "path": rel,
                       "bytes": os.path.getsize(dst), "sha256": sha256_file(dst)})

    qc_rel = "qc/%s-qc.json" % building
    qc_abs = os.path.join(out_pkg, qc_rel.replace("/", os.sep))
    os.makedirs(os.path.dirname(qc_abs), exist_ok=True)
    _dump_bytes(qc_abs, qc)
    # ★ 质检件也进指纹（2026-10-12 补）：原 `qc` 块只记 path/schema/level，**没有字节与哈希**
    #   ⇒ 包指纹对「质检报告被换掉/过期」**全盲** —— 正是本包这次要修的那类毛病（质检说的与件不符）。
    #   计入 bytes+sha256 后，改一个判词也会改包指纹；validate() 侧同步核（QC_SHA）。
    qc_block = {"path": qc_rel, "schema": qc.get("schema"), "level": qc.get("level"),
                "bytes": os.path.getsize(qc_abs), "sha256": sha256_file(qc_abs)}

    manifest = {
        "schema": SCHEMA,
        "campus_id": campus_id,
        "building_id": building,
        "created_at": created_at,
        "no_raw_imagery": True,          # 声明：包内无原始影像（§6.1 纪律 4）
        "lod": lod,                      # ★ 模型精细度声明（标准族+等级+适用关系，防「等级靠猜」）
        "artifacts": listed,
        "qc": qc_block,
    }
    # 包指纹：对 manifest 去掉自身字段后规范化再哈希（可复现、不手打）
    core = {k: v for k, v in manifest.items()}
    manifest["package_sha256"] = hashlib.sha256(
        json.dumps(core, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()

    mpath = os.path.join(out_pkg, "manifest.json")
    _dump_bytes(mpath, manifest)
    # ★ 字节层落盘后，用**另一个解析器**再读一遍（铁律 79）
    with open(mpath, "rb") as f:
        assert b"\r\n" not in f.read(), "manifest 落盘后被写进了 CRLF"
    json.load(open(mpath, encoding="utf-8"))
    return mpath


def _load_json(p):
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def validate(pkg_dir: str) -> dict:
    """返回 {"ok": bool, "reasons": [...], "counts": {...}}。任一硬条件不满足即 ok=False。"""
    reasons = []
    mpath = os.path.join(pkg_dir, "manifest.json")
    if not os.path.isfile(mpath):
        return {"ok": False, "reasons": [("MANIFEST_MISSING", "-")], "counts": {}}
    try:
        man = _load_json(mpath)
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "reasons": [("MANIFEST_BAD_JSON", str(e)[:60])], "counts": {}}

    if man.get("schema") != SCHEMA:
        reasons.append(("SCHEMA_MISMATCH", str(man.get("schema"))))
    if not man.get("campus_id") or not man.get("building_id"):
        reasons.append(("IDENTITY_MISSING", "campus_id/building_id"))

    arts = man.get("artifacts") or []
    # ★ 非空断言：空清单的绿不算绿（§10.0.2-3）
    if not arts:
        reasons.append(("ARTIFACTS_EMPTY", "0"))
    n_model = 0
    for a in arts:
        rel = a.get("path", "")
        ap = os.path.join(pkg_dir, rel.replace("/", os.sep))
        if not os.path.isfile(ap):
            reasons.append(("ARTIFACT_MISSING", rel))
            continue
        if os.path.getsize(ap) != a.get("bytes"):
            reasons.append(("ARTIFACT_SIZE", rel))
        elif sha256_file(ap) != a.get("sha256"):
            reasons.append(("ARTIFACT_SHA", rel))
        if a.get("role") == "model":
            n_model += 1
    if n_model == 0:
        reasons.append(("NO_MODEL_ARTIFACT", "-"))

    # ★ 精细度声明（lod）：没写 = 装载口不知道自己在显示什么等级 ⇒ 拒。
    #   只查**结构**（族/等级/引用三件套齐不齐、等级串非空），不查等级名对不对 —— 那要对标准正本。
    lod = man.get("lod")
    if not isinstance(lod, dict):
        reasons.append(("LOD_MISSING", str(type(lod).__name__)))
    else:
        for _k in ("standard", "level", "relation", "citations"):
            if not lod.get(_k):
                reasons.append(("LOD_BAD", _k))

    # 原始影像：先看显式声明，再走兜底启发式
    if man.get("no_raw_imagery") is not True:
        reasons.append(("NO_RAW_DECLARATION", "-"))
    for root, _dirs, files in os.walk(pkg_dir):
        for fn in files:
            ext = os.path.splitext(fn)[1].lower()
            rel = os.path.relpath(os.path.join(root, fn), pkg_dir).replace("\\", "/")
            raw_dir = any(seg in ("raw", "原片", "photos", "_photos") for seg in rel.split("/"))
            if ext in RAW_CAMERA_EXT or raw_dir or (ext in RAW_IMAGE_EXT and "texture" not in rel):
                reasons.append(("RAW_IMAGERY_PRESENT", rel))

    # 质检：缺报告 / 不过 / 没有正对照 —— 任一条都装不上
    qc_meta = man.get("qc") or {}
    qrel = qc_meta.get("path")
    if not qrel:
        reasons.append(("NO_QC_REPORT", "-"))
    else:
        qp = os.path.join(pkg_dir, qrel.replace("/", os.sep))
        if not os.path.isfile(qp):
            reasons.append(("NO_QC_REPORT", qrel))
        else:
            # ★ 质检件必须**在指纹之内**：manifest 的 qc 块记了 bytes/sha256，这里逐个核。
            #   老包（2026-10-12 之前）没有这两键 ⇒ 报 QC_UNPINNED 而不是静默放过。
            want_b, want_h = qc_meta.get("bytes"), qc_meta.get("sha256")
            if want_b is None or want_h is None:
                reasons.append(("QC_UNPINNED", "manifest.qc 缺 bytes/sha256"))
            else:
                if os.path.getsize(qp) != want_b:
                    reasons.append(("QC_SIZE", str(os.path.getsize(qp))))
                elif sha256_file(qp) != want_h:
                    reasons.append(("QC_SHA", want_h[:16]))
            qc = _load_json(qp)
            if qc.get("schema") != QC_SCHEMA:
                reasons.append(("QC_BAD_SCHEMA", str(qc.get("schema"))))
            pc = qc.get("positive_control") or {}
            if pc.get("fired") is not True:
                reasons.append(("QC_NO_POSITIVE_CONTROL", str(pc.get("fired"))))
            lvl = str(qc.get("level", "")).upper()
            if lvl not in _ALLOWED_QC_LEVEL:
                reasons.append(("QC_LEVEL_FAIL", lvl or "空"))
            g = qc.get("gauge") or {}
            v, th = g.get("value"), g.get("threshold")
            if v is None or th is None:
                reasons.append(("QC_NO_GAUGE", "-"))
            elif float(v) < float(th):
                reasons.append(("QC_BELOW_THRESHOLD", "%.4f<%.4f" % (v, th)))

    return {"ok": not reasons, "reasons": reasons,
            "counts": {"artifacts": len(arts), "model": n_model}}
