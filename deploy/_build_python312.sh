#!/bin/bash
# 在 openEuler 22.03 上装 Python 3.12（仓库里只有 3.9，装不了 requirements-server.txt）。
#
# ★ 为什么必须装：settings.py:43 `data_dir: Path | None = None` 是 pydantic-settings 的字段，
#   pydantic 在 **import 那一刻**求值这个注解 —— 3.9 上直接 TypeError，
#   后端连 import 都过不去（2026-10-01 在本机 ssh 上实测，不是推的）。
#
# 用法：nohup bash /root/_build_python312.sh > /root/_build_python312.log 2>&1 &
# 判据（脚本自己跑，不符就退非零）：
#   ① /opt/python3.12/bin/python3.12 -V  → 3.12.10
#   ② 能建成 venv 并 pip 装得上 fastapi/uvicorn/psycopg/numpy
set -euo pipefail

# 让「跑完没有 / 结果如何」有一个**不靠 pgrep 猜**的读数：
# pgrep -f 会匹配到「我自己那条 ssh 命令行里的字符串」，于是永远报「仍在跑」（2026-10-01 实测踩到）。
trap 'echo $? > /root/_build_python312.rc' EXIT
rm -f /root/_build_python312.rc

PREFIX=/opt/python3.12
VER=3.12.10
TARBALL=Python-$VER.tgz
URL=https://www.python.org/ftp/python/$VER/$TARBALL
# ★ 这里**故意不写**一个 sha256 常量：手打的期望值一旦写错，会把「我抄错了」报成
#   「下载坏了」，方向正好反（铁律 105）。真实且能测的判据是下面三条：
#     ① TLS 直连 python.org（curl -fSL，证书链由 curl 默认校验）
#     ② gzip -t  —— 抓的是这条链路真正的失败模式：截断
#     ③ 解包后读 Include/patchlevel.h 里的版本号 == 我要的那个
#   sha256 仍然打印并存档，供事后再核，但它不当闸门。
BUILD=/opt/_build_py312
NPROC=$(nproc)

echo "=== [1/6] $(date +%T) 装编译依赖 ==="
dnf install -y --setopt=install_weak_deps=False \
    zlib-devel openssl-devel libffi-devel bzip2-devel xz-devel sqlite-devel readline-devel

echo "=== [2/6] $(date +%T) 下载 $TARBALL ==="
mkdir -p "$BUILD"
cd "$BUILD"
if [ ! -f "$TARBALL" ]; then
    curl -fSL --retry 3 --max-time 600 -o "$TARBALL" "$URL"
fi
ls -l "$TARBALL"
echo "  sha256 = $(sha256sum "$TARBALL" | cut -d' ' -f1)   （存档用，不当闸门）"
echo "  → 完整性判据：gzip -t"
gzip -t "$TARBALL"          # 截断会在这里炸，不会带病进 make

echo "=== [3/6] $(date +%T) 解包 + 核版本号 + configure ==="
rm -rf "Python-$VER"
tar xzf "$TARBALL"
cd "Python-$VER"
# 读源码自己声明的版本 —— 与 $VER 不符就停（这是「解出来的确实是 3.12.10」的直接证据）
grep -E '^#define PY_(MAJOR|MINOR|MICRO)_VERSION' Include/patchlevel.h
# ★ 这里**不许**用 `/PY_VERSION\b/` 这类正则：\b 不是每个 awk 都认（openEuler 上实测
#   抽出来是空串，于是把一次好的下载判成「版本对不上」——量具坏成假红，铁律 173）。
#   用精确字段匹配，语义为零。
SRCVER=$(awk '$1 == "#define" && $2 == "PY_VERSION" { v = $3; gsub(/"/, "", v); print v; exit }' Include/patchlevel.h)
echo "  源码自报版本：[${SRCVER}]（期望 $VER）"
if [ -z "$SRCVER" ]; then
    echo "  ✗ 抽不到版本号 —— 先查是不是抽取本身坏了（grep 上面那三行在不在），别急着判源码有问题"
    exit 3
fi
[ "$SRCVER" = "$VER" ] || { echo "✗ 版本对不上，停"; exit 3; }
# 不开 --enable-optimizations（PGO 要 15 分钟换 10~20%，而本服务是 I/O 型）；
# 不开 --enable-shared（venv 用不着，还省掉 ldconfig 那一步）。
./configure --prefix="$PREFIX" --with-ensurepip=install

echo "=== [4/6] $(date +%T) make -j$NPROC（约 3~5 分钟）==="
make -j"$NPROC"

echo "=== [5/6] $(date +%T) make install ==="
make install

echo "=== [6/6] $(date +%T) 判据 ==="
"$PREFIX/bin/python3.12" -V
"$PREFIX/bin/python3.12" -c 'from pathlib import Path; print("Path|None 可用:", Path | None)'
"$PREFIX/bin/python3.12" -c 'import ssl, sqlite3, zlib, bz2, lzma, ctypes, readline; print("ssl:", ssl.OPENSSL_VERSION)'

echo "=== 建一个试装 venv，核 requirements-server.txt 真能装上 ==="
TMPV=/opt/_build_py312/probe-venv
rm -rf "$TMPV"
"$PREFIX/bin/python3.12" -m venv "$TMPV"
"$TMPV/bin/pip" install -q --upgrade pip
"$TMPV/bin/pip" install -q "fastapi~=0.115" "uvicorn[standard]~=0.32" "pydantic~=2.9" \
    "pydantic-settings~=2.6" "python-dotenv~=1.0" "psycopg[binary]~=3.2" "numpy~=2.1"
"$TMPV/bin/python" -c 'import fastapi, uvicorn, pydantic, pydantic_settings, psycopg, numpy; print("fastapi", fastapi.__version__, "| pydantic", pydantic.VERSION, "| numpy", numpy.__version__, "| psycopg", psycopg.__version__)'
rm -rf "$TMPV"

echo "=== ✓ DONE $(date +%T)  Python 3.12 装在 $PREFIX ==="
