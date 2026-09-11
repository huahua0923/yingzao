# -*- coding: utf-8 -*-
"""并排对比渲染：每层「源图纸(A·真值) vs 第一轮识别叠加(B)」。

B = 复用第一轮画法(_dxf_png_batch.render_floor_png：灰实=识别墙/红=门/绿=楼梯井/蓝=柱，
    灰细线=该层源墙线垫底)——当时用户嫌它碎/断，正是要拿来对照真值找识别问题。
输出（本脚本**只拥有后两项**）:
  data/buildings/<name>/compare.html                  每层 A|B 并排对比页
  data/buildings/_dxf_compare.html                    全部楼对比总目录
  data/buildings/<name>/dxf_plan_recog/floor{F}.png   ← 所有者是 _dxf_png_batch.py；
      本脚本仅在缺失或比 floor JSON 旧时重画（复用同一 render_floor_png），不反复互写。
用法: python -u _dxf_compare_render.py [<name> ...]
"""
import os, sys, json, glob, re
sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
sys.path[:0] = [r"D:\gym3d\backend\web", r"D:\gym3d\backend\vision",
                r"D:\gym3d\backend", r"D:\gym3d"]
import _dxf_png_batch as V1   # 第一轮画法复用

BASE = r"D:\gym3d\data\buildings"


def _cn_from_dxf(p):
    base = os.path.splitext(os.path.basename(p.dxf))[0]
    return re.sub(r"^[A-Za-z]+\d+[-_ ]*", "", base).strip(" -_") or base


def _compare_html(name, cn, floors, stats):
    disp = f"{name} · {cn}" if cn else name
    rows = []
    for F in floors:
        st = stats.get(F, {})
        cap = (f"{disp} · {F+1}层　门 {st.get('doors', '?')} · "
               f"楼梯井 {st.get('stairs', '?')} · 房间 {st.get('rooms', '?')} · "
               f"面积 {st.get('area', '?')}㎡")
        rows.append(
            f'<figure class=cmp><div class=pair>'
            f'<div class=side><span class=tag>源图纸 A</span>'
            f'<img loading="lazy" src="dxf_plan/floor{F}.png" alt="{name} F{F} 源图纸"></div>'
            f'<div class=side><span class=tag>第一轮识别 B</span>'
            f'<img loading="lazy" src="dxf_plan_recog/floor{F}.png" alt="{name} F{F} 识别"></div>'
            f'</div><figcaption>{cap}</figcaption></figure>')
    return ("<!DOCTYPE html><html lang=zh><head><meta charset=utf-8>"
            f"<title>{disp} 源图 vs 识别</title><style>"
            "body{font-family:sans-serif;background:#eef0f3;margin:0;padding:16px}"
            "h1{font-size:17px;color:#222;margin:4px 0 6px}"
            "p.leg{font-size:12px;color:#555;margin:0 0 12px}"
            "a{color:#0366d6;text-decoration:none}"
            "figure.cmp{display:block;background:#fff;border:1px solid #d4d8dd;"
            "border-radius:6px;padding:10px;margin:0 0 16px}"
            "div.pair{display:grid;grid-template-columns:1fr 1fr;gap:10px}"
            "div.side{position:relative}"
            "span.tag{position:absolute;top:6px;left:6px;z-index:2;background:rgba(255,255,255,.92);"
            "color:#222;font:600 11px/1 sans-serif;padding:2px 7px;border-radius:4px;"
            "border:1px solid #c9ced6}"
            "img{width:100%;height:auto;border:1px solid #e0e3e7}"
            "figcaption{font-size:12px;color:#333;margin-top:6px}"
            "@media(max-width:900px){div.pair{grid-template-columns:1fr}}"
            "</style></head><body>"
            f"<h1>{disp} · 逐层对照：源图纸(真值) vs 第一轮识别</h1>"
            f"<p class=leg>左 A = 忠实源 CAD 线稿；右 B = 第一轮识别叠加 "
            f"(灰实心=识别墙 / 红=门 / 绿块=楼梯井 / 蓝=柱 / 灰细线=源墙垫底)。"
            f"同一层并排看：B 缺元素=识别漏、B 墙碎或连成块=墙识别错。"
            f"标题带 门/楼梯井/房间/面积 计数可对照。</p>"
            f"<p><a href=\"../_dxf_compare.html\">← 全部楼对比目录</a>　"
            f"<a href=\"dxf_plan/index.html\">单看源图纸页</a></p>"
            + "".join(rows) + "</body></html>")


