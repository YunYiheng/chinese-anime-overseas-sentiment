# -*- coding: utf-8 -*-
"""
Reddit 批量评论采集器（PRAW 官方 API 版）

特点：
1. 不再启动浏览器，不会遇到网页端“Verify you are human”图片验证。
2. 沿用原作品池，按帖子 URL 批量采集。
3. 凭据从 .env / 系统环境变量读取，不写进代码。
4. 每抓完一个帖子就追加保存，程序中断后可继续，comment_id 自动去重。
5. 可通过 ONLY_TOP_LEVEL 决定只抓顶层评论，还是包含嵌套回复。

安装：
    pip install praw python-dotenv

运行前：
    复制 .env.example 为 .env，填入重新生成的 Reddit API 凭据。
"""

from __future__ import annotations

import csv
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import praw
import prawcore
from dotenv import load_dotenv

# 修复 Windows 控制台输出特殊字符时报 GBK 编码错误。
try:
    sys.stdout.reconfigure(encoding="utf-8")
except AttributeError:
    pass

# 加载脚本同目录下的 .env。
BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

CLIENT_ID = os.getenv("REDDIT_CLIENT_ID", "").strip()
CLIENT_SECRET = os.getenv("REDDIT_CLIENT_SECRET", "").strip()
USER_AGENT = os.getenv("REDDIT_USER_AGENT", "").strip()

# 每个 MoreComments 的展开都可能产生额外 API 请求。
# 10 对周报采样通常已经够用；设为 None 会尽量展开全部，但耗时和请求量明显增加。
EXPAND_MORE_LIMIT: int | None = 10

# True：保持与原 Playwright 脚本一致，只抓顶层评论。
# False：抓顶层评论及其所有已展开回复，并额外记录 is_top_level / parent_id。
ONLY_TOP_LEVEL = False

# 帖子之间保留少量间隔。PRAW 本身也会根据 Reddit 返回的速率限制进行等待。
POST_DELAY_SECONDS = 3
MAX_RETRIES = 3
OUT_CSV = BASE_DIR / "reddit_comments_api.csv"


