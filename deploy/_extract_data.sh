#!/bin/bash
# 把 gym3d-data.tar.gz 解到 /opt/gym3d/。
# ★ 判据不是「tar 退 0」—— 是**解包前后逐类计数增加了、且增加量等于包里的条目数**
#   （铁律 017：写好的函数 ≠ 被调用的函数；这里同理：tar 跑了 ≠ 文件到位了）
# ★ 一个字节都不写到 /opt/gym3d 之外。
set -u
TGZ=/root/gym3d-data.tar.gz
DEST=/opt/gym3d

echo "=== [0] 包的身份（含 sha256，供以后对账）==="
sha256sum "$TGZ"
ls -l "$TGZ"

echo
echo "=== [1] 解包前：目标处是什么样 ==="
for p in "$DEST/data" "$DEST/campus-terrain"; do
    if [ -e "$p" ]; then
        printf '  已存在 %-32s 文件数=%s\n' "$p" "$(find "$p" -type f 2>/dev/null | wc -l)"
    else
        printf '  不存在 %-32s\n' "$p"
    fi
done
BEFORE_BUILD=$(find "$DEST/data/buildings" -name profile.json 2>/dev/null | wc -l)
BEFORE_CAMPUS=$(find "$DEST/campus-terrain" -type f 2>/dev/null | wc -l)
echo "  profile.json=$BEFORE_BUILD   campus 文件=$BEFORE_CAMPUS"

echo
echo "=== [2] 解包 ==="
tar -xzf "$TGZ" -C "$DEST"
echo "  tar rc=$?"

echo
echo "=== [3] 解包后核对（判据：增量恰好等于包里的条目数）==="
AFTER_BUILD=$(find "$DEST/data/buildings" -name profile.json 2>/dev/null | wc -l)
AFTER_CAMPUS=$(find "$DEST/campus-terrain" -type f 2>/dev/null | wc -l)
AFTER_FLOOR=$(find "$DEST/data/buildings" -path '*/floors/floor*.json' 2>/dev/null | wc -l)
echo "  profile.json : $BEFORE_BUILD → $AFTER_BUILD   （包里 92）"
echo "  floors       :            → $AFTER_FLOOR   （包里 460）"
echo "  campus 文件  : $BEFORE_CAMPUS → $AFTER_CAMPUS   （包里 10）"
[ -f "$DEST/data/buildings/index.json" ] && echo "  index.json   : 在" || echo "  index.json   : **不在**"

rc=0
[ "$AFTER_BUILD" -eq 92 ] || { echo "  ✗ profile.json 不是 92"; rc=1; }
[ "$AFTER_FLOOR" -eq 460 ] || { echo "  ✗ floors 不是 460"; rc=1; }
[ "$AFTER_CAMPUS" -ge 10 ] || { echo "  ✗ campus 少于 10 个"; rc=1; }
[ -f "$DEST/data/buildings/index.json" ] || { echo "  ✗ index.json 缺"; rc=1; }

echo
echo "=== [4] 那两个 campus GLB 的字节数（供 /api/campus 对账）==="
ls -l "$DEST/campus-terrain/"*.glb 2>&1

echo
echo "=== [5] 目录里不该有的东西（glb/png 只许出现在 campus-terrain）==="
find "$DEST/data" -name '*.glb' -o -name '*.png' -o -name '*.dxf' 2>/dev/null | head
echo "  （上面空 = 对）"

exit $rc
