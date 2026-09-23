# -*- coding: utf-8 -*-
"""房间台账 —— 每间房一条**可管理**的记录（PostgreSQL / lihua_twin）。

## 为什么要有这一层

CAD 抽取是**机器猜的**：会漏抽（c103 图上 181 个房号只抽出 164 个）、会错层
（c103 的 floor0.json 里装的是二层房）、会把用途串成面积串（c046 的 228 间）。
靠反复改抽取器来修，代价高，而且**每次重抽都把上一轮的修正推倒重来**。

所以把两件事拆开：

    room_source    机器层：rooms.json 的快照。重抽**全量重建**，可以随便推倒。
    room_manual    人工层：只增不减，重抽**永远不动它** —— "人工修订优先"就落在这。
    room_history   审计层：append-only。谁、什么时候、把哪个字段从什么改成什么。
    room_registry  视图：  两层合并（人工优先）。网页与查询都读它。

**为什么合并用视图而不是物化表**：物化表要同步，同步就有漏同步的时机；视图不可能漂移。
**为什么人工层用 JSONB 装字段**：字段集以后会长（今天 name/purpose/dept/面积，明天可能要加
「负责人」「电话」），JSONB 加字段不用改表结构，也不用为"这间房只有用途是人工的"存一排 NULL。

## 两条铁律

1. `import_cad()` **只**重建 room_source。它绝不写 room_manual，也不删它 ——
   否则"重抽不覆盖人工值"就是一句空话。
2. key 是 `楼|层|房号`，**不是** rooms.json 里的 `id`。id 是"按 (floor, number) 排序后的下标"，
   房间集合一变全体错位（实测 c041 交集 34 间全部冲突、c104 59 间里 51 间冲突）。
   房号在楼层之间会重复（c103 的 `103-A-01-13` 在 F0 与 F1 是两间不同的房），所以层必须进 key。

命令行：
    python backend/db/rooms_registry.py --import      # 重抽导入机器层（不动人工层）
    python backend/db/rooms_registry.py --stats       # 打印台账概览
"""
import glob
import json
import os
import sys
from collections import Counter

import psycopg

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.normpath(os.path.join(_HERE, "..", "..")))   # 仓库根
sys.path.insert(0, os.path.normpath(os.path.join(_HERE, "..")))         # backend/（paths.py 在这）
sys.path.insert(0, _HERE)
from backend.api.settings import get_settings  # noqa: E402
from db_config import db_params  # noqa: E402
from paths import BUILDINGS, DATA  # noqa: E402

# ---------------------------------------------------------------- 字段定义

# 网页上可直接改的字段。
# ★ 房号/楼/层**也在可改之列**：抽取器会拿标注文字当房号（c046 有 28 间房的"房号"
#   就是「卫」），也会把房间放到错层（c103 的 floor0 里装的是二层房）。这几样不许改的话，
#   台账就修不了它最该修的那批数据。
#   改法见 set_field：新值进 room_manual.fields，**room_key 不动** —— key 是身份，
#   一旦跟着改，变更历史就断了线（历史表按 room_key 关联）。
EDITABLE = ("building", "floor", "number", "name", "area_label", "area_m2", "purpose", "dept")
NUM_FIELDS = ("area_m2", "centroid_x", "centroid_y", "floor")
TEXT_FIELDS = ("building", "number", "name", "area_label", "purpose", "dept")
# 新建房间时允许一次性带上的字段（比可编辑的多出几何：几何是导入时算出来的，人工新建没有）
# 楼/层/房号**不在这里** —— 它们是新建接口的三个独立参数，塞进 fields 会和参数打架。
ADDABLE = ("name", "area_label", "area_m2", "purpose", "dept",
           "centroid_x", "centroid_y", "boundary")

CN = {"room_key": "台账键", "building": "楼", "floor": "层", "number": "房号", "name": "名称",
      "area_label": "图纸标注面积", "area_m2": "计算面积m2", "purpose": "用途", "dept": "使用单位",
      "origin": "来源", "in_cad": "图上抽取到", "deleted": "已删除", "updated_at": "更新时间"}


def make_key(building, floor, number, seq=0):
    """`楼|层|房号`，同一 (楼,层,房号) 有第 2 间时加 `#2` 区分。"""
    k = "%s|%s|%s" % (building, int(floor), number)
    return k if not seq else "%s#%d" % (k, seq + 1)


