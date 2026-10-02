#!/usr/bin/env bash
# 本机跑：把 lihua_twin 导成**服务器 PG13 能读**的纯 SQL。
#
# ★ 为什么要动一刀：本机是 PG 17.4，服务器是 PG 13.23。
#   PG17 的 pg_dump **不做版本降级**，它按 17 的口径吐 SQL。实测（不是推的）：
#   全份 35315925 字节里，PG13 唯一不认的只有第 11 行
#       SET transaction_timeout = 0;
#   （`SET default_table_access_method = heap;` 是 PG12 就有的，13 认；
#     本机 17.4 也**没有**吐 17.6+ 才有的 `\restrict`。）
#   ⇒ 剥掉那一行。剥完必须证明「差异恰好等于我声明剥掉的那一行」（铁律 071）。
#
# 用法：bash deploy/_make_dump.sh
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
OUTDIR="$ROOT/_scratch/_deploy"
mkdir -p "$OUTDIR"

# 口令从仓里的 .env 读（铁律 005：密钥只进 .env，不写进脚本、不进对话）
[ -f "$ROOT/.env" ] || { echo "✗ 找不到 $ROOT/.env"; exit 1; }
PGPASSWORD="$(grep -m1 '^LIHUA_DB_PASSWORD=' "$ROOT/.env" | cut -d= -f2-)"
[ -n "$PGPASSWORD" ] || { echo "✗ .env 里 LIHUA_DB_PASSWORD 是空的"; exit 1; }
export PGPASSWORD

PGDUMP="/c/Program Files/PostgreSQL/17/bin/pg_dump.exe"
DB="${LIHUA_DB_NAME:-lihua_twin}"
RAW="$OUTDIR/lihua_twin.raw.sql"
LF="$OUTDIR/lihua_twin.lf.sql"
FIX="$OUTDIR/lihua_twin.sql"

echo "── ① 导出（PG17，纯 SQL）──"
"$PGDUMP" -h 127.0.0.1 -U postgres --format=plain --no-owner --no-privileges \
          --schema=public "$DB" > "$RAW"
echo "  $(wc -l < "$RAW") 行，$(stat -c %s "$RAW") 字节"

echo "── ② 把 Windows 文本模式写的 CRLF 转回 LF ──"
# ★ 这一步不是洁癖：`pg_dump.exe` 在 Windows 上按文本模式写盘，每行尾多一个 0x0D。
#   ● 纯 SQL 的语句之间多一个 CR 是能灌进去的，所以它**不会自己报错**；
#   ● 但 `COPY ... FROM stdin;` 的数据行会带着这个 CR 一起进字段 —— **每行最后一列多一个 \r**，
#     而这种坏法是静默的（数字能转、文本会长出一个看不见的尾巴）。
#   ● 更阴的是：`grep -v` 在本机（MSYS）**把全文件的 CRLF 一起翻成了 LF**，
#     于是「删掉 1 行」的产物实际是「19149 行全部逐字节变了」——
#     而 `wc -l` 只差 1，看起来完全正常（铁律 071/079/175 同族，2026-10-01 实测踩到）。
#   ⇒ 先把行尾归一，再动那一行，两件事分开做、分开证明。
sed 's/\r$//' "$RAW" > "$LF"
N_CR=$(grep -c $'\r' "$LF" || true)
[ "$N_CR" -eq 0 ] || { echo "  ✗ 还有 $N_CR 行带 CR"; exit 2; }
echo "  ✓ 行尾全是 LF（$LF）"
if grep -q '^COPY ' "$LF"; then
    echo "  （本份用 COPY 灌数据 —— 所以上面这一步是必需的，不是可选）"
fi

echo "── ③ 剥掉 PG13 不认的那一行 ──"
BAD='^SET transaction_timeout = 0;$'
N_BAD=$(grep -c "$BAD" "$LF" || true)
echo "  归一后这一行出现 $N_BAD 次"
[ "$N_BAD" -ge 1 ] || { echo "  ✗ 没找到 —— 要么 pg_dump 变了，要么我的假设错了，人工看一遍再走"; exit 2; }
awk '! /^SET transaction_timeout = 0;$/ { print }' "$LF" > "$FIX"

echo "── ④ 断言：与【归一后】相比，差异恰好是那一行 ──"
L_LF=$(wc -l < "$LF"); L_FIX=$(wc -l < "$FIX")
[ $((L_LF - L_FIX)) -eq "$N_BAD" ] || { echo "  ✗ 少掉 $((L_LF - L_FIX)) 行 ≠ $N_BAD，改动不止我说的那一处"; exit 3; }
D=$(diff "$LF" "$FIX" | grep -E '^[<>]' | grep -v '^< SET transaction_timeout = 0;$' || true)
if [ -n "$D" ]; then
  echo "  ✗ diff 里出现了我没声明的行："; printf '%s\n' "$D" | head -10; exit 4
fi
echo "  ✓ 与归一后的文本比：仅 $N_BAD 行被删，且删的就是 'SET transaction_timeout = 0;'"

echo "── ④ 两边各有几张表、各多少行（灌完要拿它对账）──"
psql -h 127.0.0.1 -U postgres -d "$DB" -At -c \
  "select table_name from information_schema.tables where table_schema='public' order by 1" > "$OUTDIR/tables.txt"
: > "$OUTDIR/rowcounts.txt"
while read -r t; do
  [ -n "$t" ] || continue
  n=$(psql -h 127.0.0.1 -U postgres -d "$DB" -At -c "select count(*) from public.\"$t\"")
  printf '%s\t%s\n' "$t" "$n" >> "$OUTDIR/rowcounts.txt"
done < "$OUTDIR/tables.txt"
cat "$OUTDIR/rowcounts.txt"

echo "── ⑤ 压缩 ──"
gzip -9 -c "$FIX" > "$OUTDIR/lihua_twin.sql.gz"
ls -lh "$OUTDIR/lihua_twin.sql.gz" | awk '{print "  "$5"\t"$9}'
echo "  sha256 $(sha256sum "$OUTDIR/lihua_twin.sql.gz" | cut -d' ' -f1)"
