#!/usr/bin/env bash
# 部署探针 —— 在**服务器上**跑，把整段输出原样贴回来。
#
# ★ 仓库里那份 `_portal_verify.py` 的判据在这里**不成立**，别拿它当验收：
#   它量的是「回环 + breakglass 开着」的本机环境 —— 它的期望值恰好是
#   这里要**证伪**的那个状态。两份探针期望相反，不是谁写错了，是被测对象不同。
#
# ★★ 第 2 条判据的**阳性对照**（我 2026-10-01 在本机实测过，不是推的）：
#     同一台机、同一份代码、同一条路由，只翻 GYM3D_LOOPBACK_BREAKGLASS 这一个变量 ——
#         GYM3D_LOOPBACK_BREAKGLASS=1  ⇒ GET /api/buildings 回 **200**
#         GYM3D_LOOPBACK_BREAKGLASS=0  ⇒ GET /api/buildings 回 **401**
#     ⇒ 这条判据有分辨力，它的 401 是真的读出来的，不是「闸永远拒」
#       （铁律 153：「永远拒」的闸能通过全部阴性对照，分辨它只能靠那一支
#        "本该放行"的输入）。
#     ★ 注意：现在本机 `.env` 里也已经是 0 ⇒ **在本机跑这份脚本，第 2 条也会绿**。
#       要复现阳性对照，得另起一个实例： GYM3D_PORT=8149 GYM3D_LOOPBACK_BREAKGLASS=1 \
#         python -u backend/api/run_api.py
#
# 用法：
#   bash deploy/verify_deploy.sh                                   # 只跑回环那几条
#   bash deploy/verify_deploy.sh http://127.0.0.1:8140 http://202.115.133.14:8141
#                                    ↑ 服务器本机地址      ↑ 另一台内网机能打到的地址
set -uo pipefail          # ★ 不 set -e：探针要跑完全部再汇总，不能第一条不过就停

BASE="${1:-http://127.0.0.1:8140}"
EXT="${2:-}"
PASS=0; FAIL=0; SKIP=0

c_ok(){ printf '✓ %s\n' "$*"; }
c_no(){ printf '✗ %s\n' "$*"; }
# ★ 「不适用」必须出声，且必须**计进 SKIP**。把它印成「通过」是在造一个像结论的
#   假数（铁律 062）；而只印一行 ⊘ 却让汇总里的 SKIP 停在 0，是同一个病的另一种形态
#   —— 屏幕上有两条 ⊘，汇总却写「不适用 0」，读的人只会看汇总。
c_sk(){ printf '⊘ %s  ← ★不适用（不是"通过"）\n' "$*"; SKIP=$((SKIP+1)); }

chk(){  # chk <编号> <名字> <期望> <实得>
  if [ "$3" = "$4" ]; then c_ok "$1 $2 → $4"; PASS=$((PASS+1))
  else c_no "$1 $2 → 期望 $3，实得 $4"; FAIL=$((FAIL+1)); fi
}
# curl 失败时 %{http_code} 会打出 000，而「000」与「没连上」是同一件事 —— 明确列出来
code(){ curl -s -o /dev/null -w '%{http_code}' --max-time 10 "$@" 2>/dev/null || echo 000; }

echo "═══════════════════════════════════════════════════════════════"
echo " 被测（回环）： $BASE"
echo " 被测（内网）： ${EXT:-(未给 —— 第 3/4 条会印成"不适用"）}"
echo " 主机：         $(hostname 2>/dev/null)   时间：$(date '+%F %T')"
echo "═══════════════════════════════════════════════════════════════"

# ── 1. 进程真的在服务 ────────────────────────────────────────────────
#   铁律 020：端口通 ≠ pm2/systemd 在服务。这条量的是"它答不答话"。
chk "①" "GET /api/health 回 200（进程在服务）"      200 "$(code "$BASE/api/health")"

# ── 2. ★ 关键的一条：breakglass 真的关了 ────────────────────────────
#   这是**唯一**能分辨「.env 写对了」和「.env 没生效」的一条。
#   只看 .env 文件不算数 —— 文件写了而进程没读，两者屏幕上一模一样。
#   回 200 = 从本机来的请求无条件拿到全校区全能力的 Principal。
chk "②" "GET /api/buildings 不带 cookie 回 401"    401 "$(code "$BASE/api/buildings")"

