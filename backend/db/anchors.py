# -*- coding: utf-8 -*-
"""体块 ↔ 楼栋 的**锚点**表 —— 校园数字孪生平台的"身份层"（PostgreSQL / lihua_twin）。

## 为什么需要这张表（而不是把楼名写进几何里）

几何是**量出来的**，身份是**登记出来的**，两者来源不同、更新节奏也不同：

    几何   实景 DSM/正射（或 CAD 轮廓）派生的体块，可以一个月重算一次
    身份   `data/buildings/index.json` 那 93 条，人写的、不随几何走
    锚点   本表：把上面两样**对上**，一行一个体块

本仓已经用一轮时间量明：**体块 ↔ 93 栋楼之间的那个变换在盘上不存在**
（`REPORT_building_placement.md` 原文「覆盖 gym3d 楼栋 0 / 95」）。所以 identity
**只能**由人工锚点建立 —— 这正是用户 2.2 那句「我可以把位置基本上 1 对 1 地给你点上」。

把锚点单独存一张表（而不是给几何文件的每条塞一个 name 字段）的全部意义是：
**重算几何不会抹掉身份**。几何文件可以随便推倒重来，这张表一行不动。
与 `room_source` / `room_manual` 的分层是同一个道理（见 rooms_registry.py）。

## 两条铁律

1. ★ `block_id` 是体块的**身份**，必须是"从实物读回来的那个串"
   （模拟期是 `blk-001`；接上真几何之后是 `ringsA[0]` 这种）。
   **不许**拿"第几行"当身份 —— 数据重排一次就全体错位，而屏幕上一切正常。

2. ★ `building_code` 必须**当场**在 `data/buildings/index.json` 里查得到。
   查不到就拒（不是"先存着"）：一个指向不存在楼栋的锚点，在页面上表现为
   「这栋楼没有名字」—— 与「还没锚定」**逐字同形**（本仓铁律 144 那一族）。

命令行：
    python backend/db/anchors.py --init     # 只建表（幂等）
    python backend/db/anchors.py --list     # 列锚点
    python backend/db/anchors.py --stats    # 覆盖率
"""
import argparse
import json
import os
import sys

import psycopg

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.normpath(os.path.join(_HERE, "..", ".."))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.normpath(os.path.join(_HERE, "..")))
sys.path.insert(0, _HERE)
from db_config import db_params  # noqa: E402

INDEX = os.path.join(_ROOT, "data", "buildings", "index.json")

# 锚点是怎么来的。三档**含义不同**，不许合并：
#   manual        人在页面上点的（可信最高，唯一的"真值"来源）
#   seed          脚本预置的已知控制点（当阳性对照用）
#   outline_match 自动轮廓匹配挑出来的（**必须**带 confidence，且默认不采信）
METHODS = ("manual", "seed", "outline_match")

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS building_anchors (
  id            BIGSERIAL PRIMARY KEY,
  block_id      TEXT NOT NULL UNIQUE,          -- 体块身份（见文件头铁律 1）
  building_code TEXT NOT NULL,                 -- 'c006'，须在 index.json 里
  method        TEXT NOT NULL DEFAULT 'manual',
  confidence    REAL,                          -- 只有 outline_match 有值
  set_by        BIGINT REFERENCES users(id) ON DELETE SET NULL,
  set_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
  note          TEXT,
  CONSTRAINT building_anchors_method_ck
    CHECK (method IN ('manual', 'seed', 'outline_match'))
);
CREATE INDEX IF NOT EXISTS building_anchors_code_idx ON building_anchors (building_code);
"""

# 已锚定块数 / 有锚点的楼栋数 —— 一个查询出两个数，别在 Python 里再数一遍
# （数两遍就有两个数，两个数一致也证明不了它们是对的，铁律 18）。
STATS_SQL = """
SELECT count(*) AS n_blocks,
       count(DISTINCT building_code) AS n_buildings,
       count(*) FILTER (WHERE method = 'manual')       AS n_manual,
       count(*) FILTER (WHERE method = 'outline_match') AS n_auto
  FROM building_anchors
 WHERE (%(codes)s::text[] IS NULL OR building_code = ANY(%(codes)s))
