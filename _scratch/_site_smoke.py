# -*- coding: utf-8 -*-
"""前台烟测：真浏览器打开呈现页，验**语义**（模型真渲染了、图真解码了），
不是验 HTTP 状态码。用法: python _scratch/_site_smoke.py [楼号 ...]"""
import sys, json
from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8140/site/building.html?b="
names = sys.argv[1:] or ["c001"]

with sync_playwright() as pw:
    b = pw.chromium.launch()
    for nm in names:
        pg = b.new_page(viewport={"width": 1440, "height": 900})
        errs, bad = [], []
        pg.on("console", lambda m: errs.append(m.text[:200]) if m.type == "error" else None)
        pg.on("requestfailed", lambda r: bad.append((r.url[-70:], r.failure)))
        pg.goto(BASE + nm, wait_until="load")
        pg.wait_for_timeout(6000)
        d = pg.evaluate("""() => {
          const q = (s) => document.querySelector(s);
          const img = q('.draw-img');
          const cv  = q('canvas#gl');
          const fl  = [...document.querySelectorAll('.flr .flr-mid')].map(e => e.textContent.trim());
          let pix = null, tri = null, hud = null;
          if (cv) { const g = cv.getContext('webgl2') || cv.getContext('webgl');
                    pix = g ? cv.width + 'x' + cv.height : 'no-webgl'; }
          hud = q('#hud') ? q('#hud').textContent.trim() : null;
          return { title: document.title, nfloors: fl.length, floors: fl.slice(0, 8),
                   imgOk: img ? img.complete && img.naturalWidth > 0 : null,
                   imgSize: img ? img.naturalWidth + 'x' + img.naturalHeight : null,
                   imgSrc: img ? img.getAttribute('src') : null,
                   canvas: pix, hud: hud,
                   miss: q('.draw-miss') ? q('.draw-miss').textContent.trim().slice(0,120) : null,
                   stageMiss: q('.stage-miss') ? q('.stage-miss').textContent.trim().slice(0,120) : null,
                   panic: q('.panic') ? q('.panic').textContent.trim().slice(0,200) : null };
        }""")
        print("=" * 90)
        print("【%s】%s" % (nm, d["title"]))
        print(json.dumps(d, ensure_ascii=False, indent=1))
        if errs: print("  ⚠ console.error:", errs[:4])
        if bad:  print("  ⚠ requestfailed:", bad[:4])
        pg.close()
    b.close()
