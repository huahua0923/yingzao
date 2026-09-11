# -*- coding: utf-8 -*-
"""把已薄墙化的楼层也按「踏步剔除版」rebuild_floor 重新生成（绕过 is_blob 门槛）。

_wall_thin_batch 只重建 blob 层；已薄墙化的楼层仍保留旧版 pair_wall_faces 配出的
楼梯踏步假墙（0.3m×1.58m，用户「楼梯识别成内墙」）。本脚本对指定楼每一层都强制重跑
rebuild_floor + verify_floor（门槛同批次），通过才写盘，失败该层保留原状并回报。

用法: python _wall_thin_force.py <name> [<name> ...]
"""
import json, glob, os, sys, shutil
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path[:0] = [r"D:\gym3d", r"D:\gym3d\backend", r"D:\gym3d\backend\web"]
import ezdxf
import _wall_thin_batch as B

ROOT = r"D:\gym3d\data\buildings"


def run(name):
    d = os.path.join(ROOT, name)
    fd = os.path.join(d, "floors")
    if not os.path.isdir(fd):
        return name, "NO_FLOORS", []
    bak = os.path.join(d, ".orig", "floors.before_force_stairtread")
    try:
        p = B.load_profile(name)
        doc = ezdxf.readfile(p.dxf)
        msp = doc.modelspace()
        walls_dxf, doors, stairs, cols = B.classify.classify(msp, p)
    except Exception as e:  # noqa: BLE001
        return name, "DXF_FAIL %s" % str(e)[:80], []
    raw_by_floor = B.wall_lines_by_floor(p, walls_dxf)

    changed, failed, skip = [], [], []
    for fp in sorted(glob.glob(os.path.join(fd, "floor*.json"))):
        F = int(os.path.basename(fp)[5:-5])
        fl = json.load(open(fp, encoding="utf-8"))
        ol = __import__("shapely.geometry", fromlist=["Polygon"]).Polygon(fl["outline"])
        if not ol.is_valid or ol.area < 1:
            skip.append((F, "no-outline"))
            continue
        try:
            inner_walls, rect_share = B.rebuild_floor(fl, p, raw_by_floor.get(F, []), F)
        except Exception as e:  # noqa: BLE001
            failed.append((F, "except:%s" % str(e)[:60]))
            continue
        if inner_walls is None:
            failed.append((F, "no-wall"))
            continue
        ok, nw, cover, big, dgood, ovm = B.verify_floor(fl, inner_walls, ol, ol.area)
        if not (ok and rect_share >= 0.30):
            failed.append((F, "nw=%d cov=%.0f%% big=%d door=%.0f%% ov=%.1f%% rect=%.0f%%"
                           % (nw, cover, big, dgood, ovm, 100 * rect_share)))
            continue
        os.makedirs(bak, exist_ok=True)
        if not os.path.exists(os.path.join(bak, os.path.basename(fp))):
            shutil.copy2(fp, os.path.join(bak, os.path.basename(fp)))
        keep = [w for w in fl["walls"] if w["type"] != "inner"]
        fl["walls"] = keep + inner_walls
        json.dump(fl, open(fp, "w", encoding="utf-8"), ensure_ascii=False)
        changed.append((F, nw))
    return name, ("OK changed=%d fail=%d skip=%d" % (len(changed), len(failed), len(skip))
                  if changed or failed else "NO_CHANGE"), changed, failed


if __name__ == "__main__":
    for nm in sys.argv[1:]:
        nm = nm.strip()
        res = run(nm)
        name, status = res[0], res[1]
        print("%-6s %s" % (name, status), flush=True)
        if len(res) > 3 and res[3]:
            print("        FAIL floors: %s" % res[3][:5], flush=True)
