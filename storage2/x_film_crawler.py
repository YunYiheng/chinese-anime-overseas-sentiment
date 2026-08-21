# -*- coding: utf-8 -*-
"""
X (Twitter) 电影层评论采集器 —— Dataset B（Animated Film）

采集对象：6 部动画电影（Ne Zha 2 / White Snake / Jiang Ziya /
          New Gods: Nezha Reborn / New Gods: Yang Jian / I Am What I Am）

设计沿用 x_crawler.py（已跑通）：
1. 预算：X API 0.005 美元/条，余额约 2.85 美元 ≈ 570 条
2. 12 个关键词 = 6 部电影 × (英文 lang:en 50条 + 中文 lang:zh 30条)
3. 最坏情况 6×50 + 6×30 = 480 条 ≈ 2.40 美元，留余量
4. 每个关键词只发 1 次请求、不翻页（翻页=持续烧钱）
5. 只能抓最近 7 天（Basic 档 recent search 上限）
6. 排除转发（-is:retweet）、按语言过滤去噪音
7. 表头 9 列与其它平台完全一致
8. 按 comment_id 去重，支持中断续跑
9. 每关键词跑完立即追加保存（中断不丢已爬的）
10. 走 Clash 代理（api.x.com 被墙，需 127.0.0.1:7890）

⚠️ 命名注意：anime_name 必须用 DATA_SPEC 规范名，且 Ne Zha 2 与 Ne Zha
   是两部独立电影，不要合并。
"""
import sys
import time
import csv
import os
from datetime import datetime

sys.stdout.reconfigure(encoding="utf-8")

import requests
from dotenv import load_dotenv

# ============ 密钥与代理（从 .env 读，绝不写进代码） ============
load_dotenv()
BEARER_TOKEN = (os.getenv("X_BEARER_TOKEN") or "").strip()
CLASH_PROXY = (os.getenv("CLASH_PROXY") or "").strip()
if not BEARER_TOKEN:
    raise RuntimeError("没有读取到 X_BEARER_TOKEN，请检查 .env")

API_URL = "https://api.x.com/2/tweets/search/recent"
OUT_CSV = "x_film_data.csv"
HEADER = ["page_url", "anime_name", "source", "comment_id",
          "author", "post_time", "score", "crawl_time", "content"]

PROXIES = None
if CLASH_PROXY:
    PROXIES = {"http": CLASH_PROXY, "https": CLASH_PROXY}
TIMEOUT = 90

# ============ 关键词池 ============
# anime: 写入 CSV 的作品名（DATA_SPEC 规范名）
# query: X 搜索式（精确短语 + 语言过滤 + 排除转发）
# max_results: 单个关键词最多返回条数
#
# 备注（歧义提示，跑之前可微调 query）：
#   - "White Snake" / "I Am What I Am" 英文名较通用，可能混入无关推文，
#     中文名（白蛇缘起 / 雄狮少年）才是高精度信号。
#   - Ne Zha 2 中文有「哪吒之魔童闹海」和「哪吒2」两种写法，这里取正式片名，
#     需要更多可自行加一条 "哪吒2" 关键词（注意预算）。
KEYWORDS = [
    {"anime": "Ne Zha 2",                 "query": '"Ne Zha 2" lang:en -is:retweet',                 "max_results": 50},
    {"anime": "Ne Zha 2",                 "query": '"哪吒之魔童闹海" lang:zh -is:retweet',             "max_results": 30},
    {"anime": "White Snake",              "query": '"White Snake" lang:en -is:retweet',               "max_results": 50},
    {"anime": "White Snake",              "query": '"白蛇缘起" lang:zh -is:retweet',                   "max_results": 30},
    {"anime": "Jiang Ziya",               "query": '"Jiang Ziya" lang:en -is:retweet',                "max_results": 50},
    {"anime": "Jiang Ziya",               "query": '"姜子牙" lang:zh -is:retweet',                     "max_results": 30},
    {"anime": "New Gods: Nezha Reborn",   "query": '"Nezha Reborn" lang:en -is:retweet',              "max_results": 50},
    {"anime": "New Gods: Nezha Reborn",   "query": '"哪吒重生" lang:zh -is:retweet',                   "max_results": 30},
    {"anime": "New Gods: Yang Jian",      "query": '"New Gods: Yang Jian" lang:en -is:retweet',        "max_results": 50},
    {"anime": "New Gods: Yang Jian",      "query": '"新神榜：杨戬" lang:zh -is:retweet',                "max_results": 30},
    {"anime": "I Am What I Am",           "query": '"I Am What I Am" lang:en -is:retweet',            "max_results": 50},
    {"anime": "I Am What I Am",           "query": '"雄狮少年" lang:zh -is:retweet',                   "max_results": 30},
]


