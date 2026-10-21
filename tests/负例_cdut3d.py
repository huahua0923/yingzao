# -*- coding: utf-8 -*-
"""标准清单自证：故意坏一份，确认指北针会红。"""

import json
import shutil
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    manifest = ROOT / "规范.json"
    if not manifest.is_file():
        print("没量到：规范.json 不在")
        return 2
    data = json.loads(manifest.read_text(encoding="utf-8"))
    if not data.get("规范"):
        print("✗ 规范清单为空")
        return 1

    exe = shutil.which("指北针") or shutil.which("指北针.bat")
    if not exe:
        local = Path("D:/指北针系统/指北针.bat")
        exe = str(local) if local.is_file() else None
    if not exe:
        print("没量到：PATH 上没有 `指北针`；不是通过")
        return 0

    bad = json.loads(json.dumps(data, ensure_ascii=False))
    bad["规范"][0]["判据"] = {"类型": "不存在的判据"}
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "规范.json"
        p.write_text(json.dumps(bad, ensure_ascii=False), encoding="utf-8")
        proc = subprocess.run([exe, "规范", "--在", tmp], capture_output=True, text=True)
    if proc.returncode == 0:
        print("✗ 坏输入仍然全绿，判据没有分辨力")
        return 1
    print("✓ 坏输入按预期变红")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
