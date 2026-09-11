# -*- coding: utf-8 -*-
"""批量渲染 11 栋教学楼立面图库：每栋 front/side/top/iso 四视图。

补「DXF 只有平面图、无立面图」的缺口：为每栋楼生成正立面/侧立面/顶视/轴测
四张参考图，存 data/buildings/<name>/images/，并写 images.json 索引清单。

用法:
  python blender/render_all.py                 # 全部 11 栋
  python blender/render_all.py c006 c009       # 指定若干栋
"""
import json
import os
import subprocess
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

BLENDER = r"C:\Program Files\Blender Foundation\Blender 5.2\blender.exe"
RENDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "render_views.py")
ROOT = r"D:\gym3d"
VIEWS = ["front", "side", "top", "iso"]
MANIFEST = os.path.join(ROOT, "data", "buildings", "images.json")


def building_names():
    index = json.load(open(os.path.join(ROOT, "data", "buildings", "index.json"), encoding="utf-8"))
    return [b["name"] for b in index if b["dir"].startswith("data/buildings/")]


def render_one(name, glb, outdir):
    imgs = {}
    for view in VIEWS:
        out = os.path.join(outdir, f"{name}-{view}.png")
        if os.path.exists(out):
            imgs[view] = out
            print(f"[{name}] {view} 已存在，跳过", flush=True)
            continue
        cmd = [BLENDER, "-b", "-P", RENDER, "--",
               "--glb", glb, "--out", out, "--view", view, "--res", "1920x1080"]
        print(f"[{name}] 渲染 {view} ...", flush=True)
        r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
        if r.returncode != 0 or not os.path.exists(out):
            print(f"  ✗ {view} 失败: {(r.stderr or '')[-400:]}", flush=True)
            continue
        imgs[view] = out
        print(f"  ✓ {view} -> {out}", flush=True)
    return imgs


def main():
    names = [a for a in sys.argv[1:] if not a.startswith("-")] or building_names()
    # 增量：已有清单里的成功项直接沿用
    manifest = []
    if os.path.exists(MANIFEST):
        try:
            manifest = json.load(open(MANIFEST, encoding="utf-8"))
        except Exception:
            manifest = []
    done = {m["name"]: m for m in manifest}

    for name in names:
        glb = os.path.join(ROOT, "data", "buildings", name, f"{name}-building.glb")
        if not os.path.exists(glb):
            print(f"跳过 {name}（无 GLB）", flush=True)
            continue
        outdir = os.path.join(ROOT, "data", "buildings", name, "images")
        os.makedirs(outdir, exist_ok=True)
        imgs = render_one(name, glb, outdir)
        entry = {"name": name, "glb": glb, "images": imgs}
        if name in done:
            done[name]["images"].update(imgs)
            done[name]["glb"] = glb
        else:
            done[name] = entry
    json.dump(list(done.values()), open(MANIFEST, "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print(f"\n已写索引 {MANIFEST}，共 {len(done)} 栋")


if __name__ == "__main__":
    main()
