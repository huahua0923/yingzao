# -*- coding: utf-8 -*-
r"""页面体检 —— 逐个打开本仓的 HTML，量「它到底有没有内容」，并记下为什么没有。

为什么要有它（2026-10-20，用户「很多没有内容」）：
  页面是不是能看，原来只靠人一个个点。点不过来就会漏，漏了就变成「页面在、
  内容是空的」而没人知道。本工具只做**体检**，不修任何东西。

量什么（每条都是**现场读数**，不读任何自报）：
  · HTTP 状态、`document.title`
  · `body.innerText` 的**可见字数**（空白折叠后）
  · 三维/图文元素的个数：`canvas` / `img` / `svg` / `iframe`
  · 控制台 error、页面脚本异常（`pageerror`）
  · 资源请求失败（4xx/5xx 或 net::ERR_*）

★ 盲区（铁律 158，先声明再给判词）：
  · 「字数少」不等于「没内容」：纯 WebGL 页（`demo/building.html` 一类）正文可以只有一个
    标题，内容全在 canvas 里 ⇒ 判词看**字数与元素数两条**，不许只看一条。
  · 页面若要靠**人点一下**才加载（懒加载、按钮触发），本工具不会去点 ⇒ 它报的空
    = 「打开时立刻就是空」，不等于「永远空」。
  · 跨域 CDN 被墙时，本工具报的是**这台机器此刻**的读数；换网络结论会变。

用法：
    python tools/page_health.py                  # 本仓现存页面（默认清单见 DEFAULT_PAGES）
    python tools/page_health.py --base http://127.0.0.1:8451
输出：`过程/_out/page_health.json` + 控制台一张表
退出码：0 = 全部有内容 · 1 = 有页面空/报错 · 4 = 服务没起（一条都量不到）
"""
from __future__ import annotations

import argparse
import io
import json
import os

from playwright.sync_api import sync_playwright

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUT = os.path.join(ROOT, "过程", "_out", "page_health.json")

# ★ 2026-10-20 用户令：只留「首页 + 合并后台 + 对照/分层合页」。
#   下面这份清单跟着那次改动收窄（其余页已归档在
#   `rebuild/_archive/pages-20261020-125017/pages.zip` 后删除）。
#   流程台四页与工作台两页**不在这里**：它们有自己的服务与路由，
#   用 `--base http://127.0.0.1:8150 --paths pipeline,pipeline/flow,...` 单独量。
DEFAULT_PAGES = [
    "portal.html",               # 唯一入口（四标签）
    "admin",                     # 标签② 建模工作台
    "pipeline",                  # 标签③ 流程台
    "compare",                   # 标签④ 对照 / 分层
    "demo/building.html",        # 标签① 首页（也是直接可开的原页）
]
# ★ 这四个是**路由**不是盘上的文件（`workbench/server.py` 里现发），
#   所以不能拿 `ROOT/<rel>` 去验存在性 —— 那样会把它们当成「盘上没有」跳过。
ROUTES_NOT_FILES = {"portal.html", "admin", "pipeline", "compare"}

MEASURE_JS = r"""() => {
  const t = (document.body ? document.body.innerText : "") || "";
  const vis = t.replace(/\s+/g, " ").trim();
  const q = (s) => document.querySelectorAll(s).length;
  // ★ 同源 iframe 里的字也算「本页有内容」：`demo/compare.html` 是一页两标签、
  //   内容全在两个 iframe 里，只量父页会把它判成「内容很薄」（2026-10-20 实测 44 字）。
  //   跨源 iframe 读不到 ⇒ 记 0，不报错（本页都是同源，读不到就是真读不到）。
  let frameText = 0, frameCanvas = 0;
  try {
    for (const fr of document.querySelectorAll("iframe")) {
      try {
        const d = fr.contentDocument;
        if (!d) continue;
        if (d.body) frameText += (d.body.innerText || "").replace(/\s+/g, " ").trim().length;
        frameCanvas += d.querySelectorAll("canvas").length;
      } catch (e) { /* 跨源：不计 */ }
    }
  } catch (e) { /* 不计 */ }
  const cvs = [...document.querySelectorAll("canvas")].map(c => ({
      w: c.width, h: c.height,
      drawn: (() => { try { return !!(c.width && c.height); } catch (e) { return null; } })()
  }));
  return {
      title: document.title,
      text_len: vis.length,
      frame_text_len: frameText,
      frame_canvas: frameCanvas,
      text_head: vis.slice(0, 120),
      n_canvas: q("canvas"), n_img: q("img"), n_svg: q("svg"), n_iframe: q("iframe"),
      canvases: cvs,
      html_len: document.documentElement ? document.documentElement.innerHTML.length : 0
  };
}"""


