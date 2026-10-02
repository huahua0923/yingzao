#!/bin/bash
# 只读侦察：把「动手之前必须先知道」的东西一次量出来。**不写任何东西。**
# 用法：bash /root/_recon.sh
export LC_ALL=C
echo "=== [1] 机器与系统 ==="
hostname; cat /etc/os-release | grep -E '^(PRETTY_NAME|VERSION_ID)='
echo "  CPU: $(nproc) 核  内存: $(free -m | awk '/^Mem:/{print $2" MB"}')"
echo "  磁盘 /: $(df -h / | awk 'NR==2{print $4" 可用 / "$2" 共"}')"
echo "  磁盘 /opt: $(df -h /opt 2>/dev/null | awk 'NR==2{print $4" 可用 / "$2" 共"}')"

echo
echo "=== [2] /opt 现有的东西（别踩到别人的）==="
ls -la /opt/ 2>&1 | head -20
echo "  --- /opt/gym3d ---"
ls -la /opt/gym3d/ 2>&1 | head -25

echo
echo "=== [3] Python ==="
/opt/python3.12/bin/python3.12 -V 2>&1
/opt/gym3d/.venv/bin/python -V 2>&1

echo
echo "=== [4] PostgreSQL ==="
psql --version 2>&1
psql -V 2>&1
systemctl is-active postgresql 2>&1
echo "  --- 服务名 ---"
systemctl list-units --type=service --all 2>/dev/null | grep -i postgres
echo "  --- 版本目录 ---"
ls -d /usr/pgsql-* /var/lib/pgsql/*/ 2>/dev/null | head
echo "  --- 监听 ---"
ss -lntp 2>/dev/null | grep -E '5432|8140|8141|:80|:443'
echo "  --- 现有数据库 ---"
su - postgres -c "psql -At -c 'select datname from pg_database order by 1'" 2>&1 | head -20

echo
echo "=== [5] 现有角色 ==="
su - postgres -c "psql -At -c \"select rolname from pg_roles where rolcanlogin order by 1\"" 2>&1 | head -20

echo
echo "=== [6] pg_hba.conf 在哪、长什么样 ==="
HBA=$(su - postgres -c "psql -At -c 'show hba_file'" 2>/dev/null)
echo "  hba_file = [$HBA]"
if [ -n "$HBA" ] && [ -f "$HBA" ]; then
    echo "  sha256 = $(sha256sum "$HBA" | cut -d' ' -f1)"
    echo "  --- 非注释行（带行号）---"
    grep -n -v '^[[:space:]]*#' "$HBA" | grep -v '^[[:space:]]*$'
fi

echo
echo "=== [7] lihua_twin 存在吗 ==="
su - postgres -c "psql -At -d lihua_twin -c \"select count(*) from information_schema.tables where table_schema='public'\"" 2>&1

echo
echo "=== [8] 服务用户/端口/防火墙 ==="
id gym3d 2>&1
echo "  --- firewalld ---"
systemctl is-active firewalld 2>&1
firewall-cmd --list-ports 2>&1 | head -3
echo "  --- nginx ---"
systemctl is-active nginx 2>&1
nginx -v 2>&1
ls /etc/nginx/conf.d/ 2>&1 | head -20

echo
echo "=== [9] 已传上来的包（如果有）==="
ls -l /root/*.tar.gz /root/*.sql.gz /tmp/*.tar.gz /tmp/*.sql.gz 2>&1 | head

echo
echo "=== ✓ 侦察结束（本次一个字节都没写）==="
