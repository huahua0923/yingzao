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
11. **判据的容差档位全模块统一 1e-6（相对）**，别为"更严"写 1e-9。地垫 / 场地环这类
    **从几何生成**的产物与源多边形之间只该有浮点往返噪声（相对 ~1e-7）；用绝对 1e-9 判
    "点集完全相同"会把噪声报成「不是任何房间的地垫」，把人往数据问题上带偏
    （c103 实测：1537.4470 m² 的房间，差 0.0001 m² = 相对 6.5e-8）。同一模块已有三处 1e-6，
    新判据照抄这档。
12. **写进 spec 的字段，无条件加就等于改每一栋的字节**。复现门是 sha256 **逐字节**比对，
    任何"自证字段"都必须条件添加（如 `if len(f0) > 1`），否则 lihua/ny27 立刻假红 ——
    哪怕那栋楼一个字都不该动。
13. **报错要把「0 个」和「≥2 个」分开说**。两者是**不同的病**：0 个 = 地垫与房间不同源（生成侧
    问题）；≥2 个 = **房间嵌套或重复**（数据问题）。混成一句"不是任何房间的地垫"，会指错方向
    （本段实测按错方向查了两轮）。
14. **"房间多边形非法"不能一刀切成"非法即拦"**：全库 **558 个自交多边形、分布在 21 栋**
    （c017 250 / c059 72 / c006 51 / c034 48 / c032 36 / c104 20 / c009 17 / c080 17 /
     ny27 12 / c103 11 / c033 8 / c027 7，c018 c022 c028 c041 c054 c055 c083 c085 c114 各 1~2），
    GEOS 只在**恰好撞上**某个运算时才抛 —— 只能把抛出的那一刻指名道姓报出来（`_geos_meas`），
    不能整层拦。2026-09-13 已修 **543 间**（20 栋 / 68 层，`_scratch/_fix_self_intersections.py`），
    **15 间**保留原样（c006 13 / c009 1 / c041 1，见「已知缺口」）。
    可改范围的上限见铁律 17：**只允许"区域逐点不变"的清洗**；
    真会改区域的必须走**铁律 18 的具名例外表**（不放宽判据，只开一个口子）。
15. **复现门必须跑在固定输出路径上**。spec 的 `"name"` 字段派生自 `-o` 的**文件名**
    （`-o lihua.json` → `"name":"lihua"`；`-o _lihua_floors_spec.json` → `"name":"_lihua_floors_spec"`），
    换个输出名 sha256 必然不同 —— 2026-09-13 一次假红的根因：lihua 三个字节数
    （1399891 / 1399896 / 1399904）的差**全部**来自 name 字段长度，几何逐字节相同。
    可比的前提只有一条命令形：
    `python backend/modeling/su_spec_floors_fleet.py <name> -o _scratch/su_jobs/_<name>_floors_spec.json`
16. **dry-run 必须真的跑过写盘那条路**。`if not apply: continue` 若挡在 `json.dumps` 前面，
    那么 dry-run 全绿只等于"这段代码从没被执行过"—— 2026-09-13 `read_indent` 的 bytes/str
    不匹配（`open(fp,"rb").read()` 配 str 正则）在 dry-run 全绿之后于 **apply 首跑崩掉**。
    修法：把「构造待写内容」移到 `continue` **之前**（`_fix_self_intersections.py` 已改）。
17. **量什么就写什么**（"量一个、写另一个"是最隐蔽的一类错）。交付格式定死了能表达什么，
    守卫就必须量**那件真正要落盘的东西**，不能量中间量。
    ★ 2026-09-13 判例：`_fix_self_intersections.py` 取 `buffer(0)` 的**最大块**，守卫量的是
    `main_p.area`（Polygon **已扣孔**），落盘写的却是 `main_p.exterior.coords`（**把孔填掉**）。
    c006/floor1 #31 `6-C-02-05`：量到 694.5681、写成 **1036.1174（+48.7%）**，1% 面积守卫
    照旧放行 —— 填掉的孔 341.5493 m² 里正是 `6-C-02-03` 整间（124.2560）+ `6-C-02-04`
    （49.1226），**等于让一间房盖住两间房**。
    ⇒ 两条硬约定：① 交付 `poly` 只有单个外环 ⇒ `interiors` 非空的**一律不改**；
       ② 判据一律量**要落盘的那条环**（`written`），面积差判据让位给
       `written.symmetric_difference(buffer(0)).area <= 1e-6`（区域逐点不变）。
    代价：可修 535 → **532** 间；收益：**可证零影响**（49/49 spec 逐字节相同）。
    ⚠️ 那次比对的**方法有个盲区**：只比了 `spec_pre/` 里已有的 49 份，**改前不存在的文件不算数**
    —— 恰好当时 c103 还没过闸门（没有 spec），所以"零影响"结论对那 532 间仍然成立，
    但这个盲区会在下次把主角静默跳过（见「已知缺口」与铁律 18 末尾）。
    ⚠️ 注意本条的**另一半**：spec 里**有**房间派生数据（下条），所以"几何没变"必须逐间实测，
    不能靠"spec 不含房间坐标"这句话推。
