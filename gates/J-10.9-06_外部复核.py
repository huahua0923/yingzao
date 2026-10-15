# -*- coding: utf-8 -*-
r"""判据 J-10.9-06：成品件由**别的软件**独立量一遍，读数落到本仓模型库的期望值上；
并且「我们对尺子说的话」当场验真伪。

★ 为什么要这条（用户原话：「你不能老是自证，你自证要有依据，要有判据，要有模型库，要有标准」）：
  本仓二十多条判据里绝大多数是**自己量自己** —— 几何是 Python 生成的，判据也是 Python 写的，
  同一个约定错了两边一起错，**全绿也证明不了件是对的**（铁律 137/192）。本闸是第一条
  「读数出自别家软件」的判据。

★★ 三把尺子读**同一份 .obj**（铁律 174/196）：
  先前试过「Blender 读 OBJ、three.js 读 GLB」——那是**换主语**：两个件的三角化方式天生不同，
  `n_tri` 不一样是正常的，拿它互证等于什么都没证。现在三把都读 OBJ。

★★★ 坐标系必须各报各的，再换算后比：
  实测（2026-10-15）好件三把尺子读数 `size`：
    · 文本      [129300,  45000,  84000]   原样（文件轴，高在 **Y**）
    · three.js  [129300,  45000,  84000]   原样（OBJLoader 不换算）
    · Blender   [129300,  84000,  45000]   **导入自带 Y-up→Z-up** ⇒ 报的是 (fx, fz, fy)
  不换算直接比大小，会把「同一个件」判成「对不上」。所以换算写在 `to_frame()` 里，
  并且**只对 Blender 做**（它是唯一会动的那个）——换算规则由好件实测反推，不照抄文档。

判据
 ① **件没漂**：每件 sha256 与 `件.json` 记录一致。
 ② **尺寸对得上**：每件、每把尺子的 `size` 与「本件期望值经该尺子轴换算」一致（相对 <1e-6）。
 ③ **计数对得上**：文本 `n_v/n_f/n_g`、three `n_mesh` 与期望**完全相等**；
    Blender `n_vert` 与期望比，**但当本件是「丢面的件」时不断言**（丢面后 Blender 会不会
    连同失去引用的顶点一起丢掉，取决于它的导入器实现，我没量过就不许写进判据）。
 ④ **断言表验真伪**（★ 反自证的核心）：每件声明「某量具的某字段应当**变**/应当**不变**」，
    闸当场把坏件读数与好件读数比，**声明与实测不符即红**。
    —— 我要是写「包围盒抓不到这一件」而它其实动了，这条就红；反之亦然。

量具
 `rebuild/模型库/件.json`（模型库清单，程序生成）；`rebuild/模型库/obj_text_metrics.py`（文本尺子）；
 `rebuild/_scratch/probe_blender_metrics.py`（Blender）；`rebuild/_scratch/probe_three_obj.mjs`（three.js）。
 三把尺子都起**独立进程**跑（不共享内存 ⇒ 一把崩了不许把别人的读数带绿）。

量具盲区（★先声明，再判）
 · ① 只量**包围盒 + 计数**。件里面「墙对不对、门开在哪」本闸一概看不见 —— 那是
   `J-09.2-A1*` / `J-10.9-01/02/03` 的活。
 · ② Blender 的 OBJ 导入自带 Y-up→Z-up ⇒ **它对「把高度轴换到水平」这型缺陷的读数会跟着换回去**。
   这条不是推断：`坏_高度轴横过来` 那行的 Blender 读数会当场印出来。
 · ③ 本闸不比**体积/非流形边**：Blender 会报，但另两把量不到，比不了的就是不能比。
 · ④ 「没量到」与「量出来不对」分开：工具不在 ⇒ rc=4，不是 rc=1（铁律 199）。

正对照（喂坏输入，必须**因该因**而红；铁律 137）
 P1 好件                       —— 基线，三把尺子互不矛盾
 P2 坏_放大25.4倍              —— ② 红（尺寸 ×25.4）
 P3 坏_高度轴横过来            —— ② 红（高度 45000 落到别的分量）
 P4 坏_没有门头墙              —— ★ ② **不红**（尺寸一字不变）、③ 红（组/面数掉）
                                 —— 这条就是「不是一把尺子刷三遍」的证明
 P5 `--bad-sha` 把某件 sha256 判错 —— ① 红
 P6 blender 路径指到不存在处   —— rc=4 SKIP

三态：rc=0 PASS ／ rc=1 FAIL ／ rc=4 SKIP（Blender 或 node 不在、模型库不在）
"""
import hashlib
import io
import json
import os
import subprocess
import sys
import time

