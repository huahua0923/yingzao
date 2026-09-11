# -*- coding: utf-8 -*-
"""DWG → DXF 自动转换算法（封装 ODA File Converter）

把 `D:\\dwg_source` 里的 DWG 自动转成 `D:\\dxf_output` 里的 DXF，
供 ezdxf 后续解析（ezdxf 读不了二进制 DWG，必须先过 ODA 这一刀）。

算法要点：
  1. 自动发现 ODA File Converter（默认安装路径 → ezdxf 配置 → PATH）
  2. 扫描输入目录的 *.dwg
  3. 增量转换：DXF 缺失、或 DWG 比 DXF 新才转（--force 全量重转）
  4. Windows 下无 GUI 后台运行（STARTUPINFO + SW_HIDE）
  5. 中文路径/文件名安全（subprocess list 传参，走 CreateProcessW）
  6. 转完用 ezdxf 逐文件校验合法性，汇总成败

用法：
  python convert_dwg_to_dxf.py                        # 增量转（默认目录）
  python convert_dwg_to_dxf.py --dry-run              # 只看会做什么，不实际转
  python convert_dwg_to_dxf.py --force                # 全量重转
  python convert_dwg_to_dxf.py --force --filter C108  # 只重转文件名含 C108 的
  python convert_dwg_to_dxf.py -i D:\\a -o D:\\b
"""

import argparse
import glob
import shutil
import subprocess
import sys
import time
from pathlib import Path

# ---------------- 常量 ----------------
DEFAULT_INPUT = r"D:\dwg_source"
DEFAULT_OUTPUT = r"D:\dxf_output"
OUT_VERSION = "ACAD2018"  # 与 ezdxf 1.4.4 支持上限一致，也与现有 DXF 一致
OUT_FORMAT = "DXF"
RECURSE = "0"             # 不递归子目录
AUDIT = "1"               # ODA/FreeCAD 都要求 audit=1，否则转换易失败
ODA_GLOB = r"C:\Program Files\ODA\ODAFileConverter *\ODAFileConverter.exe"


# ---------------- 1. 发现 ODA ----------------
def find_oda() -> Path:
    """定位 ODAFileConverter.exe。找不到抛 FileNotFoundError。"""
    # (a) 默认安装路径（Windows 标准，含版本号目录）
    hits = glob.glob(ODA_GLOB)
    if hits:
        return Path(hits[0])

    # (b) ezdxf 配置里登记的 win_exec_path
    try:
        import ezdxf
        p = ezdxf.options.get("odafc-addon", "win_exec_path").strip('"')
        if p and Path(p).is_file():
            return Path(p)
    except Exception:
        pass

    # (c) 系统 PATH
    found = shutil.which("ODAFileConverter")
    if found:
        return Path(found)

    raise FileNotFoundError(
        "找不到 ODAFileConverter.exe。请安装 ODA File Converter，"
        "或用 -i/-o 之外的 --oda 指定路径。"
    )


# ---------------- 2. 增量判断 ----------------
def needs_convert(dwg: Path, dxf: Path, force: bool) -> bool:
    """DXF 缺失 / DWG 比 DXF 新 / 强制 任一成立就转。"""
    if force:
        return True
    if not dxf.exists():
        return True
    return dwg.stat().st_mtime > dxf.stat().st_mtime


# ---------------- 3. 单文件转换 ----------------
def convert_one(oda: Path, dwg: Path, out_dir: Path) -> tuple[bool, str]:
    """用 ODA 转单个 DWG。返回 (是否成功, 说明)。

    ODA 命令行为：ODAFileConverter 输入目录 输出目录 版本 格式 递归 audit [文件名]
    第 7 个参数传具体文件名（中文 OK），只转这一个。
    """
    args = [
        str(oda),
        str(dwg.parent),   # 输入目录
        str(out_dir),      # 输出目录
        OUT_VERSION,
        OUT_FORMAT,
        RECURSE,
        AUDIT,
        dwg.name,          # 文件名过滤（只转这个）
    ]
    # Windows 无 GUI 运行：隐藏窗口（ezdxf 源码同款技巧）
    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags = subprocess.CREATE_NEW_CONSOLE | subprocess.STARTF_USESHOWWINDOW
    startupinfo.wShowWindow = subprocess.SW_HIDE

    try:
        proc = subprocess.run(
            args,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            startupinfo=startupinfo,
        )
    except Exception as e:  # noqa: BLE001
        return False, f"启动失败: {e}"

    stderr = proc.stderr.decode("utf-8", errors="replace").strip()
    if proc.returncode != 0 or stderr:
        return False, f"returncode={proc.returncode} stderr={stderr[:200]}"
    return True, "ok"


