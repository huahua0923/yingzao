# -*- coding: utf-8 -*-
"""把 `packs/<场区>/<楼栋>/` 下**已经打好的包**汇成一张楼栋清单 `packs/index.json`。

给谁用：展示页 `demo/building.html` 的楼栋下拉 —— 它**不许**把楼栋名手打在前端，
        也不许调后端（这页是纯静态、零构建）。清单一处生成、页面只读。

★★ 为什么不并进 `demo/build_pack.py` 里一起跑：重打一遍包 ⇒ `manifest.created_at` 变 ⇒
   **包指纹（package_sha256）跟着变**，而指纹被若干判据钉着 ⇒ 为了「页面上多一个下拉」
   把整包重打、让一串绿判据变红，**代价不对等**。本脚本**只读包、只写 `packs/index.json`
   这一个文件**，跑完包内任何一件的字节数/哈希都必须不变（`--check` 就是验这一条）。
   ⇒ `build_pack.py` 末尾调 `refresh()`：将来重打包时清单一并刷新，**不会过期**
     （铁律 017：源码改了那边不改，下次跑就把清单冲成旧的）。

★ 卡里每一个数**都从盘上读**（manifest / meta/layering.json / qc/*.json / meta/profile.json），
  一个都不手打（铁律 103 / 018）。
★ 显示名取 `meta/profile.json::title`（盘上是「第六教学楼（逸夫楼）」；没有就退回楼栋号）。
  ⚠⚠ 这个包里**有两套层高**：`meta/profile.json::layer_height` 与 `meta/spec.json::floor_h`
     **都是 3.5 m** —— 那是 **gym3d 那条链的常量，与交付件无关**（换链换的正是这一条）。
     **交付件的层高是 `meta/layering.json::floor_h_m`（现算自落盘件 = 4.0 m）**。
     页面只许引用后者；读前者就是拿链外的常量当交付件的读数（铁律 192）。
"""
import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8")

CDUT = r"D:\项目\cdut3d"
PACKS = os.path.join(CDUT, "packs")
OUT = os.path.join(PACKS, "index.json")
# ★★ 2026-10-17 用户令「理化楼是完全按照 cdut3d 的线路生成，和其他没有关系」：
#   理化楼 c005 **不是外部件** —— 它已按本仓口径打成 `packs/cdut-main/c005/`
#   （见 `demo/build_pack_c005.py`），与 c006 并列在同一张清单里。
#   ⇒ 原来那个 `external_buildings.json` 与 `external` 键**整段删掉**：留着等于同一栋楼
#     在页面上下拉里出现两次、两套说法（一次说「本仓的包」、一次说「别家的查看器」）。


def _read_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _dump_bytes(path, obj):
    """★ 字节层写盘 + 强制 LF（铁律 79）：文本模式在 Windows 上会把 LF 翻成 CRLF，
    多出来的字节会让「有没有动过」这类比对永远不等。"""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    data = json.dumps(obj, ensure_ascii=False, indent=1).encode("utf-8").replace(b"\r\n", b"\n")
    with open(path, "wb") as f:
        f.write(data)


def _row(pack_dir, campus, bid):
    man = _read_json(os.path.join(pack_dir, "manifest.json"))
    arts = man.get("artifacts") or []
    model = next((a for a in arts if a.get("role") == "model"), None)

    title, blind = bid, []
    prof_p = os.path.join(pack_dir, "meta", "profile.json")
    if os.path.isfile(prof_p):
        try:
            title = _read_json(prof_p).get("title") or bid
        except Exception as e:                                   # noqa: BLE001
            blind.append("meta/profile.json 读不动：%s" % e)
    else:
        blind.append("包里没有 meta/profile.json ⇒ 显示名退回楼栋号")

    # ★ 楼层/层高/标高只从 layering.json 来（见文件头那段 ⚠⚠：profile/spec 里那两套 3.5 不算数）
    floors = {"n_floors": None, "floor_h_m": None, "elevation_m": None, "up_axis": None,
              "source_model": None}
    lay_p = os.path.join(pack_dir, "meta", "layering.json")
    if os.path.isfile(lay_p):
        lay = _read_json(lay_p)
        floors = {"n_floors": lay.get("n_floors"), "floor_h_m": lay.get("floor_h_m"),
                  "elevation_m": lay.get("elevation_m"), "up_axis": lay.get("up_axis"),
                  "source_model": lay.get("source_model")}
        if lay.get("floor_h_m") is None:
            blind.append("meta/layering.json 里没有 floor_h_m")
    else:
        blind.append("包里没有 meta/layering.json ⇒ 楼层/层高/标高这一格为 null（**不是 0**）")

    qc = {"level": None, "gauge": None, "positive_control_value": None, "n_blind_spots": None}
    qc_rel = (man.get("qc") or {}).get("path")
    if qc_rel and os.path.isfile(os.path.join(pack_dir, qc_rel)):
        q = _read_json(os.path.join(pack_dir, qc_rel))
        qc = {"level": q.get("level"),
              "gauge": {k: (q.get("gauge") or {}).get(k)
                        for k in ("name", "value", "threshold", "unit", "weakest_floor_by_linecov")},
              "positive_control_value": (q.get("positive_control") or {}).get("value"),
              "n_blind_spots": len(q.get("blind_spots") or [])}
    else:
        blind.append("包里找不到 manifest 声明的质检件（qc.path=%s）" % qc_rel)

    return {
        "campus": man.get("campus_id") or campus,
        "id": man.get("building_id") or bid,
        "raw_id": bid,
        "title": title,
        "created_at": man.get("created_at"),
        "package_sha256": man.get("package_sha256"),
        "bytes": sum(a.get("bytes") or 0 for a in arts),
        "n_artifacts": len(arts),
        "model": ({"path": model.get("path"), "bytes": model.get("bytes"),
                   "sha256": model.get("sha256")} if model else None),
        "floors": floors,
        "qc": qc,
        "pack_dir": "packs/%s/%s" % (campus, bid),
        "blind_spots": blind,
    }


