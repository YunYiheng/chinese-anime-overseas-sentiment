# -*- coding: utf-8 -*-
"""
Reddit 批量评论采集器 v2 —— Stealth 伪装版
- 真实 Chrome + 伪装指纹(playwright_stealth) + 自定义 UA，降低验证墙出现频率
- 字段：page_url, anime_name, subreddit, comment_id, author, post_time, score, crawl_time, content
- 温和爬取：帖子间 sleep 10s，评论间 sleep 2s
- 遇到验证墙（含 "prove your humanity"）：弹墙后给 5 分钟人工点击窗口，点完自动继续；
  检测到硬封锁 "you've been blocked" 直接跳过记 blocked（IP 级，换节点才有救）
- 开头探测浏览器出口 IP，确认走没走代理
"""
import sys
import time
import csv
from datetime import datetime

sys.stdout.reconfigure(encoding="utf-8")

from playwright.sync_api import sync_playwright
from playwright_stealth import Stealth


# 真实浏览器 UA（伪装用）
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")


# ============ 作品池：每部作品 10~20 个帖子，URL 从这里手动收集填入 ============
# 收集方法：浏览器打开 https://www.reddit.com/r/Donghua/search/?q=关键词&restrict_sr=1
#          分别搜 "RMJI" / "Link Click" / "Ling Cage" / "Ne Zha"，复制帖子链接加进列表
POSTS = [
    # 凡人修仙传 RMJI（已验证可用）
    {
        "url": "https://www.reddit.com/r/Donghua/comments/1vbvngg/a_record_of_a_mortals_journey_to_immortality/",
        "anime": "RMJI",
        "subreddit": "Donghua",
    },
    {
        "url": "https://www.reddit.com/r/Donghua/comments/1tsh826/i_made_a_grave_mistake_by_watching_rmji_as_my/",
        "anime": "RMJI",
        "subreddit": "Donghua",
    },
    {
        "url": "https://www.reddit.com/r/Donghua/comments/1r1f3p9/rmji_just_caught_up_with_the_series_it_is/",
        "anime": "RMJI",
        "subreddit": "Donghua",
    },
    {
        "url": "https://www.reddit.com/r/MartialMemes/comments/1is7z1c/is_rmji_that_good/",
        "anime": "RMJI",
        "subreddit": "MartialMemes",
    },
    # Link Click 时光代理人
    {
        "url": "https://www.reddit.com/r/LinkClick/comments/1v7onn3/so_glad_i_started_watching_link_click/",
        "anime": "Link Click",
        "subreddit": "LinkClick",
    },
    {
        "url": "https://www.reddit.com/r/LinkClick/comments/1mm06s3/whats_something_about_link_click_that_made_you_go/",
        "anime": "Link Click",
        "subreddit": "LinkClick",
    },
    {
        "url": "https://www.reddit.com/r/CharacterRant/comments/1nbeqvk/link_click_is_incredibly_disappointing/",
        "anime": "Link Click",
        "subreddit": "CharacterRant",
    },
    # Ling Cage 灵笼
    {
        "url": "https://www.reddit.com/r/Donghua/comments/1r6p06u/just_finished_watching_ling_cage_and_wow/",
        "anime": "Ling Cage",
        "subreddit": "Donghua",
    },
    {
        "url": "https://www.reddit.com/r/Donghua/comments/1my02pa/ling_cage_is_not_good_as_people_say/",
        "anime": "Ling Cage",
        "subreddit": "Donghua",
    },
    {
        "url": "https://www.reddit.com/r/Donghua/comments/1mem9vl/ling_cage_is_excellent_but/",
        "anime": "Ling Cage",
        "subreddit": "Donghua",
    },
    # Ne zha 哪吒
    {
        "url": "https://www.reddit.com/r/boxoffice/comments/1loreko/nezha_2_ends_its_domestic_run_in_china_with/",
        "anime": "Ne zha",
        "subreddit": "boxoffice",
    },
    {
        "url": "https://www.reddit.com/r/movies/comments/1j2r7x7/ne_zha_2_surpasses_2billion_mark_becomes_first/",
        "anime": "Ne zha",
        "subreddit": "movies",
    },
    # Soul Land 斗罗大陆
    {
        "url": "https://www.reddit.com/r/Donghua/comments/1gaceqe/why_is_soul_land_so_popular/",
        "anime": "Soul Land",
        "subreddit": "Donghua",
    },
    {
        "url": "https://www.reddit.com/r/Donghua/comments/1qcgz4t/is_soul_land_2_good/",
        "anime": "Soul Land",
        "subreddit": "Donghua",
    },
    # Battle Through the Heavens 斗破苍穹
    {
        "url": "https://www.reddit.com/r/Donghua/comments/1tuu3zx/battle_through_the_heavens/",
        "anime": "Battle Through the Heavens",
        "subreddit": "Donghua",
    },
    # TODO: 继续添加 Link Click / Ling Cage / Ne Zha 等作品的帖子
]

