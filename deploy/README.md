# 部署到服务器（202.115.133.14 · RHEL/CentOS + nginx）

> 目标形态：**浏览器 → nginx → 127.0.0.1:8140 uvicorn（systemd 常驻）→ PostgreSQL**。
> 本目录只放**部署件**：跑之前先把 `..` 里的代码提交并推上去。

## 分工（2026-10-01 定）

| 阶段 | 谁做 | 在哪 |
|---|---|---|
| 0 提交推送 | 我 | 本机（`git push`） |
| 1 打包数据 | 我 | 本机，产出 `gym3d-data-<日期>.tar.gz` |
| 2 服务器上的命令 | **你**（我只给命令，不 SSH、不 scp、不要密码） | 服务器 |
| 3 端到端探针 | **你**跑，把输出贴回来 | 服务器 |

---

## 阶段 1 · 本机打包（我）

```
bash deploy/pack_data.sh
```

它**只带走**门户页与 API 必需的最小集（747 个文件 / 压缩后 20 MB）：

```
data/buildings/index.json
data/buildings/*/profile.json  spec.json  rooms.json
data/buildings/*/floors/*.json
campus-terrain/            ← 10 件：8 个固定名 + 2 张洞底截图
```

名单是**现算**的（洞底截图的名字从 `campus_terrain_viewdata.json` 现读，与
`/campus/hole/{name}` 路由同源），三条断言也都钉在现算的数上：

1. `tar -tzf` 的文件数 == 名单行数（一个不多一个不少）
2. `data/buildings/` 下零个 `.glb/.png/.jpg/.dxf`，全包零点目录，且包内 `.glb` 恰好 2 个
3. **真解一遍**：`profile.json` 92 个、`index.json` 1 个、campus 10 件

> ★ 断言 2 原先在方案里写成「全包零 `.glb` / 零 `.png`」——那是**错的**：
> campus 那两件 `.glb` 和三张图正是**要带走的交付件**，照原话写会把它们一起拦下。
> 已改成只管 `data/buildings/` 一侧。

**不带走的**（≈2.3 GB，明说，不静默）：单栋 `.glb` 793 MB、楼层图 / CAD 图 232 MB、
`.orig/` 备份 1.1 GB。代价：服务器上「点开一栋看三维和图纸」不可用，其余全可用。

## 阶段 2 · 服务器（你跑）

**2.1 拉代码**
```
cd /opt && sudo git clone https://github.com/huahua0923/yingzao.git gym3d
```

**2.2 装依赖**（这份 requirements **刻意不含** ezdxf/shapely/trimesh，服务器不需要）
```
cd /opt/gym3d && sudo python3.12 -m venv .venv && sudo .venv/bin/pip install -r requirements-server.txt
```

**2.3 放数据**（把阶段 1 的 tar.gz 传上来之后）
```
cd /opt/gym3d && sudo tar -xzf gym3d-data-<日期>.tar.gz && sudo chown -R gym3d:gym3d /opt/gym3d
```

**2.4 建库灌库**
```
sudo -u postgres createdb lihua_twin
sudo -u postgres pg_restore -d lihua_twin /tmp/lihua_twin.dump
sudo -u postgres psql -d lihua_twin -c "create role gym3d_ro login password '<你定的口令>'"
sudo -u postgres psql -d lihua_twin -c "grant select on all tables in schema public to gym3d_ro"
```

灌完**立刻删那三个演示号**（它们的口令进过对话记录）：
```
sudo -u postgres psql -d lihua_twin -c "delete from users where username in ('admin','c006admin','viewer')"
```

删完要留一个能登进去的搭建方：
```
sudo -u postgres env GYM3D_SETPW_DSN="dbname=lihua_twin" \
  python3 -m backend.db.set_password <你定的用户名> --role builder --scope '*'
```
它会**隐藏着**让你敲口令（不回显、不进 shell 历史、不进进程表、不打印）。
也可以先把口令放进环境变量：`export GYM3D_NEW_PASSWORD='...'`（**别写进任何文件**）。