def split_key(key):
    building, floor, number = str(key).split("|", 2)
    if "#" in number:
        number = number.split("#")[0]
    return building, int(floor), number


def coerce(field, value):
    """把网页/CLI 传来的值转成库里该有的类型。空串一律当"没有值"。"""
    if value is None:
        return None
    if isinstance(value, str) and not value.strip():
        return None
    if field in NUM_FIELDS:
        try:
            return float(value) if field != "floor" else int(value)
        except (TypeError, ValueError):
            raise ValueError("%s 必须是数字，收到 %r" % (field, value))
    if field == "boundary":
        if isinstance(value, (list, dict)):
            return value
        return json.loads(value)
    return str(value).strip()


# ---------------------------------------------------------------- 建表


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS room_source (
  room_key   TEXT PRIMARY KEY,
  building   TEXT NOT NULL,
  floor      INT  NOT NULL,
  number     TEXT NOT NULL,
  name       TEXT,
  area_label TEXT,
  area_m2    DOUBLE PRECISION,
  purpose    TEXT,
  dept       TEXT,
  centroid_x DOUBLE PRECISION,
  centroid_y DOUBLE PRECISION,
  boundary   JSONB,
  imported_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_room_source_bf ON room_source(building, floor);

CREATE TABLE IF NOT EXISTS room_manual (
  room_key   TEXT PRIMARY KEY,
  building   TEXT NOT NULL,
  floor      INT  NOT NULL,
  number     TEXT NOT NULL,
  fields     JSONB NOT NULL DEFAULT '{}'::jsonb,   -- 只装人工定过的字段
  deleted    BOOLEAN NOT NULL DEFAULT FALSE,       -- 人工删除（重抽也不会复活）
  author     TEXT,
  note       TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_room_manual_bf ON room_manual(building, floor);

CREATE TABLE IF NOT EXISTS room_history (
  id        BIGSERIAL PRIMARY KEY,
  room_key  TEXT NOT NULL,
  action    TEXT NOT NULL,      -- set / add / delete / restore / revert
  field     TEXT,
  old_value TEXT,
  new_value TEXT,
  author    TEXT,
  note      TEXT,
  at        TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_room_history_key ON room_history(room_key, at);

-- 台账 = 机器层 ⨝ 人工层（人工优先）。FULL OUTER JOIN 让"人工新建、图上没有"的房间也进得来。
-- src 逐字段说明该字段当前值来自 cad 还是 manual，网页据此打"人工改过"徽标。
CREATE OR REPLACE VIEW room_registry AS
SELECT
  room_key,
  COALESCE(m.fields->>'building', m.building, s.building)             AS building,
  COALESCE((m.fields->>'floor')::int, m.floor, s.floor)               AS floor,
  COALESCE(m.fields->>'number', m.number, s.number)                   AS number,
  COALESCE(m.fields->>'name', s.name)                                AS name,
  COALESCE(m.fields->>'area_label', s.area_label)                    AS area_label,
  COALESCE((m.fields->>'area_m2')::double precision, s.area_m2)      AS area_m2,
  COALESCE(m.fields->>'purpose', s.purpose)                          AS purpose,
  COALESCE(m.fields->>'dept', s.dept)                                AS dept,
  COALESCE((m.fields->>'centroid_x')::double precision, s.centroid_x) AS centroid_x,
  COALESCE((m.fields->>'centroid_y')::double precision, s.centroid_y) AS centroid_y,
  CASE WHEN m.fields ? 'boundary' THEN m.fields->'boundary' ELSE s.boundary END AS boundary,
  CASE WHEN s.room_key IS NULL THEN 'manual'
       WHEN COALESCE(m.fields, '{}'::jsonb) = '{}'::jsonb THEN 'cad'
       ELSE 'both' END                                               AS origin,
  (s.room_key IS NOT NULL)                                           AS in_cad,
  COALESCE(m.deleted, FALSE)                                         AS deleted,
  COALESCE(m.updated_at, s.imported_at)                              AS updated_at,
  COALESCE((SELECT jsonb_object_agg(e.key, 'manual')
              FROM jsonb_each(COALESCE(m.fields, '{}'::jsonb)) AS e),
           '{}'::jsonb)                                              AS src
FROM room_source s
FULL OUTER JOIN room_manual m USING (room_key);
"""


def connect():
    conn = psycopg.connect(**db_params())
    conn.autocommit = False
    return conn


def ensure_schema(conn):
    conn.execute(SCHEMA_SQL)
    conn.commit()


# ---------------------------------------------------------------- 机器层导入

# 数据源：(rooms.json 路径, building 名)。与 load_rooms_db.py 同源：理化楼在 data/ 根。
def sources():
    out = [(str(DATA / "rooms.json"), "lihua")]
    for path in sorted(glob.glob(str(BUILDINGS / "*" / "rooms.json"))):
        if not os.path.exists(path):
            continue
        data = json.load(open(path, encoding="utf-8"))
        if not data:
            continue
        out.append((path, os.path.basename(os.path.dirname(path))))
    return out


def collect_cad_rows():
    """读全库 rooms.json → [(row_dict, ...)]。同 (楼,层,房号) 撞号时按出现顺序加 #2。

    返回 (rows, report)；report 里如实报出撞号，不静默去重（撞号是要看见的事）。
    """
    rows, report = [], []
    for path, building in sources():
        data = json.load(open(path, encoding="utf-8"))
        seen = Counter()
        for r in data:
            b = str(r.get("building") or building)
            f = int(r.get("floor") or 0)
            n = str(r.get("number") or "")
            key = make_key(b, f, n, seen[(b, f, n)])
            seen[(b, f, n)] += 1
            c = r.get("centroid") or [None, None]
            rows.append({
                "room_key": key, "building": b, "floor": f, "number": n,
                "name": r.get("name"), "area_label": r.get("area"),
                "area_m2": r.get("area_m2"), "purpose": r.get("purpose"),
                "dept": r.get("dept"),
                "centroid_x": c[0] if len(c) > 0 else None,
                "centroid_y": c[1] if len(c) > 1 else None,
                "boundary": json.dumps(r.get("boundary") or []),
            })
        dup = {k: v for k, v in seen.items() if v > 1}
        if dup:
            report.append((building, len(dup), sum(dup.values()) - len(dup)))
    return rows, report


def import_cad(conn):
    """把 rooms.json 重建成机器层。**只动 room_source。**

    返回一份对账单：这次导入多少行、其中多少行有人工修订、多少间人工房在图上找不到了。
    """
    rows, dup = collect_cad_rows()
    conn.execute("DELETE FROM room_source")
    with conn.cursor() as cur:
        cur.executemany(
            """INSERT INTO room_source
               (room_key, building, floor, number, name, area_label, area_m2, purpose, dept,
                centroid_x, centroid_y, boundary, imported_at)
               VALUES (%(room_key)s,%(building)s,%(floor)s,%(number)s,%(name)s,%(area_label)s,
                       %(area_m2)s,%(purpose)s,%(dept)s,%(centroid_x)s,%(centroid_y)s,
                       %(boundary)s::jsonb, now())""", rows)
    conn.commit()
    return {"imported": len(rows), "dup_groups": dup}


def merge_report(conn):
    """导入之后，人工层怎么样了 —— 必须报出来，不能让人工值悄悄落空。"""
    n_manual = conn.execute("SELECT COUNT(*) FROM room_manual").fetchone()[0]
    n_manual_fields = conn.execute(
        "SELECT COUNT(*) FROM room_manual WHERE fields <> '{}'::jsonb").fetchone()[0]
    n_deleted = conn.execute("SELECT COUNT(*) FROM room_manual WHERE deleted").fetchone()[0]
    # 人工新建（图上没有）的：这些是"CAD 抽漏了、人补上"的房间，最该盯住
    n_added = conn.execute(
        "SELECT COUNT(*) FROM room_manual m LEFT JOIN room_source s USING (room_key) "
        "WHERE s.room_key IS NULL").fetchone()[0]
    # 图上也有、并且人工改过的
    n_both = conn.execute(
        "SELECT COUNT(*) FROM room_manual m JOIN room_source s USING (room_key) "
        "WHERE m.fields <> '{}'::jsonb").fetchone()[0]
    return {"manual_rows": n_manual, "with_edits": n_manual_fields,
            "deleted": n_deleted, "manual_only": n_added, "edited_on_cad": n_both}


# ---------------------------------------------------------------- 查询


ROW_COLS = ("room_key, building, floor, number, name, area_label, area_m2, purpose, dept, "
            "origin, in_cad, deleted, src, updated_at")


def _row(r):
    return {"room_key": r[0], "building": r[1], "floor": r[2], "number": r[3], "name": r[4],
            "area_label": r[5], "area_m2": r[6], "purpose": r[7], "dept": r[8],
            "origin": r[9], "in_cad": r[10], "deleted": r[11],
            "src": r[12] if isinstance(r[12], dict) else json.loads(r[12] or "{}"),
            "updated_at": r[13].isoformat() if r[13] else None}


def _filters(building, floor, q, origin, include_deleted):
    where, params = [], []
    if building:
        where.append("building = %s"); params.append(building)
    if floor is not None and floor != "":
        where.append("floor = %s"); params.append(int(floor))
    if origin:
        where.append("origin = %s"); params.append(origin)
    if not include_deleted:
        where.append("NOT deleted")
    if q:
        # 用 position() 而不是 LIKE：省掉给用户输入转义 % 和 _ 的麻烦（那是个经典漏洞位）
        cols = ("number", "COALESCE(name,'')", "COALESCE(purpose,'')", "COALESCE(dept,'')")
        where.append("(" + " OR ".join(
            "position(lower(%%s) in lower(%s)) > 0" % c for c in cols) + ")")
        params.extend([q] * len(cols))
    return (" AND ".join(where) if where else "TRUE"), params


def list_rooms(conn, building=None, floor=None, q=None, origin=None,
               include_deleted=False, limit=200, offset=0):
    w, params = _filters(building, floor, q, origin, include_deleted)
    total = conn.execute("SELECT COUNT(*) FROM room_registry WHERE " + w, params).fetchone()[0]
    rows = conn.execute(
        "SELECT %s FROM room_registry WHERE %s ORDER BY building, floor, number, room_key "
        "LIMIT %%s OFFSET %%s" % (ROW_COLS, w),
        params + [int(limit), int(offset)]).fetchall()
    return {"total": total, "limit": int(limit), "offset": int(offset),
            "rows": [_row(r) for r in rows]}


def get_room(conn, key):
    r = conn.execute("SELECT %s FROM room_registry WHERE room_key = %%s" % ROW_COLS,
                     (key,)).fetchone()
    return _row(r) if r else None


def history(conn, key, limit=200):
    rows = conn.execute(
        "SELECT id, action, field, old_value, new_value, author, note, at "
        "FROM room_history WHERE room_key = %s ORDER BY at DESC, id DESC LIMIT %s",
        (key, int(limit))).fetchall()
    return [{"id": r[0], "action": r[1], "field": r[2], "old_value": r[3], "new_value": r[4],
             "author": r[5], "note": r[6], "at": r[7].isoformat() if r[7] else None}
            for r in rows]


def stats(conn):
    total = conn.execute("SELECT COUNT(*) FROM room_registry WHERE NOT deleted").fetchone()[0]
    manual_n = conn.execute(
        "SELECT COUNT(*) FROM room_registry WHERE src <> '{}'::jsonb AND NOT deleted").fetchone()[0]
    deleted_n = conn.execute("SELECT COUNT(*) FROM room_registry WHERE deleted").fetchone()[0]
    rows = conn.execute(
        """SELECT building, COUNT(*) FILTER (WHERE NOT deleted),
                  COUNT(*) FILTER (WHERE src <> '{}'::jsonb AND NOT deleted),
                  array_agg(DISTINCT floor ORDER BY floor)
           FROM room_registry GROUP BY building ORDER BY building""").fetchall()
    # floors 给的是**层号列表**不只是个数：网页的下拉要拿它填选项，
    # 只给个数的话前端只能瞎猜 0..n-1，遇上层号不连续（退台楼、缺层楼）就会选出空结果。
    return {"total": total, "manual_n": manual_n, "deleted_n": deleted_n,
            "buildings": [{"building": b, "rooms_n": n, "manual_n": mn,
                           "floors": list(fs or []), "floors_n": len(fs or [])}
                          for b, n, mn, fs in rows]}


# ---------------------------------------------------------------- 人工层写入


def _manual(conn, key, for_update=False):
    sql = "SELECT building, floor, number, fields, deleted FROM room_manual WHERE room_key=%s"
    if for_update:
        sql += " FOR UPDATE"
    return conn.execute(sql, (key,)).fetchone()


def _log(conn, key, action, field=None, old=None, new=None, author=None, note=None):
    conn.execute(
        "INSERT INTO room_history (room_key, action, field, old_value, new_value, author, note) "
        "VALUES (%s,%s,%s,%s,%s,%s,%s)",
        (key, action, field,
         None if old is None else str(old), None if new is None else str(new), author, note))


def _put_fields(conn, key, fields, deleted=None, author=None, note=None):
    """写回人工层。行不存在就按 key 建（楼/层/房号从 machine 层借，借不到就拒绝）。"""
    row = _manual(conn, key, for_update=True)
    if row is None:
        src = conn.execute(
            "SELECT building, floor, number FROM room_source WHERE room_key=%s", (key,)).fetchone()
        if src is None:
            raise ValueError("台账里没有这间房，且机器层也找不到它：%s" % key)
        conn.execute(
            """INSERT INTO room_manual (room_key, building, floor, number, fields, deleted,
                                        author, note, created_at, updated_at)
               VALUES (%s,%s,%s,%s,%s::jsonb,%s,%s,%s, now(), now())""",
            (key, src[0], src[1], src[2], json.dumps(fields), bool(deleted), author, note))
    else:
        conn.execute(
            """UPDATE room_manual SET fields=%s::jsonb, deleted=COALESCE(%s, deleted),
                   author=COALESCE(%s, author), note=COALESCE(%s, note), updated_at=now()
               WHERE room_key=%s""",
            (json.dumps(fields), deleted, author, note, key))


def set_field(conn, key, field, value, author=None, note=None):
    """改一个字段的人工值。**value 为空 = 撤销该字段的人工值（回到 CAD 原值）**。

    空串和 NULL 在文本字段里没法区分"我想清空"和"我不要人工值了"，而"清空"这个需求
    在台账里没有意义（图纸上有的就该显示图纸的），所以统一解释成撤销 —— 这样也省掉一个接口。
    """
    if field not in EDITABLE:
        raise ValueError("不可编辑的字段：%s（可编辑：%s）" % (field, "、".join(EDITABLE)))
    room = get_room(conn, key)
    if room is None:
        raise ValueError("台账里没有这间房：%s" % key)
    old_effective = room.get(field)
    val = coerce(field, value)
    if field in ("building", "floor", "number") and val is not None:
        # 改身份字段要挡住"改成和另一间房一模一样"。同一 (楼,层,房号) 有两间房，
        # 下游任何配对（rooms↔floors、房间↔导航节点）都会二义，不如在这里挡下来。
        nf = {"building": room["building"], "floor": room["floor"], "number": room["number"]}
        nf[field] = val
        dup = conn.execute(
            "SELECT room_key FROM room_registry WHERE building=%s AND floor=%s AND number=%s "
            "AND room_key <> %s LIMIT 1",
            (nf["building"], nf["floor"], nf["number"], key)).fetchone()
        if dup:
            raise ValueError("改完会撞号：%s|%s|%s 已经是 %s —— 同一层同一房号不能有两间房"
                             % (nf["building"], nf["floor"], nf["number"], dup[0]))
    row = _manual(conn, key, for_update=True)
    fields = dict(row[3] or {}) if row else {}
    if val is None:
        if field not in fields:
            raise ValueError("该字段本来就没有人工值，无须撤销：%s.%s" % (key, field))
        fields.pop(field)
        action = "revert"
    else:
        fields[field] = val
        action = "set"
    _put_fields(conn, key, fields, author=author, note=note)
    _log(conn, key, action, field, old_effective, val, author, note)
    conn.commit()
    return {"room": get_room(conn, key),
            "changed": [{"field": field, "old_value": old_effective, "new_value": val}]}


def add_room(conn, building, floor, number, fields=None, author=None, note=None):
    """新建一间房（CAD 抽漏、人工补上）。已存在（机器层或人工层）就拒绝，不覆盖。"""
    if not building or not number:
        raise ValueError("楼和房号必填")
    fields = dict(fields or {})
    bad = [k for k in fields if k not in ADDABLE]
    if bad:
        raise ValueError("不可填写的字段：%s（可填：%s）" % ("、".join(bad), "、".join(ADDABLE)))
    key = make_key(building, floor, number)
    if get_room(conn, key) is not None:
        raise ValueError("这间房已经在台账里了：%s（同一层同一房号不能建两间）" % key)
    clean = {}
    for k, v in fields.items():
        cv = coerce(k, v)
        if cv is not None:
            clean[k] = cv
    conn.execute(
        """INSERT INTO room_manual (room_key, building, floor, number, fields, deleted,
                                    author, note, created_at, updated_at)
           VALUES (%s,%s,%s,%s,%s::jsonb,FALSE,%s,%s, now(), now())""",
        (key, building, int(floor), str(number), json.dumps(clean), author, note))
    _log(conn, key, "add", None, None, json.dumps(clean, ensure_ascii=False), author, note)
    conn.commit()
    return {"room": get_room(conn, key)}


def set_deleted(conn, key, deleted, author=None, note=None):
    """软删除 / 恢复。删除是**人工标记**，不是 DELETE —— 重抽不会把它复活，也留得下痕迹。"""
    room = get_room(conn, key)
    if room is None:
        raise ValueError("台账里没有这间房：%s" % key)
    if bool(room["deleted"]) == bool(deleted):
        raise ValueError("这间房已经是%s状态" % ("已删除" if deleted else "正常"))
    row = _manual(conn, key, for_update=True)
    fields = dict(row[3] or {}) if row else {}
    _put_fields(conn, key, fields, deleted=bool(deleted), author=author, note=note)
    _log(conn, key, "delete" if deleted else "restore", None,
         "正常" if deleted else "已删除", "已删除" if deleted else "正常", author, note)
    conn.commit()
    return {"room": get_room(conn, key)}


def revert_field(conn, key, field, author=None, note=None):
    """撤销某字段的人工值（与 set_field 传空值等价，单独留一个入口给网页上的「撤销」按钮）。"""
    room = get_room(conn, key)
    if room is None:
        raise ValueError("台账里没有这间房：%s" % key)
    if field not in EDITABLE:
        raise ValueError("不可编辑的字段：%s" % field)
    row = _manual(conn, key, for_update=True)
    fields = dict(row[3] or {}) if row else {}
    if field not in fields:
        raise ValueError("该字段本来就没有人工值：%s.%s" % (key, field))
    old = fields.pop(field)
    _put_fields(conn, key, fields, author=author, note=note)
    _log(conn, key, "revert", field, old, room.get(field), author, note)
    conn.commit()
    return {"room": get_room(conn, key)}


def export_rows(conn, building=None, include_deleted=True):
    """导出用：一次取全（不走分页）。boundary 不导 —— 几万个坐标点塞进 CSV 没人看得懂。"""
    w, params = _filters(building, None, None, None, include_deleted)
    rows = conn.execute(
        "SELECT building, floor, number, name, area_label, area_m2, purpose, dept, origin, "
        "in_cad, deleted, src, updated_at FROM room_registry WHERE %s "
        "ORDER BY building, floor, number, room_key" % w, params).fetchall()
    out = []
    for r in rows:
        src = r[11] if isinstance(r[11], dict) else json.loads(r[11] or "{}")
        out.append({"building": r[0], "floor": r[1], "number": r[2], "name": r[3],
                    "area_label": r[4], "area_m2": r[5], "purpose": r[6], "dept": r[7],
                    "origin": r[8], "in_cad": r[9], "deleted": r[10],
                    "manual_fields": "、".join(sorted(src)),
                    "updated_at": r[12].isoformat() if r[12] else ""})
    return out


# ---------------------------------------------------------------- CLI


def main(argv):
    conn = connect()
    try:
        ensure_schema(conn)
        if "--import" in argv:
            rep = import_cad(conn)
            print("机器层已重建：%d 行" % rep["imported"])
            if rep["dup_groups"]:
                print("  ⚠ 同一 (楼,层,房号) 撞号的：%d 组，多出 %d 行（已按 #2 区分）"
                      % (len(rep["dup_groups"]), sum(d for _, _, d in rep["dup_groups"])))
            m = merge_report(conn)
            print("人工层（本次导入**一个字没动**）：")
            print("  有人工行 %d；其中改过字段 %d、人工新建(图上没有) %d、在图上且改过 %d、标记删除 %d"
                  % (m["manual_rows"], m["with_edits"], m["manual_only"],
                     m["edited_on_cad"], m["deleted"]))
            s = stats(conn)
            print("台账合计 %d 间（%d 栋）" % (s["total"], len(s["buildings"])))
        s = stats(conn)
        print("=" * 70)
        print("台账概览：%d 间，其中人工改过 %d、已删除 %d" % (s["total"], s["manual_n"], s["deleted_n"]))
        for b in s["buildings"][:12]:
            print("  %-8s %5d 间 / %d 层 / 人工 %d" % (b["building"], b["rooms_n"],
                                                     b["floors_n"], b["manual_n"]))
        if len(s["buildings"]) > 12:
            print("  …共 %d 栋" % len(s["buildings"]))
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