def _master_html(items):
    lis = "".join(f'<li><a href="{n}/compare.html">{n} {cn}</a>'
                  f' <small>{cnt}层</small></li>' for n, cn, cnt in items)
    return ("<!DOCTYPE html><html lang=zh><head><meta charset=utf-8>"
            "<title>全部楼 源图 vs 识别</title><style>"
            "body{font-family:sans-serif;background:#eef0f3;padding:18px}"
            "h1{font-size:19px;color:#222}p{font-size:12px;color:#555}"
            "a{color:#0366d6;text-decoration:none}li{margin:5px 0}"
            "small{color:#999}</style></head><body>"
            "<h1>源图纸 vs 识别 · 逐楼对照</h1>"
            "<p>每楼一页、每层 A|B 并排：左=源 CAD，右=第一轮识别叠加，找识别问题。</p><ul>"
            + lis + "</ul></body></html>")


def main():
    import run_step
    names = sorted(d for d in os.listdir(BASE)
                   if os.path.isdir(os.path.join(BASE, d, "floors")))
    if sys.argv[1:]:
        names = [n for n in names if n in sys.argv[1:]]
    tot = 0; failed = []; master = []
    for i, name in enumerate(names, 1):
        fd = os.path.join(BASE, name, "floors")
        floors = sorted(int(os.path.basename(f)[5:-5])
                        for f in glob.glob(os.path.join(fd, "floor*.json")))
        try:
            p = run_step.load_profile(name)
            cn = _cn_from_dxf(p)
        except Exception as e:  # noqa: BLE001
            failed.append((name, "*", f"profile {str(e)[:80]}")); continue
        od = os.path.join(BASE, name, "dxf_plan_recog")
        os.makedirs(od, exist_ok=True)
        stats = {}; ok = 0
        for F in floors:
            try:
                fp = os.path.join(fd, f"floor{F}.json")
                fl = json.load(open(fp, encoding="utf-8"))
                # dxf_plan_recog/ 的**所有者是 _dxf_png_batch.py**。本脚本只在叠加图缺失或
                # 比 floor JSON 旧时才重画（复用同一个 render_floor_png，内容一致），
                # 避免两个脚本反复互写同一目录（2026-09-10 图纸事故的同源风险）。
                dstpng = os.path.join(od, f"floor{F}.png")
                if not os.path.exists(dstpng) or os.path.getmtime(dstpng) < os.path.getmtime(fp):
                    V1.render_floor_png(name, F, fl, dstpng)
                ok += 1
                ol = fl.get("outline")
                area = int((max(x for x, _ in ol) - min(x for x, _ in ol)) *
                           (max(y for _, y in ol) - min(y for _, y in ol))) if ol else None
                stats[F] = dict(doors=len(fl.get("doors", [])),
                                stairs=len(fl.get("stairwells", [])),
                                rooms=len(fl.get("rooms", [])), area=area)
            except Exception as e:  # noqa: BLE001
                failed.append((name, F, str(e)[:90]))
        tot += ok
        with open(os.path.join(BASE, name, "compare.html"), "w", encoding="utf-8") as f:
            f.write(_compare_html(name, cn, floors, stats))
        master.append((name, cn, len(floors)))
        print(f"[{i}/{len(names)}] {name:6s} {ok}/{len(floors)}", flush=True)
    with open(os.path.join(BASE, "_dxf_compare.html"), "w", encoding="utf-8") as f:
        f.write(_master_html(master))
    print(f"\n=== 对比完成 {tot} 张识别图 / {len(names)} 栋 / 失败 {len(failed)} ===")
    for nm, F, err in failed[:20]:
        print(f"  FAIL {nm} F{F}: {err}")


if __name__ == "__main__":
    main()