18. **要放的宽，必须是"具名口子"，不是"放宽判据"**。判据（铁律 17 的区域逐点不变）一旦为了
    某一栋调松，就对全库 49 栋一起松了 —— 那 3 间的例外会变成 500 多间的例外。
    ⇒ 例外按 **(栋, 层文件, 房号)** 逐条列进 `REGION_CHANGE_OK`，并**记下实测损失量**，
    跑的时候用 `LOSS_TOL`（5e-4 m²）**对账**：数据一变（"当初批的是 0.3455、现在变成 3.4"）
    就**中止不写**，不静默放行；且必须显式 `--allow-region-change`，默认一律按 17 走；
    报告里**单独一行**印，不许混进"零影响"那批。
    ★ 2026-09-13 判例：c103 是全库**唯一**没过 SU 规格闸门的栋，卡点实测（沙盘三情景对照
    `_scratch/_probe_c103_partial_fix.py`：①原样红 ②只修区域不变那 8 间**仍红**
    ③修满 11 间才绿）就是 F2/F3/F4 的 A 翼 `103-A-0N-02` 各自交。用户拍板"修满 11 间"后
    落盘：8 间零影响 + 3 间各丢 0.3455 m²（A 翼末端一小叶，与主体仅隔 0.03 m、
    **不落在任何别的房间里** ⇒ 修完该处成为地板空洞；占该房 0.01%）。
    变异验证：把表里损失量谎报成 0.05 ⇒ 3 间全被"对不上、中止不写"拦住（守卫非空断言）。
    ⚠️ 沙盘还有一条更贵的教训：控制组要能**有效**。第一版沙盘只搬 floors/rooms/profile，
    漏了 `spec.json` ⇒ `load_spec()` 静默落进**没有 `style`** 的硬编码兜底 ⇒ 9376 个部件
    落成 `#888888`/`#8a5a38` ⇒ **三情景全红、控制组失效**，差点据此推翻"c103 卡在自交"。
    ⇒ 搭沙盘必须把**闸门真正读的那份输入**整套搬过去，并硬守卫"缺了就 SystemExit"。
19. **格式探测失败时，正确动作是"别动格式"，不是挑一个默认值**。改写交付文件前要照原文
    探测缩进/行尾，**探不到就不要加**。
    ★ 2026-09-13 判例（本仓最贵的一次静默副作用）：`read_indent` 用 `rb'\n(\s+)"'` 探缩进，
    在**紧凑单行**文件上必然匹配不到，于是 `return 1` —— 把整份 JSON 重新缩进排版：
    **62 个交付层文件 19.4 MB → 35.9 MB（×1.85）、0 行 → 7 万行**，语义一字未变所以
    **任何解析型门禁都发现不了**（spec 逐字节相同、`qa_structural` 逐行相同），
    只有"比文件字节"才看得见。⇒ 现在 `read_indent` 无换行时返回 `None`（按紧凑写回）、
    多行时用 `( *)` 而非 `(\s+)`（否则 indent=0 会被"补"上缩进）。
    已从 `.orig` 备份整批回滚重跑，验证：重出的 c103 spec 与缩进版时代**逐字节相同**
    （`8f21ca3b18258758`，12,766,064 字节）⇒ 证明回写是语义中性的、几何修复完好；
    全库闸门仍 **49/49**、`qa_structural` 与改前**逐行相同**。
    **判据：格式探测必须能"解析后按探测结果写回 == 原文逐字节"**（本条已用
    compact / indent=1 两类文件各测过）。

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
| 人工修复 | `data/buildings/*/.orig/` | **唯一来源**，实测 **47/49 栋有**（2026-09-13 核）；永不删、永不同步删除 |
| 产物完整性 | ~~`manifest.json` + `verify-sync.py`~~ | ⚠️ **还没做**：`manifest.json` / `make-manifest.py` / `verify-sync.py` **三个文件在仓库里都不存在**（2026-09-13 实测），本行原先是把 `重构方案·后端前端.md` 里的**计划**写成了现状。同步**目前没有完整性门禁**，靠人工比对；要落地见那份方案的"数据同步"一节 |

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
- ~~**SU 分层建模（`su_spec_floors_fleet.py`）全库 50 栋：49 通过，c103 未通。**~~
  **2026-09-13 已收口：全库 49/49 通过**（`_scratch/_su_fleet_census.py --jobs 4`，
  通过 49 / 49，总墙钟 127.3 s，报告 `_qa_selfint/fleet_census_after_c103.txt`；lihua 不在此
  普查内 —— 它在 `data/floors`，另有逐字节复现门 sha256 `c67ba3e8a19a…` ✓ 不变）。
  c103 卡点是 `floors/` 里 11 个房间多边形**自交**（F1×2、F2–F4 各 3），GEOS 判地垫归属时抛
  `TopologyException`；处置见**铁律 18**（8 间零影响 + 3 间走具名例外表各丢 0.3455 m²）。
  ⚠️ **c103 的下游这次真的过期了**（与此前"49/49 spec 逐字节相同 ⇒ 什么都不用做"**不同**）：
  它的 `floors` 有 3 间房几何变小 ⇒ **c103 的 GLB 需重出**，`rooms` 那份 DB 也需重新同步。
  同时 `rooms.json` 侧**没改**（那 3 间在 `rooms.json` 里仍是自交的原环）⇒ 两份交付件
  在这些房间上**此刻不一致**，见下面那条。
