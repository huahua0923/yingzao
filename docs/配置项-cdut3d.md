# 配置项清单

| 配置项 | 来源 | 默认 | 说明 |
|---|---|---|---|
| `CDUT3D_HOST` | 环境变量/命令行 | `127.0.0.1` | 生产必须保持本机监听 |
| `CDUT3D_PORT` | 环境变量/命令行 | `8150` | Python 内部端口 |
| `CDUT3D_ALLOWED_ORIGINS` | 环境变量 | 空 | 额外允许的写请求来源，逗号分隔 |
| `PYTHONUTF8` | 环境变量 | `1` | 中文路径与输出 |
| `PYTHONIOENCODING` | 环境变量 | `utf-8` | 日志编码 |
| Nginx `server_name` | Nginx | 待定 | 校园域名 |
| TLS 证书路径 | Nginx | 待定 | 只进服务器 |
| `auth_basic_user_file` | Nginx | 待定 | 管理端口令文件，不进仓库 |

## 文件路径约定

- 代码根：`/srv/cdut3d/current`
- 发布清单：`/srv/cdut3d/current/release-manifest.json`
- 运行状态：`/srv/cdut3d/current/workbench/_jobs` 等
- 模型包：`/srv/cdut3d/current/packs`
- 实景层：`/srv/cdut3d/current/process`（磁盘目录可为中文 `过程/`）

## 禁止项

- 不在仓库写真实密码、令牌、证书私钥。
- 不在代码里写死生产域名和上传口令。
- 不让测试环境读取生产数据目录。

