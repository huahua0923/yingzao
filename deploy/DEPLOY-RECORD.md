# 校园数字孪生平台 · 部署记录（2026-10-01）

> 这份是**这一趟实际做了什么、凭什么说它成了**的记录，不是计划。
> 计划里被实测推翻的地方，下面按「实测」写，不按计划写。

## 一、形态（已定死）

```
浏览器（校内网）
  → http://202.115.132.14:8141/portal/     ← 直连，不套 nginx、不加域名、不上 TLS
      → uvicorn @ 0.0.0.0:8141（systemd 常驻，single worker）
          → PostgreSQL lihua_twin @ localhost:5432（角色 gym3d_app）
```

用户 2026-10-01 定：「不要域名，用 8141」。**没有 nginx**（这台机上 nginx 本来也没在跑）。
★ 直连比反代**更安全一档**，不是妥协：反代到 `127.0.0.1` 会让 `client_is_loopback()`
对**任何**能到 nginx 的人都回「是回环」；直连时 TCP 对端就是真实客户端地址
（实测日志里看到的是 `172.26.115.238`，NAT 后的真地址）。

## 二、盘上布局

| 路径 | 是什么 |
|---|---|
| `/opt/gym3d/` | git clone，属主 `gym3d:gym3d` |
| `/opt/gym3d/.env` | 600，属主 `gym3d`，**不在 git 里** |
| `/opt/gym3d/data/buildings/` | 92 栋 profile/spec/rooms + 460 个 floors/floor*.json |
| `/opt/gym3d/campus-terrain/` | 10 个 campus 产物（`.env` 的 `GYM3D_CAMPUS_DIR` 指这里） |
| `/etc/systemd/system/gym3d-api.service` | 已 enable |
| `/root/gym3d_db_password.txt` | 600，库口令（**只在服务器上**） |
| `/root/gym3d_builder_password.txt` | 600，搭建方账号首登口令 |

## 三、三道闸（`.env` 里都是显式写的，不靠默认值）

| 键 | 值 | 它守什么 |
|---|---|---|
| `GYM3D_COMPUTE` | `0` | 执行面。`deps.py` 里 `if not cfg.compute` 排在回环判断**之前** ⇒ 与对端地址无关地整条关死。**不误伤**门户页写入（`require_cap` 不读这个键）。 |
| `GYM3D_LOOPBACK_BREAKGLASS` | `0` | authz 那层。默认是 **True**，命中直接给全校区全能力的 `builder`。 |
| `GYM3D_SESSION_COOKIE_SECURE` | `0` | 明文 HTTP 下 cookie 要能回传。置 1 的症状是「登录页能开、点了没反应」，而服务端一切正常。**上了 HTTPS 再改回 1。** |

`GYM3D_HOST=0.0.0.0` / `GYM3D_PORT=8141` / `GYM3D_ENV=prod` / `LIHUA_DB_REQUIRED=1`。

## 四、与计划不符的几处（实测说了算）

1. **不改 `pg_hba.conf`。** 计划里要插一行 `local all postgres trust` 开临时窗口 ——
   实测**不需要**：兄弟应用的 `.env` 里就有能连上的超管凭据
   （`/opt/cdut70-v2/.env`、`/opt/cdut-meeting/.env` 的 `DATABASE_URL`，实测 `rolsuper=true`）。
   零改动就能建库灌库 ⇒ 那个「改共享配置、用完还原」的窗口整个取消。

2. **`pg_dump` 不能带 `--schema=public`。** 带上它 pg_dump 改按「导一个 schema」的口径吐，
   会把 initdb 早建好的 `public` 也写成要创建的对象（`CREATE SCHEMA public;` +
   `COMMENT ON SCHEMA public …`），而这两条在目标库必错（已存在 / 不是属主），
   且**排在所有建表之前** ⇒ 一行数据都进不去。去掉旗标，两条根本不会出现。

3. **灌库用应用角色 `gym3d_app`，不是 `postgres`。** dump 是 `--no-owner` 的，
   谁灌谁拥有 ⇒ 用应用角色灌，它就拥有每一张表，**不需要**灌完再做一遍 `GRANT` 扫描
   （那种扫描很容易漏，而漏了的症状要等某个路由第一次被调用才出现）。

