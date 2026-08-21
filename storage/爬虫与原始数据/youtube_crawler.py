# -*- coding: utf-8 -*-
"""
YouTube 评论采集器 v2 —— 对照 12 项要求实现
1. requests 直连 YouTube Data API REST
2. 从 VIDEOS 列表读取 video_id / url / anime
3. 每视频只采顶层评论，最多 30 条
4. order = relevance（相关度排序，取最有代表性的评论）
5. 从 .env 读取 API Key
6. 走 Clash 代理 + 超时 90s（googleapis 被墙且节点慢）
7. 每完成一个视频立即追加保存（中断不丢已爬的）
8. 按 comment_id 去重，支持中断续跑
9. 输出 utf-8-sig CSV（Excel 不乱码）
10. sys.stdout.reconfigure(encoding="utf-8")
11. 不用 search.list，也不采集回复（只 commentThreads 顶层）
12. 字段与 Reddit/AniList 完全统一（9 列一致）
"""
import sys
import time
import csv
import os
import re
from datetime import datetime

sys.stdout.reconfigure(encoding="utf-8")

import requests
from dotenv import load_dotenv

# 密钥从 .env 读取（绝不写进代码）
load_dotenv()
API_KEY = os.getenv("YOUTUBE_API_KEY")
if not API_KEY:
    raise RuntimeError("未读取到 YOUTUBE_API_KEY，请检查 .env")

# Clash 代理：requests 不自动读系统代理，必须显式传
PROXIES = {"http": "http://127.0.0.1:7890", "https": "http://127.0.0.1:7890"}
TIMEOUT = 90   # 节点到 googleapis 较慢，超时给足

API = "https://www.googleapis.com/youtube/v3/commentThreads"
OUT_CSV = "youtube_data.csv"
MAX_COMMENTS = 30   # 每个视频最多取 30 条顶层评论

# 表头：与 Reddit/AniList 完全一致（9 列）
HEADER = ["page_url", "anime_name", "source", "comment_id",
          "author", "post_time", "score", "crawl_time", "content"]

# ============ 视频池：从 候选YouTube视频.txt 整理而来 ============
VIDEOS = [
    {"video_id": "LXDouB-6zMM", "url": "https://www.youtube.com/watch?v=LXDouB-6zMM", "anime": "RMJI"},
    {"video_id": "oAyA5mFt1bI", "url": "https://www.youtube.com/shorts/oAyA5mFt1bI", "anime": "RMJI"},
    {"video_id": "A807VKqZ-y8", "url": "https://www.youtube.com/watch?v=A807VKqZ-y8", "anime": "RMJI"},
    {"video_id": "KUBqBkGrmso", "url": "https://www.youtube.com/watch?v=KUBqBkGrmso", "anime": "Link Click"},
    {"video_id": "hsGpTsQr8O0", "url": "https://www.youtube.com/watch?v=hsGpTsQr8O0", "anime": "Link Click"},
    {"video_id": "DuJK-c08yvs", "url": "https://www.youtube.com/watch?v=DuJK-c08yvs", "anime": "Link Click"},
    {"video_id": "TLA-cfH2kIQ", "url": "https://www.youtube.com/watch?v=TLA-cfH2kIQ", "anime": "Ling Cage"},
    {"video_id": "rqD66LrLYHI", "url": "https://www.youtube.com/watch?v=rqD66LrLYHI", "anime": "Ling Cage"},
    {"video_id": "8lWANgONwYc", "url": "https://www.youtube.com/shorts/8lWANgONwYc", "anime": "Ne Zha"},
    {"video_id": "ETlOSBR92Fs", "url": "https://www.youtube.com/watch?v=ETlOSBR92Fs", "anime": "Ne Zha"},
    {"video_id": "luYBLz35Xy4", "url": "https://www.youtube.com/watch?v=luYBLz35Xy4", "anime": "Ne Zha"},
    {"video_id": "sC0fy3NBl6g", "url": "https://www.youtube.com/watch?v=sC0fy3NBl6g", "anime": "Soul Land"},
    {"video_id": "AtXBtbvNq2c", "url": "https://www.youtube.com/watch?v=AtXBtbvNq2c", "anime": "Soul Land"},
    {"video_id": "dpqsyufBpu4", "url": "https://www.youtube.com/watch?v=dpqsyufBpu4", "anime": "Battle Through the Heavens"},
    {"video_id": "inamzXsjq8c", "url": "https://www.youtube.com/watch?v=inamzXsjq8c", "anime": "Scissor Seven"},
    {"video_id": "5_ozrdp5OXk", "url": "https://www.youtube.com/watch?v=5_ozrdp5OXk", "anime": "Scissor Seven"},
    {"video_id": "YlKvk9v9-as", "url": "https://www.youtube.com/watch?v=YlKvk9v9-as", "anime": "Scissor Seven"},
]


