# 部署拓扑与安全边界

## 1 拓扑

```text
校园网 / 公网访客
        │ HTTPS
        ▼
    Nginx 443
    ├─ 公共静态：/demo /packs /process
    ├─ 健康检查：/live /health
    └─ 管理端：/admin /pipeline /api /files  (Basic Auth + 校园网/VPN)
        │ 127.0.0.1:8150
        ▼
    Python cdut3d service
        │ 只读
        ▼
    发布目录 /srv/cdut3d/current

本地生产机
  建模/质检/切片 → release-manifest.json → SFTP/内网对象存储 → 发布目录
```

## 2 端口

| 端口 | 暴露范围 | 用途 |
|---:|---|---|
| 443 | 校园网/公网 | HTTPS 展示与受保护管理入口 |
| 80 | 校园网 | 301 到 443 |
| 8150 | 仅 `127.0.0.1` | Python 内部服务 |

禁止开放：AutoCAD/Blender/FreeCAD、任务队列调试口、Python 直连口、任何数据库端口。

## 3 认证与授权

- 公共展示页：匿名可读。
- 工作台、流程台、写接口、文件下载：Nginx 基础认证。
- 如接入统一身份认证，后续以学校 SSO 替代基础认证，保留 Nginx ACL。
- 不把管理员口令写进 `.bat`、README、发布清单或 Git。

## 4 日志与审计

- Nginx：访问日志、错误日志、认证失败记录。
- Python：错误日志；后续增加写操作审计。
- 一级项目要求审计记录可留 6 个月、可按人/时间查询；当前为待办。

## 5 备份与回滚

- 发布目录按版本保存，不原地覆盖。
- `current` 指向当前版本。
- 回滚：`ln -sfn releases/<上一版> current && systemctl restart cdut3d`。
- 数据归档：`packs`、实景层、发布清单、判据输出按季度冷备。

