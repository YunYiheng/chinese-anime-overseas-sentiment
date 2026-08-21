# -*- coding: utf-8 -*-
"""
AniList 官方 API 采集器 v2 —— 保底数据源
- 不走浏览器、不撞风控：直接调 https://graphql.anilist.co 的公开 GraphQL API
- 对作品池每部动漫，拉取 Reviews 长文评测（正文 + 评分 + 作者 + 时间），支持分页
- 落 CSV：anilist_data.csv，字段对齐 Reddit 爬虫，周报可直接合并分析
    page_url, anime_name, source, comment_id, author, post_time, score, crawl_time, content
说明：
  - 只用 Python 自带 urllib，不额外装包
  - 必须带浏览器 User-Agent，否则 AniList 返回 403
  - 作品可指定 id（最稳）或 search（按标题搜）。已确认的 id：
      Link Click=126403（AniList 上约 500 条评测，是主要数据源）
      其余作品评测很少或为 0，属于真实现状
"""
import sys
import csv
import json
import time
import urllib.request
from datetime import datetime

sys.stdout.reconfigure(encoding="utf-8")

API = "https://graphql.anilist.co"

# 浏览器 UA：不带它 AniList 直接 403
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36")

# ============ 作品池：name 用于 CSV 的 anime_name 列；id 优先，没有 id 就走 search ============
WORKS = [
    {"name": "RMJI", "search": "Fanren Xiu Xian Zhuan"},          # 搜日文转写才是正片(id=115844)，英文长标题会匹配到番外
    {"name": "Link Click", "id": 126403},                          # 评测最多的金矿，固定 id
    {"name": "Ling Cage", "search": "Ling Cage"},
    {"name": "Ne Zha", "search": "Ne Zha"},
    {"name": "Ne Zha 2", "search": "Ne Zha 2"},
    {"name": "Soul Land", "search": "Soul Land"},
    {"name": "Battle Through the Heavens", "search": "Battle Through the Heavens"},
]

MAX_PAGES = 4   # 每部作品最多翻 4 页评测（每页 25 条），Link Click 能拿到约 100 条

# ============ GraphQL：一部作品按 id 或标题查 Reviews，分页 ============
QUERY = """
query($id: Int, $search: String, $page: Int) {
  Media(id: $id, search: $search, type: ANIME) {
    id
    title { romaji english native }
    siteUrl
    reviews(page: $page, perPage: 25, sort: RATING_DESC) {
      pageInfo { total hasNextPage }
      nodes {
        id
        siteUrl
        rating
        score
        summary
        body(asHtml: false)
        createdAt
        user { name }
      }
    }
  }
}
"""

OUT_CSV = "anilist_data.csv"


def anilist_query(variables, retries=3):
    """发一个 GraphQL 请求；遇到限流/报错会等待后重试"""
    body = json.dumps({"query": QUERY, "variables": variables}).encode("utf-8")
    req = urllib.request.Request(
        API,
        data=body,
        headers={"Content-Type": "application/json", "Accept": "application/json",
                 "User-Agent": UA},
    )
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            print(f"    HTTP {e.code}，等 30s 重试 ({attempt + 1}/{retries})")
            time.sleep(30)
            continue
        except Exception as e:
            print(f"    请求失败: {type(e).__name__}: {e}")
            time.sleep(5)
            continue

        if "errors" in data:
            msg = data["errors"][0].get("message", "")
            print(f"    API 报错: {msg}")
            if "Too Many" in msg or "Rate" in msg:
                time.sleep(30)
                continue
            return None
        return data.get("data", {}).get("Media")
    return None


def unix_to_iso(ts):
    return datetime.fromtimestamp(ts).isoformat(timespec="seconds") if ts else ""


def main():
    rows = []
    for w in WORKS:
        name = w["name"]
        # 构造查询变量：有 id 用 id，没有用 search
        vars_base = {}
        if w.get("id"):
            vars_base["id"] = w["id"]
        else:
            vars_base["search"] = w["search"]

        print(f"\n>>> 采集: {name}")
        first = anilist_query({**vars_base, "page": 1})
        if not first or not first.get("id"):
            print("    未找到作品，跳过")
            continue

        title = first.get("title") or {}
        shown = title.get("english") or title.get("romaji") or title.get("native")
        total = (first.get("reviews") or {}).get("pageInfo", {}).get("total", 0)
        print(f"    匹配到: {shown} (id={first['id']}) {first.get('siteUrl')}  | 评测总量: {total}")
        now = datetime.now().isoformat(timespec="seconds")

        # 分页收集评测
        all_nodes = []
        for page in range(1, MAX_PAGES + 1):
            media = anilist_query({**vars_base, "page": page})
            if not media:
                break
            nodes = (media.get("reviews") or {}).get("nodes") or []
            all_nodes.extend(nodes)
            has_next = (media.get("reviews") or {}).get("pageInfo", {}).get("hasNextPage")
            if not has_next or not nodes:
                break
            time.sleep(1.5)   # 页之间限速

        print(f"    本批拉到评测: {len(all_nodes)} 条")
        for r in all_nodes:
            content = (r.get("summary") or "") + "\n\n" + (r.get("body") or "")
            rows.append([
                r.get("siteUrl") or "",
                name,
                "AniList",
                f"review:{r.get('id')}",
                (r.get("user") or {}).get("name") or "",
                unix_to_iso(r.get("createdAt")),
                r.get("score") or "",
                now,
                content.strip(),
            ])

        time.sleep(1.5)   # 作品之间限速

    # 落 CSV（utf-8-sig，Excel 打开不乱码）
    with open(OUT_CSV, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(["page_url", "anime_name", "source", "comment_id",
                         "author", "post_time", "score", "crawl_time", "content"])
        writer.writerows(rows)

    print(f"\n完成: 共 {len(rows)} 条 -> {OUT_CSV}")


if __name__ == "__main__":
    main()