**2.5 `.env`**（复制 `.env.example` 再填；**这份文件不进 git**）
```
GYM3D_ROOT=/opt/gym3d
GYM3D_HOST=127.0.0.1
GYM3D_PORT=8140
GYM3D_ENV=prod
GYM3D_COMPUTE=0                 # ★ 执行面整条关死
GYM3D_LOOPBACK_BREAKGLASS=0     # ★ 环回放行闸关掉
GYM3D_SESSION_COOKIE_SECURE=1   # 走 HTTPS 时；纯 http 的 IP:端口 要置 0，否则登录后立刻又变匿名
GYM3D_CORS_ORIGINS=
GYM3D_CAMPUS_DIR=/opt/gym3d/campus-terrain
LIHUA_DB_HOST=localhost
LIHUA_DB_PORT=5432
LIHUA_DB_NAME=lihua_twin
LIHUA_DB_USER=gym3d_ro
LIHUA_DB_PASSWORD=<填>
LIHUA_DB_REQUIRED=1
```

> **`GYM3D_COMPUTE=0` 为什么是必须的**：`deps.py` 的执行面闸看的是 TCP 对端地址
> （`client_is_loopback`，明写「不读 Host、不读 X-Forwarded-For」）。nginx 与本进程
> **同机** ⇒ 对端恒为 `127.0.0.1` ⇒ 整条执行面对任何能到达 nginx 的人敞开，且这与
> breakglass **无关**。`GYM3D_COMPUTE=0` 的 `if not cfg.compute` 排在 loopback 判断
> **之前**，一关全关。
> 已核过它**不误伤门户页的写入**：`require_cap` 完全不读 `cfg.compute`，而
> `POST /api/portal/anchors` 挂的是 `require_cap("manage")`，没有 `require_compute`
> ⇒ **搭建方在服务器上照样能锚定**。

**2.6 服务单元与 nginx**
```
sudo cp /opt/gym3d/deploy/gym3d-api.service /etc/systemd/system/
sudo cp /opt/gym3d/deploy/nginx-gym3d.conf  /etc/nginx/conf.d/
sudo systemctl daemon-reload && sudo systemctl enable --now gym3d-api
sudo nginx -t && sudo systemctl reload nginx
```

**2.7 开端口**（走内网域名 + 443 就不需要这一步）
```
sudo firewall-cmd --permanent --add-port=8141/tcp && sudo firewall-cmd --reload
```

## 阶段 3 · 探针（你跑，把输出贴回来）

```
bash /opt/gym3d/deploy/verify_deploy.sh http://127.0.0.1:8140 http://202.115.133.14:8141
```

第 2 条（不带 cookie 拿不到数据）是**唯一**能分辨「`.env` 写对了」与「`.env` 没生效」
的一条 —— 只看文件不算数。它的阳性对照我实测过：同一台机、同一份代码、同一条路由，
只翻 `GYM3D_LOOPBACK_BREAKGLASS` 一个变量 → `1` 时回 **200**、`0` 时回 **401**。

探针不能替你看的两条（要用浏览器）：
5) 打开 `/portal/` → 出登录屏，且**一条数据都不出**
6) 登录搭建方 → 点一块 → 锚定一栋 → 面板出楼层与用途

---

## 已知在服务器上会坏的（如实说，不静默）

- **`/api/path`**：`backend/nav/*.mask.bin` 盘上一份都没有 ⇒ 这条路由必然坏。
- **单栋三维模型与图纸**：不在最小集里（见阶段 1）。
- **`/api/buildings/<id>/source_dxf`**：`GYM3D_DXF_DIR` 留空 ⇒ 明确回 404 并说明原因，
  这是**设计**不是故障。
- **高德底图**：本机 key 绑域名白名单、`127.0.0.1` 不在里面，两条通道都被拒（已实测）。

## 这一轮不做的

实景三维整片接入（124 格 / 48701 文件 / 9.9 GB → 3D Tiles）。它是**独立的一轮**，
本机链路已经跑通，产物是静态文件，走 nginx 直接 serve，与上面的进程和数据库无关。
