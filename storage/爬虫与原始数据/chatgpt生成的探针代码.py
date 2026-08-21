# -*- coding: utf-8 -*-
"""
X Recent Search API 单关键词探针

功能：
1. 搜索最近 7 天包含指定关键词的公开帖子；
2. 排除转发；
3. 获取正文、作者、时间、点赞数等字段；
4. 自动生成帖子 URL；
5. 输出与 Reddit、AniList、YouTube 对齐的 9 列 CSV。
"""

import csv
import os
import sys
from datetime import datetime

import requests
from dotenv import load_dotenv


# 修复 Windows 控制台无法输出 emoji 的问题
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


# ==================== 基础配置 ====================

load_dotenv()

BEARER_TOKEN = (os.getenv("X_BEARER_TOKEN") or "").strip()
CLASH_PROXY = (os.getenv("CLASH_PROXY") or "").strip()

if not BEARER_TOKEN:
    raise RuntimeError("没有读取到 X_BEARER_TOKEN，请检查 .env 文件")

API_URL = "https://api.x.com/2/tweets/search/recent"

# 第一次只测试 Link Click
ANIME_NAME = "Link Click"

# 不需要在网站搜索框输入，这个字符串由 API 直接执行
QUERY = '"Link Click" -is:retweet'

OUT_CSV = "x_probe.csv"

# 有 Clash 就使用；没有配置则尝试直连
PROXIES = None
if CLASH_PROXY:
    PROXIES = {
        "http": CLASH_PROXY,
        "https": CLASH_PROXY,
    }


# ==================== 请求 API ====================

def fetch_recent_posts() -> dict:
    """调用 X Recent Search API，返回原始 JSON。"""

    headers = {
        "Authorization": f"Bearer {BEARER_TOKEN}",
        "User-Agent": "donghua-sentiment-project/1.0",
    }

    params = {
        "query": QUERY,

        # 探针先只取 10 条；正式脚本可改为 100
        "max_results": 10,

        # 需要返回的帖子字段
        "tweet.fields": ",".join([
            "created_at",
            "lang",
            "author_id",
            "conversation_id",
            "public_metrics",
        ]),

        # 一并获取作者用户名，方便生成帖子网址
        "expansions": "author_id",
        "user.fields": "username,name",
    }

    try:
        response = requests.get(
            API_URL,
            headers=headers,
            params=params,
            proxies=PROXIES,
            timeout=90,
        )
    except requests.exceptions.RequestException as exc:
        raise RuntimeError(
            f"网络请求失败：{type(exc).__name__}: {exc}"
        ) from exc

    print("HTTP 状态码：", response.status_code)

    if response.status_code != 200:
        # 不打印请求头，避免泄露 Bearer Token
        print("接口返回内容：")
        print(response.text[:3000])

        raise RuntimeError(
            f"X API 请求失败，HTTP {response.status_code}"
        )

    return response.json()


# ==================== 解析并保存 ====================

def parse_and_save(payload: dict) -> None:
    """解析 API 返回值，并写入统一字段 CSV。"""

    posts = payload.get("data", [])
    included_users = payload.get("includes", {}).get("users", [])

    # author_id -> username
    user_map = {
        user.get("id", ""): user.get("username", "")
        for user in included_users
    }

    print("本次返回数量：", len(posts))
    print("meta：", payload.get("meta", {}))

    rows = []
    crawl_time = datetime.now().isoformat(timespec="seconds")

    for index, post in enumerate(posts, start=1):
        post_id = post.get("id", "")
        text = post.get("text", "").strip()
        author_id = post.get("author_id", "")
        username = user_map.get(author_id, "")

        metrics = post.get("public_metrics", {})
        like_count = metrics.get("like_count", 0)

        if username:
            page_url = f"https://x.com/{username}/status/{post_id}"
        else:
            page_url = f"https://x.com/i/web/status/{post_id}"

        rows.append({
            "page_url": page_url,
            "anime_name": ANIME_NAME,
            "source": "X",
            "comment_id": post_id,
            "author": username or author_id,
            "post_time": post.get("created_at", ""),
            "score": like_count,
            "crawl_time": crawl_time,
            "content": text,
        })

        print(f"\n========== 第 {index} 条 ==========")
        print("作者：", username or author_id)
        print("时间：", post.get("created_at", ""))
        print("语言：", post.get("lang", ""))
        print("点赞：", like_count)
        print(
            "互动：",
            {
                "reply_count": metrics.get("reply_count", 0),
                "retweet_count": metrics.get("retweet_count", 0),
                "quote_count": metrics.get("quote_count", 0),
            },
        )
        print("网址：", page_url)
        print("正文：", text)

    with open(
        OUT_CSV,
        "w",
        newline="",
        encoding="utf-8-sig",
    ) as file:
        writer = csv.DictWriter(
            file,
            fieldnames=[
                "page_url",
                "anime_name",
                "source",
                "comment_id",
                "author",
                "post_time",
                "score",
                "crawl_time",
                "content",
            ],
        )
        writer.writeheader()
        writer.writerows(rows)

    print(f"\n完成：保存 {len(rows)} 条 -> {OUT_CSV}")


def main() -> None:
    payload = fetch_recent_posts()
    parse_and_save(payload)


if __name__ == "__main__":
    main()