# ★★ 控制台是 GBK（cp936），而本文件要印「⇒ / → / ✗」这类符号 —— `⇒`(U+21D2) **不在 GBK 里**。
#   2026-10-15 正对照 P6 当场踩到：SKIP 那句一印就抛 UnicodeEncodeError，
#   退出码从 4（没量到）变成 1（真差）—— **正好就是铁律 199 那个形状，长在本闸自己身上**。
#   修法：把自己的 stdout/stderr 明说成 UTF-8，编不出的字符退化成 `?` 而不是抛异常。
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
LIB = os.path.join(ROOT, "rebuild", "模型库")
MANIFEST = os.path.join(LIB, "件.json")
REPORT = os.path.join(LIB, "复核.json")
TEXT_GAUGE = os.path.join(LIB, "obj_text_metrics.py")
BLENDER_PROBE = os.path.join(ROOT, "rebuild", "_scratch", "probe_blender_metrics.py")
THREE_PROBE = os.path.join(ROOT, "rebuild", "_scratch", "probe_three_obj.mjs")

BLENDER = os.environ.get(
    "CDUT3D_BLENDER", "C:/Program Files/Blender Foundation/Blender 5.2/blender.exe")
NODE = os.environ.get("CDUT3D_NODE", "C:/Program Files/nodejs/node.exe")
TOL_REL = 1e-6


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for blk in iter(lambda: f.read(1 << 20), b""):
            h.update(blk)
    return h.hexdigest()


def run(cmd, timeout=1200):
    try:
        p = subprocess.run(cmd, capture_output=True, timeout=timeout)
    except FileNotFoundError as e:
        return 127, "", str(e)
    return p.returncode, p.stdout.decode("utf-8", "replace"), p.stderr.decode("utf-8", "replace")


def grab(prefix, out):
    for line in out.splitlines():
        if line.startswith(prefix):
            return json.loads(line[len(prefix):])
    return None


def to_frame(gauge, size):
    """把「文件里的 size」换算成该量具自己那一套轴。只对 Blender 动（换算规则见文件头）。

    这是 (1,2) 位置换，自逆 ⇒ 期望值和实测值用同一个函数换，方向自然对。
    """
    if gauge == "blender":
        return [size[0], size[2], size[1]]
    return [size[0], size[1], size[2]]


def close(a, b, rel=TOL_REL):
    if a is None or b is None or len(a) != len(b):
        return False
    return all(x is not None and y is not None and abs(x - y) <= rel * max(1.0, abs(y))
               for x, y in zip(a, b))


def measure(path):
    """三把尺子各起一个进程，量同一份文件。返回 (读数dict, 说明)。"""
    got, notes = {}, {}
    rc, out, _ = run([sys.executable, "-I", TEXT_GAUGE, path])
    got["文本"], notes["文本"] = grab("OBJTEXT ", out), "rc=%d" % rc
    rc, out, _ = run([BLENDER, "-b", "--factory-startup", "--python", BLENDER_PROBE, "--", path])
    got["blender"], notes["blender"] = grab("PROBE_JSON ", out), "rc=%d" % rc
    rc, out, _ = run([NODE, THREE_PROBE, path])
    got["three"], notes["three"] = grab("PROBE_JSON ", out), "rc=%d" % rc
    return got, notes


def moved(a, b):
    """两个读数算不算「动了」：list 用相对容差，标量用相等；有一个是 None ⇒ 不知道。"""
    if a is None or b is None:
        return None
    if isinstance(a, list):
        return not close(a, b)
    return a != b


def check_assertions(entry, got, ref):
    """④ 断言表：把坏件与好件比，声明「变/不变」必须与实测相符。"""
    out = []
    for key, claim in sorted((entry.get("断言") or {}).items()):
        g, field = key.split(".", 1)
        if field == "size":
            a, b = to_frame(g, got[g]["size"]), to_frame(g, ref[g]["size"])
        else:
            a, b = got[g].get(field), ref[g].get(field)
        m = moved(a, b)
        ok = (m is not None) and (("变" if m else "不变") == claim)
        out.append({"键": "断言·" + key, "声明": claim,
                    "实测": None if m is None else ("变" if m else "不变"), "对": ok})
    return out


