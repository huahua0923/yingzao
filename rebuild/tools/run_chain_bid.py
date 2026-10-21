# -*- coding: utf-8 -*-
"""一栋楼按 cdut3d 链从头跑到装包（**一条命令**，逐步入闸，失败即停）。

为什么要有它（2026-10-17）：剩下 60 多栋楼，逐步手敲九条命令既慢又容易漏步；
而漏一步的症状是「后面全绿、件是旧的」（例如忘了 export_contours，FreeCAD 吃的是上一版轮廓）。
本脚本只做三件事：按顺序跑、每步**等它真的出件**再走下一步、把读数原样留在日志里。

用法：
    python -I rebuild/tools/run_chain_bid.py c009
    python -I rebuild/tools/run_chain_bid.py c009 --from 建件      # 从某一步重跑
    python -I rebuild/tools/run_chain_bid.py c009 --to 轮廓        # 只跑到某一步
    python -I rebuild/tools/run_chain_bid.py c009 --dry            # 只打印将跑的步骤

退出码：
    0 全部通过 · 2 参数错 · 5 「rc=0 但件不在」· 其它 = 那一步自己的 rc
    ★ rc 与「有没有真干成」不许同形（铁律 199）：每步跑完都去看产物在不在。

前置：`rebuild/构件库/楼栋.json` 里要有这栋楼的档案（src_dxf / keep_layers / drawing …）。
"""
from __future__ import annotations

import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
CDUT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)


def _root_for(bid):
    """数据根 —— **只认** `building.root_for()`（原来这条规则在这里和装包器各写一份，
    装包器那份把 c006 指到不存在的 `rebuild/c006/`，c006 因此从没进过共用装包器）。"""
    import building as B
    return B.root_for(bid)


def _steps(bid, root):
    import building as B
    name = B.out_name(bid)
    pack = os.path.join(CDUT, "packs", "cdut-main", bid)
    py = [sys.executable, "-I"]
    steps = [
        # (名字, 命令, 跑完必须存在的件)
        # ★ 2026-10-17 实测：切图幅的产物是 `<根>/windows.json`（**没有** `01_cad/sheets.json`
        #   这一件 —— 我上一版把它写成要出 01_cad/sheets.json，于是 rc=0 却被判「产物不在」，
        #   三栋楼全卡在第一步。判据要认**真的那一件**，不是我以为的那一件。）
        ("切图幅", py + ["sheet_windows.py"],
         os.path.join(root, "windows.json")),
        ("导出图幅", py + ["export_sheet.py", "--all"],
         os.path.join(root, "01_cad", "raw")),
        # ★★ 2026-10-20 用户「办公楼副楼 3 楼和 4 楼错开了」：切图幅把**窗口角**当楼栋原点，
        #   而源 DXF 里各层平面在各自窗口内**放得不一样**（c004f1 第 4 张高 1700 mm）⇒
        #   整层平移。这一步用楼梯/文字两把尺子把每层搬回同一基准，落盘
        #   `01_cad/raw/_registration.json`。**必须在识别之前**：后面每一步都读平移后的 raw。
        ("楼面配准", py + ["sheet_register.py", "--all"],
         os.path.join(root, "01_cad", "raw", "_registration.json")),
        ("识别", py + ["recognize.py", "--all"],
         os.path.join(root, "02_recognize")),
        # ★ 2026-10-19：文字语义（`5面积`「露台」/`6房间号`/`7用途`/`8单位`）→ 分区。
        #   `build3d` 与 `export_contours` 的**露台无顶**都吃这份文件；漏这一步 ⇒
        #   图改了而露台表还是旧的，件会「全链绿 + 静默过期」（铁律 187）。
        ("语义识别", py + ["recognize_semantics.py"],
         os.path.join(root, "02_recognize", "语义.json")),
        # ★ 2026-10-19：挑空（**对照件**识别，用户「按 ts4 补全」）—— 源图无任何标注，
        #   证据只有手建件；`build3d`/`export_contours` 的楼板洞与屋面洞都吃这份文件。
        #   档案里没有 `对照件` 的楼栋：本步 rc=2，链停在这里（不许静默当「没有挑空」）。
        ("挑空识别", py + ["recognize_voids.py"],
         os.path.join(root, "02_recognize", "挑空.json")),
        ("建件", py + ["build3d.py"],
         os.path.join(root, "05_build", "build.json")),
        ("轮廓", py + ["export_contours.py"],
         os.path.join(root, "06_su", "contours", "index.json")),
        # ★ 2026-10-21：楼梯方向报告要读 `06_su/contours/index.json`，因此必须排在轮廓之后。
        #   原先排在“建件”之前，全新楼栋没有旧轮廓时会在这一步假失败（c103/c104/c105 实测）。
        #   本步仍然只报不翻，不参与建件。
        ("楼梯方向", py + ["report_stair_direction.py"],
         os.path.join(root, "02_recognize", "楼梯方向.json")),
        ("FreeCAD", py + ["run_freecad.py"],
         os.path.join(root, "06_su", "%s_fc.obj" % name)),
        ("GLB", py + ["fc_obj_to_glb.py"],
         os.path.join(root, "06_su", "%s_fc.glb" % name)),
        ("逐块清单", py + ["mk_catalog.py"],
         os.path.join(root, "06_su", "%s_catalog.json" % name)),
        ("装包", py + [os.path.join(CDUT, "demo", "build_pack_bid.py"), bid],
         os.path.join(pack, "manifest.json")),
        # ★ 2026-10-18：装完包立刻对**层号配对**（用户「C006 房屋使用的那个面和房间错开了」）。
        #   判据是 `check_pack_floors.py`：拿基线柱心去清单里找（平移不变），逐层过 90% 才算对上，
        #   顺带验 `floors[]` 按 z0 排序（查看器按下标取层的前提）。
        #   `need` 用 manifest.json 而不是 blocks.json：单网格包没有 blocks.json，
        #   拿它当「产物在不在」会把这步判成假红。
        ("层号对账", py + [os.path.join(HERE, "check_pack_floors.py"), bid],
         os.path.join(pack, "manifest.json")),
    ]
    # ★ 2026-10-19：只有档案里写了 `对照件` 的楼栋才做挑空识别。其余楼栋**明确印一行**
    #   跳过（不许让 rc=2 把整条链卡死，也不许静默当「没有挑空」）。
    if not (B.profile(bid).get("对照件") or {}).get("obj"):
        print("★ %s 档案无 `对照件` ⇒ 跳过挑空识别（楼板/屋面不扣挑空）" % bid)
        steps = [s for s in steps if s[0] != "挑空识别"]
    return steps


