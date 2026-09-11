# -*- coding: utf-8 -*-
"""把某层的交付 outline 复制成另一层的(只读 dry-run 优先)。

场景: 某层墙已做过「整层移植」(如 c043 层0 移植了层1 的墙), 但轮廓没跟着换,
于是墙压在旧轮廓的缺口上 → 「轮廓外的墙面积」虚高。

floors/*.json 是紧凑 JSON(无缩进无换行), json.dumps(ensure_ascii=False) 可逐字节复现,
所以回写是安全的: 只改 outline 一处, 其余键值字节不变。

用法:
  python _patch_outline_copy.py c043 1 0            # dry-run, 只报差异
  python _patch_outline_copy.py c043 1 0 --apply    # 备份后写入
"""
import io, os, json, sys, shutil, hashlib, time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = r"D:\gym3d\data\buildings"

name, src, dst = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
apply_ = "--apply" in sys.argv

p_src = os.path.join(ROOT, name, "floors", "floor%d.json" % src)
p_dst = os.path.join(ROOT, name, "floors", "floor%d.json" % dst)
fl_s = json.load(io.open(p_src, encoding="utf-8"))
raw_d = io.open(p_dst, encoding="utf-8", newline="").read()
fl_d = json.loads(raw_d)

o_s, o_d = fl_s["outline"], fl_d["outline"]
print("== %s  floor%d -> floor%d ==" % (name, src, dst))
print("   源轮廓 %d 顶点, 目标原轮廓 %d 顶点" % (len(o_s), len(o_d)))
print("   目标墙 %d 条, 与原轮廓 md5 %s"
      % (len(fl_d["walls"]), hashlib.md5(json.dumps(o_d).encode()).hexdigest()[:8]))
if len(o_s) == len(o_d) and o_s == o_d:
    print("   两层轮廓已相同, 无需修改")
    sys.exit(0)

fl_d["outline"] = o_s
new = json.dumps(fl_d, ensure_ascii=False)

# 校验: 除 outline 外必须字节等价
chk = dict(fl_d)
chk["outline"] = o_d
assert json.dumps(chk, ensure_ascii=False) == raw_d, "非 outline 部分被改动了, 中止"
# 校验: 新文本重新解析后 walls 一致
assert json.loads(new)["walls"] == fl_d["walls"], "walls 被改动了, 中止"

print("   写入后: 目标轮廓 %d 顶点; 文本长度 %d -> %d" % (len(o_s), len(raw_d), len(new)))
if not apply_:
    print("   [dry-run] 未写入(加 --apply 生效)")
    sys.exit(0)

bk = p_dst + ".orig_" + time.strftime("%Y%m%d_%H%M%S")
shutil.copy2(p_dst, bk)
io.open(p_dst, "w", encoding="utf-8", newline="").write(new)
print("   已写入; 备份 %s" % bk)
