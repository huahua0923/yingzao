# cdut3d 部署与发布管理

## 1. 运行边界

当前代码是单进程单体：Python 同时托管静态文件和 API。生产上仍可按“前端/后台”管理，但不建议把 Python 直接暴露到公网。

推荐两层：

| 层 | 谁提供 | 对外内容 |
|---|---|---|
| 展示面 | Nginx | `/`、`/demo/`、`/packs/`、`/process/`、静态模型和查看器 |
| 管理面 | Nginx 基础认证 + 本机 Python | `/admin`、`/pipeline`、`/compare`、`/api/`、`/files/`、写接口 |

Python 进程只监听 `127.0.0.1:8150`。Nginx 负责 TLS、限速、压缩、基础认证和访问日志。

## 2. 服务器目录

```text
/srv/cdut3d/
  releases/
    20261020-001/
      release-manifest.json
      ...
  current -> releases/20261020-001
  venv/
  logs/
```

每次发布都是一个完整目录。切换版本只改 `current` 符号链接，回滚就是切回上一个目录。
首次部署时先创建 `workbench/_jobs`、`workbench/_quick`、`workbench/_backup` 和 `rebuild/构件库` 这些可写目录，并确认运行用户有写权限。

## 3. 本地生成发布包

```powershell
cd D:\项目\cdut3d
python -X utf8 deploy\scripts\release.py build D:\tmp\cdut3d-release-20261020
python -X utf8 deploy\scripts\release.py verify D:\tmp\cdut3d-release-20261020
```

`release-manifest.json` 记录每个文件的相对路径、字节数和 SHA-256；上传后必须再跑一次 `verify`。

## 4. 上传与切换

上传建议使用校内有线网络、SFTP 或内网对象存储。不要把口令写进脚本。

```bash
sudo mkdir -p /srv/cdut3d/releases/20261020-001
sudo rsync -a --delete <本地发布目录>/ /srv/cdut3d/releases/20261020-001/
sudo ln -sfn /srv/cdut3d/releases/20261020-001 /srv/cdut3d/current
sudo systemctl restart cdut3d
```

切换后立刻探活：

```bash
python3 /srv/cdut3d/current/deploy/scripts/healthcheck.py \
  --base https://cdut3d.example.edu.cn
```

`/live` 失败表示进程没起来；`/health` 失败表示进程在，但 UI、模型包索引或判据输出缺失。

## 5. 配置

复制 `deploy/env.example` 到 `/etc/cdut3d/cdut3d.env`，由 systemd 读取。

- `CDUT3D_HOST`：生产固定 `127.0.0.1`
- `CDUT3D_PORT`：默认 `8150`
- `CDUT3D_ALLOWED_ORIGINS`：额外允许的写请求来源，逗号分隔
- TLS 证书与私钥只放服务器，不进仓库

## 6. Nginx

模板见 `deploy/nginx/cdut3d.conf`。上线前必须替换：

- `server_name`
- 证书路径
- `auth_basic_user_file`
- 静态资源根目录

建议对 `/admin`、`/pipeline`、`/api/`、`/files/`、`/quick/` 启用基础认证；若管理端只在校内，再叠加 VPN 或校园网 ACL。

## 7. 生产纪律

1. 服务器不运行建模、摄影测量、切片或 CAD。
2. 服务器只接收已验收的 `packs/` 和实景层。
3. 每次发布都带清单和 SHA-256。
4. 发布后必须探活，探活记录至少保留到下一次发布。
5. 回滚不重建数据，只切换 `current` 并重启服务。

