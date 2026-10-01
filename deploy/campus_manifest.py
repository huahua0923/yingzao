# -*- coding: utf-8 -*-
"""列出 campus 产物的**最小集**：8 个固定名 + 数据层点名的洞底截图。

为什么要单独一个文件而不是在 shell 里 grep 名字：
洞底截图的名字**不在本文件里**，它活在 `campus_terrain_viewdata.json` 的
`interior_holes.blocks[].crop` 里 —— 同一个来源正是
`backend/api/routers/campus.py:231 /campus/hole/{name}` 那条路由现算名单的地方。
从同一处读，才能保证「路由放得出去的」与「打包带得走的」永远是同一份名单
（铁律 041/018：两份清单必须同源，兜底会把「漏了一条」变成「安静地走默认」）。

用法：  python deploy/campus_manifest.py <campus 目录>
输出：  每行一个路径（原样拼目录，不规范化成绝对路径）
"""
import json
import os
import sys

# ★ 与 backend/api/routers/campus.py 的 *_NAME 常量逐字对应，不多不少。
#   改那里就要改这里 —— 判据在 pack_data.sh 里（campus 必须恰好 10 件）。
FIXED = (
    "campus_terrain_viewdata.json",
    "campus_terrain.glb",
    "campus_buildings.glb",
    "campus_buildings_viewdata.json",
    "campus_ortho.jpg",
    "campus_ortho.json",
    "campus_lod1_blocks.json",
    "campus_outlines.json",
)


def crops(campus_dir):
    """数据层点名的洞底截图文件名（去重、保序、只留真的在盘上的）。"""
    vd = os.path.join(campus_dir, "campus_terrain_viewdata.json")
    try:
        man = json.loads(open(vd, encoding="utf-8").read())
    except (OSError, ValueError) as e:
        # 读不出来就**出声**：静默返回空会让「10 件」少掉 2 件而照样打包成功
        sys.stderr.write("⚠ 读不出 %s（%s）⇒ 洞底截图这一项为空\n" % (vd, type(e).__name__))
        return []
    seen, out = set(), []
    for b in (man.get("interior_holes", {}).get("blocks") or []):
        c = b.get("crop")
        if isinstance(c, str) and c and c not in seen:
            seen.add(c)
            out.append(c)
    return out


def main(argv):
    if len(argv) < 2:
        sys.stderr.write(__doc__)
        return 2
    # ★ Windows 上 stdout 默认文本模式 ⇒ print 出的是 CRLF，而调用方（pack_data.sh）
    #   用 bash 的 printf 写的是 LF。两者拼进同一份清单 ⇒ tar 读到
    #   `...json\r`，`Cannot stat`，而它长得像「文件不在盘上」。
    #   行尾必须在源头统一（本仓铁律 081/175 的同族：文本模式写盘会翻行尾）。
    try:
        sys.stdout.reconfigure(newline="\n")
    except (AttributeError, OSError):
        pass
    d = argv[1]
    n_missing = 0
    for name in list(FIXED) + crops(d):
        p = os.path.join(d, name)
        if os.path.isfile(p):
            print(p.replace("\\", "/"))
        else:
            n_missing += 1
            sys.stderr.write("⚠ 名单里点了名但盘上没有：%s\n" % p)
    return 1 if n_missing else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
