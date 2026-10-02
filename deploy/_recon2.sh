#!/bin/bash
# 侦察第二轮：把「怎么进 PG」和「这台机上还跑着什么」问清楚。**一个字节都不写。**
# ★ 本脚本**不打印任何口令**：只报「这个键在哪、有没有值」，值一律不 echo。
export LC_ALL=C

echo "=== [A] 全端口 ==="
ss -lntp 2>/dev/null | awk 'NR==1 || /LISTEN/'

echo
echo "=== [B] 谁在跑（pm2 / docker / 各服务）==="
for s in nginx pm2 docker cdut-meeting coze-agents exhibition-nav; do
    printf '  %-16s %s\n' "$s" "$(systemctl is-active $s 2>&1)"
done
command -v pm2 docker podman 2>&1
echo "  --- 202 个端口背后是谁 ---"
for p in 3005 5005 6001 6006 8100; do
    pid=$(ss -lntp 2>/dev/null | awk -v P=":$p" '$4 ~ P {match($0,/pid=[0-9]+/); if(RSTART){print substr($0,RSTART+4,RLENGTH-4); exit}}')
    if [ -n "$pid" ]; then
        printf '    %-6s pid=%-7s %s\n' "$p" "$pid" "$(tr "\0" " " < /proc/$pid/cmdline 2>/dev/null | cut -c1-90)"
    fi
done

echo
echo "=== [C] pg_hba.conf（root 直接读文件，不连库）==="
HBA=/var/lib/pgsql/data/pg_hba.conf
ls -l "$HBA" 2>&1
echo "  sha256 = $(sha256sum "$HBA" 2>/dev/null | cut -d' ' -f1)"
echo "  --- 全部非注释行（带行号）---"
grep -n -v '^[[:space:]]*#' "$HBA" 2>/dev/null | grep -v '^[[:space:]]*[0-9]*:[[:space:]]*$'

echo
echo "=== [D] 那三个演示库到底在不在（不走 psql，直接数 base 目录）==="
ls -la /var/lib/pgsql/data/base/ 2>&1 | head -20

echo
echo "=== [E] 兄弟应用的库配置在哪（只报键名，不报值）==="
for d in /opt/cdut-meeting /opt/cdut70-v2 /opt/coze-agents /opt/exhibition-nav; do
    echo "  --- $d ---"
    find "$d" -maxdepth 2 -name '.env*' -o -maxdepth 2 -name '*.env' 2>/dev/null | head -5
done
echo
echo "  --- 这些文件里有哪些 [库/口令] 相关的键（值不打印）---"
find /opt/cdut-meeting /opt/cdut70-v2 /opt/coze-agents /opt/exhibition-nav \
     -maxdepth 3 \( -name '.env' -o -name '.env.*' -o -name '*.env' \) 2>/dev/null | while read -r f; do
    k=$(grep -oE '^[A-Z_]*(PASSWORD|PASSWD|DSN|DATABASE_URL|DB_URL)[A-Z_]*' "$f" 2>/dev/null | sort -u | tr '\n' ' ')
    n=$(grep -cE '^[A-Z_]*(PASSWORD|PASSWD|DSN|DATABASE_URL|DB_URL)[A-Z_]*=' "$f" 2>/dev/null)
    filled=$(grep -E '^[A-Z_]*(PASSWORD|PASSWD|DSN|DATABASE_URL|DB_URL)[A-Z_]*=.+' "$f" 2>/dev/null | wc -l)
    printf '    %-62s 键:[%s] 有值:%s\n' "$f" "$k" "$filled"
done

echo
echo "=== [F] postgres 家目录里有没有 .pgpass ==="
ls -la /var/lib/pgsql/.pgpass /root/.pgpass 2>&1

echo
echo "=== [G] 现有站点配置（nginx 虽然没跑，配置可能留着）==="
ls /etc/nginx/conf.d/ 2>/dev/null
ls /etc/nginx/nginx.conf 2>/dev/null
for f in /etc/nginx/conf.d/*.conf; do [ -f "$f" ] && echo "  $(basename $f): $(grep -c 'server_name' $f 2>/dev/null) 个 server_name"; done

echo
echo "=== ✓ 侦察二结束（一个字节都没写）==="
