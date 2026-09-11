# -*- coding: utf-8 -*-
"""重出 GLB 并**看守数据**：跑前跑后各算一遍 floors/spec 的指纹，不一致就报错。

为什么要这一步：这一轮改的全是渲染层（glb_common / build_standard_glb），
楼层的 floor*.json 一个字节都不该动。一个"只出 GLB"的步骤要是动了数据，
说明我碰了不该碰的东西 —— 必须立刻知道，不能等到 49 栋跑完才发现。

用法：python _scratch/_rebuild_guarded.py c103 c027 c018
      python _scratch/_rebuild_guarded.py --all
"""
import glob
import hashlib
import json
import os
import subprocess
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

B = r"D:\gym3d\data\buildings"
WEB = r"D:\gym3d\backend\web"


def fingerprint(name):
    """floors/*.json + spec.json 的内容指纹（按文件名排序，逐字节）。"""
    d = os.path.join(B, name)
    h = hashlib.sha256()
    files = sorted(glob.glob(os.path.join(d, "floors", "*.json"))) + \
        [os.path.join(d, "spec.json")]
    for p in files:
        h.update(os.path.basename(p).encode())
        with open(p, "rb") as f:
            h.update(f.read())
    return h.hexdigest()[:16], len(files)


def audit(name):
    """读回 GLB 核：字节 / 面数 / 有向体积 / 边闭合（按坐标做键）。"""
    p = os.path.join(B, name, "%s-building.glb" % name)
    if not os.path.exists(p):
        return "  (没有 %s-building.glb)" % name
    import numpy as np
    raw = open(p, "rb").read()
    if raw[:4] != b"glTF":
        return "  不是 GLB"
    off, jlen = 12, int.from_bytes(raw[12:16], "little")
    js = json.loads(raw[20:20 + jlen].decode("utf-8"))
    boff = 20 + jlen + 8
    pos = []
    for m in js.get("meshes", []):
        for pr in m["primitives"]:
            acc = js["accessors"][pr["attributes"]["POSITION"]]
            bv = js["bufferViews"][acc["bufferView"]]
            st = boff + bv.get("byteOffset", 0) + acc.get("byteOffset", 0)
            n = acc["count"]
            arr = np.frombuffer(raw, dtype="<f4", count=n * 3, offset=st)
            pos.append(arr.reshape(n, 3).astype(np.float64))
    V = np.concatenate(pos) if pos else np.zeros((0, 3))
    idx = []
    for m in js.get("meshes", []):
        for pr in m["primitives"]:
            if "indices" not in pr:
                continue
            acc = js["accessors"][pr["indices"]]
            bv = js["bufferViews"][acc["bufferView"]]
            st = boff + bv.get("byteOffset", 0) + acc.get("byteOffset", 0)
            dt = {5121: "<u1", 5123: "<u2", 5125: "<u4"}[acc["componentType"]]
            idx.append(np.frombuffer(raw, dtype=dt, count=acc["count"],
                                     offset=st).astype(np.int64).reshape(-1, 3))
    F = np.concatenate(idx) if idx else np.zeros((0, 3), dtype=np.int64)
    vol = float(np.einsum("ij,ij->i", V[F[:, 0]],
                          np.cross(V[F[:, 1]], V[F[:, 2]])).sum() / 6.0)
    q = np.round(V, 5).astype(np.float64)
    qi = np.round(q * 1e5).astype(np.int64)
    tri = qi[F]
    ed = np.concatenate([tri[:, [0, 1]], tri[:, [1, 2]], tri[:, [2, 0]]])
    ed = np.sort(ed, axis=1)
    _, cnt = np.unique(ed, axis=0, return_counts=True)
    open_e = int((cnt == 1).sum())
    over_e = int((cnt > 2).sum())
    return ("  %.1f MB  面=%d  顶点=%d  体积=%.1f m³  开边=%d(%.3f%%)  叠边=%d"
            % (len(raw) / 1e6, len(F), len(V), vol, open_e,
               100.0 * open_e / max(1, len(cnt)), over_e))


names = sys.argv[1:]
if names == ["--all"]:
    names = sorted(n for n in os.listdir(B)
                   if os.path.isdir(os.path.join(B, n, "floors")))

bad = []
for name in names:
    before, nf = fingerprint(name)
    t = time.time()
    r = subprocess.run([sys.executable, "run_step.py", name, "glb"],
                       cwd=WEB, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    dt = time.time() - t
    after, _ = fingerprint(name)
    tag = "数据未动" if before == after else "**数据被改了！**"
    print("%-6s %6.1fs rc=%d  %s(%s→%s)"
          % (name, dt, r.returncode, tag, before, after))
    if r.returncode != 0:
        print((r.stdout or "")[-1500:])
        print((r.stderr or "")[-1500:])
        bad.append(name)
        continue
    if before != after:
        bad.append(name)
    print(audit(name))

print()
print("完成 %d 栋，异常 %d 栋 %s" % (len(names), len(bad), bad if bad else ""))
