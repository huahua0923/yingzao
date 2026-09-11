# 数字孪生平台（gym3d）

成都理工大学校园建筑数字孪生平台：**DWG/DXF → 自动建模 → 浏览 → 室内导航 → 构件识别**。

**当前规模：49 栋 / 360 个楼层 JSON / 57 个 GLB**（其中 49 个 `data/buildings/<名>/<名>-building.glb` 为交付 GLB），
全部由 DXF 自动识别生成。49 栋的交付 GLB 已全部重出并审计通过：**开边 0.000%**（`_scratch/_check_mesh.py`）。

> ⚠️ 本项目的模型是**纯文本 JSON + GLB**。所有判断必须靠几何/数值脚本，截图和肉眼都不可靠。
> 改任何算法前先读 **`算法与流程总览.md`**（阈值与铁律都在那里）。

## 目录结构

```
D:\gym3d
├── run_building.py          # 单栋管道入口（backend/web/run_step.py 真 import）
├── run_batch.py             # 批量管道（⚠️ 铁律：不许跑）
├── convert_dwg_to_dxf.py    # DWG → DXF，管线第一步（audit=1 铁律）
├── build_index.py           # 生成 data/buildings/index.json
├── qa_structural.py         # 结构体检 I1–I10 门禁（⚠️ 只读，不可改）
├── _wall_thin_batch.py      # 内墙重建生产线（交付链真正的一环）
├── _wall_thin_force.py      # 内墙重建单栋强制
├── _dxf_cad_render.py       # 忠实源图纸 → dxf_plan/（该目录所有者）
├── _dxf_png_batch.py        # 识别叠加图 → dxf_plan_recog/
├── _dxf_compare_render.py   # A|B 对比页 + 总目录
├── _dxf_audit.py            # 覆盖度审计
├── _glb_only.py             # 只重出 GLB，不重跑 recognize
├── _door_punch_apply.py     # 门洞外科式落地
│
├── backend/
│   ├── recognizer/          # ★ 识别引擎
│   │   ├── classify.py             # LWPOLYLINE 分类器（非 c006）
│   │   ├── classify_line.py        # LINE+INSERT 分类器（仅 c006）
│   │   ├── component_library.py    # 识别经验固化库（识别错就更新它）
│   │   ├── geometry.py             # pair_wall_faces 配对 + 轮廓推导
│   │   ├── floor.py                # extract_floor 22 步 + verify_floor 门禁
│   │   ├── recognize.py            # 13 步识别主链
│   │   ├── profile.py              # BuildingProfile + 坐标数学
│   │   ├── curve_walls.py          # 弧墙配对
│   │   └── standard.py             # STANDARD 常量
│   ├── modeling/
│   │   └── build_standard_glb.py   # GLB 建模（三段挤出 + 门头过梁）
│   ├── db/
│   │   └── serve_rooms.py          # 8123：房间 API + 单层页
│   ├── web/
│   │   ├── control.py              # 8130：建模控制台后端
│   │   └── run_step.py             # 控制台步骤执行器
│   └── nav/                        # 室内导航（build_graph.py → adjacency.json）
│
├── frontend/
│   ├── building.html        # 多楼层浏览（读 data/buildings/index.json）
│   ├── control.html         # 建模控制台
│   ├── floor1_3d.html       # 单层 3D
│   └── render_j6.html       # 六教查看器（读 ../data/j6-walls.glb）
│
├── data/
│   ├── buildings/<name>/    # ★ 48 栋主数据（见下）
│   ├── buildings/index.json # 网页选择器消费
│   ├── rooms.json           # 房间（房间号不唯一，用 id）
│   ├── adjacency.json       # 房间图（门边 + 楼梯井跨层边）
│   └── j6-walls.glb         # render_j6.html 专用
│
├── kb/                      # CAD 识图知识库（00-overview … 08-su-reference）
├── blender/                 # 3D 视觉校验：render_views.py 渲染立面/顶/轴测
└── _scratch/                # 一次性脚本与历史遗留归档（340 项，可一键还原）
```

根目录只保留**管线/生产/门禁/回归资产**。历史遗留（`archive/`、`render_c103/`、
`_al_check/`、理化楼时代建模器与 GLB、旧 `backend/extract`、`PLAN.md` 等）已全部归档进
`_scratch/legacy/`；还原入口：`python _scratch/_unarchive.py --apply`（读全部 4 份清单）。

