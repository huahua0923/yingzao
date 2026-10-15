# -*- coding: utf-8 -*-
r"""参照件快回路：只跑 `build3d.py` + `J-10.8-01`，**不碰 SU / glb / 包**。

为什么要有它（2026-10-15；用户原话「完善感觉很慢」）：
  改一处几何语义（例如栏杆归层），现在要看见效果得**整条链重跑**：
  build3d → export_contours → SU 无人值守 → su_obj_to_glb → render3d → mk_catalog → build_pack。
  但「语义对不对」这件事，**参照件 `rebuild/05_build/` + 判据 `J-10.8-01` 就答得了** ——
  SU 那一段只是把同一批闭合轮廓按层高拉伸成实体（见 `rebuild/06_su/su_step2_build.rb`
  头注第 16–25 行：「洞现在在 Python 侧就切掉了 … SU 的三条抠洞路全实测、全不通」），
  **它不引入新语义**。

★ 代价（铁律 28：处置是个决定，决定完把代价写在旁边）：
  跑完这一趟，`rebuild/06_su/` 那半条链**与 `05_build` 不再同趟** ⇒
  **定稿仍必须跑全链**，否则 `J-10.8-02` 量的是旧件。这是快回路的代价，不是它的错。

用法：
  python rebuild/tools/ref_loop.py
"""
import os
import subprocess
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
ROOT = r"D:\项目\cdut3d"
STEPS = [
    ("build3d（出参照件 05_build）", os.path.join(ROOT, "rebuild", "tools", "build3d.py")),
    ("J-10.8-01（量参照件）", os.path.join(ROOT, "gates", "J-10.8-01_build3d.py")),
]

print("参照件快回路 —— 只跑参照件那半条链（不碰 SU / glb / 包）")
print("-" * 70)
t_all = time.time()
rcs = []
for name, path in STEPS:
    t0 = time.time()
    # ★ 与 run_gates.py 同一套环境（判据里的中文/希腊字母在 cp936 控制台上会炸在
    #   print 上，那种炸是**量具**的错、不是被测件的错）。
    env = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    r = subprocess.run([sys.executable, path], cwd=ROOT, env=env, capture_output=True)
    secs = time.time() - t0
    rcs.append(r.returncode)
    txt = (r.stdout.decode("utf-8", "replace") + r.stderr.decode("utf-8", "replace"))
    # 只印末尾几行：回路工具要的是 rc 与耗时，不要整屏 stdout（要看全部就单跑那一步）
    tail = [ln for ln in txt.strip().splitlines() if ln.strip()][-6:]
    print("rc=%-3d %6.1fs  %s" % (r.returncode, secs, name))
    for ln in tail:
        print("      | " + ln)
print("-" * 70)
print("回路共 %.1fs ｜ rc=%s" % (time.time() - t_all, rcs))
print("★ 这一趟只保证「参照件那半条链」。定稿仍要跑全链："
      "export_contours → SU 无人值守 → su_obj_to_glb → render3d → mk_catalog → build_pack。")
sys.exit(0 if all(rc == 0 for rc in rcs) else 1)