# ============ 作品池：沿用你原来收集的帖子 URL ============
POSTS = [
    # 凡人修仙传 RMJI
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
    # Ne Zha 哪吒
    {
        "url": "https://www.reddit.com/r/boxoffice/comments/1loreko/nezha_2_ends_its_domestic_run_in_china_with/",
        "anime": "Ne Zha",
        "subreddit": "boxoffice",
    },
    {
        "url": "https://www.reddit.com/r/movies/comments/1j2r7x7/ne_zha_2_surpasses_2billion_mark_becomes_first/",
        "anime": "Ne Zha",
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
]

FIELDNAMES = [
    "platform",
    "page_url",
    "post_title",
    "anime_name",
    "subreddit",
    "comment_id",
    "parent_id",
    "is_top_level",
    "author",
    "post_time",
    "score",
    "crawl_time",
    "content",
]


def validate_config() -> None:
    """在发出请求前检查凭据，避免报出难懂的 401。"""
    missing = []
    if not CLIENT_ID:
        missing.append("REDDIT_CLIENT_ID")
    if not CLIENT_SECRET:
        missing.append("REDDIT_CLIENT_SECRET")
    if not USER_AGENT or "yourusername" in USER_AGENT.lower():
        missing.append("REDDIT_USER_AGENT（请包含你的 Reddit 用户名）")

    if missing:
        raise SystemExit(
            "缺少配置：" + "、".join(missing)
            + "\n请复制 .env.example 为 .env，填入重新生成的凭据后再运行。"
        )


def create_reddit() -> praw.Reddit:
    """创建只读 Reddit API 客户端；采集公开内容不需要账号密码。"""
    reddit = praw.Reddit(
        client_id=CLIENT_ID,
        client_secret=CLIENT_SECRET,
        user_agent=USER_AGENT,
        # Reddit若返回不超过 5 分钟的明确等待时间，允许 PRAW 自动等待。
        ratelimit_seconds=300,
    )
    reddit.read_only = True
    return reddit


def load_existing_ids(path: Path) -> set[str]:
    """读取已有 CSV 的 comment_id，支持断点续采和去重。"""
    if not path.exists():
        return set()

    ids: set[str] = set()
    try:
        with path.open("r", newline="", encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                comment_id = (row.get("comment_id") or "").strip()
                if comment_id:
                    ids.add(comment_id)
    except (OSError, csv.Error) as exc:
        print(f"警告：读取旧 CSV 失败，将从空去重集开始：{exc}")
    return ids


def append_rows(path: Path, rows: list[dict[str, object]]) -> None:
    """每完成一个帖子就落盘，避免中途失败丢失全部结果。"""
    if not rows:
        return

    write_header = not path.exists() or path.stat().st_size == 0
    with path.open("a", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        if write_header:
            writer.writeheader()
        writer.writerows(rows)


def fetch_submission_rows(
    reddit: praw.Reddit,
    post: dict[str, str],
    existing_ids: set[str],
) -> list[dict[str, object]]:
    """抓取单个帖子的评论并转换为统一字段。"""
    submission = reddit.submission(url=post["url"])

    # 先触发帖子数据加载，便于尽早发现 403/404 等问题。
    post_title = submission.title
    submission.comment_sort = "confidence"

    # 展开部分“更多评论”。设为 None 会尽量展开全部，老帖/大帖可能非常慢。
    submission.comments.replace_more(limit=EXPAND_MORE_LIMIT)

    if ONLY_TOP_LEVEL:
        comments = list(submission.comments)
    else:
        comments = submission.comments.list()

    rows: list[dict[str, object]] = []
    crawl_time = datetime.now(timezone.utc).isoformat(timespec="seconds")

    for comment in comments:
        comment_id = str(getattr(comment, "id", "") or "")
        if not comment_id or comment_id in existing_ids:
            continue

        body = str(getattr(comment, "body", "") or "").strip()
        if not body or body in {"[deleted]", "[removed]"}:
            continue

        parent_id = str(getattr(comment, "parent_id", "") or "")
        is_top_level = parent_id.startswith("t3_")
        if ONLY_TOP_LEVEL and not is_top_level:
            continue

        author_obj = getattr(comment, "author", None)
        author = str(author_obj) if author_obj is not None else "[deleted]"
        created_utc = float(getattr(comment, "created_utc", 0.0) or 0.0)
        post_time = (
            datetime.fromtimestamp(created_utc, tz=timezone.utc).isoformat(timespec="seconds")
            if created_utc
            else ""
        )

        rows.append(
            {
                "platform": "reddit",
                "page_url": post["url"],
                "post_title": post_title,
                "anime_name": post["anime"],
                "subreddit": post["subreddit"],
                "comment_id": comment_id,
                "parent_id": parent_id,
                "is_top_level": is_top_level,
                "author": author,
                "post_time": post_time,
                "score": int(getattr(comment, "score", 0) or 0),
                "crawl_time": crawl_time,
                "content": body,
            }
        )
        existing_ids.add(comment_id)

    return rows


def main() -> None:
    validate_config()
    reddit = create_reddit()
    existing_ids = load_existing_ids(OUT_CSV)

    print(f"API 客户端已初始化，read_only={reddit.read_only}")
    print(f"输出文件：{OUT_CSV}")
    print(f"已有评论 ID：{len(existing_ids)} 条")

    success_posts = 0
    failed_posts = 0
    new_comments = 0

    for index, post in enumerate(POSTS, start=1):
        print(
            f"\n[{index}/{len(POSTS)}] 抓取：{post['anime']} "
            f"(r/{post['subreddit']})"
        )

        for attempt in range(1, MAX_RETRIES + 1):
            try:
                rows = fetch_submission_rows(reddit, post, existing_ids)
                append_rows(OUT_CSV, rows)
                print(f"    新增 {len(rows)} 条评论")
                new_comments += len(rows)
                success_posts += 1
                break

            except prawcore.exceptions.NotFound:
                print("    跳过：帖子不存在或已删除（404）")
                failed_posts += 1
                break
            except prawcore.exceptions.Forbidden:
                print("    跳过：帖子/社区不可公开访问（403）")
                failed_posts += 1
                break
            except (
                prawcore.exceptions.RequestException,
                prawcore.exceptions.ResponseException,
                prawcore.exceptions.ServerError,
                prawcore.exceptions.TooManyRequests,
            ) as exc:
                if attempt >= MAX_RETRIES:
                    print(f"    失败：重试 {MAX_RETRIES} 次后仍异常：{type(exc).__name__}")
                    failed_posts += 1
                    break
                wait_seconds = 5 * (2 ** (attempt - 1))
                print(
                    f"    临时异常 {type(exc).__name__}，"
                    f"{wait_seconds} 秒后第 {attempt + 1} 次尝试..."
                )
                time.sleep(wait_seconds)
            except Exception as exc:
                print(f"    跳过：未预期异常 {type(exc).__name__}: {exc}")
                failed_posts += 1
                break

        time.sleep(POST_DELAY_SECONDS)

    print("\n========== 采集完成 ==========")
    print(f"成功帖子：{success_posts}")
    print(f"失败帖子：{failed_posts}")
    print(f"本次新增评论：{new_comments}")
    print(f"结果文件：{OUT_CSV}")


if __name__ == "__main__":
    main()