### 单栋数据布局 `data/buildings/<name>/`

```
profile.json      # BuildingProfile（classifier 分派开关等）
spec.json         # 楼栋规格
floors/floor{N}.json   # ★ 标准楼层几何（N 从 0 开始 = 首层）
dxf_plan/         # 忠实源图纸 PNG + A|B 对比页（_dxf_cad_render 所有）
dxf_plan_recog/   # 识别叠加图（_dxf_png_batch 所有）
<name>.glb        # 交付模型
.orig/            # ⚠️ 数据回滚备份，不是噪音，永远不要删
```

## 数据管道

```
DWG
 │  convert_dwg_to_dxf.py          audit=1（不开会漏实体）
 ▼
DXF (CAD 毫米)
 │  classify.py 或 classify_line.py    ← profile.json 的 classifier 字段分派
 ▼
walls / doors / stairs / columns
 │  extract_floor()  22 步
 ▼
floors/floor{N}.json
 │  ⚠️ recognize() 产的内墙是"粗环 blob"，不是交付物
 │  _wall_thin_batch.py  从 DXF 重配对 → 真实厚内墙
 │  + _punch_doors()     门洞必须在这里再挖一次
 ▼
floors/floor{N}.json  (终态)
 ├─► qa_structural.py        I1–I10 不变量门禁
 ├─► build_standard_glb.py   → .glb
 ├─► _dxf_cad_render.py      → 源图纸
 └─► _dxf_png_batch.py       → 识别叠加图
```

**生产路径辨识（最容易走错）：**
```
❌ recognize() 直接产出的内墙     → 粗环 blob，覆盖率 >20%，不是交付物
✅ recognize() → _wall_thin_*     → 真实厚内墙，才是交付链
```

## 两个分类器（每栋楼不同）

通过 `profile.json` 的 `classifier` 字段分派（`getattr(p,"classifier","lwpolyline")`）：

| | `classify.py` | `classify_line.py` |
|---|---|---|
| 约定 | LWPOLYLINE | LINE + INSERT |
| 适用 | 除 c006 外全部 | **仅 c006 逸夫楼** |
| 墙 | 闭合多段线 | 双线配对（厚 240/270/350/380mm） |
| 柱 | 独立图层矩形 | INSERT 块，scale 编码尺寸 |
| 门 | 几何量取 700–1500 | INSERT 块 scale 解码 |

两者返回同构四元组 `(walls, doors, stairs, columns_raw)`，下游无感。

## 铁律（改动前必读）

1. **一个产物目录只有一个所有者脚本**（`dxf_plan/` 归 `_dxf_cad_render`，`dxf_plan_recog/` 归 `_dxf_png_batch`）
2. **门 = gap 不是 hole** —— 门洞盒深度必须 > 墙厚，否则出「洞中洞」
3. **门洞必须在 recognize 和 wall_thin 两处都挖**
4. **墙 `id` 必须唯一**；切墙后最大块继承原 id（保住 `windows[].wallId`）
5. **楼层内部从 0 开始，显示从 1 开始**
6. **FROZEN = {c006, c009, c103, c104}** 不得批量重建
7. **`qa_structural.py` 只读**，不可改不可移
8. **不得跑 `run_batch.py`**
9. **不得对有 `.orig` 备份（曾人工修过楼层）的建筑跑 `run_building.py`**
10. **`data/` 不在 git 里** —— git 只管代码；`data/` 2.75 GB 走机外备份（服务器副本 + 移动硬盘）。
    `data/buildings/*/.orig/` 是人工修复成果的**唯一来源**，45 栋楼的 `.orig` 一个都不能删，
    同步脚本**永远不加 `--delete`**。改引擎前手动备份 + 数值化复验 + 失败自动回滚。

## 标准命令序列

```bash
python -u convert_dwg_to_dxf.py <name>      # 0) DWG → DXF
python -u run_building.py <name>            # 1) 识别 → 楼层 JSON
python -u _wall_thin_batch.py <name>        # 2) 内墙重建（交付链真内墙）
python -u qa_structural.py                  # 3) 门禁（任何改动后必跑）
python -u _glb_only.py <name>               # 4) 出 GLB（不重跑 recognize）
python -u _dxf_cad_render.py <name>         # 5) 源图纸
python -u _dxf_png_batch.py <name>          # 6) 识别叠加图
python -u _dxf_compare_render.py            # 7) A|B 对比页 + 总目录
python -u build_index.py                    # 8) 刷新索引
```

