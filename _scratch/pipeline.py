# -*- coding: utf-8 -*-
"""CAD → DXF → 侦查 一条龙 pipeline

三步串联（每步都能单独跑，也都可被外部 import 复用）：
  1. gather   — 从已知源位置归集 DWG 到 D:\\dwg_source（MD5 去重）
  2. convert  — D:\\dwg_source → D:\\dxf_output（增量，封装 ODA File Converter）
  3. inspect  — 对每个 DXF 侦查（图层 + 墙层 Y 聚类→楼层/OFFSET），写 <楼>_inspect.txt

用法：
  python pipeline.py             # 全流程 gather + convert + inspect
  python pipeline.py --gather    # 只归集
  python pipeline.py --convert   # 只转换
  python pipeline.py --inspect   # 只侦查
  python pipeline.py --force     # convert 全量重转
"""
import argparse
import sys
from pathlib import Path

import gather_dwg
import convert_dwg_to_dxf
import inspect_building


def step_gather():
    print("=" * 60)
    print("[1/3] 归集 DWG →", gather_dwg.DEFAULT_SRC_DIR)
    c, d, m = gather_dwg.gather(gather_dwg.KNOWN_SOURCES, gather_dwg.DEFAULT_SRC_DIR)
    print(f"  复制 {c} / 去重 {d} / 缺失 {m}")
    return True


def step_convert(force):
    print("=" * 60)
    print("[2/3] 转换 DWG → DXF")
    rc = convert_dwg_to_dxf.convert_all(
        convert_dwg_to_dxf.DEFAULT_INPUT,
        convert_dwg_to_dxf.DEFAULT_OUTPUT,
        force=force,
        dry_run=False,
        name_filter="",
    )
    return rc == 0


def step_inspect():
    print("=" * 60)
    print("[3/3] 侦查各楼 →", inspect_building.DEFAULT_OUT_DIR)
    out = Path(inspect_building.DEFAULT_OUT_DIR)
    out.mkdir(parents=True, exist_ok=True)
    dxfs = sorted(Path(convert_dwg_to_dxf.DEFAULT_OUTPUT).glob("*.dxf"))
    if not dxfs:
        print("  (D:\\dxf_output 里没有 DXF，先跑 --convert)")
        return True
    for dxf in dxfs:
        tag = dxf.stem
        txt = inspect_building.inspect_building(tag, str(dxf))
        (out / f"{tag}_inspect.txt").write_text(txt + "\n", encoding="utf-8")
        # 只回显关键结论：楼层数 + OFFSET
        keys = [ln.strip() for ln in txt.splitlines() if "Y 聚类" in ln or "推断 OFFSET" in ln]
        print(f"  {tag}:")
        for k in keys:
            print(f"    {k}")
    print(f"  侦查 {len(dxfs)} 栋，报告写至 {out}\\*_inspect.txt")
    return True


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description="CAD → DXF → 侦查 一条龙")
    ap.add_argument("--gather", action="store_true", help="只归集 DWG")
    ap.add_argument("--convert", action="store_true", help="只转换 DWG→DXF")
    ap.add_argument("--inspect", action="store_true", help="只侦查 DXF")
    ap.add_argument("--force", action="store_true", help="转换时全量重转")
    args = ap.parse_args()

    selected = [n for n in ("gather", "convert", "inspect") if getattr(args, n)]
    run_all = not selected  # 不带任何 flag 就全跑

    steps = []
    if run_all or "gather" in selected:
        steps.append(("gather", step_gather))
    if run_all or "convert" in selected:
        steps.append(("convert", lambda: step_convert(args.force)))
    if run_all or "inspect" in selected:
        steps.append(("inspect", step_inspect))

    for name, fn in steps:
        try:
            if not fn():
                print(f"\n[{name}] 未完成，中止后续步骤")
                return 1
        except Exception as e:  # noqa: BLE001
            print(f"\n[{name}] 异常: {e}")
            return 1
    print("\n全部完成。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
