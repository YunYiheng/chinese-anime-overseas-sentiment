"""
RT（Rotten Tomatoes）观众评论爬虫 —— 修正版
============================================================
【修正说明】替换 A 之前那版 rotten_tomatoes.py：
  原版有 4 个问题（见 docs/rt_probe_findings.md 和 DATA_SPEC）：
  1. 抓错了对象 —— 抓的是「影评人」评论(review-card-critic)，项目要的是「观众」评论
  2. 字段完全没按 9 列规范（用了 movie_title/platform/critic/publication...）
  3. score 混乱 —— 影评人评分刻度不一(4/5、8/10、17.5/20、B-)，还用 inner_text 抓成了乱码
  4. 没有 comment_id，没法去重续跑

本版修正为：
  - 只抓【观众评论】audience reviews（页面 /m/{slug}/reviews/all-audience）
  - 严格输出 9 列：page_url, anime_name, source, comment_id, author, post_time, score, crawl_time, content
  - score 取观众评分（rating-stars-group 的 score 属性，0.5~5 半星），干净统一
  - comment_id = rt:{ratingId}（UUID，平台内唯一），支持续跑去重
  - 用 Playwright 翻页（napi 接口有 Akamai 401，requests 翻不了，Playwright 是唯一能拿全量的方式）

输出：rt_film_data.csv（utf-8-sig，9 列）
============================================================
"""
import sys
import csv
import json
import re
import time
from datetime import datetime
from pathlib import Path

import requests
from playwright.sync_api import sync_playwright, TimeoutError as PTE

# ============================================================
# 0. 基础配置
# ============================================================
OUTPUT_CSV = "rt_film_data.csv"
FIELDNAMES = ["page_url", "anime_name", "source", "comment_id",
              "author", "post_time", "score", "crawl_time", "content"]

# 7 部电影（Dataset B 规范英文名 + RT slug，来源 docs/rt_probe_findings.md）
# 注意：Ne Zha 和 Ne Zha 2 是两个独立 anime_name，别合并
MOVIES = [
    {"anime_name": "Ne Zha", "slug": "ne_zha"},
    {"anime_name": "Ne Zha 2", "slug": "ne_zha_ii"},
    {"anime_name": "White Snake", "slug": "white_snake"},
    {"anime_name": "Jiang Ziya", "slug": "jiang_ziya"},
    {"anime_name": "New Gods: Nezha Reborn", "slug": "new_gods_nezha_reborn"},
    {"anime_name": "New Gods: Yang Jian", "slug": "new_gods_yang_jian"},
    {"anime_name": "I Am What I Am", "slug": "i_am_what_i_am"},
]

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
      "AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/149.0.0.0 Safari/537.36")
PROXY = "http://127.0.0.1:7890"  # Clash 代理（RT 在美国，走代理稳）
PROXIES = {"http": PROXY, "https": PROXY}

PAGE_TIMEOUT = 60_000          # 页面加载超时
CARD_WAIT_TIMEOUT = 20_000     # 等第一张评论卡出现
LOAD_MORE_WAIT_TIMEOUT = 20_000  # 点 Load More 后等新卡
SLEEP_BETWEEN_MOVIES = 2       # 部与部之间温和限速
SLEEP_AFTER_LOAD_MORE = 2      # 每次 Load More 后限速