4. **账号是可写的，不是只读。** 一开始想建 `gym3d_ro` —— 那是错的：登录本身就要
   `INSERT INTO sessions` / `auth_log`，锚定要写 `building_anchors`，运行期还有
   `CREATE TABLE IF NOT EXISTS`。只读账号会让**登录本身**失败。

5. **systemd unit 里删掉了 `IPAddressAllow=localhost` + `IPAddressDeny=any`。**
   那两行是按「nginx 反代」写的。形态改成直连后，它们会把所有非回环的包在内核里挡掉：
   systemd 报 `active`、本机 curl 健康检查也过、**外面一台都连不上** —— 一个「看起来全绿」
   的半死状态。要改回反代时，把这两行加回来才是对的。

6. **`.env.example` 里那两个键其实早就有**（`GYM3D_LOOPBACK_BREAKGLASS`、`GYM3D_SESSION_COOKIE_SECURE`）。
   计划里说「模板里一个都没有」，已核为**不成立**。

7. **numpy 锁 1.26.4。** 这台机的 vCPU 是 `QEMU Virtual CPU version 2.5+`，只有 SSE2 级别，
   而 numpy 2.x 要求 x86-64-v2 ⇒ `RuntimeError: NumPy was built with baseline
   optimizations: (X86_V2) but your machine doesn't support`。**只有 numpy 受影响**，
   其余依赖照常。

## 五、验收：量出来的，不是信出来的

### 5.1 数据库（12 张表逐张对）
装入时 / 现在，**每一处差异都有解释**：

| 表 | 装入 | 现在 | 差 | 为什么 |
|---|---|---|---|---|
| rooms | 8803 | 8803 | 0 | 数据本体没动 |
| room_registry | 8789 | 8789 | 0 | 〃 |
| room_source | 8772 | 8772 | 0 | 〃 |
| floor_areas | 304 | 304 | 0 | 〃 |
| room_history | 19 | 19 | 0 | 〃 |
| room_manual | 17 | 17 | 0 | 〃 |
| roles | 4 | 4 | 0 | 〃 |
| building_anchors | 0 | 0 | 0 | 探针写了 1 条、跑完删掉 |
| users | 3 | 1 | −2 | 3 个演示号删掉 + 加 `builder` |
| grants | 3 | 1 | −2 | 演示号授权级联删 + builder 的 `*` |
| sessions | 192 | 3 | −189 | 演示号会话级联删；剩下的是探针登的 |
| auth_log | 271 | 294 | +23 | 探针的登录尝试（含故意的错口令那条） |

演示号计数 `admin`/`c006admin`/`viewer` = **0**。账号表现状：`builder` / `must_change=t` / `is_active=t`，授权 `builder|*`。

### 5.2 HTTP 面（从**外部**打，不是本机回环）

| 请求 | 期望 | 实测 |
|---|---|---|
| `GET /api/health` | 200 | **200**（`compute:false`） |
| `GET /api/buildings`（无 cookie） | **401** | **401** ★ 这条是唯一能分辨「配置写对了」和「配置生效了」的一条 |
| `GET /api/portal/anchors`（无 cookie） | 401 | 401 |
| `POST /api/portal/anchors`（无 cookie） | 401 | 401 |
| `POST /api/auth/login`（空体） | 422 | 422 |
| `/` `/portal/` `/site/` | 200 | 200 |
| `/openapi.json` `/docs` | 404 | 404（prod 关掉了，对） |

### 5.3 端到端（服务器本机，真账号，口令不打印）
匿名 401 → 登录 200（拿到 `lihua_twin_sid`）→ `/api/buildings` 带 cookie **200 / 92 栋**
→ `/api/portal/anchors` 200 → 建一条探针锚点 200 → 读回来 1 条 → **删掉 200**
→ **前后计数 0→0 且那条确实不在了** → 登出 200 → 再打 `/api/buildings` **401**（会话真吊销了）。

### 5.4 campus 八条路由（带身份，逐条量字节）
`model.glb` 8071248 / `ortho.jpg` 1021719 / `ortho.json` 2534 / `outlines.json` 115071 /
`lod1.json` 217469 / `buildings.glb` 178892 / `buildings.json` 130427 / `viewdata` 4496 ——
**全部 200，且前三个字节数与盘上实物逐字节相同**。

### 5.5 浏览器（`/portal/`）
- 未登录时：21 个请求里**数据请求 0 个**，只有一条 `/api/auth/session`；控制台 **0 条消息**。
  （`app.js` docstring 声称「未登录一个数据请求都不发」—— 现在是量出来的。）
