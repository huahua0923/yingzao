# 部署到服务器（202.115.132.14 · RHEL/CentOS）

> **★ 现状（as-built，2026-10-02 实测）**：**浏览器 → uvicorn:8141（systemd `gym3d-api`）→ PostgreSQL**。
> **没有 nginx**（`systemctl is-active nginx` = `inactive`），**没有 TLS，不走域名**。
> `.env` 实测：`GYM3D_HOST=0.0.0.0` / `GYM3D_PORT=8141` / `COMPUTE=0` /
> `LOOPBACK_BREAKGLASS=0` / `SESSION_COOKIE_SECURE=0`。
> 外部实测 `curl http://202.115.132.14:8141/portal/` → **200**。
>
> 下面 2.6 那段 nginx 是**早期方案**，留着当备选，**不是现在的路**。
> ★ 号段别搞混：`202.115.132.14` 是这台；`133.14` **是另一台机器**（实测 8141 连不上）。
> 早先把两个地址当成一台，依据是「主机密钥逐位相同」——那个依据推不出这个结论
> （克隆镜像会带着同一个主机密钥）。分辨它们的是**钥匙接受与否**。

> 本目录只放**部署件**：跑之前先把 `..` 里的代码提交并推上去。

## 分工（2026-10-01 定，2026-10-02 更新）

| 阶段 | 谁做 | 在哪 |
|---|---|---|
| 0 提交推送 | 我 | 本机（`git push`） |
| 1 打包数据 | 我 | 本机，产出增量 `tgz` + sha 名单 |
| 2 服务器上的命令 | **我**（有 key 可登录；**口令一律在服务器上敲，不发进对话**） | 服务器 |
| 3 端到端探针 | 我跑，读数贴回 | 服务器 |

> ★ 2026-10-01 那一版写的是「我不 SSH、只给你命令」。后来的实际做法变了：
> 用已在 `~/.ssh` 里的钥匙直连部署，**口令仍在服务器上敲**，从未进过对话。
> 表格里的做法以本行为准。

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
> ★ 2026-10-02 实测：这三个号计数已是 **0**（本机与服务器两侧都删了）。
> 口令最后只出现在**本机开发库**里，泄漏面就那一处。

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
GYM3D_HOST=0.0.0.0
GYM3D_PORT=8141
GYM3D_ENV=prod
GYM3D_COMPUTE=0                 # ★ 执行面整条关死
GYM3D_LOOPBACK_BREAKGLASS=0     # ★ 环回放行闸关掉
GYM3D_SESSION_COOKIE_SECURE=0   # ★ 已定：走 IP:8141 的 http。置 1 会让浏览器**不发**这个 cookie
                                #   ⇒ 登录成功后下一个请求又变匿名，症状像"登录没生效"
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
> （`client_is_loopback`，明写「不读 Host、不读 X-Forwarded-For」）。
> ★ **若前面套 nginx**：nginx 与本进程同机 ⇒ 对端恒为 `127.0.0.1` ⇒ 整条执行面
> 对任何能到达 nginx 的人敞开，且这与 breakglass **无关**——这就是当初必须关它的理由。
> **现状没有 nginx**（`HOST=0.0.0.0` 直听），外部来的对端是真实远端地址 ⇒ loopback 判为假，
> 闸本来就关着。但 `COMPUTE=0` 仍然保留：它是**第二把锁**，不依赖「前面有没有 nginx」
> 这个会变的前提。`if not cfg.compute` 排在 loopback 判断**之前**，一关全关。
> 已核过它**不误伤门户页的写入**：`require_cap` 完全不读 `cfg.compute`，而
> `POST /api/portal/anchors` 挂的是 `require_cap("manage")`，没有 `require_compute`
> ⇒ **搭建方在服务器上照样能锚定**。

**2.6 服务单元**（★ 现状**只做前者**；nginx 那两行是备选，现在没在用）
```
sudo cp /opt/gym3d/deploy/gym3d-api.service /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now gym3d-api
# —— 以下仅在「决定改套 nginx」时才做（要单独问，不许顺手加）——
# sudo cp /opt/gym3d/deploy/nginx-gym3d.conf /etc/nginx/conf.d/
# sudo nginx -t && sudo systemctl reload nginx
```
> ★ **改完 `.env` 必须 `systemctl restart gym3d-api`** —— `EnvironmentFile`
> 只在**启动那一刻**读一次，改文件不重启 = 没改（现场实测过）。

**2.7 开端口**（★ 已定用 IP:8141 对外，**这一步必须做**）
```
sudo firewall-cmd --permanent --add-port=8141/tcp && sudo firewall-cmd --reload
```
> 漏了它的症状不是报错，是「服务器本机 curl 全通、外面一律连不上」——
> 本仓出过一次（5005），排查了半天才发现是 firewalld。

## 阶段 3 · 探针（你跑，把输出贴回来）

```
bash /opt/gym3d/deploy/verify_deploy.sh http://127.0.0.1:8141 http://202.115.132.14:8141
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
- **`/api/components` → 503**（**已修，不是坏**）：`ezdxf` 被这份 requirements
  **刻意排除**，而 handler 里那个 import 原先**没有 try** ⇒ 回的是 **500**。
  2026-10-02 已包进 try，实测：`503` + 中文说明（点名缺 `ezdxf`）；
  阳性对照 `/api/buildings` = `200`；阴性对照无 cookie = `401`。
- ~~`/api/console/branches` → 503~~ **已修**：原因是 `config/branches.json`
  **从没进过 git**（`git ls-files config` = 0，且不在 `.gitignore` 里）——
  这是**仓的问题不是服务器的问题**，谁 clone 谁踩。现已把 `config/` 收进 git。

## 这一轮不做的

实景三维整片接入（124 格 / 48701 文件 / 9.9 GB → 3D Tiles）。它是**独立的一轮**，
本机链路已经跑通，产物是静态文件，**由 uvicorn 的 `StaticFiles` 发**（现在没有 nginx）。

> ★ 那里有一条**要先量再定**的风险：`gym3d-api` 是 **single worker 的 uvicorn**，
> 一次整片校区浏览会拉起成百上千个小 `.glb` 请求。先量 P50/P95 与失败率；
> 撑不住才谈「为静态大文件单开一条 nginx `location /tiles/`」——
> 那是**另一件事**，要单独确认，**不许顺手加**。