def scan(root=None):
    root = root or PACKS
    rows = []
    if not os.path.isdir(root):
        return rows
    for campus in sorted(os.listdir(root)):
        cdir = os.path.join(root, campus)
        if not os.path.isdir(cdir):
            continue
        for bid in sorted(os.listdir(cdir)):
            pdir = os.path.join(cdir, bid)
            # ★ 没有 manifest.json 的目录**不进清单**：那是「没打完的包」，
            #   列出来等于把一个半成品当成可看的楼栋。
            if os.path.isfile(os.path.join(pdir, "manifest.json")):
                rows.append(_row(pdir, campus, bid))
    return rows


def _fingerprints(root=None):
    """包内每一件的 (相对路径 → 字节数, 修改时刻)。`--check` 用它证明本脚本没碰过包。"""
    root = root or PACKS
    out = {}
    for campus in sorted(os.listdir(root)):
        cdir = os.path.join(root, campus)
        if not os.path.isdir(cdir):
            continue
        for bid in sorted(os.listdir(cdir)):
            pdir = os.path.join(cdir, bid)
            if not os.path.isdir(pdir):
                continue
            for dp, _dn, fns in os.walk(pdir):
                for fn in fns:
                    fp = os.path.join(dp, fn)
                    st = os.stat(fp)
                    out[os.path.relpath(fp, root).replace("\\", "/")] = (st.st_size, st.st_mtime_ns)
    return out


def refresh(root=None, out=None):
    root, out = root or PACKS, out or OUT
    rows = scan(root)
    _dump_bytes(out, {
        "schema": "cdut3d-packindex/1",
        "campus_root": "packs",
        "n": len(rows),
        "note": "由 demo/build_index.py 从盘上现算；页面（demo/building.html）只读这一份。"
                "★ 只列**有 manifest.json 的**目录；`blind_spots` 非空 = 该包有格子量不到"
                "（量不到一律写 null，**不写 0**）。",
        "shapes": {
            "id": "<场区>/<楼栋>，直接进 `demo/index.html?pack=<id>`",
            "floors.floor_h_m": "★ 只取自 meta/layering.json（现算自落盘件）；"
                                "meta/profile.json::layer_height 与 meta/spec.json::floor_h "
                                "里那两套 3.5 m 是 gym3d 那条链的常量，**不是**本包的读数",
        },
        "packs": rows,
    })
    return rows


def main(argv):
    if "--check" in argv:
        before = _fingerprints()
        rows = refresh()
        after = _fingerprints()
        if before != after:
            only = sorted(set(before) ^ set(after))
            diff = sorted(k for k in set(before) & set(after) if before[k] != after[k])
            print("★ 本脚本动了包内文件（越界）：新增/删除 %s · 内容变了 %s" % (only, diff))
            return 1
        print("--check 通过：包内 %d 件，一个字节都没动" % len(after))
    else:
        rows = refresh()
    print("楼栋清单: %d 个包 ⇒ %s" % (len(rows), OUT))
    for r in rows:
        f = r["floors"] or {}
        print("   %s/%s  %s  ·  %s MB / %s 件  ·  层 %s × %s m  ·  标高 %s  ·  QC %s"
              % (r["campus"], r["id"], r["title"], round((r["bytes"] or 0) / 1e6, 1),
                 r["n_artifacts"], f.get("n_floors"), f.get("floor_h_m"),
                 f.get("elevation_m"), r["qc"]["level"]))
        for b in r["blind_spots"]:
            print("      ⚠ %s" % b)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