- 用**错口令**提交：`POST /api/auth/login` → **401** → 页面上出现「**用户名或口令不对。**」
  ⇒ 整条登录接线（`app.js → session.js → api.js → 401 → 渲染文案`）在浏览器里真跑通了，
  而且**全程没碰过真口令**。

### 5.6 服务
`is-enabled=enabled` · `is-active=active` · 监听 `0.0.0.0:8141` · 启动日志零警告 ·
`firewall-cmd` 已放行 8141/tcp · 开机软链在 `multi-user.target.wants/`。

## 六、这一轮**没做**的（明说）

- **单栋三维模型与楼层图**：`*.glb` 793 MB + `*.png` 232 MB 没搬 ⇒ 服务器上「点开一栋看模型和图纸」不可用，其余全可用。
- **源 DXF（318 MB）**：`GYM3D_DXF_DIR` 留空；`source_dxf` 路由本来就设计成明确 404。
- **`/api/path`**：`backend/nav/*.mask.bin` 盘上一份都没有 ⇒ 那条路由在服务器上必然坏。
- **实景三维整片接入**（30 GB → 重切片 → 3D Tiles）：独立的一轮。
- **`rooms` 只覆盖 51 栋而盘上 92 栋** —— 问题原样带到了服务器，没解决。

## 七、一件我自己造成的安全事故（已处置）

`_db_setup.py` 第 [9] 步里，自检写成了 `("LIHUA_DB_PASSWORD=" + dbpw, ...)` 而打印用的是
`needle` **整串** ⇒ 库口令原样进了 `/root/_db_setup.log` **和对话记录**。用户的原话是
「新口令不许打印进对话」。

处置：**轮换**（不是删日志 —— 口令落过任何一处文字记录，删日志就不算修好了）。
`_rotate_db_pw.py` 三步：①先量旧口令扩散到哪几个文件 ②`ALTER ROLE` 换掉，并且
**新口令能进 + 旧口令进不去两侧都测** ③删掉扩散点、复扫归零。实测旧口令只在 3 个文件里
（`.env`、口令文件、运行日志），换完后**一个都不剩**。

★ 规矩（已写进 `_db_setup.py` 的注释）：**凡是「读完核对」这一类的打印，被判的那个值
必须先经过一次「只比不印」** —— 印长度和「一致/不一致」，不印值。
★ 教训：对话记录里那串收不回来；但轮换之后它只是一串无用字符。

## 八、改这台机器的注意事项

- **改完 `/opt/gym3d/.env` 必须 `systemctl restart gym3d-api`**（`EnvironmentFile` 只在启动时读一次）。
- **端口已开在防火墙里**：新加端口要 `firewall-cmd --permanent --add-port=N/tcp && firewall-cmd --reload`，两步都要。
- **不要动 `pg_hba.conf`**：现在这条路不需要它。
- **登录限流的计数在进程内存里** ⇒ 重启即清零。单 worker 够用；横向扩之前必须挪到 Redis/PG。
- **读服务器上的 git 要用 `sudo -u gym3d git -C /opt/gym3d …`**。用 root 读会
  `fatal: detected dubious ownership`（文件属主是 `gym3d`）而**直接退出** ——
  这时 `| wc -l` 会给你一串 **0**，看起来像「这些文件没被跟踪」。
  ★ 我自己就这样差点报出一个不存在的发现（本仓铁律 016：命令报错时的空输出不是「没有数据」）。

## 九、git 卫生（一处已堵，一处待你定）

`/opt/gym3d/campus-terrain/` 那 9.7 MB 数据产物，**不在 `.gitignore` 里**
（本机那份藏在 `_scratch/_campus3d/` 下，所以本机从没暴露过这个问题；
`data/*` 倒是第 17 行就挡住了）。服务器上它在仓根，`git add -A` 会把 9.7 MB 二进制收进去。

已处置：写进 `/opt/gym3d/.git/info/exclude`（**每个 clone 自己的**忽略表，不进仓、不改历史），
并用 `git check-ignore -v campus-terrain/campus_terrain.glb` 做了**正向对照**，
确认规则真的在生效而不是写了个空规则。

**仍建议**（没做，要你点头才动仓）：往仓的 `.gitignore` 里加一行 `campus-terrain/` ——
否则下次重新 clone 到别的机器，同一个口子会再开一次。这是**改仓**，不是改服务器，所以我没动。

