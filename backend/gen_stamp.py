# -*- coding: utf-8 -*-
"""生成时间账本：**谁生成、谁盖章**，落在 `data/buildings/<name>/generated.json`。

## 为什么不能靠 mtime，也不能在产物内部盖章

· **mtime 不是内容**（本仓已有教训 `mtime-change-is-not-content-change`）：复制、同步、
  还原都会改 mtime 而内容一字未动 ⇒ 「mtime 很新」推不出「刚生成」。
· **产物内部插不进**，三处各有一个硬理由：
    1. GLB 的 glTF `asset` 头是 **trimesh 自己写的**（`glb_common.export_glb` 末尾就一句
       `mesh.export(path, file_type="glb")`），没有可插的槽；
    2. SU 的 `<name>_floors.skp` 是 **SketchUp 自己写的**，外部插不进；
    3. `data/su/<name>.json` 的 `meta` 是**理化楼逐字节复现的验收基线**
       （重出后必须与建体时吃的那一份 sha256 相同）—— 往里加时间戳会把那条基线打掉。
  ⇒ 所以用**同目录的一份账本**，形状与既有的 `data/su/_meta.json` 一致。

## 账本的形状与两条纪律

    {"glb":    {"at": "...", "file": "c006-building.glb", "bytes": 18179228,
                "sha256_12": "e21c6b6841b1", "by": "run_building", "source": "generator"},
     "floors": {"at": "...", "n": 11, "by": "run_building", "source": "generator"}}

字段名一律用 `by`（谁盖的）而不是 `path` —— `path` 在这套代码里指的是**产物文件的路径**，
两者混用会撞（第一版 `backfill(name, part, path, **extra)` 就被我自己传的 `path=` 撞掉了）。

· **只增不改**：同一栋被重跑时覆盖的是**同一把键**，别的键原样留着。
· **「没记」与「记了」必须能分开**：读不到就是 `None`，调用方印「未记录」，
  **不许兜底成今天**（铁律 60：分母为 0 的 k/N 是最像结论的假数）。
· `source` 只有两个合法值：`generator`（生成方当场盖的）/ `mtime-backfill`
  （从产物 mtime 回填的**推算值**）。两者在页面上必须能分开 —— 回填值不是生成时刻。

退出码无关；本模块只提供函数。
"""
import datetime
import hashlib
import io
import json
import os

from paths import BUILDINGS

LEDGER = "generated.json"

# `source` 的两个合法取值。回填值**不是**生成时刻，只是「那份文件最后一次被写」的推算。
SRC_GENERATOR = "generator"
SRC_BACKFILL = "mtime-backfill"


def _now():
    """本地时区的带偏移 ISO 秒级时间。用 `astimezone()` 而不是 `utcnow()` ——
    账本是给人看的，用户问「什么时候生成的」问的是本地钟。"""
    return datetime.datetime.now().astimezone().isoformat(timespec="seconds")


def ledger_path(name, base=None):
    """账本落点。

    `base` = **这栋楼的数据目录**（就是 index.json 里 `dir` 那一列）。
    · 批次楼 → `data/buildings/<name>/`（= `dirname(p.out_dir)`）
    · 理化楼（注册表楼）→ `data/`（= `dirname(p.out_dir)`，它的产物就在 data/ 根）
    默认 `data/buildings/<name>/`，但**所有调用方都应当显式传 `base=dirname(p.out_dir)`** ——
    否则理化楼会被写进一个新建的 `data/buildings/lihua/` 里（那目录连 profile.json 都没有）。
    """
    if base is None:
        base = os.path.join(str(BUILDINGS), name)
    return os.path.join(base, LEDGER)


def read(name, base=None):
    """读账本。**读不到就返回 {}**（不抛、不编）。"""
    p = ledger_path(name, base)
    if not os.path.exists(p):
        return {}
    try:
        with io.open(p, encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def digest(path, n=12):
    """文件内容的短指纹。★ 空文件/不存在返回 **None**，绝不返回 `sha256("")[:12]` ——
    那是个常数，而常数会让「前后都是空」读成「未变」（铁律 45）。"""
    if not os.path.exists(path):
        return None
    if os.path.getsize(path) == 0:
        return None
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()[:n]


def _write(name, cur, base=None):
    p = ledger_path(name, base)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = p + ".tmp"
    with io.open(tmp, "w", encoding="utf-8", newline="\n") as f:
        json.dump(cur, f, ensure_ascii=False, indent=1, sort_keys=True)
    os.replace(tmp, p)


def stamp(name, part, base=None, source=SRC_GENERATOR, **extra):
    """把 `part`（如 "glb" / "floors" / "su"）这一格盖上时间戳。

    写盘是 **同目录临时文件 + `os.replace`**（原子），并且显式 `newline="\\n"` ——
    文本模式默认会把 LF 翻成 CRLF，+1 字节/行，事后看起来像「改好了」（铁律 79）。
    返回这一格的内容，方便调用方顺手打印。
    """
    cur = read(name, base)
    cell = dict(extra)
    cell["at"] = _now()
    cell["source"] = source
    cur[part] = cell
    _write(name, cur, base)
    return cell


def stamp_file(name, part, path, base=None, **extra):
    """`stamp` 的常用形态：顺手把落盘产物的 `bytes` / `sha256_12` 一起记下来。

    ★ 0 字节**不是**「记一笔空指纹」，而是**缺陷**：`bytes` 记 0、`sha256_12` 记 `None`，
      并在 `error` 里写明白。这样「产物是空的」不会被读成「产物生成好了」。
    """
    size = os.path.getsize(path) if os.path.exists(path) else None
    extra["file"] = os.path.basename(path)
    extra["bytes"] = size
    extra["sha256_12"] = digest(path)
    if not size:
        extra["error"] = "产物不存在或 0 字节"
    return stamp(name, part, base, **extra)


def backfill(name, part, artifact, base=None, **extra):
    """从**产物 mtime** 回填一格，并把 `source` 标成 `mtime-backfill`。

    回填只做一件事：让账本在有真实生成记录之前**不是空的**。它写下的时刻是
    「那份文件最后一次被写」，**不是**生成时刻（复制/同步也会改 mtime）——
    所以它带的 `source` 与生成方盖的不一样，页面据此分开显示。

    ⚠ 第三个参数叫 `artifact` 不叫 `path`：调用方往往还要在 `**extra` 里带一个
      说明来源的字段，两个都叫 `path` 会 `TypeError`（第一版就这么撞的）。
    """
    if not os.path.exists(artifact):
        return None
    cur = read(name, base)
    if part in cur:
        return cur[part]          # 已有（可能是生成方盖的）⇒ 不覆盖
    t = datetime.datetime.fromtimestamp(os.path.getmtime(artifact)).astimezone()
    extra["at"] = t.isoformat(timespec="seconds")
    extra["source"] = SRC_BACKFILL
    cur[part] = extra
    _write(name, cur, base)
    return extra
