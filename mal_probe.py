import time
import os
import requests
import pandas as pd

BASE_URL = "https://api.jikan.moe/v4"

# 读取 .env 中的 Clash 代理配置
PROXY = None
try:
    with open(".env", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line.startswith("CLASH_PROXY="):
                PROXY = line.split("=", 1)[1]
                break
except FileNotFoundError:
    pass

PROXIES = {"http": PROXY, "https": PROXY} if PROXY else None

WORKS = {
    "Link Click": [
        "Shiguang Dailiren",
        "Link Click"
    ],
    "RMJI": [
        "Fanren Xiu Xian Chuan",
        "A Record of a Mortal's Journey to Immortality"
    ],
    "Ling Cage": [
        "Ling Long",
        "Ling Cage"
    ],
    "Soul Land": [
        "Douluo Dalu",
        "Soul Land"
    ],
    "BTTH": [
        "Doupo Cangqiong",
        "Battle Through the Heavens"
    ],
    "Scissor Seven": [
        "Cike Wu Liuqi",
        "Scissor Seven"
    ],
    "Ne Zha": [
        "Ne Zha"
    ]
}


session = requests.Session()

session.headers.update({
    "User-Agent": "ChineseAnimeSentimentResearch/1.0"
})

if PROXY:
    print(f"[代理] 使用 Clash 代理 {PROXY}")
else:
    print("[无代理] 直连")


def request_json(url, params=None, retries=4):
    for attempt in range(retries):
        try:
            r = session.get(
                url,
                params=params,
                timeout=20,
                proxies=PROXIES
            )

            if r.status_code == 200:
                return r.json()

            if r.status_code == 429:
                wait = 5 * (attempt + 1)
                print(f"[429] 限流，等待 {wait}s")
                time.sleep(wait)
                continue

            if r.status_code >= 500:
                wait = 3 * (attempt + 1)
                print(
                    f"[{r.status_code}] 服务端异常，"
                    f"等待 {wait}s"
                )
                time.sleep(wait)
                continue

            print(
                f"[ERROR] status={r.status_code} "
                f"url={r.url}"
            )
            return None

        except requests.RequestException as e:
            wait = 3 * (attempt + 1)
            print(
                f"[NETWORK ERROR] {e}，"
                f"等待 {wait}s"
            )
            time.sleep(wait)

    return None


def search_anime(work_key, query, limit=5):
    print(f"\n搜索：{work_key} | {query}")

    data = request_json(
        f"{BASE_URL}/anime",
        params={
            "q": query,
            "limit": limit
        }
    )

    if not data:
        return []

    rows = []

    for rank, item in enumerate(
        data.get("data", []),
        start=1
    ):
        rows.append({
            "work_key": work_key,
            "search_query": query,
            "candidate_rank": rank,
            "mal_id": item.get("mal_id"),
            "title": item.get("title"),
            "title_english": item.get(
                "title_english"
            ),
            "title_japanese": item.get(
                "title_japanese"
            ),
            "type": item.get("type"),
            "episodes": item.get("episodes"),
            "status": item.get("status"),
            "year": item.get("year"),
            "score": item.get("score"),
            "scored_by": item.get("scored_by"),
            "members": item.get("members"),
            "url": item.get("url")
        })

    return rows


def main():
    all_rows = []

    for work_key, queries in WORKS.items():

        for query in queries:

            rows = search_anime(
                work_key,
                query
            )

            all_rows.extend(rows)

            # 保守一点，避免打满限速
            time.sleep(1.2)

    df = pd.DataFrame(all_rows)

    df.to_csv(
        "mal_probe_candidates.csv",
        index=False,
        encoding="utf-8-sig"
    )

    print("\n========================")
    print("MAL 探针完成")
    print("========================")

    if len(df) == 0:
        print("没有获取到任何候选结果。")
        return

    show_cols = [
        "work_key",
        "search_query",
        "candidate_rank",
        "mal_id",
        "title",
        "title_english",
        "type",
        "episodes",
        "year",
        "score",
        "scored_by"
    ]

    print(
        df[show_cols].to_string(
            index=False
        )
    )

    print(
        "\n已保存：mal_probe_candidates.csv"
    )


if __name__ == "__main__":
    main()