# ── 3/4. 内网面 ──────────────────────────────────────────────────────
if [ -n "$EXT" ]; then
  # ★ 与「同一条路由从回环打过去是什么结果」成对报 —— 否则分不清
  #   「闸生效」和「路由根本是坏的」（铁律 162：把下一件必须做的事喂进闸里跑一遍）。
  chk "③" "  POST /api/portal/anchors 回 403"      403 "$(code -X POST -H 'Content-Type: application/json' -d '{}' "$EXT/api/portal/anchors")"
  chk "④" "  GET /api/buildings 回 401"            401 "$(code "$EXT/api/buildings")"
  chk "④b" " 对拍：同一条路由回环 GET /api/portal/anchors" 403 "$(code "$BASE/api/portal/anchors")"
else
  c_sk "③ POST /api/portal/anchors（内网面）——没给第二个参数"
  c_sk "④ GET /api/buildings（内网面）——没给第二个参数"
fi

# ── 5. 外壳公开、数据受闸 ────────────────────────────────────────────
chk "⑤" "GET /portal/ 回 200（外壳公开）"           200 "$(code "$BASE/portal/")"

# ── 6. 权限层与写闸的自检 ────────────────────────────────────────────
# ★ 解释器要**先找到再跑**。先前这里是 `... || PY=python3`，于是本机（只有 `python`）
#   两个自检都印 rc=127 + `python3: command not found`，而 rc=127 与「自检不过（rc=1）」
#   在汇总里长得一样 —— 那是「量具没起来」被当成「被测对象不合格」（铁律 168 同族）。
PY="${GYM3D_PY:-}"
if [ -z "$PY" ]; then
  if   [ -x /opt/gym3d/.venv/bin/python ]; then PY=/opt/gym3d/.venv/bin/python
  elif command -v python3 >/dev/null 2>&1;  then PY=python3
  elif command -v python  >/dev/null 2>&1;  then PY=python
  fi
fi
ROOT_DIR="${GYM3D_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
if [ -z "$PY" ]; then
  c_sk "⑥ authz / deps 自检 —— 这台机器上找不到可用的 python"
else
  echo "    解释器：$PY   仓库根：$ROOT_DIR"
  for m in backend.api.authz backend.api.deps; do
    out="$(cd "$ROOT_DIR" && PYTHONIOENCODING=utf-8 "$PY" -m "$m" 2>&1)"; rc=$?
    if [ $rc -eq 0 ]; then c_ok "⑥ $m 自检 → rc=0（$(printf '%s' "$out" | tail -1)）"; PASS=$((PASS+1))
    else c_no "⑥ $m 自检 → rc=$rc"; printf '%s\n' "$out" | tail -15; FAIL=$((FAIL+1)); fi
  done
fi

# ── 7. 服务单元 ──────────────────────────────────────────────────────
if command -v systemctl >/dev/null 2>&1; then
  chk "⑦a" "systemctl is-active  gym3d-api"  active  "$(systemctl is-active gym3d-api 2>/dev/null || echo inactive)"
  chk "⑦b" "systemctl is-enabled gym3d-api"  enabled "$(systemctl is-enabled gym3d-api 2>/dev/null || echo disabled)"
  printf '    最近 5 行日志：\n'; journalctl -u gym3d-api -n 5 --no-pager 2>/dev/null | sed 's/^/      /'
else
  c_sk "⑦ systemctl ——这台机器上没有 systemd"
fi

echo "═══════════════════════════════════════════════════════════════"
printf '通过 %d   失败 %d   不适用 %d\n' "$PASS" "$FAIL" "$SKIP"
echo
echo "★ 仍需你**用眼睛**过的两条（浏览器，这两条脚本量不了）："
echo "   5) 打开 /portal/  → 出登录屏，且**一条数据都不出**"
echo "   6) 登录搭建方 → 点一块 → 锚定一栋 → 面板出楼层与用途"
echo
# ★ 「不适用」不许并进「通过」里报（铁律 167：表尾那个码是严重度，不是红的个数）
if [ "$SKIP" -gt 0 ]; then
  printf '★ 有 %d 条**不适用** —— 它们是「没跑」，不是「过了」，汇报时不许合并。\n' "$SKIP"
fi
if [ "$FAIL" -eq 0 ] && [ "$SKIP" -eq 0 ]; then
  echo "✓ 全过"
fi
if [ "$FAIL" -eq 0 ]; then exit 0; else exit 1; fi
