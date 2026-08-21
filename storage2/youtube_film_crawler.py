# -*- coding: utf-8 -*-
"""
YouTube 电影层评论采集器 —— Dataset B（Animated Film）

采集对象：6 部动画电影（Ne Zha 2 / White Snake / Jiang Ziya /
          New Gods: Nezha Reborn / New Gods: Yang Jian / I Am What I Am）

设计沿用 youtube_crawler.py（已跑通）：
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
12. 字段与其它平台完全统一（9 列一致）

⚠️ VIDEOS 里的视频 id 来自 search.list 探针（预告片为主，预告片评论最多）。
   运行前建议核对：视频 id 若失效，脚本会报 404，可自行替换。
   anime_name 必须用 DATA_SPEC 规范名，Ne Zha 2 与 Ne Zha 是两个独立电影。
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
OUT_CSV = "youtube_film_data.csv"
MAX_COMMENTS = 30   # 每个视频最多取 30 条顶层评论

# 表头：与其它平台完全一致（9 列）
HEADER = ["page_url", "anime_name", "source", "comment_id",
          "author", "post_time", "score", "crawl_time", "content"]

# ============ 视频池：6 部电影的预告片/官方片段 ============
VIDEOS = [
    # Ne Zha 2（哪吒之魔童闹海）
    {"video_id": "nsXQijb0F4I", "url": "https://www.youtube.com/watch?v=nsXQijb0F4I", "anime": "Ne Zha 2"},
    {"video_id": "iPZYPWdrta4", "url": "https://www.youtube.com/watch?v=iPZYPWdrta4", "anime": "Ne Zha 2"},
    {"video_id": "6k_V-1Q3JsY", "url": "https://www.youtube.com/watch?v=6k_V-1Q3JsY", "anime": "Ne Zha 2"},
    # White Snake（白蛇缘起）
    {"video_id": "FCY7E0oHW6Y", "url": "https://www.youtube.com/watch?v=FCY7E0oHW6Y", "anime": "White Snake"},
    {"video_id": "JeTy_t4WAfo", "url": "https://www.youtube.com/watch?v=JeTy_t4WAfo", "anime": "White Snake"},
    {"video_id": "k1olZ3xLdz4", "url": "https://www.youtube.com/watch?v=k1olZ3xLdz4", "anime": "White Snake"},
    # Jiang Ziya（姜子牙）
    {"video_id": "3tCbqugFxI8", "url": "https://www.youtube.com/watch?v=3tCbqugFxI8", "anime": "Jiang Ziya"},
    {"video_id": "wc4vZdG3bZ4", "url": "https://www.youtube.com/watch?v=wc4vZdG3bZ4", "anime": "Jiang Ziya"},
    {"video_id": "0l6-2ZOL3tI", "url": "https://www.youtube.com/watch?v=0l6-2ZOL3tI", "anime": "Jiang Ziya"},
    # New Gods: Nezha Reborn（新神榜：哪吒重生）
    {"video_id": "4_FvK9FUG2I", "url": "https://www.youtube.com/watch?v=4_FvK9FUG2I", "anime": "New Gods: Nezha Reborn"},
    {"video_id": "TTa-7m92JLE", "url": "https://www.youtube.com/watch?v=TTa-7m92JLE", "anime": "New Gods: Nezha Reborn"},
    {"video_id": "97YHvquUTtA", "url": "https://www.youtube.com/watch?v=97YHvquUTtA", "anime": "New Gods: Nezha Reborn"},
    # New Gods: Yang Jian（新神榜：杨戬）
    {"video_id": "PFPT24YbaSc", "url": "https://www.youtube.com/watch?v=PFPT24YbaSc", "anime": "New Gods: Yang Jian"},
    {"video_id": "IaELO-4rPnE", "url": "https://www.youtube.com/watch?v=IaELO-4rPnE", "anime": "New Gods: Yang Jian"},
    # I Am What I Am（雄狮少年）
    {"video_id": "212O3pkzfFQ", "url": "https://www.youtube.com/watch?v=212O3pkzfFQ", "anime": "I Am What I Am"},
    {"video_id": "upbIKuT-cFU", "url": "https://www.youtube.com/watch?v=upbIKuT-cFU", "anime": "I Am What I Am"},
    {"video_id": "yWPx15hY6Y6s", "url": "https://www.youtube.com/watch?v=yWPx15hY6Y6s", "anime": "I Am What I Am"},
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