def fetch_posts(keyword):
    """发一次请求。返回 (posts, user_map, err_msg)。不翻页。"""
    headers = {
        "Authorization": f"Bearer {BEARER_TOKEN}",
        "User-Agent": "donghua-sentiment-project/1.0",
    }
    params = {
        "query": keyword["query"],
        "max_results": keyword["max_results"],
        "tweet.fields": "created_at,lang,author_id,conversation_id,public_metrics",
        "expansions": "author_id",
        "user.fields": "username,name",
    }
    for attempt in range(3):   # 网络异常/限流最多重试 3 次
        try:
            r = requests.get(API_URL, headers=headers, params=params,
                             proxies=PROXIES, timeout=TIMEOUT)
        except requests.exceptions.RequestException as e:
            if attempt < 2:
                time.sleep(5 * (attempt + 1))
                continue
            return [], {}, f"{type(e).__name__}: {e}"

        if r.status_code == 200:
            d = r.json()
            user_map = {
                u.get("id", ""): u.get("username", "")
                for u in d.get("includes", {}).get("users", [])
            }
            return d.get("data", []), user_map, None

        if r.status_code == 429 and attempt < 2:
            wait = 15 * (attempt + 1)
            print(f"    限流 429，等待 {wait}s 重试...")
            time.sleep(wait)
            continue
        if r.status_code == 403:
            return [], {}, "403 额度或权限不足"
        if r.status_code == 401:
            return [], {}, "401 token 无效"
        if r.status_code == 400:
            return [], {}, "400 查询语法有误"
        return [], {}, f"HTTP {r.status_code}"
    return [], {}, "重试 3 次仍失败"


def load_existing_ids():
    """读已保存 CSV 里的 comment_id，用于去重和续跑"""
    ids = set()
    if os.path.exists(OUT_CSV):
        try:
            with open(OUT_CSV, encoding="utf-8-sig") as f:
                for row in csv.DictReader(f):
                    cid = (row.get("comment_id") or "").strip()
                    if cid:
                        ids.add(cid)
        except Exception:
            pass
    return ids


def main():
    seen = load_existing_ids()
    header_written = os.path.exists(OUT_CSV) and os.path.getsize(OUT_CSV) > 0
    if not header_written:
        with open(OUT_CSV, "w", newline="", encoding="utf-8-sig") as f:
            csv.writer(f).writerow(HEADER)

    summary = []
    for kw in KEYWORDS:
        print(f"\n>>> 关键词: {kw['query']}")
        posts, user_map, err = fetch_posts(kw)
        if err:
            print(f"    失败: {err}")
            summary.append((kw["anime"], kw["query"], 0, err))
            continue

        now = datetime.now().isoformat(timespec="seconds")
        new_rows = []
        for p in posts:
            cid = p.get("id", "")
            if not cid or cid in seen:
                continue
            seen.add(cid)
            author_id = p.get("author_id", "")
            username = user_map.get(author_id, "")
            if username:
                page_url = f"https://x.com/{username}/status/{cid}"
            else:
                page_url = f"https://x.com/i/web/status/{cid}"
            metrics = p.get("public_metrics", {})
            new_rows.append([
                page_url, kw["anime"], "X",
                cid,
                username or author_id,
                p.get("created_at", ""),
                metrics.get("like_count", 0),
                now,
                p.get("text", "").strip(),
            ])

        # 每关键词跑完立即追加保存
        with open(OUT_CSV, "a", newline="", encoding="utf-8") as f:
            csv.writer(f).writerows(new_rows)

        print(f"    返回 {len(posts)} 条，新存 {len(new_rows)} 条（去重后）")
        summary.append((kw["anime"], kw["query"], len(new_rows), "ok"))
        time.sleep(1.5)   # 关键词之间限速

    print(f"\n========== 采集结果 ==========")
    print(f"本次新存 {sum(x[2] for x in summary)} 条 -> {OUT_CSV}")
    for anime, q, cnt, status in summary:
        flag = "✓" if status == "ok" else "✗"
        print(f"  {flag} {anime:<28} {cnt:>3} 条  {status}")


if __name__ == "__main__":
    main()