# ---------------- 4. 校验 ----------------
def verify_dxf(dxf: Path) -> bool:
    """用 ezdxf 试着读，确认产出的是合法 DXF。"""
    try:
        import ezdxf
        ezdxf.readfile(str(dxf))
        return True
    except Exception:  # noqa: BLE001
        return False


# ---------------- 5. 主流程 ----------------
def convert_all(
    input_dir: str, output_dir: str, force: bool, dry_run: bool, name_filter: str
) -> int:
    """扫描→筛选→逐个转→校验→汇总。返回退出码（0 成功，1 有失败）。"""
    src = Path(input_dir)
    dst = Path(output_dir)
    if not src.is_dir():
        print(f"[错误] 输入目录不存在: {src}")
        return 2

    oda = find_oda()
    print(f"ODA File Converter: {oda}")
    print(f"输入: {src}   输出: {dst}\n")

    dwgs = sorted(src.glob("*.dwg"))
    if name_filter:
        dwgs = [d for d in dwgs if name_filter.lower() in d.stem.lower()]
    if not dwgs:
        print("(没有匹配的 .dwg 文件)")
        return 0

    # 先筛出真正要转的（dry-run 也要按这个口径展示）
    todo = [d for d in dwgs if needs_convert(d, dst / (d.stem + ".dxf"), force)]

    if dry_run:
        print(f"== dry-run：共 {len(dwgs)} 个 DWG，其中 {len(todo)} 个需要转换 ==")
        for d in dwgs:
            dxf = dst / (d.stem + ".dxf")
            if d in todo:
                why = "强制重转" if force else ("DXF 缺失" if not dxf.exists() else "DWG 更新")
                print(f"  [转] {d.name}  ({why})")
            else:
                print(f"  [跳过] {d.name}")
        return 0

    if not todo:
        print(f"共 {len(dwgs)} 个 DWG，全部已是最新，无需转换。")
        return 0

    dst.mkdir(parents=True, exist_ok=True)
    ok = skip = fail = 0
    print(f"开始转换 {len(todo)} 个文件...\n")
    for i, d in enumerate(todo, 1):
        dxf = dst / (d.stem + ".dxf")
        t0 = time.time()
        success, msg = convert_one(oda, d, dst)
        dt = time.time() - t0
        if success and verify_dxf(dxf):
            ok += 1
            print(f"  [{i}/{len(todo)}] ✓ {d.name}  ({dt:.1f}s)")
        else:
            fail += 1
            reason = msg if not success else "DXF 校验失败（ezdxf 读不动）"
            print(f"  [{i}/{len(todo)}] ✗ {d.name}  {reason}")

    print(f"\n汇总: 成功 {ok} / 失败 {fail}  (另有 {len(dwgs) - len(todo)} 个跳过)")
    return 0 if fail == 0 else 1


def main() -> int:
    # Windows 控制台/管道默认 GBK，强制 UTF-8 输出避免中文乱码
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    ap = argparse.ArgumentParser(description="DWG → DXF 自动转换（封装 ODA File Converter）")
    ap.add_argument("-i", "--input", default=DEFAULT_INPUT, help="输入目录（默认 D:\\dwg_source）")
    ap.add_argument("-o", "--output", default=DEFAULT_OUTPUT, help="输出目录（默认 D:\\dxf_output）")
    ap.add_argument("--force", action="store_true", help="全量重转，忽略增量判断")
    ap.add_argument("--dry-run", action="store_true", help="只看会做什么，不实际转换")
    ap.add_argument("--filter", default="", metavar="SUB", help="只处理文件名含 SUB 的 DWG")
    args = ap.parse_args()

    try:
        return convert_all(args.input, args.output, args.force, args.dry_run, args.filter)
    except FileNotFoundError as e:
        print(f"[错误] {e}")
        return 2


if __name__ == "__main__":
    sys.exit(main())
