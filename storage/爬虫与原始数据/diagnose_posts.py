# -*- coding: utf-8 -*-
"""
诊断脚本：弄清为什么探针里 13 条链接"能打开但没评论"
对几条有代表性的挂掉链接：
  1. 打印页面正文开头 -> 判断是"帖被删了"还是"评论区根本没加载"
  2. 模拟往下滚动 -> 看评论是否懒加载
  3. 若滚动后有评论，打印首条评论的全部属性名 -> 找出 comment-id 的正确属性名
每次诊断都存一张截图，方便直接看页面长啥样。
"""
import sys
import time

sys.stdout.reconfigure(encoding="utf-8")

from playwright.sync_api import sync_playwright


# 有代表性的"能打开但没评论"的链接
URLS = [
    ("ne_zha_movies", "https://www.reddit.com/r/movies/comments/1j2r7x7/ne_zha_2_surpasses_2billion_mark_becomes_first/"),
    ("rmji_1tsh826", "https://www.reddit.com/r/Donghua/comments/1tsh826/i_made_a_grave_mistake_by_watching_rmji_as_my/"),
    ("soul_land_1gaceqe", "https://www.reddit.com/r/Donghua/comments/1gaceqe/why_is_soul_land_so_popular/"),
    ("link_click_char", "https://www.reddit.com/r/CharacterRant/comments/1nbeqvk/link_click_is_incredibly_disappointing/"),
]


with sync_playwright() as p:
    browser = p.chromium.launch(headless=False)

    for tag, url in URLS:
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        print(f"\n===== {tag} =====")
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=30000)
        except Exception as e:
            print(f"  打开失败: {type(e).__name__}: {e}")
            page.close()
            continue

        time.sleep(8)   # 给首屏一点渲染时间

        # 1) 打印页面正文开头，判断页面真实状态
        txt = page.locator("body").inner_text()
        print(f"--- 正文开头(前700字) ---")
        print(txt[:700].replace("\n", " | ")[:700])
        print("--- 正文开头结束 ---")

        # 2) 滚动前评论数
        before = page.locator("shreddit-comment").count()
        print(f"滚动前评论数: {before}")

        # 3) 模拟往下滚动，触发懒加载
        for _ in range(12):
            page.mouse.wheel(0, 900)
            time.sleep(1.0)
        after = page.locator("shreddit-comment").count()
        print(f"滚动后评论数: {after}")

        # 4) 滚动后若出现评论，打印首条评论的全部属性名
        if after > 0:
            c = page.locator("shreddit-comment").first
            attrs = c.evaluate(
                "el => Array.from(el.attributes).map(a => a.name + '=' + a.value.slice(0, 30)).join('  |  ')"
            )
            print(f"首条评论属性: {attrs}")

        page.screenshot(path=f"diag_{tag}.png")
        print(f"截图已存: diag_{tag}.png")
        page.close()
        time.sleep(5)   # 页面之间限速

    browser.close()

print("\n诊断完成")