OUT_CSV = "reddit_comments.csv"


def wait_comments(page, comments, timeout=90):
    """等评论渲染；检测到验证墙提示人工点击并延长窗口到 5 分钟；硬封锁返回 blocked"""
    verify_seen = False
    deadline = time.time() + timeout
    while True:
        if comments.count() > 0:
            time.sleep(3)   # 等懒加载补全
            return "ok"
        body = page.locator("body").inner_text()[:800].lower()
        if ("you've been blocked" in body or "you have been blocked" in body
                or "blocked by network security" in body):
            return "blocked"
        if ("prove your humanity" in body
                or "verify you are human" in body
                or "are you human" in body):
            if not verify_seen:
                verify_seen = True
                deadline = time.time() + 300   # 弹墙后给 5 分钟人工点击窗口
                print("    >>> 弹出了验证墙！请在浏览器里点一下验证（可能要连点几次），点完自动继续...")
        if time.time() > deadline:
            return "verify" if verify_seen else "no_comments"
        time.sleep(1)


def extract_comment(c):
    """从一条 shreddit-comment 拆出各字段（score / comment-id 用多属性名兜底）"""
    author = c.get_attribute("author") or ""
    comment_id = c.get_attribute("comment-id") or c.get_attribute("id") or ""
    score = c.get_attribute("score") or "0"
    t = c.locator("time").first
    post_time = t.get_attribute("datetime") if t.count() else ""
    body = c.locator("div[id$='-post-rtjson-content']")
    content = body.first.inner_text() if body.count() else ""
    return author, comment_id, score, post_time, content


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

    # 0) 探出口 IP：确认走没走代理
    try:
        page.goto("https://ipinfo.io/json", wait_until="domcontentloaded", timeout=30000)
        time.sleep(3)
        txt = page.locator("body").inner_text()
        print("浏览器出口IP:", txt[:120].replace("\n", " | "))
    except Exception as e:
        print("IP探测失败:", type(e).__name__, e)

    rows = []
    results = []

    for idx, post in enumerate(POSTS, 1):
        page = context.new_page()
        Stealth().apply_stealth_sync(page)
        print(f"\n>>> [{idx}/{len(POSTS)}] 抓取: {post['anime']} (r/{post['subreddit']})")
        try:
            page.goto(post["url"], wait_until="domcontentloaded", timeout=30000)
            time.sleep(10)   # 帖子之间限速

            comments = page.locator("shreddit-comment")
            status = wait_comments(page, comments)
            if status == "blocked":
                print("    硬封锁: Reddit 直接拒绝（IP 级），跳过")
                results.append((post["anime"], post["subreddit"], "blocked", 0))
                page.close()
                continue
            if status != "ok":
                print(f"    跳过: {status}（没加载到评论）")
                results.append((post["anime"], post["subreddit"], status, 0))
                page.close()
                continue

            total = comments.count()
            print(f"    评论数: {total}")
            results.append((post["anime"], post["subreddit"], "ok", total))
            for i in range(total):
                c = comments.nth(i)
                # 过滤嵌套回复
                parent = c.locator("xpath=..").first
                if parent.count() and parent.evaluate("el => el.tagName") == "SHREDDIT-COMMENT":
                    continue

                author, comment_id, score, post_time, content = extract_comment(c)
                rows.append([
                    post["url"], post["anime"], post["subreddit"], comment_id, author,
                    post_time, score, datetime.now().isoformat(timespec="seconds"), content,
                ])
                time.sleep(2)   # 评论之间限速
        except Exception as e:
            print(f"    异常: {type(e).__name__}: {e}")
            results.append((post["anime"], post["subreddit"], f"error:{type(e).__name__}", 0))
        page.close()
        time.sleep(10)

    # 落 CSV（utf-8-sig，Excel 打开不乱码）
    with open(OUT_CSV, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(["page_url", "anime_name", "subreddit", "comment_id",
                         "author", "post_time", "score", "crawl_time", "content"])
        writer.writerows(rows)

    print("\n========== 采集结果 ==========")
    ok = [r for r in results if r[2] == "ok"]
    print(f"成功: {len(ok)} / {len(POSTS)}，共 {len(rows)} 条评论 -> {OUT_CSV}")
    for anime, sub, status, cnt in results:
        flag = "✓" if status == "ok" else "✗"
        print(f"  {flag} {anime:<24} r/{sub:<12} {status}  {cnt} 评论")

    browser.close()
