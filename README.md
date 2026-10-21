# cdut3d

成都理工大学校园三维数字底座。当前仓库包含三维白模生产链、模型包、浏览器查看器、建模工作台和图纸到模型流程台。

## 怎么跑

要求：Windows 或 Linux、Python 3.12、浏览器支持 WebGL2。

```powershell
cd D:\项目\cdut3d
python -m uv sync
python -X utf8 -I workbench/server.py --host 127.0.0.1 --port 8150
```

也可以双击 `go.bat`。启动后访问：

- 入口：`http://127.0.0.1:8150/`
- 楼房状态矩阵：`http://127.0.0.1:8150/buildings`
- 工作台：`http://127.0.0.1:8150/admin`
- 流程台：`http://127.0.0.1:8150/pipeline`
- 健康检查：`http://127.0.0.1:8150/live`、`http://127.0.0.1:8150/health`

## 生产服务器

- 地址：`https://202.115.132.14:8800/`
- 兼容入口：`http://202.115.132.14/`（同 6001 的 HTTP 直达方式）
- 入口：统一登录页
- 生产内容：三维模型首页、`/info` 房屋信息与统计页、只读模型包
- 生产模式：`CDUT3D_MODE=viewer`，工作台/流程台/写接口不在服务器开放
- 部署说明：`docs/服务器只读部署-2026-10-21.md`

当前使用 IP 自签名证书，浏览器首次访问会有证书提示；有正式域名后替换证书即可。

## 架构

当前是单体运行：`workbench/server.py` 同时托管静态前端和本地 API；`pipeline/server.py` 由工作台通过 `importlib` 复用，不再单独起 8800 端口。

生产部署应把它拆成两个管理面：

1. **展示面**：Nginx 提供 TLS、静态缓存、限速和压缩，对外只开放查看器、模型包、实景层与只读页面。
2. **管理面**：Python 服务只绑 `127.0.0.1`，由 Nginx/VPN/基础认证保护工作台、流程台和写接口。

详见 `docs/部署拓扑-cdut3d.md` 与 `deploy/README.md`。

## 数据边界

- 本地负责：CAD 识别、建模、质检、倾斜摄影重建、切片、正式模型包生成。
- 服务器负责：只读装载已验收的 `packs/`、实景层和检查报告，负责查看、检索、展示。
- 服务器不运行 AutoCAD、Blender、FreeCAD、RealityCapture、COLMAP，不做原片处理或切片。

## 目录

| 路径 | 用途 |
|---|---|
| `workbench/` | 本地建模工作台与唯一 HTTP 服务 |
| `pipeline/` | 图纸到模型流程台 |
| `demo/` | Three.js 查看器与展示页 |
| `packs/` | 已验收模型包 |
| `rebuild/` | 本地重建链、构件库与中间件 |
| `过程/` | 实景分层、对照与过程证据 |
| `gates/` | 判据与实测输出 |
| `docs/` | 需求、设计、数据、安全、部署与验收材料 |
| `deploy/` | systemd、Nginx、发布与探活脚本 |

## 验证

```powershell
python -m uv run pytest
python -X utf8 tests\负例_cdut3d.py
python -X utf8 tools\run_gates.py --tiers viewer,other
```

判据状态以 `gates/_out/_ledger.json` 的最近实跑时刻为准，不把旧读数当今天的结论。

## 当前状态

- 本仓已纳入指北针标准化基线：`规范.json`、`registry/栈.json`、`observed/`。
- 2026-10-21 全楼矩阵：67 栋 × 4 条 = 268 格，**225 通过 / 34 红 / 9 没量到**。
- 状态页：`/buildings`；逐楼明细：`docs/楼房状态矩阵-2026-10-21.md`。
- 63 / 67 栋通过 `J-10.8-04` 原始 DXF 叠加比对，房间台账合计 11,104 间。
- 已知未完成项见 `docs/缺陷-2026-10-20.md`、`docs/上线水平评估-2026-10-21.md` 和 `docs/系统评估与清理-2026-10-20.md`。

