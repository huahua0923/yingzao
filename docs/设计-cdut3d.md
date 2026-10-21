# cdut3d 设计说明

## 1 逻辑架构

```text
本地生产面
  CAD/DXF + 航拍原片 + 控制点
       │
       ├─ 识别/重画/建件/FreeCAD/GLB
       ├─ 闸账与正对照
       └─ 倾斜摄影 SfM/MVS → 网格/点云 → 3D Tiles
       │
       ▼
发布包（release-manifest.json + SHA-256）
       │
       ▼
服务器展示面
  Nginx(TLS/认证/限速/缓存)
       ├─ 静态：demo / packs / process
       └─ 管理：Python API + 工作台 + 流程台
```

## 2 模块划分

| 模块 | 职责 | 边界 |
|---|---|---|
| `rebuild/tools/` | 识别、重画、建件、几何与格式转换 | 只读源图，写本楼工作目录 |
| `gates/` | 独立判据、正对照、台账 | 不复制生产实现 |
| `packs/` | 已验收交付包 | 不带原片，只带 manifest、几何、元数据和质检 |
| `demo/` | Three.js 查看器与展示页 | 不生成几何，只消费 published pack |
| `workbench/` | HTTP 服务、工作台、参数与任务 | 本地/管理面；写操作必须受保护 |
| `pipeline/` | 图纸到模型流程台 | 复用同一 Python 进程，不另起公网端口 |
| `deploy/` | 发布、Nginx、systemd、探活 | 不含口令 |

## 3 数据模型

- `campus_id`：校区/数据域，例如 `cdut-main`。
- `building_id`：楼栋稳定 ID，例如 `c006`。
- `component_id`：构件稳定 ID，按规范由楼层、类型和几何指纹生成。
- `pack`：一个楼栋的一次可交付快照。
- `gate_run`：判据一次实跑的输入、输出、退出码和时刻。
- `release`：一次可部署的全量发布，带文件清单和 SHA-256。

## 4 关键取舍

1. **单体服务先保留**：当前代码和部署规模不需要立即拆微服务；先通过 Nginx 分展示/管理面，降低改造风险。
2. **白模与实景分层**：白模负责可剖切、可点选、可查询；实景负责远景真实观感。
3. **判据独立于生产实现**：能红的正对照比“看起来对”更重要。
4. **发布目录不可变**：切换靠符号链接，不覆盖正在服务的目录。
5. **大文件流式传输**：不在 Python 内存中整读 GLB。
6. **标准基线随项目走**：`规范.json` 是指北针池子的自包含副本，离开指北针也能核。

## 5 接口

- 页面：`/`、`/buildings`、`/admin`、`/pipeline`、`/compare`、`/criteria`。
- 健康：`/live`、`/health`。
- 静态：`/demo/`、`/packs/`、`/process/`、`/rebuild/`。
- 工作台 API：`/api/overview`、`/api/building`、`/api/state`、`/api/run` 等。

详细字段见 `docs/数据交换与接口.md`。

