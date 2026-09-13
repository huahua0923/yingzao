# -*- coding: utf-8 -*-
r"""把 c103/c104 的 `door` 配色从笔误的 `#6b7078` 改回 `#8a5a38`（唯一所有者）。

为什么是这两栋（全库普查实测，不是猜）：
  · 全库 99 张配色表里，「一码两用」只出现 **4 处**，全在 c103/c104 的 profile.json + spec.json：
    `"roof": "#6b7078"` 与 `"door": "#6b7078"` 同值 —— 门被涂成了屋面色。
  · 其余 47 栋一律 `roof=#6b5a4a` / `door=#8a5a38`（门是暖棕、屋面是深褐）。
  · 门的标准色常量在 `backend/modeling/glb_common.py`：`C_DOOR=[196,150,92]` = `#c4965c` 的族，
    而交付侧一律写 `#8a5a38`。本次只改 door，**roof 保持 `#6b7078` 不动**（用户已定）。

为什么用字节级替换而不是文本编辑器改行：
  这四个文件是**纯 CRLF**（c103 profile 49 行、spec 33 行…实测 lone_lf=0）。
  任何按行重写的工具都可能把行尾统一成 LF，而 `profile.json` 的混行尾在前几栋已经踩过坑
  （见 c009：CRLF/LF 混杂）。字节替换 = 除了那 7 个字节，文件其余部分逐字节不动。

判据（改完自证）：
  ① 每个文件里 `"door": "#6b7078"` 恰好 1 处 → 改后 `"door": "#8a5a38"` 恰好 1 处；
  ② `"roof": "#6b7078"` 改前改后都恰好 1 处（证明只碰了 door）；
  ③ 文件长度不变（两个色值都是 7 字符）；CRLF 计数不变。

用法：
  python _scratch/_fix_door_color.py            # 只报，不写（默认）
  python _scratch/_fix_door_color.py --apply    # 备份后改写
备份：`data/buildings/<name>/.orig/<file>.before_doorcolor`（已存在则不覆盖）。
写盘：先写 `.tmp` 再 `os.replace`（原子；直写会把交付文件截成 0 字节）。
"""
import argparse
import io
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = r"D:\gym3d"
BUILDINGS = os.path.join(ROOT, "data", "buildings")

OLD = b'"door": "#6b7078"'
NEW = b'"door": "#8a5a38"'
ROOF = b'"roof": "#6b7078"'
TARGETS = [("c103", "profile.json"), ("c103", "spec.json"),
           ("c104", "profile.json"), ("c104", "spec.json")]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="真写盘（默认只报）")
    a = ap.parse_args()

    bad = 0
    for name, fn in TARGETS:
        base = os.path.join(BUILDINGS, name)
        fp = os.path.join(base, fn)
        raw = open(fp, "rb").read()
        n_old, n_new, n_roof = raw.count(OLD), raw.count(NEW), raw.count(ROOF)
        # 判据①：要么「1 处旧、0 处新」（待改），要么「0 处旧、1 处新」（已改过）。其余都不许写。
        if not ((n_old == 1 and n_new == 0) or (n_old == 0 and n_new == 1)):
            print("  ✗ %s/%s 命中数不对（旧=%d 新=%d）—— 拒绝改写，先人看"
                  % (name, fn, n_old, n_new))
            bad += 1
            continue
        if n_old == 0:
            print("  · %s/%s 已是 #8a5a38（door 1 处、roof 1 处=%s），跳过"
                  % (name, fn, n_roof == 1))
            continue
        out = raw.replace(OLD, NEW)
        # 判据②③：只碰 door、长度与行尾不变
        assert out.count(NEW) == 1 and out.count(OLD) == 0, "替换结果不合判据①"
        assert out.count(ROOF) == 1, "roof 被动了（判据②）"
        assert len(out) == len(raw), "长度变了（判据③）"
        assert out.count(b"\r\n") == raw.count(b"\r\n"), "CRLF 计数变了（判据③）"
        print("  %s %s/%s  door #6b7078 → #8a5a38（roof 保持 #6b7078；%d 字节不变）"
              % ("✎" if a.apply else "·", name, fn, len(raw)))
        if not a.apply:
            continue
        bk = os.path.join(base, ".orig")
        os.makedirs(bk, exist_ok=True)
        dst = os.path.join(bk, fn + ".before_doorcolor")
        if not os.path.exists(dst):
            with open(dst, "wb") as f:
                f.write(raw)
        tmp = fp + ".tmp"
        with open(tmp, "wb") as f:
            f.write(out)
        os.replace(tmp, fp)

    if bad:
        print("\n有 %d 个文件不合判据，未改写" % bad)
        return 1
    print("\n%s" % ("已写盘 4 处" if a.apply else "未写盘（加 --apply 才写）"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