**外科式修单栋**（不整栋重跑，避免窗数变化）：
```bash
python -u _door_punch_apply.py <name>       # 备份 → 挖洞 → 数值复验 → 失败自动回滚
```

## 运行

```bash
# 建模控制台（8130）
python backend/web/control.py

# 房间 API + 单层查看页（8123）
python backend/db/serve_rooms.py

# 静态前端（8000）
python -m http.server 8000 --directory D:/gym3d
```

- 多楼层浏览：`http://localhost:8000/frontend/building.html`
- 建模控制台：`http://localhost:8130/`
- 六教查看器：`http://localhost:8000/frontend/render_j6.html`

## 配置：先复制 .env

**代码里不再有任何口令默认值。** 读不到 `LIHUA_DB_PASSWORD` 就拒绝连接，不会静默退回弱口令。

```bash
cp .env.example .env     # 然后编辑 .env 填入口令
```

`.env` 已被 `.gitignore` 排除，不会进版本库。键清单见 `.env.example`，本机/服务器的差异见下表：

| | Windows 本机 | Linux 服务器 |
|---|---|---|
| `GYM3D_COMPUTE` | `1`（可建模、可改参数） | `0`（只发产物，写接口一律 403） |
| `GYM3D_DXF_DIR` | `D:/dxf_output` | 不设 |
| `LIHUA_DB_USER` | `postgres` | 建**只读账号**，不要超级用户直连 |
| 文件位置 | `D:\gym3d\.env` | `/opt/gym3d/.env`（`chmod 600`），**不进 ecosystem.config.js** |

## 备份与回退

git 接管的是**代码**；`data/`（2.75 GB）不在版本库里，靠机外备份保命。

| 对象 | 手段 | 说明 |
|---|---|---|
| 代码 | git（`pre-refactor` 及 `phase-N` 标签） | 每阶段一个锚点，`git revert` 单提交即可回退 |
| `data/` | 服务器副本 + 移动硬盘冷备 | rsync 用 `--checksum --partial --append-verify` |
| 人工修复 | `data/buildings/*/.orig/` | **唯一来源**，45 栋有；永不删、永不同步删除 |
| 产物完整性 | `manifest.json`（每栋 sha256 + buildId） | 同步末步用 `verify-sync.py` 核验，非零退出即失败 |

> ⚠️ 一个产物目录只能有一个所有者脚本（铁律 1）。批量脚本必须拒绝单栋调试覆写总目录
> —— 2026-09-10 的图纸回归事故就是这么来的。

## 数据库

PostgreSQL `lihua_twin`：`host=localhost port=5432 user=postgres`
口令**只从环境变量 `LIHUA_DB_PASSWORD` 读**（见 `.env`，不入库）；
读取逻辑统一在 `backend/db/db_config.py`，`load_rooms_db.py` 与 `serve_rooms.py` 都走它。

## 文档地图

| 文档 | 内容 |
|---|---|
| **`算法与流程总览.md`** | ★ 全链路算法、阈值总表、铁律（**先读这个**） |
| **`重构方案·后端前端.md`** | ★ 后端 FastAPI + 前端 React 重构路线图（阶段/验收/回退/风险） |
| `三维建模·算法总结与下一阶段规划.md` | 诊断 + 三阶段规划 |
| `建模方法论·现状·缺口·专业优化路线.md` | 方法论现状与缺口 |
| `楼层对齐修复方案.md` | 楼层对齐 |
| `楼层错位排查·思路复盘.md` | 方法论：构件对应法 |
| `kb/` | CAD 识图知识库 |
| `_scratch/README.md` | 归档脚本分组导航 |

## 已知缺口

- 窗全为 `synthetic=True`（窗缺框）；楼梯缺扶手；电梯缺轿厢（`elevators[]` 建模层不消费）
- 13 栋建筑 `sw=0`（无窗）
- c059–065 / c056 / c057 有约 1.5 m 楼梯井碎片
- **`data/lihua-building.glb` 仍 29.863% 开边**（理化楼基线，不在 49 栋批次内，待单独重出）
- c022 首层未重出（`walls=4`），缺陷是引擎级的：粗环 + 斜墙，并入宿舍识别方向处理
- c043 首层、c034 南带曾审计出墙漏检，已完成首层试点移植