def main(argv):
    bad_sha = "--bad-sha" in argv          # 正对照 P5

    if not os.path.exists(MANIFEST):
        print("SKIP：模型库不在 %s（先跑 python rebuild/模型库/make_lib.py）" % MANIFEST)
        return 4
    for tool in (BLENDER, NODE):
        if not os.path.exists(tool):
            print("SKIP：本机没有 %s ⇒ 这一条**没量到**（不是回归）" % tool)
            return 4

    with io.open(MANIFEST, encoding="utf-8") as f:
        man = json.load(f)
    good_entry = man["件"][0]

    bad = 0
    rows = []
    ref = None
    versions = {}

    for entry in man["件"]:
        path = os.path.join(ROOT, entry["path"])
        if not os.path.exists(path):
            print("FAIL %s：文件不在 %s" % (entry["名"], path))
            bad += 1
            continue

        got, notes = measure(path)
        if any(got[k] is None for k in ("文本", "blender", "three")):
            print("FAIL %s：三把尺子有一把没吐出读数（%s）—— 也许是件坏了，也许是探针坏了，"
                  "这里**不猜**" % (entry["名"], notes))
            bad += 1
            continue
        if ref is None:
            ref = got
            versions = {"blender": got["blender"].get("ver"), "three": got["three"].get("three")}

        sid = sha256(path)
        declared_sha = entry["sha256"]
        if bad_sha and entry["名"] == "坏_放大25.4倍":
            # 正对照 P5：改的是**声明值**（换一个字符），不是把判词直接写成 False ——
            # 否则红行上「声明」与「实测」会印成同一个串，看着像判据自己错了（铁律 174 那一类）。
            # ★★ 2026-10-15 第二版：第一版改的是**末位**（第 63 位），而判词只印**前 12 位**
            #    ⇒ 改的那个字符落在印不出来的窗口外，红行照旧印成「声明=X 实测=X」，
            #    读起来像判据坏了。P5 当场就是这么红的：`✗ sha256 声明=f2ad91e984cb 实测=f2ad91e984cb`。
            #    规矩：**正对照改动的那个量，必须落在判词会印出来的窗口里**（铁律 158 那一类）。
            #    所以改第 1 位 —— 它一定在 [:12] 窗口内，红行上两个串必然不同。
            declared_sha = ("0" if declared_sha[0] != "0" else "1") + declared_sha[1:]
        sha_ok = (sid == declared_sha)
        checks = [{"键": "sha256", "声明": declared_sha[:12], "实测": sid[:12], "对": sha_ok}]

        # ② 尺寸（按量具各自的轴换算后再比）
        for g in ("文本", "blender", "three"):
            exp = to_frame(g, entry["期望"]["size"])
            act = got[g]["size"]
            checks.append({"键": "%s.size" % g, "声明": exp, "实测": act, "对": close(act, exp)})

        # ③ 计数
        exp_nv, exp_nf, exp_ng = entry["期望"]["n_v"], entry["期望"]["n_f"], entry["期望"]["n_g"]
        t = got["文本"]
        for k, exp, act in (("文本.n_v", exp_nv, t["n_v"]), ("文本.n_f", exp_nf, t["n_f"]),
                            ("文本.n_g", exp_ng, t["n_g"]),
                            ("three.n_mesh", exp_ng, got["three"]["n_mesh"])):
            checks.append({"键": k, "声明": exp, "实测": act, "对": act == exp})
        if exp_nf == good_entry["期望"]["n_f"]:
            checks.append({"键": "blender.n_vert", "声明": exp_nv,
                           "实测": got["blender"]["n_vert"], "对": got["blender"]["n_vert"] == exp_nv})
        else:
            checks.append({"键": "blender.n_vert", "声明": "未声明",
                           "实测": got["blender"]["n_vert"], "对": None,
                           "注": "本件丢了面；Blender 会不会连失去引用的顶点一起丢，"
                                 "我没量过就不写进判据"})

        # ④ 断言表
        checks += check_assertions(entry, got, ref)

        bad_here = [c for c in checks if c["对"] is False]
        bad += len(bad_here)
        rows.append({"件": entry["名"], "路径": entry["path"], "sha256": sid[:12],
                     "文本": got["文本"], "blender": got["blender"], "three": got["three"],
                     "检查": checks, "结论": "OK" if not bad_here else ("红 %d 条" % len(bad_here))})
        print("%-18s %-4s 文本=%s | blender=%s | three=%s" % (
            entry["名"], "OK" if not bad_here else "红",
            t["size"], got["blender"]["size"], got["three"]["size"]))
        for c in bad_here:
            print("        ✗ %s 声明=%s 实测=%s" % (c["键"], c["声明"], c["实测"]))

    report = {
        "时刻": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "件_json_生成时刻": man.get("生成时刻"),
        "尺子": {
            "文本": {"算法": "只按行首读 OBJ（v/f/g），不 import 任何三维库", "轴": "原样（高在 Y）"},
            "blender": {"版本": versions.get("blender"), "轴": "报 (fx, fz, fy)：导入自带 Y-up→Z-up"},
            "three": {"版本": versions.get("three"), "轴": "原样（OBJLoader 不换算）"},
        },
        "容差": man.get("容差"),
        "行": rows,
        "结论": {"红条数": bad, "rc": 0 if bad == 0 else 1},
    }
    with io.open(REPORT, "w", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(report, ensure_ascii=False, indent=1))

    print("\n尺子版本：Blender %s / three r%s" % (versions.get("blender"), versions.get("three")))
    print("报告 → %s" % REPORT)
    print("结论：" + ("全绿：%d 件、三把尺子、断言表逐条相符" % len(rows) if bad == 0
                    else "有 %d 条不符" % bad))
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
