# -*- coding: utf-8 -*-
"""后台烟测：真浏览器打开后台首页，看它是否真的把视图和数据渲染出来。

判据不是 HTTP 200，而是「屏幕上出现了几行数字」——所以量 DOM 里的文本与卡片数。
用法：python _scratch/_admin_smoke.py [路径 ...]   默认只测首页
"""
import json
import sys

from playwright.sync_api import sync_playwright

pathes = sys.argv[1:] or [""]

with sync_playwright() as pw:
    b = pw.chromium.launch()
    for path in pathes:
        pg = b.new_page(viewport={"width": 1600, "height": 1000})
        errs = []
        pg.on("console", lambda m: errs.append(m.text[:200]) if m.type == "error" else None)
        pg.goto("http://127.0.0.1:8140/" + path, wait_until="load")
        pg.wait_for_timeout(5000)
        d = pg.evaluate("""() => {
          const txt = document.body.innerText || '';
          const cards = document.querySelectorAll('[class*=card],[class*=kpi],[class*=stat],[class*=tot]').length;
          const nav = [...document.querySelectorAll('nav a,nav button,[class*=tab]')]
                        .map(e => e.textContent.trim()).filter(Boolean).slice(0, 14);
          const rows = document.querySelectorAll('table tr').length;
          const digits = txt.split('').filter(c => c >= '0' && c <= '9').length;
          return { title: document.title, textLen: txt.length, digits, cards,
                   tables: document.querySelectorAll('table').length, rows, nav,
                   head: txt.split('\\n').filter(Boolean).slice(0, 14).join(' | ') };
        }""")
        print("=" * 90)
        print("【/%s】" % path)
        print(json.dumps(d, ensure_ascii=False, indent=1))
        if errs:
            print("  ⚠ console.error:", errs[:5])
        pg.close()
    b.close()