- **全库房间多边形自交已修 543 间（20 栋 / 68 层）**（`_scratch/_fix_self_intersections.py`，
  备份 `.orig/floors.before_selfint/`）：532 间是**区域逐点不变**的清洗 ——
  与改前逐间比对，对称差 ≤1e-6 m²、房间**条数**不变（`_scratch/_probe_fix_scope.py`）；
  另 11 间（c103，4 层）见铁律 18。
  ⚠️ 口径以**脚本自己的合计**为准（`_qa_selfint/apply4_compact.txt`：20 栋 / 68 层 / 543 间）；
  早先本文件写的"65 层"是错的（减掉 c103 的 4 层后，其余那批是 **19 栋 / 64 层 / 532 间**）。
  备份目录里有 **69** 个文件、比实际改动的 68 层**多一个**（`c006/floor6.json`）—— 那是
  **旧判据（1% 面积差）时代的遗物**：它那间 `6-C-07-02` 当时被判"可修"所以写了盘，
  判据换成区域对称差后归入"保住不改"⇒ 该层不再写盘；备份内容与原文件**逐字节相同**，
  回滚它就是无操作。**"有备份" ≠ "被改过"**（铁律 19）。
  **15 间保留原样**（c006 13 / c009 1 / c041 1，逐间四类清单
  `_scratch/_qa_selfint/remaining_invalid_after_c103.txt`，由唯一所有者
  `_scratch/_probe_selfint_refused.py` 生成 —— 判据**直接引主脚本常量**，
  不再自带一份 `MAX_REL`）：
  - c006 11 间是**自相吞并**（`buffer(0)` 砍 27%~49%，`6-C-08-01` 343.25→174.93，
    F7–F10 四层同型）—— 自动改 = 自动丢房间；
  - 另 3 间**修后区域真的会变**（c006 `6-C-02-05` / `6-C-07-02`、c009 `09-C-01-01`；
    `6-C-02-05` 更是修后带 1 个 341.55 m² 的**孔**，见铁律 17）；
  - c041 `41-06-04` 1 间（修掉要丢 132.75 m² / −44.23%，只能交人工）。
  **这次有 spec 层面的零影响证据（且必须分开读）**：全库 **49 份改前 spec 逐字节相同 / 0 不同**
  （`_scratch/_probe_spec_census_diff.py` → `_qa_selfint/spec_census_diff3.txt`），
  并**新增 11 份**改前不存在的 spec —— 其中本链相关的是 `_c103_floors_spec.json`
  （12,766,064 字节，c103 改前没过闸门 ⇒ 没写盘 ⇒ 不在改前那 49 份里）。
  ⚠️ **不列"新增"这一栏，就会得出"49/49 逐字节相同"这种看着干净、实际漏掉主角的结论。**
  `qa_structural` ERROR=3/WARN=307/FAIL=1 栋（仅 c104）与改前**逐条相同**。