def extract_video_id(url):
    """从各种链接里取出 11 位视频 id（watch?v= / youtu.be / shorts / live / embed）"""
    m = re.search(r"[?&]v=([0-9A-Za-z_-]{11})", url)
    if m:
        return m.group(1)
    m = re.search(r"youtu\.be/([0-9A-Za-z_-]{11})", url)
    if m:
        return m.group(1)
    m = re.search(r"/(?:shorts|live|embed)/([0-9A-Za-z_-]{11})", url)
    if m:
        return m.group(1)
    return url.strip()


def fetch_comments(video_id):
    """调一次 commentThreads（order=relevance，最多 30 条顶层评论）；返回 (rows, err_msg)"""
    params = {
        "part": "snippet",
        "videoId": video_id,
        "maxResults": MAX_COMMENTS,
        "order": "relevance",
        "textFormat": "plainText",
        "key": API_KEY,
    }
    try:
        r = requests.get(API, params=params, proxies=PROXIES, timeout=TIMEOUT)
    except requests.exceptions.RequestException as e:
        return [], f"{type(e).__name__}: {e}"
    if r.status_code == 403:
        return [], "403 配额耗尽 或 评论被关闭(commentsDisabled)"
    if r.status_code == 404:
        return [], "404 视频不存在"
    if r.status_code != 200:
        return [], f"HTTP {r.status_code}"

    data = r.json()
    return data.get("items", []), None


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
    seen = load_existing_ids()   # 已爬过的 comment_id（中断续跑时非空）
    header_written = os.path.exists(OUT_CSV) and os.path.getsize(OUT_CSV) > 0

    # 已有 CSV 则只追加；否则先写表头（utf-8-sig 会带 BOM，Excel 正常识别）
    if not header_written:
        with open(OUT_CSV, "w", newline="", encoding="utf-8-sig") as f:
            csv.writer(f).writerow(HEADER)

    summary = []
    for v in VIDEOS:
        video_id = v.get("video_id") or extract_video_id(v["url"])
        print(f"\n>>> 抓取: {v['anime']}  https://youtu.be/{video_id}")

        items, err = fetch_comments(video_id)
        if err:
            print(f"    失败: {err}")
            summary.append((v["anime"], video_id, 0, err))
            continue

        # 只取顶层评论，过滤掉已爬过的（按 comment_id 去重）
        now = datetime.now().isoformat(timespec="seconds")
        new_rows = []
        for item in items:
            s = item["snippet"]["topLevelComment"]["snippet"]
            cid = item["id"]
            if cid in seen:
                continue
            seen.add(cid)
            new_rows.append([
                v["url"], v["anime"], "YouTube",
                cid,
                s.get("authorDisplayName", ""),
                s.get("publishedAt", ""),
                s.get("likeCount", 0),
                now,
                s.get("textDisplay", ""),
            ])

        # 每完成一个视频立即追加保存
        with open(OUT_CSV, "a", newline="", encoding="utf-8") as f:
            csv.writer(f).writerows(new_rows)

        print(f"    新存 {len(new_rows)} 条（去重后）")
        summary.append((v["anime"], video_id, len(new_rows), "ok"))
        time.sleep(1.5)   # 视频之间限速

    print(f"\n========== 采集结果 ==========")
    print(f"本次新存 {sum(x[2] for x in summary)} 条 -> {OUT_CSV}")
    for anime, vid, cnt, status in summary:
        flag = "✓" if status == "ok" else "✗"
        print(f"  {flag} {anime:<28} {vid:<12} {cnt} 条  {status}")


if __name__ == "__main__":
    main()
