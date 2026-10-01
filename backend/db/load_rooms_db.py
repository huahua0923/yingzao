# -*- coding: utf-8 -*-
"""把各楼 rooms.json 导入 PostgreSQL (lihua_twin.rooms)。幂等：可重复运行。

每间房带 building 字段（理化楼=lihua / 各教学楼=c006..c114），id 全局唯一
（理化楼 1..118，教学楼从各自 ID_BASE=100000 起，见各 extract_rooms_*.py）。
只导入「非空」的 rooms.json（其余教学楼尚未提取房间，空数组自动跳过）。
"""
import glob
import json
import os
import sys
from collections import Counter

import psycopg

sys.path.insert(0, os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")))   # 仓库根
from backend.api.settings import get_settings  # noqa: E402
from paths import BUILDINGS, DATA  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from db_config import db_params  # noqa: E402

_SETTINGS = get_settings()
DB_NAME = _SETTINGS.db_name

# 数据源：(rooms.json 路径, building 名)。基线理化楼在 data/ 根，教学楼在 data/buildings/<name>/
SOURCES = [(str(DATA / "rooms.json"), "lihua")]
for path in sorted(glob.glob(str(BUILDINGS / "*" / "rooms.json"))):
    name = os.path.basename(os.path.dirname(path))
    SOURCES.append((path, name))


def load_rooms():
    rooms = []
    for path, building in SOURCES:
        if not os.path.exists(path):
            continue
        data = json.load(open(path, encoding="utf-8"))
        if not data:
            print(f"  跳过空房间文件：{building}")
            continue
        for r in data:
            rooms.append((building, r))
    return rooms


# 1) 建库（连 postgres 管理库，CREATE DATABASE 不能在事务里）
admin = psycopg.connect(**db_params(dbname="postgres"), autocommit=True)
exists = admin.execute("SELECT 1 FROM pg_database WHERE datname = %s", (DB_NAME,)).fetchone()
if not exists:
    admin.execute(f'CREATE DATABASE "{DB_NAME}"')
    print("已创建数据库", DB_NAME)
else:
    print("数据库已存在", DB_NAME)
admin.close()

# 2) 建表（rooms.json 是唯一数据源，直接重建；building 区分多楼）
conn = psycopg.connect(**db_params(dbname=DB_NAME))
conn.execute("DROP TABLE IF EXISTS rooms")
conn.execute("""
CREATE TABLE rooms (
  id INT PRIMARY KEY,
  building TEXT NOT NULL DEFAULT 'lihua',
  floor INT NOT NULL,
  number TEXT NOT NULL,
  name TEXT,
  area_label TEXT,
  area_m2 DOUBLE PRECISION,
  purpose TEXT,
  dept TEXT,
  centroid_x DOUBLE PRECISION,
  centroid_y DOUBLE PRECISION,
  boundary JSONB NOT NULL
);
""")
conn.execute("CREATE INDEX IF NOT EXISTS idx_rooms_floor ON rooms(floor)")
conn.execute("CREATE INDEX IF NOT EXISTS idx_rooms_building ON rooms(building)")

# 3) 导入（幂等：先清空再重建）
conn.execute("DELETE FROM rooms")
rooms = load_rooms()
for building, r in rooms:
    c = r.get("centroid") or [None, None]
    conn.execute(
        """INSERT INTO rooms
           (id, building, floor, number, name, area_label, area_m2, purpose, dept, centroid_x, centroid_y, boundary)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
        (r["id"], building, r["floor"], r["number"], r.get("name"), r.get("area"), r.get("area_m2"),
         r.get("purpose"), r.get("dept"), c[0], c[1], json.dumps(r["boundary"])),
    )
conn.commit()

n = conn.execute("SELECT COUNT(*) FROM rooms").fetchone()[0]
print("已导入", n, "间房")
rows = conn.execute(
    "SELECT building, COUNT(*) FROM rooms GROUP BY building ORDER BY building").fetchall()
print("  各楼分布：", {b: c for b, c in rows})

# 抽样校验 c006
sample = conn.execute(
    "SELECT building, number, name, area_label, area_m2, purpose, dept "
    "FROM rooms WHERE building='c006' ORDER BY id LIMIT 6").fetchall()
print("c006 样例：")
for building, number, name, area, m2, purpose, dept in sample:
    print(f"  {number}  名称={name or '—'}  标注面积={area or '—'}  计算={m2}m2  用途={purpose or '—'}  单位={dept or '—'}")

# 4) 楼层面积表（数字孪生要的"这层多大/整栋多大"；rooms 只回答"这间多大"）
#    数据源**只用交付件**：floors/floor*.json 的 `outline` + rooms.json。不读 _scratch、
#    不读 SU 里的楼板 —— 那两个是建模过程的中间产物，交付链不能依赖它们。
#    口径：建筑面积 = 外墙外围水平面积（GB/T 50353）。注意 SU 里的**楼板**是扣了
#    楼梯/电梯井道洞的结构板，两者实测只差那几块井（理化楼 F1 差 49.91 m² = 3 个井），
#    建筑面积口径**不扣井**，所以这里用 outline 而不是楼板。
conn.execute("DROP TABLE IF EXISTS floor_areas")
conn.execute("""
CREATE TABLE floor_areas (
  building TEXT NOT NULL,
  floor INT NOT NULL,
  gfa_m2 DOUBLE PRECISION,          -- 建筑面积（外墙外围水平面积）
  rooms_n INT,
  room_net_m2 DOUBLE PRECISION,     -- 房间净面积（墙内皮，rooms.area_m2 之和）
  room_label_m2 DOUBLE PRECISION,   -- 图纸标注面积之和（口径不同，只能并列）
  purposes JSONB,                   -- {用途: 间数}
  PRIMARY KEY (building, floor)
);
""")
conn.execute("CREATE INDEX IF NOT EXISTS idx_floor_areas_building ON floor_areas(building)")


def shoelace(pts):
    s = 0.0
    n = len(pts)
    for i in range(n):
        x1, y1 = pts[i]
        x2, y2 = pts[(i + 1) % n]
        s += x1 * y2 - x2 * y1
    return abs(s) / 2.0


def ring_of(outline):
    """outline 可能首尾重复（闭合写法）；去重后再当环算面积。"""
    pts = [[float(a), float(b)] for a, b in outline]
    if len(pts) > 2 and pts[0] == pts[-1]:
        pts = pts[:-1]
    return pts


def load_floor_areas():
    """逐楼逐层算面积。floors 目录 = rooms.json 同级的 floors/（理化楼在 data/floors）。"""
    out, skipped = [], []
    for path, building in SOURCES:
        if not os.path.exists(path):
            continue
        fdir = os.path.join(os.path.dirname(path), "floors")
        if not os.path.isdir(fdir):
            skipped.append((building, "没有 floors 目录"))
            continue
        rooms = json.load(open(path, encoding="utf-8"))
        by_floor = {}
        for r in rooms:
            by_floor.setdefault(r["floor"], []).append(r)
        for fp in sorted(glob.glob(os.path.join(fdir, "floor*.json"))):
            d = json.load(open(fp, encoding="utf-8"))
            if not d.get("outline"):
                skipped.append((building, os.path.basename(fp) + " 没有 outline"))
                continue
            b = int(d["floor"])
            rs = by_floor.get(b, [])
            lab = 0.0
            for r in rs:
                try:
                    lab += float(str(r.get("area") or 0).rstrip("mM"))
                except ValueError:
                    skipped.append((building, "房号 %s 标注面积非数 %r" % (r.get("number"), r.get("area"))))
            out.append((building, b, round(shoelace(ring_of(d["outline"])), 2), len(rs),
                        round(sum(r.get("area_m2") or 0.0 for r in rs), 2), round(lab, 2),
                        json.dumps(dict(Counter(r["purpose"] for r in rs)), ensure_ascii=False)))
    return out, skipped


fa, skipped = load_floor_areas()
for row in fa:
    conn.execute("""INSERT INTO floor_areas
                    (building, floor, gfa_m2, rooms_n, room_net_m2, room_label_m2, purposes)
                    VALUES (%s,%s,%s,%s,%s,%s,%s)""", row)
conn.commit()
print("已导入", len(fa), "层面积")
# 守卫：建筑面积必须 ≥ 房间净面积（墙体占位）。违反 = outline 用错了，报出来不静默。
viol = conn.execute(
    "SELECT building, floor, gfa_m2, room_net_m2 FROM floor_areas "
    "WHERE room_net_m2 IS NOT NULL AND gfa_m2 < room_net_m2 ORDER BY building, floor").fetchall()
print("  逐楼（楼层数 / 建筑面积合计 m²）：",
      [(b, n, round(g or 0, 1)) for b, n, g in conn.execute(
          "SELECT building, COUNT(*), SUM(gfa_m2) FROM floor_areas GROUP BY building ORDER BY building")
       .fetchall()][:6], "… 共", len(set(b for b, _, _ in conn.execute(
          "SELECT building, COUNT(*), SUM(gfa_m2) FROM floor_areas GROUP BY building").fetchall())), "栋")
print("  理化楼：")
for b, f, g, n, net in conn.execute(
        "SELECT building, floor, gfa_m2, rooms_n, room_net_m2 FROM floor_areas "
        "WHERE building='lihua' ORDER BY floor").fetchall():
    print("    F%d  建筑面积 %8.2f  房间 %2d 间  房间净面积 %8.2f" % (f, g, n, net))
if viol:
    print("  ⚠ 建筑面积 < 房间净面积 的层 %d 个（outline 可疑）：%s" % (len(viol), viol[:8]))
if skipped:
    print("  ⚠ 跳过/异常 %d 条：" % len(skipped), skipped[:8])
conn.close()
