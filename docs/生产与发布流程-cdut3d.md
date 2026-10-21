# 本地生产与服务器发布流程

## 1 总原则

**本地算，服务器只展示。**

服务器不装 AutoCAD、Blender、FreeCAD、RealityCapture、COLMAP；不接收原始航拍、不跑 SfM/MVS、不切片。服务器只装载已验收的模型包与实景层。

## 2 本地生产链

```text
1. CAD 源图
2. 识别
3. 重画
4. 审图
5. 建件
6. FreeCAD / SU 出件
7. GLB / 模型包
8. 判据与质检
9. 发布包
```

每一段都必须有：

- 输入清单与版本。
- 输出文件、字节数、SHA-256。
- 判据结果与最近实跑时刻。
- 失败时的回执文件，不只依赖外部程序退出码。

## 3 建模冻结条件

一个楼栋进入发布包前至少满足：

1. 包 manifest 合法，`campus_id`、`building_id`、`lod`、模型和质检齐全。
2. 轮廓、形体、叠加、构件齐全等硬判据通过。
3. 正对照仍能变红，不是恒绿尺子。
4. 模型包与图层、房间台账、参数版本一致。
5. 没有未解释的“没量到”。

## 4 实景冻结条件

1. 有 `tileset.json`、根变换、坐标基准和瓦片清单。
2. LOD 层级和 coverage 可枚举。
3. 与白模控制点配准，偏移量有记录。
4. 瓦片包不含原片、POS、控制点。
5. 通过浏览器加载、内存和首屏时间测试。

## 5 生成发布包

```powershell
cd D:\项目\cdut3d
python -X utf8 deploy\scripts\release.py build D:\tmp\cdut3d-release-20261020
python -X utf8 deploy\scripts\release.py verify D:\tmp\cdut3d-release-20261020
```

发布清单记录：

- Git commit
- 每个文件相对路径
- 字节数
- SHA-256
- 生成时刻

## 6 上传

建议：

- 校内 SFTP 或内网对象存储。
- 大文件断点续传。
- 上传后重新 `verify`。
- 不使用含口令的脚本。

服务器目录：

```text
/srv/cdut3d/releases/<version>/
/srv/cdut3d/current -> releases/<version>
```

## 7 切换与回滚

```bash
sudo ln -sfn /srv/cdut3d/releases/20261020-001 /srv/cdut3d/current
sudo systemctl restart cdut3d
python3 /srv/cdut3d/current/deploy/scripts/healthcheck.py --base https://<域名>
```

失败回滚：

```bash
sudo ln -sfn /srv/cdut3d/releases/<上一版> /srv/cdut3d/current
sudo systemctl restart cdut3d
```

## 8 发布后检查

- `/live` 200。
- `/health` 200，四个检查项为真。
- 首页模型可加载。
- 大 GLB 无内存暴涨。
- 管理端未认证返回 401。
- Nginx 访问日志有记录。

## 9 2026-10-20 实测

- 发布构建：`release.py build` 成功。
- 文件数：2,863。
- 总字节：1,522,026,535 B。
- 清单校验：`release.py verify` 返回 0。
- Git commit：`9ae4f291c74cad9dd80528adee64f2a06f428734`。
- 临时发布目录验证后已删除，避免把测试副本长期留在本机。

## 10 不进入发布包

- `.git`、`_scratch`、`_archive`、`__pycache__`。
- 原始航拍、POS、控制点。
- 含口令的配置。
- 测试上传件与临时任务。
- 未通过判据的模型包。

