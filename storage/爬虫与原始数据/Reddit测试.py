# -*- coding: utf-8 -*-
"""
Reddit 评论探针 v2
- 用 shreddit-comment 稳定定位评论（新版 Reddit 每条评论一个该标签）
- 拆出 作者 / 发布时间 / 正文 三个字段
- 过滤掉嵌套回复，只留顶层评论
- 结果存 CSV，编码 utf-8-sig（Excel 打开不乱码）
- 温和爬取：有头浏览器 + time.sleep 限速
"""
import sys
import time
import csv
from datetime import datetime

# 关键：修复 Windows 控制台 GBK 编码崩溃（打印 • 等字符会报错）
sys.stdout.reconfigure(encoding="utf-8")

from playwright.sync_api import sync_playwright


# 测试帖子 URL：可换成任意 r/Donghua 帖子
URL = "https://www.reddit.com/r/Donghua/comments/1vbvngg/a_record_of_a_mortals_journey_to_immortality/"
OUT_CSV = "reddit_comments.csv"


def extract_comment(c):
    """从一条 shreddit-comment 元素拆出 (作者, 发布时间, 正文)"""
    author = c.get_attribute("author") or ""
    t = c.locator("time").first
    post_time = t.get_attribute("datetime") if t.count() else ""
    body = c.locator("div[id$='-post-rtjson-content']")
    content = body.first.inner_text() if body.count() else ""
    return author, post_time, content


with sync_playwright() as p:
    # 有头浏览器：降低被 Reddit 人机挑战拦截的概率
    browser = p.chromium.launch(headless=False)
    page = browser.new_page(viewport={"width": 1280, "height": 900})

    print("正在打开网页...")
    page.goto(URL, wait_until="domcontentloaded")
    time.sleep(5)   # 给动态渲染留时间 + 限速

    # 等评论真正渲染出来（比固定 sleep 更可靠）；
    # 若被 js_challenge 卡住，最多重试一次
    comments = page.locator("shreddit-comment")
    try:
        comments.first.wait_for(state="attached", timeout=30000)
    except Exception:
        print("首次加载未拿到评论，可能是 js_challenge，重试一次...")
        time.sleep(5)
        page.goto(URL, wait_until="domcontentloaded")
        time.sleep(8)
        try:
            comments.first.wait_for(state="attached", timeout=30000)
        except Exception:
            print("警告：仍未拿到评论，可能被反爬拦截，请打开浏览器手动确认后重跑")
            browser.close()
            raise SystemExit("采集失败：未加载到任何评论")

    print("\n网页标题:", page.title())
    print("当前URL:", page.url)

    total = comments.count()
    print("评论总数(含嵌套回复):", total)

    rows = []
    for i in range(total):
        c = comments.nth(i)

        # 过滤嵌套回复：父元素若是 shreddit-comment，说明是子回复，跳过
        parent = c.locator("xpath=..").first
        if parent.count() and parent.evaluate("el => el.tagName") == "SHREDDIT-COMMENT":
            continue

        author, post_time, content = extract_comment(c)
        rows.append([URL, author, post_time, datetime.now().isoformat(timespec="seconds"), content])

        preview = content[:150] + ("..." if len(content) > 150 else "")
        print(f"\n--- {author} | {post_time} ---")
        print(preview)
        time.sleep(1)   # 每条之间也限速，避免被限频

    # 落 CSV：utf-8-sig 带 BOM，Excel 直接打开不乱码
    with open(OUT_CSV, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(["page_url", "author", "post_time", "crawl_time", "content"])
        writer.writerows(rows)

    print(f"\n已保存 {len(rows)} 条顶层评论 -> {OUT_CSV}")
    page.screenshot(path="reddit_test.png", full_page=True)

    browser.close()
