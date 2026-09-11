# -*- coding: utf-8 -*-
"""构件识别引擎：DXF → 分类构件（墙/门/柱/台阶/楼梯井/房间）。

用法：
    import sys
    sys.path.insert(0, r"D:\\gym3d\\backend")
    from recognizer import recognize, get_profile, BuildingProfile
    import recognizer.profiles          # 注册各楼 profile
    recognize(get_profile("lihua"))
"""
from .profile import BuildingProfile, register, get_profile, to_local, floor_of
from .recognize import recognize

__all__ = [
    "BuildingProfile", "register", "get_profile",
    "to_local", "floor_of", "recognize",
]