---

## 十、2026-10-02 追加：现状（本节全部**本轮实测**，不是转述）

> 上面 §一~§九 是 **2026-10-01 那一趟**的测量，按原样留着（记录就是记录，
> 抄改会变成假的——本仓铁律 050/052）。下面这一节是**今天重新量的**。

### 10.1 形态没变，仍是直连
```
curl http://202.115.132.14:8141/portal/   -> 200   （从外网打，非回环）
curl http://202.115.132.14:8141/api/health-> 200
```
服务器实测：`systemctl is-active nginx` = **inactive**；`gym3d-api` = **active**。
`.env` 读到 `GYM3D_HOST=0.0.0.0` / `GYM3D_PORT=8141` / `COMPUTE=0` /
`LOOPBACK_BREAKGLASS=0` / `SESSION_COOKIE_SECURE=0`。

★ 顺带更正 `deploy/README.md` 里的一处**事实错误**：它把地址写成 `202.115.133.14`。
那是**另一台机器**——实测 `curl http://202.115.133.14:8141/portal/` = `000`（连不上）。
早先我把两个地址当成一台，依据是「主机密钥逐位相同」；**那个依据推不出这个结论**
（克隆镜像会带着同一个主机密钥）。分辨它们的是**钥匙接受与否**。

### 10.2 账号与角色（用户 2026-10-02 定：只留两个）

| | 数 | 内容 |
|---|---|---|
| `roles` | **2** | `builder`=搭建方、`line_admin`=管线管理员 |
| `users` | **1** | `builder`（搭建方）/ `must_change=t` / `is_active=t` |
| `grants` | 1 | 搭建方那条 `*` |

**已删**：普通人、普通管理员（用户明令）；三个演示号 `admin`/`c006admin`/`viewer` 计数 **0**。
口令从未进过对话，也从未进过任何打印（memory `never-print-a-secret-in-a-check`）。

### 10.3 库里的实数（92 栋已灌）

| 表 | 行数 |
|---|---|
| `rooms` | **11,019** |
| `room_source` | 8,772 |
| `floor_areas` | 465 |
| `room_history` | 19 |
| `room_manual` | 17 |
| `building_anchors` | 0 |

★ **没有 `buildings` 表**——楼栋名册是 `config/buildings.json` 这个**登记文件**，
不走 PG。查「有几栋」要去读那个文件，别在库里查。

★ `rooms` = **11,019** 这个数有一个来历值得记：手记的 88 栋 / 11128 间是**旧数**。
按文件数出来的原始合计 11,233，减 `c006pub` 的 214 恰好 11,019
（`c006pub` 是 c006 的公共流程复跑副本，它 `rooms.json` 里每条的 `building` 都写着 c006，
收进来会与 c006 撞 214 个 id，装载器按判据跳过）。
**库里的数**与**文件数出来的数**两条路各自得到 11,019 —— 这才是判据。
（`config/buildings.json` 的台账补记里已按此更正。）

### 10.4 `/api/components` 的 503（重跑确认，不是引用）

这一趟重新上传探针（上传后 sha `b8c83d1429e04bdc` 与本地逐位相同）在服务器上跑：

| | 请求 | 结果 |
|---|---|---|
| 被测 | `GET /api/components`（带 cookie） | **503** `upstream_error`，说明点名缺 `ezdxf` |
| 阳性对照 | `GET /api/buildings`（带 cookie） | **200** |
| 阴性对照 | `GET /api/components`（无 cookie） | **401** |

清理（铁律 029 两个判据都要过）：`users/sessions/grants` 计数 `(1,48,1) -> (1,48,1)` ✓，
临时账号残留 **0** ✓。

### 10.5 一处**已知状态**，别当成故障

服务器 `/opt/gym3d` 的 git HEAD 停在 **`a5e68bf`**，比本机 `master` **少一个提交**
（`bdf8750` 门户「一个世界」重做）。原因是那条改动**不是走 `git pull` 上的**，
是走增量 tgz 直接解进工作区的 ⇒ **工作区是新的、git 历史是旧的**，
所以 `git status` 在服务器上会显示一堆 ` M`。

⇒ 在服务器上**别跑 `git checkout .`** —— 那会把已上线的门户页回退成旧版。
要判断「服务器上跑的是哪一版」，**看文件内容，不看 git 历史**。
