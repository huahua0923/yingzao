# -*- coding: utf-8 -*-
"""服务器安全区服务层。

本包的模块**必须在只装 requirements-server.txt 的 venv 里可导入** ——
不得在模块级 import ezdxf / shapely / trimesh / numpy / mapbox_earcut / matplotlib。
需要重依赖的能力要么走 {@see Settings.compute} 门禁，要么读构建期冻结的产物。
"""
