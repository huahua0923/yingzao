#!/bin/bash
# 装 systemd unit 并起服务 + 开防火墙。
# ★ 判据分三层（铁律 020：「进程起来了」≠「那个进程在干活」）：
#     ① systemctl is-active == active
#     ② 端口真的在 LISTEN（且对端是 0.0.0.0，不是 127.0.0.1）
#     ③ curl 打一条真路由拿到真响应体 —— 不是端口通就算数
set -u
UNIT=/root/gym3d-api.service
DEST=/etc/systemd/system/gym3d-api.service

echo "=== [0] 先把 /opt/gym3d 的属主摆正 ==="
echo "  改前：$(find /opt/gym3d -maxdepth 2 -not -user gym3d 2>/dev/null | wc -l) 个顶层项不是 gym3d"
chown -R gym3d:gym3d /opt/gym3d
echo "  改后：$(find /opt/gym3d -not -user gym3d 2>/dev/null | wc -l) 个路径不是 gym3d（应为 0）"
find /opt/gym3d -maxdepth 1 -printf '    %-24f %u:%g\n' 2>/dev/null | sort

echo
echo "=== [1] 装 unit ==="
install -m 0644 -o root -g root "$UNIT" "$DEST"
echo "  sha256 源 = $(sha256sum "$UNIT" | cut -d' ' -f1)"
echo "  sha256 落地 = $(sha256sum "$DEST" | cut -d' ' -f1)"
systemctl daemon-reload
echo "  daemon-reload rc=$?"

echo
echo "=== [2] 起服务 ==="
systemctl enable --now gym3d-api 2>&1
sleep 4
echo "  is-enabled = $(systemctl is-enabled gym3d-api 2>&1)"
echo "  is-active  = $(systemctl is-active gym3d-api 2>&1)"

echo
echo "=== [3] 端口层（要 0.0.0.0:8141，不是 127.0.0.1:8141）==="
ss -lntp 2>/dev/null | grep 8141 || echo "  **8141 没有在 LISTEN**"

echo
echo "=== [4] 本机打真路由（不是端口通就算数）==="
for u in /api/health /api/buildings; do
    printf '  %-16s → HTTP %s\n' "$u" "$(curl -s -o /dev/null -w '%{http_code}' --max-time 8 "http://127.0.0.1:8141$u")"
done
echo "  /api/health 的响应体："
curl -s --max-time 8 http://127.0.0.1:8141/api/health | head -c 400; echo

echo
echo "=== [5] 若没起来，把 journal 摊开（别只报「失败了」）==="
if [ "$(systemctl is-active gym3d-api)" != "active" ]; then
    journalctl -u gym3d-api -n 60 --no-pager 2>&1 | tail -60
    exit 1
fi

exit 0
