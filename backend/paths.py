# -*- coding: utf-8 -*-
"""仓库路径常量 + sys.path 引导。

**只 import 标准库**，所以脚本在「还没配好 sys.path」的处境下也能先 import 它 ——
这正是它存在的理由：以前每个脚本都写 `sys.path.insert(0, r"D:\\gym3d")`，
开发机在 D 盘、服务器在 /opt，同一份代码换个机器就跑不起来。

用法（脚本在 backend/<子目录>/<脚本>.py 时）：

    import os, sys
    sys.path.insert(0, os.path.normpath(
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")))   # → backend/
    from paths import DATA, ROOT, ensure_sys_path
    ensure_sys_path("modeling", "nav")        # 需要哪些兄弟目录就挂哪些

`ROOT` 由本文件位置推导（backend/paths.py → 上两级），与
`backend/api/settings.py` 的 `Settings.root` 算法一致；两边都指向仓库根。
"""
import sys
from pathlib import Path

ROOT: Path = Path(__file__).resolve().parents[1]
BACKEND: Path = ROOT / "backend"
FRONTEND: Path = ROOT / "frontend"
DATA: Path = ROOT / "data"
BUILDINGS: Path = DATA / "buildings"
NODE_MODULES: Path = ROOT / "node_modules"
SCRIPTS: Path = ROOT / "_scratch"


def ensure_sys_path(*subdirs: str) -> Path:
    """把 ROOT、BACKEND 以及 BACKEND/<子目录> 挂上 sys.path，返回 ROOT。

    幂等：已经在 sys.path 里的不再插入，避免反复调用把路径表撑长。
    """
    candidates = [ROOT, BACKEND, *(BACKEND / s for s in subdirs)]
    for path in candidates:
        text = str(path)
        if text not in sys.path:
            sys.path.insert(0, text)
    return ROOT


def ensure_backend_path(script_file: str, *subdirs: str) -> Path:
    """给 `backend/<子目录>/<脚本>.py` 用的一步到位版：先把自己挂上，再调 ensure_sys_path。

    调用方只需 `from paths import ...` 之前插一行 `backend/`，剩下的交给它。
    保留给「脚本位置深度不定」的场景；一般直接用 ensure_sys_path 更直白。
    """
    backend = Path(script_file).resolve().parent.parent
    if str(backend) not in sys.path:
        sys.path.insert(0, str(backend))
    return ensure_sys_path(*subdirs)
