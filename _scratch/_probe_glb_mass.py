# -*- coding: utf-8 -*-
"""从 GLB 实体三角形, 沿高度分带, 量每带 水平面 X/Y 质量中心与实体左右/前后极值。
直接反映"眼睛看到"的每高度块中心, 判断上层块相对下层块是否偏。"""
import sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import numpy as np, trimesh

def bands(name):
    sc = trimesh.load(f"data/buildings/{name}/{name}-building.glb", process=False)
    gs = sc.geometry.values() if hasattr(sc,"geometry") else [sc]
    V=[]; F=[]
    for g in gs:
        if hasattr(g,"faces") and g.faces is not None:
            V.append(np.asarray(g.vertices)); F.append(np.asarray(g.faces)+ (len(V[-1]) if False else 0))
    # 合并
    off=0; verts=[]; tris=[]
    for g in gs:
        if hasattr(g,"faces") and len(g.faces):
            v=np.asarray(g.vertices); t=np.asarray(g.faces)+off
            verts.append(v); tris.append(t); off+=len(v)
    verts=np.concatenate(verts); tris=np.concatenate(tris)
    P=verts[tris].astype(float)          # (T,3,3)
    c=P.mean(axis=1)                     # 三角形质心
    # 三角形面积
    a=P[:,0];b=P[:,1];d=P[:,2]
    cross=np.cross(b-a,d-a); A=0.5*np.sqrt((cross**2).sum(1)); A=np.maximum(A,1e-12)
    # 高度轴 = 极值最大的轴
    lo=verts.min(0); hi=verts.max(0); h=int(np.argmin(hi-lo))
    floor_ax=[i for i in range(3) if i!=h]
    H0,H1=lo[h],hi[h]; NB=64
    print(f"{name}: 高度轴={'xyz'[h]} 范围[{H0:.1f},{H1:.1f}] 地面轴={'xyz'[floor_ax[0]]}/{'xyz'[floor_ax[1]]} 尺寸{hi-lo}")
    # 每带质量中心
    for k in range(NB):
        z0=H0+(H1-H0)*k/NB; z1=H0+(H1-H0)*(k+1)/NB
        m=(c[:,h]>=z0)&(c[:,h]<z1)
        if not m.any(): continue
        cm=c[m]; am=A[m]
        w=am.sum()
        cx=(cm[:,floor_ax[0]]*am).sum()/w
        cy=(cm[:,floor_ax[1]]*am).sum()/w
        # 实体存在极值
        x0,x1=cm[:,floor_ax[0]].min(),cm[:,floor_ax[0]].max()
        y0,y1=cm[:,floor_ax[1]].min(),cm[:,floor_ax[1]].max()
        bar='#'*int(40*(z1-z0)/(H1-H0))
        print(f"  高[{z0:6.1f},{z1:6.1f}] 质量中心X={cx:+6.2f} Y={cy:+6.2f}  范围X[{x0:+6.1f},{x1:+6.1f}] Y[{y0:+6.1f},{y1:+6.1f}]")
for b in sys.argv[1:]:
    bands(b); print()