- **`rooms.json` 侧的自交环从未清洗过，是一笔独立的账**（2026-09-13 新量，此前没人数过）：
  全库 `rooms.json` 里 **530 间** `boundary` 自交（19 栋：c017 250 / c059 72 / c034 48 /
  c032 36 / c080 17 / c027 14 / c103 14 / ny27 12 / c104 9 / c033 8 / 其余各 1）。
  ⚠️ **两份交付件在"自交"这一项上本来就不是同源的**：floors 侧改前 558 间、`rooms.json` 侧 530 间
  —— 差 28 间，且**具体哪几间也不同**（例：c041 floors 侧是 `41-06-04`，`rooms.json` 侧是
  `41-01-05`）。所以本次 floors 侧修完 543 间之后，两边差 543 间（**不是我改出来的分叉，
  是把旧有的分叉放大了**）。⇒ **`rooms.json` 要不要照同一套判据清洗，须单独拍板**，
  不能顺手动：它喂 `/api/rooms` 与导航（`build_path.py`），一改就得连 DB 同步一起做。
  （另注：c103 `rooms.json` 对 `103-A-0N-02` 只有**一行**，`area_m2`=1576.25 而 `boundary`
  重算是 3422/3455 —— 正是下面那条 A 翼同号冲突的另一面。）
  ⚠️ **早先"spec 不含房间坐标"的说法是错的**：spec 里有**房间派生的 `地垫` parts**
  （`cat:"地垫"`、`roomNo`/`purpose`）与 `meta.rooms_label[].area` —— 房间多边形一变 spec 就变。
  判例：改前那版把 c006 `6-C-02-05` 写成了填孔版，spec 立刻差出
  `rooms_label.area 696.589→1036.117`、`catCounts.地垫 246→241`、`kinds.wall 9841→9836`
  （地垫走 `_add` 的默认 `kind="wall"`，所以"墙少 5 件"其实是少 5 块地垫碎块）。
  **49/49 相同的原因是这次只做区域不变的清洗，不是因为 spec 与房间无关。**
  c104 的 `qa_structural` FAIL 3 已 A/B 证为既存病（`_scratch/_probe_c104_i3_ab.py`：
  改前/改后 ERROR 逐条相同）。
- **`floors/` 里房间同号 —— c103 是 42 对，不是"每层 3422 一条、六层共 5 条"**
  （`_scratch/_probe_c103_samenum.py`）：F1–F4 各 8 对、F5 10 对，**F0 无 A 翼对**。
  分两种病、处置相反，**都还没动**：
  - **B 翼 38 对 = 图纸多副本**：两条**完全不相交**（重叠 0.0%），质心距 27.16 m（F1–F4）/
    8.89 m（F5）。**四重独立证据一致指向 copy2（高下标）是真的**：① 它与"其余所有房间
    （含其它幽灵）"的交叠**精确为 0**（房间铺满楼板不重叠），copy1 压别人 79.5~219.2 m²；
    ② `rooms.json` 的 `boundary` 逐点等于 copy2（对称差 0.0000、质心距 0.000 m）；
    ③ `rooms.json` 的 `area_m2` 也等于 copy2（79.54 / 109.75 / 107.29 / 78.84）；
    ④ copy1 的对称差 = 2×面积（完全不相交）。⇒ **copy1 是幽灵**。
  - **A 翼 4 对（F1–F4）= 部分重叠的两块，证据冲突**：1537 与 3422/3455 重叠 **73.25%**
    （四层稳定），**两条都压别人**（780.7 / 1189.7），**两条都不自洽**；且 `rooms.json`
    这一行**自己矛盾**：F1 的 `boundary` 是 3422 那条（逐点相同）、`area_m2` 却是 1543.42
    （≈1537 那条），F2–F4 的 `boundary` **本身自交**（GEOS 算不了）。⇒ **不猜。**
  （早先的 `_probe_room_nesting.py` 只用"包含/重叠"判据，**看不见"同号但完全不相交"的幽灵**，
  所以漏了 B 翼 38 对 —— 普查同类问题时必须再加一问：「同号的是否相交」。）
- c041 与 c034 的 `4N-0N-01`（80.1 m² 包住 74.7 m² 同号房，差 5.46 m² ≈ 0.15 m 外墙带）、
  c033 的 `34-01-05A`（602.5 m² 包住 `34-01-11` 20.4 m²）**不动**（已记档）；
  **c009 F3 另有同号房 `09-A-04-07` 两条**（各 143.0558 m²，`_probe_room_nesting.py` 漏报，
  因两条不相交）—— 全库"同号"这一类比早先普查的 4 栋更宽。
  c041 的"逐点完全相同"副本已删 41 条（`_scratch/_dedup_floor_rooms.py`，
  备份 `.orig/floors.before_dedup/`）。
