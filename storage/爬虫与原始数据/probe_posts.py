# -*- coding: utf-8 -*-
"""
探针脚本：批量检查 reddit_crawler.py 的 POSTS 里每条链接能不能爬到
目的：在全量爬虫之前先摸底，看哪些帖子还活着、评论能否加载、哪些会弹人工验证。
用法：python probe_posts.py
说明：会弹出浏览器窗口；若看到 "verify you are human" 请在窗口里手动点一下，点完自动继续。
      顺便验证第一条评论的 score / comment-id 属性名是否真的能取到。
"""
import sys
import time

sys.stdout.reconfigure(encoding="utf-8")

from playwright.sync_api import sync_playwright


# ====== 作品池（和 reddit_crawler.py 保持一致，改动要两边同步） ======
POSTS = [
    # 凡人修仙传 RMJI
    {"url": "https://www.reddit.com/r/Donghua/comments/1vbvngg/a_record_of_a_mortals_journey_to_immortality/",
     "anime": "RMJI", "subreddit": "Donghua"},
    {"url": "https://www.reddit.com/r/Donghua/comments/1tsh826/i_made_a_grave_mistake_by_watching_rmji_as_my/",
     "anime": "RMJI", "subreddit": "Donghua"},
    {"url": "https://www.reddit.com/r/Donghua/comments/1r1f3p9/rmji_just_caught_up_with_the_series_it_is/",
     "anime": "RMJI", "subreddit": "Donghua"},
    {"url": "https://www.reddit.com/r/MartialMemes/comments/1is7z1c/is_rmji_that_good/",
     "anime": "RMJI", "subreddit": "MartialMemes"},
    # Link Click 时光代理人
    {"url": "https://www.reddit.com/r/LinkClick/comments/1v7onn3/so_glad_i_started_watching_link_click/",
     "anime": "Link Click", "subreddit": "LinkClick"},
    {"url": "https://www.reddit.com/r/LinkClick/comments/1mm06s3/whats_something_about_link_click_that_made_you_go/",
     "anime": "Link Click", "subreddit": "LinkClick"},
    {"url": "https://www.reddit.com/r/CharacterRant/comments/1nbeqvk/link_click_is_incredibly_disappointing/",
     "anime": "Link Click", "subreddit": "CharacterRant"},
    # Ling Cage 灵笼
    {"url": "https://www.reddit.com/r/Donghua/comments/1r6p06u/just_finished_watching_ling_cage_and_wow/",
     "anime": "Ling Cage", "subreddit": "Donghua"},
    {"url": "https://www.reddit.com/r/Donghua/comments/1my02pa/ling_cage_is_not_good_as_people_say/",
     "anime": "Ling Cage", "subreddit": "Donghua"},
    {"url": "https://www.reddit.com/r/Donghua/comments/1mem9vl/ling_cage_is_excellent_but/",
     "anime": "Ling Cage", "subreddit": "Donghua"},
    # Ne zha 哪吒
    {"url": "https://www.reddit.com/r/boxoffice/comments/1loreko/nezha_2_ends_its_domestic_run_in_china_with/",
     "anime": "Ne zha", "subreddit": "boxoffice"},
    {"url": "https://www.reddit.com/r/movies/comments/1j2r7x7/ne_zha_2_surpasses_2billion_mark_becomes_first/",
     "anime": "Ne zha", "subreddit": "movies"},
    # Soul Land 斗罗大陆
    {"url": "https://www.reddit.com/r/Donghua/comments/1gaceqe/why_is_soul_land_so_popular/",
     "anime": "Soul Land", "subreddit": "Donghua"},
    {"url": "https://www.reddit.com/r/Donghua/comments/1qcgz4t/is_soul_land_2_good/",
     "anime": "Soul Land", "subreddit": "Donghua"},
    # Battle Through the Heavens 斗破苍穹
    {"url": "https://www.reddit.com/r/Donghua/comments/1tuu3zx/battle_through_the_heavens/",
     "anime": "Battle Through the Heavens", "subreddit": "Donghua"},
]


def check_page(page, max_wait=35):
    """
    等评论渲染，返回 (status, comment_count, sample)
    status: ok / verify / removed / 404 / private / no_comments
    sample: 第一条评论的 (score, comment-id)，仅 status=ok 时返回
    """
    verify_seen = False
    for _ in range(max_wait):
        comments = page.locator("shreddit-comment")
        if comments.count() > 0:
            time.sleep(3)   # 等 Reddit 懒加载把评论补全一点
            return "ok", comments.count(), sample_fields(comments.first)

        body = page.locator("body").inner_text()[:800].lower()
        if "verify you are human" in body or "are you human" in body:
            if not verify_seen:
                print("      ⚠ 弹出了人工验证，请在浏览器窗口点一下，点完自动继续...")
            verify_seen = True
        elif "this post was removed" in body or "regretfully" in body or "content was removed" in body:
            return "removed", 0, None
        elif "page not found" in body or "nobody on reddit goes by that name" in body:
            return "404", 0, None
        elif "temporarily set to private" in body or "private community" in body:
            return "private", 0, None
        time.sleep(1)

    return ("verify", 0, None) if verify_seen else ("no_comments", 0, None)


def sample_fields(c):
    """验证第一条评论的 score / comment-id 属性名是否真的能取到"""
    score = c.get_attribute("score")
    cid = c.get_attribute("comment-id")
    return (score, cid)


STATUS_LABEL = {
    "ok": "✓ 能爬",
    "verify": "⚠ 人工验证",
    "removed": "✗ 帖被删/移除",
    "404": "✗ 链接失效",
    "private": "✗ 私密板块",
    "no_comments": "△ 能打开但没评论",
}


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        print("浏览器已打开。如果弹出 'verify you are human'，请手动点验证。\n")
        results = []

        for idx, post in enumerate(POSTS, 1):
            page = browser.new_page(viewport={"width": 1280, "height": 900})
            print(f">>> [{idx:>2}/{len(POSTS)}] {post['anime']} @ r/{post['subreddit']}")
            try:
                page.goto(post["url"], wait_until="domcontentloaded", timeout=30000)
                status, count, sample = check_page(page)
            except Exception as e:
                status, count, sample = f"error:{type(e).__name__}", 0, None

            label = STATUS_LABEL.get(status, status)
            msg = f"    {label}  评论数={count}"
            if sample:
                score, cid = sample
                msg += f" | 首条 score={score!r}  comment-id={cid!r}"
            print(msg)

            results.append((post["anime"], post["subreddit"], status, count))
            page.close()
            if idx < len(POSTS):
                time.sleep(6)   # 帖子之间限速

        browser.close()

        # 汇总表
        print("\n========== 汇总 ==========")
        ok = [r for r in results if r[2] == "ok"]
        print(f"能爬到: {len(ok)} / {len(POSTS)}")
        for anime, sub, status, count in results:
            flag = "✓" if status == "ok" else "✗"
            label = STATUS_LABEL.get(status, status)
            print(f"  {flag} {anime:<26} r/{sub:<12} {label}  {count} 评论")


if __name__ == "__main__":
    main()