def check(pw, base, rel, wait_ms):
    rec = {"page": rel, "url": base.rstrip("/") + "/" + rel}
    errors, failed = [], []
    browser = pw.chromium.launch(headless=True)
    ctx = browser.new_context(viewport={"width": 1400, "height": 900})
    page = ctx.new_page()
    page.on("console", lambda m: errors.append("%s: %s" % (m.type, m.text[:200]))
            if m.type == "error" else None)
    page.on("pageerror", lambda e: errors.append("pageerror: %s" % str(e)[:200]))
    page.on("requestfailed", lambda r: failed.append("%s %s" % (r.url[:120],
                                                               (r.failure or "")[:80])))
    page.on("response", lambda r: failed.append("%s HTTP %d" % (r.url[:120], r.status))
            if r.status >= 400 else None)
    try:
        resp = page.goto(rec["url"], wait_until="load", timeout=30000)
        rec["http"] = resp.status if resp else None
        page.wait_for_timeout(wait_ms)          # 给 rAF/异步 fetch 一点时间
        rec.update(page.evaluate(MEASURE_JS))
    except Exception as e:                                       # noqa: BLE001
        rec["error"] = str(e)[:300]
    finally:
        rec["console_errors"] = errors[:8]
        rec["failed_requests"] = failed[:8]
        ctx.close()
        browser.close()
    return rec


def verdict(r):
    """两条独立读数（字数 / 元素数），分开判，不合成一个 bool（铁律 174）。"""
    if r.get("error") or not r.get("http") or r["http"] >= 400:
        return "打不开"
    text = max(r.get("text_len", 0), r.get("frame_text_len", 0))
    n_el = sum(r.get(k, 0) for k in ("n_canvas", "n_img", "n_svg", "frame_canvas"))
    if text >= 80 or n_el >= 1:
        return "有内容"
    if text >= 10:
        return "内容很薄"
    return "空"


def main():
    ap = argparse.ArgumentParser()
    # 2026-10-20 起只剩一个服务（8150，四标签入口）；8451 静态站已停。
    ap.add_argument("--base", default="http://127.0.0.1:8150")
    ap.add_argument("--wait", type=int, default=1500)
    ap.add_argument("--only", default="")
    # ★ 2026-10-20：`pipeline/` 与 `workbench/` 有**自己的服务与自家路由**
    #   （8800 的 `/` `/floors` `/pages` `/flow`；8150 的 `/index.html` `/quick.html`），
    #   拿静态 8451 的路径去量它们，量到的是「路由不存在」，不是「页面空」。
    ap.add_argument("--paths", default="", help="逗号分隔的 URL 相对路径，覆盖默认清单")
    a = ap.parse_args()
    pages = ([p for p in a.paths.split(",") if p] if a.paths else DEFAULT_PAGES)
    if a.only:
        pages = [p for p in pages if a.only in p]
    if a.paths:
        missing = []                      # 自定义路径不按盘上文件校验
    else:
        missing = [p for p in pages if p not in ROUTES_NOT_FILES
                   and not os.path.exists(os.path.join(ROOT, p.replace("/", os.sep)))]
    for p in missing:
        print("★ 清单里有、盘上没有：%s（跳过）" % p)
    pages = [p for p in pages if p not in missing]

    rows = []
    with sync_playwright() as pw:
        for rel in pages:
            r = check(pw, a.base, rel, a.wait)
            r["verdict"] = verdict(r)
            rows.append(r)
            print("%-4s %-26s 字 %4d  canvas %d  img %d  err %d  fail %d  %s"
                  % (r["verdict"], rel, r.get("text_len", 0), r.get("n_canvas", 0),
                     r.get("n_img", 0), len(r.get("console_errors") or []),
                     len(r.get("failed_requests") or []), r.get("title", "")[:36]))
            for e in (r.get("console_errors") or [])[:2]:
                print("      ! %s" % e[:150])
            for e in (r.get("failed_requests") or [])[:2]:
                print("      ✗ %s" % e[:150])
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    # 端口写进文件名：8800 / 8150 / 8451 三套服务各留各的读数，不互相盖（铁律 174）
    _port = a.base.rstrip("/").rsplit(":", 1)[-1] or "0"
    _out = OUT[:-5] + "_%s.json" % _port
    with io.open(_out, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps({"when": __import__("time").strftime("%Y-%m-%dT%H:%M:%S"),
                             "base": a.base, "rows": rows}, ensure_ascii=False, indent=1))
    bad = [r for r in rows if r["verdict"] != "有内容"]
    print("\n%d 页：有内容 %d ／ 内容很薄 %d ／ 空 %d ／ 打不开 %d"
          % (len(rows), sum(1 for r in rows if r["verdict"] == "有内容"),
             sum(1 for r in rows if r["verdict"] == "内容很薄"),
             sum(1 for r in rows if r["verdict"] == "空"),
             sum(1 for r in rows if r["verdict"] == "打不开")))
    print("→ %s" % _out)
    return 0 if not bad else 1


if __name__ == "__main__":
    raise SystemExit(main())
