# -*- coding: utf-8 -*-
"""
Stealth 测试版：真实 Chrome + 伪装指纹 + 修正验证墙检测
目的：
  1. 开头先看 Playwright 浏览器出口 IP -> 确认走没走代理
  2. 爬 4 个之前失败的帖子，看验证墙出现频率、手动点击通过率
  3. 与之前 2/15 的基准对比，判断 stealth 有没有用
注意：弹验证墙时请在浏览器里手动点一下验证，点完自动继续。
"""
import sys
import time

sys.stdout.reconfigure(encoding="utf-8")

from playwright.sync_api import sync_playwright
from playwright_stealth import Stealth

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

# 之前 15 条里失败的 4 条（带不同板块类型）
POSTS = [
    {"url": "https://www.reddit.com/r/Donghua/comments/1tsh826/i_made_a_grave_mistake_by_watching_rmji_as_my/",
     "anime": "RMJI", "subreddit": "Donghua"},
    {"url": "https://www.reddit.com/r/movies/comments/1j2r7x7/ne_zha_2_surpasses_2billion_mark_becomes_first/",
     "anime": "Ne Zha", "subreddit": "movies"},
    {"url": "https://www.reddit.com/r/LinkClick/comments/1v7onn3/so_glad_i_started_watching_link_click/",
     "anime": "Link Click", "subreddit": "LinkClick"},
    {"url": "https://www.reddit.com/r/Donghua/comments/1gaceqe/why_is_soul_land_so_popular/",
     "anime": "Soul Land", "subreddit": "Donghua"},
]


def wait_comments(page, comments, timeout=90):
    """等评论渲染；检测到验证墙(含 'prove your humanity')就提示人工点击"""
    verify_seen = False
    for _ in range(timeout):
        if comments.count() > 0:
            time.sleep(3)   # 等懒加载补全
            return "ok"
        body = page.locator("body").inner_text()[:500].lower()
        if ("prove your humanity" in body
                or "verify you are human" in body
                or "are you human" in body):
            if not verify_seen:
                print("    >>> 弹出了验证墙！请在浏览器里点一下验证，点完自动继续...")
                verify_seen = True
        time.sleep(1)
    return "verify" if verify_seen else "no_comments"


with sync_playwright() as p:
    browser = p.chromium.launch(
        headless=False,
        channel="chrome",
        args=["--disable-blink-features=AutomationControlled"],
    )
    context = browser.new_context(viewport={"width": 1280, "height": 900},
                                  user_agent=UA)
    page = context.new_page()
    Stealth().apply_stealth_sync(page)

    # 0) 探出口 IP：看 Playwright 走没走代理
    try:
        page.goto("https://ipinfo.io/json", wait_until="domcontentloaded", timeout=30000)
        time.sleep(3)
        txt = page.locator("body").inner_text()
        print("浏览器出口IP信息:", txt[:200].replace("\n", " | "))
    except Exception as e:
        print("IP探测失败:", type(e).__name__, e)

    # 1) 逐个爬测试帖
    results = []
    for idx, post in enumerate(POSTS, 1):
        page = context.new_page()
        Stealth().apply_stealth_sync(page)
        print(f"\n>>> [{idx}/{len(POSTS)}] {post['anime']} @ r/{post['subreddit']}")
        try:
            page.goto(post["url"], wait_until="domcontentloaded", timeout=30000)
            comments = page.locator("shreddit-comment")
            status = wait_comments(page, comments)
            cnt = comments.count() if status == "ok" else 0
            print(f"    {status}  评论数={cnt}")
            results.append((post["anime"], post["subreddit"], status, cnt))
        except Exception as e:
            print(f"    异常: {type(e).__name__}: {e}")
            results.append((post["anime"], post["subreddit"], f"error:{type(e).__name__}", 0))
        page.close()
        time.sleep(6)

    browser.close()

    print("\n========== 测试结果 ==========")
    ok = [r for r in results if r[2] == "ok"]
    print(f"能爬到: {len(ok)} / {len(POSTS)}")
    for anime, sub, status, cnt in results:
        flag = "✓" if status == "ok" else "✗"
        print(f"  {flag} {anime:<12} r/{sub:<10} {status}  {cnt} 评论")
