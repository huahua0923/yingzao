#!/bin/bash
# 服务器侧第一步：拉代码 → 建 venv → 装依赖 → 判据。
#
# 前置：/opt/python3.12 已装好（见 _build_python312.sh）
# 用法：nohup bash /root/_setup_server.sh > /root/_setup_server.log 2>&1 &
# 读结果：cat /root/_setup_server.rc   （0 = 全过；非 0 = 第几步倒的）
set -euo pipefail
trap 'echo $? > /root/_setup_server.rc' EXIT
rm -f /root/_setup_server.rc

PY=/opt/python3.12/bin/python3.12
APP=/opt/gym3d

echo "=== [1/6] $(date +%T) 拉代码 ==="
if [ -d "$APP/.git" ]; then
    cd "$APP"
    git fetch --all -q
    git reset --hard origin/master
else
    git clone https://github.com/huahua0923/yingzao.git "$APP"
    cd "$APP"
fi
HEAD=$(git rev-parse --short HEAD)
echo "  HEAD = $HEAD  $(git log -1 --format=%s)"
echo "  frontend/portal 文件数 = $(git ls-files frontend/portal | wc -l)  （期望 14）"
echo "  deploy/ 文件数 = $(git ls-files deploy | wc -l)"
[ "$(git ls-files frontend/portal | wc -l)" -eq 14 ] || { echo "  ✗ 门户页没跟上来"; exit 2; }

echo "=== [2/6] $(date +%T) 建 venv ==="
rm -rf "$APP/.venv"
"$PY" -m venv "$APP/.venv"
"$APP/.venv/bin/pip" install -q --upgrade pip
"$APP/.venv/bin/python" -V

echo "=== [3/6] $(date +%T) 装 requirements-server.txt ==="
"$APP/.venv/bin/pip" install -r "$APP/requirements-server.txt" 2>&1 | tail -5

echo "=== [4/6] $(date +%T) import 判据（正面）==="
"$APP/.venv/bin/python" -c 'import fastapi, uvicorn, pydantic, pydantic_settings, psycopg, numpy; print("  fastapi", fastapi.__version__, "| pydantic", pydantic.VERSION, "| psycopg", psycopg.__version__, "| numpy", numpy.__version__)'

echo "=== [5/6] $(date +%T) 防线判据（反面）：这几个必须 import 不进来 ==="
for m in ezdxf shapely trimesh mapbox_earcut; do
    if "$APP/.venv/bin/python" -c "import $m" 2>/dev/null; then
        echo "  ✗ $m **装进来了** —— 「只服务不建模」那道防线破了"
        exit 4
    fi
    echo "  ✓ $m 不存在（防线成立）"
done

echo "=== [6/6] $(date +%T) 试着 import 应用本体（还没写 .env，缺库口令属正常）==="
cd "$APP"
if "$APP/.venv/bin/python" -c 'import backend.api.main; print("  backend.api.main import OK")'; then
    echo "  应用本体 import 通过"
else
    echo "  ⚠ 上面这条 import 失败 —— 先看是不是只缺 .env 的库口令（下一步会补）"
fi

echo "=== ✓ DONE $(date +%T)  代码在 $APP，venv 在 $APP/.venv，HEAD=$HEAD ==="
