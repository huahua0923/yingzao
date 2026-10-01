#!/usr/bin/env bash
# 打包「门户页 + API 必需的最小数据集」。**只在本机跑**，产物传上服务器解包。
#
#   用法：  bash deploy/pack_data.sh [输出路径]
#           默认输出 <仓库根>/gym3d-data-<YYYYMMDD>.tar.gz
#
# 它带走什么、不带走什么，由**名单**说了算，不由 tar 的排除规则说了算 ——
# 名单现算（见下），三条断言也都是现算的数，一个都不手打（铁律 105/161/174）。
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
cd "$ROOT"
OUT="${1:-$ROOT/gym3d-data-$(date +%Y%m%d).tar.gz}"

CAMPUS="campus-terrain"                        # 包内路径
CAMPUS_SRC="_scratch/_campus3d/campus-terrain" # 盘上路径（settings.py 的默认值）

MAN="$(mktemp)"; EX=""
cleanup(){ rm -f "$MAN"; [ -n "$EX" ] && rm -rf "$EX"; return 0; }
trap cleanup EXIT

die(){ printf '✗ %s\n' "$*" >&2; exit 1; }
ok(){ printf '✓ %s\n' "$*"; }

[ -d data/buildings ]   || die "在 $ROOT 下找不到 data/buildings"
[ -d "$CAMPUS_SRC" ]    || die "找不到 $CAMPUS_SRC"

echo "── ① 收集名单（现算，不手打）──"
: > "$MAN"
add(){ if [ -f "$1" ]; then printf '%s\n' "$1" >> "$MAN"; fi; return 0; }

add data/buildings/index.json
for d in data/buildings/*/; do
  add "${d}profile.json"; add "${d}spec.json"; add "${d}rooms.json"
done
for f in data/buildings/*/floors/*.json; do add "$f"; done

N_PROFILE=$(grep -c '/profile\.json$' "$MAN" 2>/dev/null || echo 0)
N_INDEX=$(grep -c '^data/buildings/index\.json$' "$MAN" 2>/dev/null || echo 0)

# campus：8 个固定名 + 数据层点名的洞底截图，名字由 campus_manifest.py 从
# campus_terrain_viewdata.json 现读（与 /campus/hole/{name} 路由同源）。
# ★ 名单里写的是**盘上的源路径**；改名到包内的 $CAMPUS/ 由 tar --transform 做。
#   先 sed 成包内路径会得到一份盘上不存在的清单（tar: Cannot stat）。
python "$HERE/campus_manifest.py" "$CAMPUS_SRC" >> "$MAN" || true

N_CAMPUS=$(grep -c "^$CAMPUS_SRC/" "$MAN" 2>/dev/null || echo 0)
TOTAL=$(wc -l < "$MAN")

[ "$TOTAL" -gt 0 ] || die "名单是空的"
[ "$N_CAMPUS" -eq 10 ] || die "campus 产物应为 10 件，实得 $N_CAMPUS —— 名单与 routers/campus.py 对不上了"
ok "名单 $TOTAL 个文件：buildings 侧 $((TOTAL - N_CAMPUS)) + campus $N_CAMPUS"

echo "── ② 打包（campus 从 _scratch 下搬到包内的 $CAMPUS/）──"
rm -f "$OUT"
tar -czf "$OUT" \
    --transform="s|^$CAMPUS_SRC/|$CAMPUS/|" \
    -T "$MAN"

echo "── ③ 断言（三条，任一条不过就退非零）──"
# 断言一：包内文件数 == 名单行数。多一个少一个都拦。
TARFILES=$(tar -tzf "$OUT" | grep -vc '/$' || true)
[ "$TARFILES" -eq "$TOTAL" ] || die "包内文件数 $TARFILES ≠ 名单 $TOTAL（tar 的排除规则和名单不是一回事）"
ok "包内 $TARFILES 个文件 == 名单，一个不多一个不少"

# 断言二：buildings 侧不许混进模型/图纸，全包不许有点目录。
#   ★ 注意这里**刻意只管 data/buildings/**：campus 那两件 .glb 和三张图
#     （campus_terrain.glb / campus_buildings.glb / campus_ortho.jpg / 两张洞底截图）
#     是**交付件**，必须带走。原先写的「全包零 .glb / 零 .png」是错的，
#     照它写会把 campus 的交付件一起拦下 —— 那是把一个正确的装置改坏。
BAD=$(tar -tzf "$OUT" | grep -E '^data/buildings/.*\.(glb|png|jpg|jpeg|dxf)$|/\.' || true)
if [ -n "$BAD" ]; then
  printf '%s\n' "$BAD" | head -20
  die "buildings 侧混进了模型/图纸，或出现了点目录（见上）"
fi
ok "buildings 侧零个 glb/png/jpg/dxf，全包零点目录"
[ "$(tar -tzf "$OUT" | grep -c '\.glb$' || true)" -eq 2 ] \
  || die "包内 .glb 应恰好 2 个（campus_terrain / campus_buildings）"
ok "包内 .glb 恰好 2 个（campus 两件交付件）"

# 断言三：真解一遍，数实物。
EX="$(mktemp -d)"
tar -xzf "$OUT" -C "$EX"
NP=$(find "$EX/data/buildings" -name profile.json | wc -l)
[ "$NP" -eq "$N_PROFILE" ] || die "解包后 profile.json $NP 个 ≠ 源 $N_PROFILE 个"
ok "解包后 profile.json $NP 个（= 源），index.json $N_INDEX 个，campus 10 件"

echo
ls -lh "$OUT" | awk '{print "  " $5 "\t" $9}'
echo
echo "★ 传上服务器后在那边跑："
echo "    cd /opt/gym3d && sudo tar -xzf $(basename "$OUT") && sudo chown -R gym3d:gym3d /opt/gym3d"
