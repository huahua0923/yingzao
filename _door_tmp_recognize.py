# -*- coding: utf-8 -*-
r"""门洞的前置产物：把「新门判据」重新识别一遍，落到临时目录 `_tmp_<名>_door`。

这一环原来是缺的
----------------
交付链 = `recognize()` → `_wall_thin_force.py`（从 DXF 重新配对生成**真内墙**）。
后者不认识门 ⇒ **内墙上的门洞被冲掉**；而 `recognize()` 自己产的内墙是「粗环 blob」
不可用（覆盖率>20%）。所以门洞只能是**外科式补丁**：门与门洞盒取自一次 recognize，
墙在**交付层上**就地挖洞。`_door_punch_apply.py`（公共流程 stage 8）就是这个补丁，
它读 `_tmp_<名>_door/floor*.json` 里的 `doors` 与门洞盒。

**产出这个目录的一步，此前不在公共流程里** —— 脚本被 2026-09-14 的大扫除归档进
`_scratch/legacy/2026-09-14-cleanup/`，于是 92 栋的门洞**自那时起一次都没打过**
（实测全库 `_tmp_*_door` 计数 = 0）。本文件把这一环补回流程。

安全（三条守卫，都不是装饰）
--------------------------
1. **只写临时目录**：`out_dir` 被指向 `_tmp_<名>_door`，写前有断言守着。
   `recognize()` 会先把 `out_dir` 里**所有旧文件删光**再写 —— 指错一个字节就是删交付层。
2. **不碰 `rooms.json`**：已核 `recognize()` 全文，它只写 `out_dir/floor*.json`
   与 `dirname(out_dir)/spec.json`，从不写 rooms。
3. **仓库根的 `spec.json` 按原样还原**：`dirname(out_dir)` 是仓库根，recognize 会
   往那里写一份 spec（它属于 `data/buildings/<名>/`，不是仓库根）。跑完还原/清掉。

为什么**每次都要重出**、不许复用旧目录
------------------------------------
旧目录可能来自旧版识别链 ⇒ 拿它去挖洞 = 用旧门去改新墙。判据（写在
`ensure()` 里）：临时产物缺失，或它的 `floor0.json` 比交付的 `floors/floor0.json`
更旧 ⇒ 重出。跑在公共流程里时，stage 1 刚写过 floors ⇒ 必然重出。

用法: python _door_tmp_recognize.py <名>
"""
import os
import shutil
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = r"D:\gym3d"


def tmp_dir(name):
    """临时产物目录。**只此一处定义**，`_door_punch_apply.py` 从这里取，不许各写一份。"""
    return os.path.join(ROOT, "_tmp_%s_door" % name)


def is_fresh(name):
    """临时产物在不在、而且不比交付层旧。"""
    t = tmp_dir(name)
    tf = os.path.join(t, "floor0.json")
    df = os.path.join(ROOT, "data", "buildings", name, "floors", "floor0.json")
    if not os.path.exists(tf):
        return False
    if not os.path.exists(df):
        return True
    return os.path.getmtime(tf) >= os.path.getmtime(df)


def build(name):
    """重识别到临时目录。返回 0 成功 / 1 失败。"""
    tmp = tmp_dir(name)
    if ROOT not in sys.path:
        sys.path[:0] = [ROOT, os.path.join(ROOT, "backend")]
    from run_building import load_profile

    p = load_profile(name)
    old_out = p.out_dir
    shutil.rmtree(tmp, ignore_errors=True)
    os.makedirs(tmp, exist_ok=True)
    p.out_dir = tmp
    # ★ 守卫：写错一个字节，recognize() 就会把交付层删光重写（它先清空 out_dir）。
    if os.path.abspath(p.out_dir) != os.path.abspath(tmp):
        print("[door-tmp] ★ 守卫不过：out_dir=%s 必须是 %s" % (p.out_dir, tmp))
        return 1
    print("[door-tmp] %s  out_dir %s -> %s" % (name, old_out, tmp))

    spec = os.path.join(ROOT, "spec.json")
    spec_before = open(spec, "rb").read() if os.path.exists(spec) else None

    t0 = time.time()
    from backend.recognizer.recognize import recognize
    floors = recognize(p)
    dt = time.time() - t0

    # 还原 recognize 顺手落在仓库根的那份 spec（它不是交付件）
    if spec_before is None:
        if os.path.exists(spec):
            os.remove(spec)
            print("[door-tmp] 已清掉落到仓库根的 spec.json（还原到「原本没有」）")
    elif open(spec, "rb").read() != spec_before:
        open(spec, "wb").write(spec_before)
        print("[door-tmp] 已还原仓库根的 spec.json")

    nd = 0
    nf = 0
    for f in sorted(os.listdir(tmp)):
        if f.startswith("floor") and f.endswith(".json"):
            import json
            nf += 1
            nd += len(json.load(open(os.path.join(tmp, f), encoding="utf-8")).get("doors") or [])
    print("[door-tmp] %s 识别 %d 层 / 门 %d 扇 -> %s  (%.1fs)" % (name, len(floors), nd, tmp, dt))
    if nf == 0:
        print("[door-tmp] ★ 临时目录里一层都没有 ⇒ 前置失败")
        return 1
    return 0


def ensure(name):
    """给 `_door_punch_apply.py` 用：需要时才产出，并说清是「复用」还是「重出」。"""
    if is_fresh(name):
        print("[door-tmp] 复用现成的临时产物 %s（不比交付层旧）" % tmp_dir(name))
        return 0
    print("[door-tmp] 临时产物缺失或比交付层旧 ⇒ 重出")
    return build(name)


def main():
    if len(sys.argv) < 2:
        sys.exit("用法: python _door_tmp_recognize.py <名>")
    sys.exit(build(sys.argv[1]))


if __name__ == "__main__":
    main()
