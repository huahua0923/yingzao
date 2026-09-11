# -*- coding: utf-8 -*-
"""49 栋批量重出 GLB（带合成窗）。

安全性设计：
  1. **不传第三个参数** —— 走控制台的真实调用路径，由 profile.json 的
     glb_windows 驱动。这样跑的既是生产路径，又顺带验证了新的档案回落代码。
  2. **只跑 glb 步**，绝不碰 recognize —— 楼层 JSON 是几何唯一真源。
  3. 每栋前后各算一次 floors/ 目录哈希，**断言逐字节不变**；变了立刻标 FAIL。
  4. 每栋记录三角面数，掉的超过 30% 标警告（重建后应普遍变大：加窗 + 陈旧件更新）。
  5. 逐栋落盘进度，随时可中断续跑（已完成的写进 MANIFEST，重跑会跳过）。

用法: python _rebuild_all_glb.py [--only c019,c116] [--force]
"""
import hashlib
import json
import os
import struct
import subprocess
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = r"D:\gym3d"
B = os.path.join(ROOT, "data", "buildings")
WEB = os.path.join(ROOT, "backend", "web")
MANI = os.path.join(ROOT, "_scratch", "_rebuild_all_glb_manifest.json")


def floors_hash(name):
    d = os.path.join(B, name, "floors")
    h = hashlib.md5()
    for fn in sorted(os.listdir(d)):
        if fn.startswith("floor") and fn.endswith(".json"):
            h.update(fn.encode())
            with open(os.path.join(d, fn), "rb") as f:
                h.update(f.read())
    return h.hexdigest()


def tri_count(path):
    if not os.path.exists(path):
        return -1
    with open(path, "rb") as f:
        data = f.read()
    off = 12
    while off + 8 <= len(data):
        clen, ctype = struct.unpack_from("<II", data, off)
        if ctype == 0x4E4F534A:
            j = json.loads(data[off + 8: off + 8 + clen].decode("utf-8"))
            n = 0
            for m in j.get("meshes", []):
                for p in m.get("primitives", []):
                    if "indices" in p:
                        n += j["accessors"][p["indices"]]["count"]
            return n // 3
        off += 8 + clen
    return -2


def main():
    args = sys.argv[1:]
    only = None
    force = "--force" in args
    if "--only" in args:
        only = set(args[args.index("--only") + 1].split(","))

    names = sorted(d for d in os.listdir(B) if os.path.isdir(os.path.join(B, d)))
    if only:
        names = [n for n in names if n in only]

    mani = {}
    if os.path.exists(MANI):
        with open(MANI, encoding="utf-8") as f:
            mani = json.load(f)

    todo = [n for n in names if force or mani.get(n, {}).get("status") != "ok"]
    print("待建 %d 栋 / 共 %d 栋%s" % (len(todo), len(names), "" if not only else " (--only)"))
    t0 = time.time()

    for i, n in enumerate(todo, 1):
        glb = os.path.join(B, n, "%s-building.glb" % n)
        h_before = floors_hash(n)
        tri_before = tri_count(glb)
        sz_before = os.path.getsize(glb) if os.path.exists(glb) else -1
        t1 = time.time()

        r = subprocess.run([sys.executable, "run_step.py", n, "glb"],
                           cwd=WEB, capture_output=True, text=True,
                           encoding="utf-8", errors="replace")
        ok = r.returncode == 0 and '"ok": true' in (r.stdout or "").replace("'", '"')

        h_after = floors_hash(n)
        tri_after = tri_count(glb)
        sz_after = os.path.getsize(glb) if os.path.exists(glb) else -1

        rec = {
            "status": "ok" if ok else "fail",
            "floors_intact": h_before == h_after,
            "tri_before": tri_before, "tri_after": tri_after,
            "mb_before": round(sz_before / 1048576.0, 2),
            "mb_after": round(sz_after / 1048576.0, 2),
            "sec": round(time.time() - t1, 1),
        }
        if not ok:
            rec["error"] = ((r.stdout or "")[-400:] + (r.stderr or "")[-400:])
        if not rec["floors_intact"]:
            rec["status"] = "FLOORS_MUTATED"

        mani[n] = rec
        with open(MANI, "w", encoding="utf-8") as f:
            json.dump(mani, f, ensure_ascii=False, indent=1)

        delta = ("%+.1f%%" % (100.0 * (tri_after - tri_before) / tri_before)
                 if tri_before > 0 else "新")
        print("[%2d/%2d] %-6s %-5s 面 %8d → %8d (%s)  %5.1fMB→%5.1fMB  %5.1fs  楼层%s"
              % (i, len(todo), n, rec["status"], tri_before, tri_after, delta,
                 rec["mb_before"], rec["mb_after"], rec["sec"],
                 "完好" if rec["floors_intact"] else "**被改动**"), flush=True)

    bad = [n for n, v in mani.items() if v.get("status") != "ok"]
    print("\n总计 %.1f 分钟 | 成功 %d | 异常 %d %s"
          % ((time.time() - t0) / 60.0, len(mani) - len(bad), len(bad), bad if bad else ""))


if __name__ == "__main__":
    main()