# ============================================================
# 1. 工具函数
# ============================================================
def load_existing_ids():
    """读现有 rt_film_data.csv 的 comment_id，用于续跑去重。"""
    existing = set()
    if Path(OUTPUT_CSV).exists():
        with open(OUTPUT_CSV, encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                if row.get("comment_id"):
                    existing.add(row["comment_id"])
    return existing


def append_rows(rows):
    """追加写入 CSV。首写带表头，续跑不带。"""
    if not rows:
        return
    write_header = not Path(OUTPUT_CSV).exists()
    with open(OUTPUT_CSV, "a", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        if write_header:
            writer.writeheader()
        writer.writerows(rows)


def dismiss_consent(page):
    """关掉 OneTrust 隐私弹窗（点 Continue）。没有弹窗就跳过。"""
    try:
        btn = page.locator("#onetrust-accept-btn-handler")
        btn.wait_for(state="attached", timeout=8000)
        if btn.count() > 0 and btn.first.is_visible():
            btn.first.click()
            time.sleep(1)
    except PTE:
        pass  # 没有弹窗，或已经接受过


def extract_cards(page):
    """
    从页面上所有 review-card-audience 卡片里抽字段，返回 list[dict]。
    用 JS 一次性抓，避免 Playwright 逐条 locator 慢、也避免 inner_text 把评分抓乱。
    """
    return page.eval_on_selector_all("review-card-audience", """els => els.map(el => {
        const q = (s) => el.querySelector(s);
        const txt = (s) => { const n = q(s); return n ? n.textContent.trim() : ""; };
        const rating = q('rating-stars-group[slot="rating"]');
        const opts = q('rt-button[slot="options-menu"]');
        return {
            author: txt('rt-link[slot="name"]'),
            post_time: txt('span[slot="timestamp"]'),
            score: rating ? (rating.getAttribute("score") || "").trim() : "",
            content: txt('drawer-more[slot="review"] span[slot="content"]'),
            rating_id: opts ? (opts.getAttribute("data-rating-id") || "").trim() : "",
        };
    })""")


# ============================================================
# 2. SSR 兜底：从主页面 reviewsData 拿「精选观众评论」
# ============================================================
def fetch_ssr_reviews(movie):
    """
    用 requests 直接抓主页面 HTML，解析 data-json="reviewsData" 里的观众评论。
    作用：兜底那些 all-audience 页不显示评论的小众电影（RT 站本身不渲染，
    但主页面 reviewsData 里其实挂着前 6 条精选观众评论）。
    返回 9 列 dict 列表（ratingId 建 comment_id，天然与 DOM 抓的能去重）。
    """
    anime_name = movie["anime_name"]
    slug = movie["slug"]
    page_url = f"https://www.rottentomatoes.com/m/{slug}/reviews/all-audience"
    url = f"https://www.rottentomatoes.com/m/{slug}"

    try:
        r = requests.get(url, headers={"User-Agent": UA}, proxies=PROXIES, timeout=40)
        if r.status_code != 200:
            return []
        m = re.search(r'data-json="reviewsData">(.*?)</script>', r.text, re.S)
        if not m:
            return []
        data = json.loads(m.group(1))
    except Exception as e:
        print(f"  [SSR兜底失败] {anime_name}: {e}")
        return []

    crawl_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    rows = []
    for rv in data.get("reviews", []):
        rid = (rv.get("ratingId") or "").strip()
        if not rid:
            continue
        rows.append({
            "page_url": page_url,
            "anime_name": anime_name,
            "source": "RT",
            "comment_id": f"rt:{rid}",
            "author": rv.get("displayName") or "",
            "post_time": rv.get("displayDate") or "",
            "score": str(rv.get("rating") if rv.get("rating") is not None else ""),
            "crawl_time": crawl_time,
            "content": rv.get("review") or "",
        })
    return rows


# ============================================================
# 3. 单部电影采集（Playwright 翻 all-audience 页）
# ============================================================
def crawl_movie(page, movie, existing):
    """
    采集一部电影的观众评论，返回新抓到的 9 列 dict 列表（已去重）。
    page_url 用该电影的观众评论页链接。
    """
    anime_name = movie["anime_name"]
    slug = movie["slug"]
    page_url = f"https://www.rottentomatoes.com/m/{slug}/reviews/all-audience"

    print(f"\n===== 《{anime_name}》{page_url} =====")

    try:
        page.goto(page_url, wait_until="domcontentloaded", timeout=PAGE_TIMEOUT)
    except PTE:
        print(f"  [跳过] 页面加载超时：{anime_name}")
        return []

    dismiss_consent(page)

    # 等第一张观众评论卡出现（有的小众电影可能 0 条观众评论）
    cards = page.locator("review-card-audience")
    try:
        cards.first.wait_for(state="attached", timeout=CARD_WAIT_TIMEOUT)
    except PTE:
        print(f"  [跳过] 没有观众评论卡片（可能 0 条或页面异常）：{anime_name}")
        return []

    new_rows = []
    seen_this_movie = set()

    while True:
        # 1) 抽取当前已加载的所有卡片
        for c in extract_cards(page):
            rid = c["rating_id"]
            if not rid:  # 缺 rating_id 的评论没法建 comment_id，跳过（几乎不会发生）
                continue
            cid = f"rt:{rid}"
            if cid in existing or cid in seen_this_movie:
                continue
            seen_this_movie.add(cid)
            existing.add(cid)
            new_rows.append({
                "page_url": page_url,
                "anime_name": anime_name,
                "source": "RT",
                "comment_id": cid,
                "author": c["author"],
                "post_time": c["post_time"],
                "score": c["score"],
                "crawl_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "content": c["content"],
            })

        # 2) 找 Load More，没有就说明翻完了
        load_more = page.get_by_text("Load More", exact=False)
        if load_more.count() == 0 or not load_more.first.is_visible():
            break

        # 3) 点 Load More，等新卡片加载出来；没新增就结束
        before = page.locator("review-card-audience").count()
        try:
            load_more.first.click()
            page.wait_for_function(
                "n => document.querySelectorAll('review-card-audience').length > n",
                arg=before,
                timeout=LOAD_MORE_WAIT_TIMEOUT,
            )
        except PTE:
            # 点击后没等到新卡片：要么到底了，要么被挡，结束当前电影
            time.sleep(1)
            break

        time.sleep(SLEEP_AFTER_LOAD_MORE)

    print(f"  《{anime_name}》本次新增 {len(new_rows)} 条")
    return new_rows


# ============================================================
# 4. 主流程
# ============================================================
def main():
    existing = load_existing_ids()
    print(f"已读入 {len(existing)} 条已有 comment_id（续跑去重）")

    targets = MOVIES
    if "--test" in sys.argv:  # 冒烟测试：只跑第一部 Ne Zha
        targets = MOVIES[:1]
        print("[冒烟模式] 只跑 Ne Zha")

    total_new = 0
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=False,                 # 有头模式，配合 UA 更稳
            proxy={"server": PROXY},
        )
        context = browser.new_context(user_agent=UA)
        page = context.new_page()
        page.set_default_timeout(20_000)

        for movie in targets:
            # 1) Playwright 翻 all-audience 页拿全量观众评论
            rows = crawl_movie(page, movie, existing)

            # 2) requests 兜底主页面精选评论（小众电影 all-audience 页是空的，靠这个补）
            ssr_rows = fetch_ssr_reviews(movie)
            for r in ssr_rows:
                if r["comment_id"] not in existing:
                    existing.add(r["comment_id"])
                    rows.append(r)
            if ssr_rows:
                print(f"  《{movie['anime_name']}》SSR 兜底补 {len(ssr_rows)} 条（去重后并入）")

            append_rows(rows)
            total_new += len(rows)
            time.sleep(SLEEP_BETWEEN_MOVIES)

        context.close()
        browser.close()

    print(f"\n全部完成，本次共新增 {total_new} 条 → {OUTPUT_CSV}")


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    main()
