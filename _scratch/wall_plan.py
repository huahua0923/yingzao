# -*- coding: utf-8 -*-
"""第一层墙体平面图（白底深线，风格同 DXF）：只画竖直墙面的水平投影，忽略楼板水平面。
输出：wallplan.png
"""
import numpy as np
import trimesh
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

GLB = r"D:\gym3d\lihua-v2-floor1.glb"
mesh = trimesh.load(GLB)
if isinstance(mesh, trimesh.Scene):
    g = list(mesh.geometry.items())
    mesh = g[0][1] if len(g) == 1 else trimesh.util.concatenate([x[1] for x in g])
V, F, n = mesh.vertices, mesh.faces, mesh.face_normals

vertical = np.abs(n[:, 1]) < 0.45     # 竖直墙体
fig, ax = plt.subplots(figsize=(20, 7))
for f in F[vertical]:
    for i in range(3):
        a, b = f[i], f[(i + 1) % 3]
        ax.plot([V[a, 0], V[b, 0]], [V[a, 2], V[b, 2]], color="#1a1a1a", lw=0.5)
# 楼板轮廓（水平面外圈）浅灰描边，便于对照
for f in F[~vertical]:
    ext = np.abs(np.cross(V[f[1]] - V[f[0]], V[f[2]] - V[f[0]]))
    pass
ax.set_aspect('equal')
ax.set_xlim(V[:, 0].min() - 2, V[:, 0].max() + 2)
ax.set_ylim(V[:, 2].min() - 2, V[:, 2].max() + 2)
ax.axis('off')
plt.tight_layout()
plt.savefig(r"D:\gym3d\wallplan.png", dpi=120)
print("saved wallplan.png")
