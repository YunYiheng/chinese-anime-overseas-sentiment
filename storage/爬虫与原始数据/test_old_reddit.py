# -*- coding: utf-8 -*-
"""
测试 old.reddit.com 老版界面：能不能绕过 "Prove your humanity" 验证墙，正常读到评论
- 用同样的帖子链接，换成 old.reddit.com 域名
- 检查老版评论结构（div.comment）和评论数
- 顺便看首条评论的 data-fullname / id / score / time，为改写爬虫做准备
"""
import sys
import time

sys.stdout.reconfigure(encoding="utf-8")

from playwright.sync_api import sync_playwright


# 用几条"被验证墙挡住"的链接测试
URLS = [
    ("ne_zha_movies", "https://old.reddit.com/r/movies/comments/1j2r7x7/ne_zha_2_surpasses_2billion_mark_becomes_first/"),
    ("rmji_1tsh826", "https://old.reddit.com/r/Donghua/comments/1tsh826/i_made_a_grave_mistake_by_watching_rmji_as_my/"),
    ("link_click_char", "https://old.reddit.com/r/CharacterRant/comments/1nbeqvk/link_click_is_incredibly_disappointing/"),
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

        time.sleep(6)
        print("  当前URL:", page.url)

        # 页面正文开头，判断是不是验证墙
        txt = page.locator("body").inner_text()
        print("  正文开头:", txt[:180].replace("\n", " | "))

        # 老版评论容器
        comments = page.locator("div.thing.comment")
        cnt = comments.count()
        print(f"  老版评论数(div.thing.comment): {cnt}")

        if cnt > 0:
            first = comments.first
            # 评论各字段在老版里的取法
            fullname = first.get_attribute("data-fullname")
            cid = first.get_attribute("id")
            author = first.locator("a.author").first.inner_text() if first.locator("a.author").first.count() else ""
            score = first.locator("span.score").first.inner_text() if first.locator("span.score").first.count() else ""
            t = first.locator("time").first
            ptime = t.get_attribute("datetime") if t.count() else ""
            body = first.locator("div.md").first.inner_text() if first.locator("div.md").first.count() else ""
            print(f"  首条: fullname={fullname!r} id={cid!r}")
            print(f"        author={author!r} score={score!r} time={ptime!r}")
            print(f"        正文前80字: {body[:80]!r}")

        page.screenshot(path=f"old_{tag}.png")
        page.close()
        time.sleep(5)

    browser.close()

print("\nold.reddit 测试完成")