"""


def connect():
    """连库。autocommit=False —— 与 accounts.connect() / rooms_registry.connect() 同一约定。"""
    conn = psycopg.connect(**db_params())
    conn.autocommit = False
    return conn


def ensure_schema(conn):
    """建表。**幂等**，可反复跑。"""
    conn.execute(SCHEMA_SQL)
    conn.commit()


# ---------------------------------------------------------------- 楼栋名录

def known_codes() -> dict:
    """`{code: title}` —— 从 `data/buildings/index.json` 现读。

    ★ 每次调用都重新读盘，**不缓存**：这是一份"此刻的"名录，缓存下来就成了一份
      带时刻的测量（铁律 50/73）。这份文件只有几十 KB，读它比读错便宜。
    """
    if not os.path.isfile(INDEX):
        raise RuntimeError("楼栋名录不在盘上：%s" % INDEX)
    with open(INDEX, encoding="utf-8") as fh:
        raw = json.load(fh)
    ent = raw if isinstance(raw, list) else raw.get("buildings", raw)
    if not isinstance(ent, list):
        raise RuntimeError("名录形状不认识（顶层既不是 list 也没有 buildings）：%s" % INDEX)
    out = {}
    for e in ent:
        if isinstance(e, dict) and e.get("name"):
            out[str(e["name"])] = str(e.get("title") or e.get("name"))
    return out


# ---------------------------------------------------------------- 读写

def list_anchors(conn, codes=None) -> list:
    """列锚点。`codes` 给了就只回那几栋的（范围过滤在路由层做完再传进来）。

    ★ `None` 与 `[]` **含义不同**：`None` = 不筛（全量），`[]` = 筛出来是空集。
      写成 `codes or []` 会把两者并成一个，正是那个"空值跳过整段核对"的形状（铁律 144）。
    """
    sql = ("SELECT block_id, building_code, method, confidence, set_at, note"
           "  FROM building_anchors")
    args = ()
    if codes is not None:
        if not codes:
            return []
        sql += " WHERE building_code = ANY(%s)"
        args = (list(codes),)
    sql += " ORDER BY block_id"
    with conn.cursor() as cur:
        cur.execute(sql, args)
        return [{"block_id": r[0], "building_code": r[1], "method": r[2],
                 "confidence": r[3],
                 "set_at": r[4].isoformat() if r[4] else None, "note": r[5]}
                for r in cur.fetchall()]


def upsert_anchor(conn, block_id, building_code, *, method="manual",
                  confidence=None, set_by=None, note=None) -> dict:
    """建/改锚点。改的时候**不改 block_id**（它是身份，见文件头铁律 1）。

    ★ `building_code` 当场核名录，查不到抛 `ValueError`（路由层翻成 400）。
    """
    block_id = str(block_id or "").strip()
    building_code = str(building_code or "").strip()
    if not block_id:
        raise ValueError("block_id 不许为空")
    if method not in METHODS:
        raise ValueError("method 只认 %s，收到 %r" % (METHODS, method))
    codes = known_codes()
    if building_code not in codes:
        raise ValueError("楼栋代号 %r 不在名录里（%d 条）" % (building_code, len(codes)))
    with conn.cursor() as cur:
        cur.execute(
            """INSERT INTO building_anchors
                   (block_id, building_code, method, confidence, set_by, note)
               VALUES (%s, %s, %s, %s, %s, %s)
               ON CONFLICT (block_id) DO UPDATE
                 SET building_code = EXCLUDED.building_code,
                     method        = EXCLUDED.method,
                     confidence    = EXCLUDED.confidence,
                     set_by        = EXCLUDED.set_by,
                     note          = EXCLUDED.note,
                     set_at        = now()
               RETURNING block_id, building_code, method, confidence, set_at, note""",
            (block_id, building_code, method, confidence, set_by, note))
        r = cur.fetchone()
    conn.commit()
    return {"block_id": r[0], "building_code": r[1], "method": r[2],
            "confidence": r[3], "set_at": r[4].isoformat() if r[4] else None,
            "note": r[5]}


def drop_anchor(conn, block_id) -> bool:
    """撤锚点。**返回有没有真删到行** —— 不是"有没有报错"。

    ★ 退出码/布尔值只说"没报错"是不够的：删一个不存在的 block_id 同样不报错，
      调用方会以为撤掉了（铁律 29：两个方向都要断）。
    """
    with conn.cursor() as cur:
        cur.execute("DELETE FROM building_anchors WHERE block_id = %s", (str(block_id),))
        n = cur.rowcount
    conn.commit()
    return n > 0


def stats(conn, codes=None) -> dict:
    """覆盖率。`codes` 给了就只数那几栋的 —— 与 `list_anchors` 同一套约定。

    ★ `None` 与 `[]` **含义不同**（同 `list_anchors`）：`None` = 不筛，`[]` = 空集 ⇒ 全 0。
      这里靠 SQL 的 `ANY('{}') = false` 自然兑现，**不需要**再写一个 Python 分支 ——
      两处各写一遍的话，空集那一头迟早只改一处（铁律 018/122）。
    """
    with conn.cursor() as cur:
        cur.execute(STATS_SQL, {"codes": None if codes is None else list(codes)})
        r = cur.fetchone()
    return {"n_blocks": r[0], "n_buildings": r[1], "n_manual": r[2], "n_auto": r[3]}


# ---------------------------------------------------------------- 命令行

def main():
    ap = argparse.ArgumentParser(description="体块↔楼栋 锚点表")
    ap.add_argument("--init", action="store_true", help="建表（幂等）")
    ap.add_argument("--list", action="store_true", help="列锚点")
    ap.add_argument("--stats", action="store_true", help="覆盖率")
    args = ap.parse_args()

    codes = known_codes()
    print("楼栋名录 %s ⇒ %d 条" % (INDEX, len(codes)))
    with connect() as conn:
        if args.init or not (args.list or args.stats):
            ensure_schema(conn)
            print("✓ 建表完成：building_anchors")
        if args.list:
            rows = list_anchors(conn)
            print("锚点 %d 条" % len(rows))
            for r in rows:
                print("   %-14s → %-8s %-14s %s"
                      % (r["block_id"], r["building_code"], r["method"],
                         codes.get(r["building_code"], "✗ 不在名录里")))
        if args.stats or not (args.list or args.init):
            s = stats(conn)
            print("覆盖率：%d 个体块已锚定，覆盖 %d 栋楼（名录共 %d 栋）"
                  % (s["n_blocks"], s["n_buildings"], len(codes)))
            print("   人工 %d / 自动 %d" % (s["n_manual"], s["n_auto"]))


if __name__ == "__main__":
    # 判词全中文，Windows 控制台默认 GBK ⇒ 不加这四行会在打印时炸（铁律 168 同族）。
    for s in (sys.stdout, sys.stderr):
        if hasattr(s, "reconfigure"):
            s.reconfigure(encoding="utf-8", errors="replace")
    main()
