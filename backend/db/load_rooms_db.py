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
conn.close()