def main(argv):
    if not argv or argv[0].startswith("-"):
        print(__doc__)
        return 2
    bid = argv[0]
    dry = "--dry" in argv
    only_from = argv[argv.index("--from") + 1] if "--from" in argv else None
    only_to = argv[argv.index("--to") + 1] if "--to" in argv else None

    import building as B
    root = _root_for(bid)
    # ★ 2026-10-17 实测：新楼栋的数据根还不存在 ⇒ `sheet_windows.py` 写 `windows.json`
    #   当场 FileNotFoundError（c009/c025 就这么死的，0.2 min 全军覆没）。
    #   根目录由**跑链的人**建，不是让每一步各自去猜父目录。
    os.makedirs(root, exist_ok=True)
    env = dict(os.environ)
    env["CDUT_BUILDING"] = bid
    env["CDUT_REBUILD_ROOT"] = root
    # ★ 2026-10-17：FreeCAD 的暂存区**按楼栋分开**（原来全用 `C:\sutest\fcstage`）。
    #   同一个目录会被 `run_freecad.py` 复制脚本 + 写 `profile.resolved.json`，
    #   两栋楼同时跑就互相冲掉（症状是「件建出来了，但是隔壁楼那一栋」）。
    #   分开之后可以并行跑多栋；显式设了 CDUT_FC_STAGE 就听环境变量。
    if not os.environ.get("CDUT_FC_STAGE"):
        env["CDUT_FC_STAGE"] = r"C:\sutest\fcstage_" + bid
    prof = B.profile(bid)
    print("楼栋 %s · %s" % (bid, prof.get("title") or "（档案无 title）"))
    print("数据根 %s" % root)
    print("层   %s  |  地下室 %s  |  画法 %s"
          % (B.floor_names(bid), prof.get("basement"), prof.get("drawing")))
    steps = _steps(bid, root)
    names = [s[0] for s in steps]
    if only_from:
        if only_from not in names:
            print("★ --from 的步骤名不在 %s 里" % names)
            return 2
        steps = steps[names.index(only_from):]
        # ★ 2026-10-17 实测：`--from` 截过之后 `names` 还是全长的 ⇒ 再拿它算 `--to` 的下标
        #   就会**多跑几步**（c001 `--from 识别 --to 轮廓` 实际跑到了 GLB）。截完必须重取。
        names = [s[0] for s in steps]
    if only_to:
        if only_to not in names:
            print("★ --to 的步骤名不在 %s 里" % names)
            return 2
        steps = steps[:names.index(only_to) + 1]
    if dry:
        for i, (nm, cmd, out) in enumerate(steps, 1):
            print("  %d. %-6s %s  ⇒ 要出 %s" % (i, nm, " ".join(cmd[2:]), out))
        return 0

    logp = os.path.join(CDUT, "过程/_scratch", "%s_chain.log" % bid)
    os.makedirs(os.path.dirname(logp), exist_ok=True)
    t_all = time.time()
    with open(logp, "w", encoding="utf-8", newline="\n") as log:
        for i, (nm, cmd, need) in enumerate(steps, 1):
            print("\n===== [%d/%d] %s =====" % (i, len(steps), nm))
            log.write("\n===== [%d/%d] %s : %s =====\n" % (i, len(steps), nm, " ".join(cmd)))
            log.flush()
            t0 = time.time()
            p = subprocess.run(cmd, cwd=HERE, env=env, capture_output=True, text=True,
                               encoding="utf-8", errors="replace")
            dt = time.time() - t0
            for ln in (p.stdout or "").splitlines():
                print(ln)
                log.write(ln + "\n")
            if p.stderr.strip():
                print("---- stderr ----")
                print(p.stderr[-3000:])
                log.write("---- stderr ----\n" + p.stderr[-8000:] + "\n")
            log.flush()
            if p.returncode != 0:
                print("\n★ %s 失败 rc=%d（%.1fs）—— 停在这里，后面的步骤不跑"
                      % (nm, p.returncode, dt))
                print("  日志：%s" % logp)
                return p.returncode
            if not os.path.exists(need):
                # rc=0 但件不在：与「跑成了」不许同形（铁律 199）
                print("\n★ %s rc=0 但产物不在：%s（%.1fs）" % (nm, need, dt))
                print("  日志：%s" % logp)
                return 5
            print("-- %s ok %.1fs ⇒ %s" % (nm, dt, os.path.basename(need)))
            log.write("-- %s ok %.1fs ⇒ %s\n" % (nm, dt, need))
    print("\n==== 全链通过 %s · %.1f min · 日志 %s"
          % (bid, (time.time() - t_all) / 60.0, logp))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
