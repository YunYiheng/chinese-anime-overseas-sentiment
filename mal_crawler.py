"""
MAL 正式爬虫 —— requests 直连 + BeautifulSoup 解析

关键机制（探针 v2/v3 已验证）：
  1. 正确 URL 必须带 slug：https://myanimelist.net/anime/{mal_id}/{slug}/reviews?p={page}
     不带 slug（/anime/{id}/reviews）只返回 3 条缩略视图。
  2. 评论是服务器端渲染，requests 直接 GET 就能拿到完整 HTML，无需 Playwright。
  3. 分页：?p=N，每页 20 条，最后一页 <20 条；?p 越界会回退到第 1 页（需靠去重判断结束）。
  4. 评论容器 = .review-element.js-review-element（MAL 2026 改版，旧 .borderDark 已失效）。

输出：mal_data.csv，9 列与 Reddit/AniList/YouTube/X 完全对齐：
  page_url, anime_name, source, comment_id, author, post_time, score, crawl_time, content
"""
import sys, os, time, csv, json
import requests
from bs4 import BeautifulSoup
from datetime import datetime

# === 7 部作品映射表（MAL ID + slug） ===
WORKS = [
    {"anime_name": "Link Click",    "mal_id": 44074, "slug": "Shiguang_Dailiren"},
    {"anime_name": "RMJI",          "mal_id": 41219, "slug": "Fanren_Xiu_Xian_Zhuan"},
    {"anime_name": "Ling Cage",     "mal_id": 39675, "slug": "Ling_Long__Incarnation"},
    {"anime_name": "Soul Land",     "mal_id": 37150, "slug": "Douluo_Dalu"},
    {"anime_name": "BTTH",          "mal_id": 36491, "slug": "Doupo_Cangqiong"},
    {"anime_name": "Scissor Seven", "mal_id": 38409, "slug": "Cike_Wu_Liuqi"},
    {"anime_name": "Ne Zha",        "mal_id": 40111, "slug": "Nezha_Zhi_Mo_Tong_Jiang_Shi"},
]

OUTPUT_CSV = "mal_data.csv"
FIELDNAMES = ["page_url", "anime_name", "source", "comment_id",
              "author", "post_time", "score", "crawl_time", "content"]

REQUEST_TIMEOUT = 40
SLEEP_BETWEEN_PAGES = 1.2  # 温和限速

# === 读取 Clash 代理（.env） ===
PROXY = None
try:
    with open(".env", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line.startswith("CLASH_PROXY="):
                PROXY = line.split("=", 1)[1]
except FileNotFoundError:
    pass

PROXIES = {"http": PROXY, "https": PROXY} if PROXY else None
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/149.0.0.0 Safari/537.36"
}

session = requests.Session()
session.headers.update(HEADERS)


def fetch_page(url, retries=4):
    """GET 一个 URL，带重试。返回 HTML 文本或 None。"""
    for attempt in range(retries):
        try:
            r = session.get(url, timeout=REQUEST_TIMEOUT, proxies=PROXIES)
            if r.status_code == 200:
                return r.text
            wait = 3 * (attempt + 1)
            print(f"    [status={r.status_code}] 等待 {wait}s 重试...")
            time.sleep(wait)
        except requests.RequestException as e:
            wait = 3 * (attempt + 1)
            print(f"    [网络错误] {e}，等待 {wait}s 重试...")
            time.sleep(wait)
    return None


def parse_review(el):
    """从单个 .review-element 容器提取字段。返回 dict 或 None。"""
    review = {}

    # -- 评论唯一 ID（.icon-reaction 的 data-id，最精确）--
    rid = ""
    icon = el.select_one(".icon-reaction")
    if icon and icon.get("data-id"):
        rid = icon["data-id"]
    if not rid:
        # 兜底：permalink 链接 reviews.php?id=
        link = el.select_one("a[href*='reviews.php?id=']")
        if link:
            href = link.get("href", "")
            if "reviews.php?id=" in href:
                rid = href.split("reviews.php?id=")[1].split("&")[0]
    if not rid:
        return None  # 拿不到 ID 的容器跳过
    review["comment_id"] = f"review:{rid}"
    review["page_url"] = f"https://myanimelist.net/reviews.php?id={rid}"

    # -- 评论者 --
    uname = el.select_one(".username a")
    review["author"] = uname.get_text(strip=True) if uname else ""

    # -- 日期 --
    upd = el.select_one(".update_at")
    review["post_time"] = upd.get_text(strip=True) if upd else ""

    # -- 正文（.text 的 get_text 会包含 style=display:none 的折叠内容）--
    text_el = el.select_one(".text")
    review["content"] = text_el.get_text(" ", strip=True)[:5000] if text_el else ""

    # -- 推荐标签（data-id=1/2/3 才是推荐状态，funny/preliminary 是附加标签）--
    label = ""
    for tag in el.select(".tag"):
        data_id = tag.get("data-id", "")
        if data_id in ("1", "2", "3"):
            label = tag.get_text(" ", strip=True)
            break
    review["label"] = label

    # -- 评分（.rating .num，容器是 display:none，get_text 仍能拿到）--
    num = el.select_one(".rating .num")
    review["score"] = num.get_text(strip=True) if num else ""

    # -- 有用数（data-reactions JSON 的 num）--
    helpful = ""
    raw = el.get("data-reactions")
    if raw:
        try:
            helpful = str(json.loads(raw).get("num", ""))
        except Exception:
            pass
    review["helpful_count"] = helpful

    return review


def load_existing_ids():
    """读现有 mal_data.csv，返回已有 comment_id 集合（用于续跑去重）。"""
    existing = set()
    if os.path.exists(OUTPUT_CSV):
        with open(OUTPUT_CSV, encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                if row.get("comment_id"):
                    existing.add(row["comment_id"])
    return existing


def crawl_work(work, existing_ids):
    """抓取单部作品的全部评论，返回新增行列表。"""
    anime_name = work["anime_name"]
    base = f"https://myanimelist.net/anime/{work['mal_id']}/{work['slug']}/reviews"

    print(f"\n{'='*60}")
    print(f"作品：{anime_name} (MAL {work['mal_id']})")
    print(f"URL ：{base}")
    print(f"{'='*60}")

    rows = []
    page = 1
    seen_this_work = set()

    while True:
        url = f"{base}?p={page}" if page > 1 else base
        html = fetch_page(url)
        if html is None:
            print(f"  [ERROR] 第 {page} 页抓取失败，停止该作品")
            break

        soup = BeautifulSoup(html, "lxml")
        containers = soup.select(".review-element")
        n_this_page = len(containers)

        if n_this_page == 0:
            print(f"  第 {page} 页无评论，停止翻页")
            break

        # 解析本页，统计新增
        new_this_page = 0
        all_seen = True
        for el in containers:
            r = parse_review(el)
            if not r:
                continue
            cid = r["comment_id"]
            if cid in existing_ids or cid in seen_this_work:
                continue  # 已抓过（去重/续跑）
            if cid not in seen_this_work:
                all_seen = False
            seen_this_work.add(cid)
            existing_ids.add(cid)
            row = {
                "page_url": r["page_url"],
                "anime_name": anime_name,
                "source": "MAL",
                "comment_id": cid,
                "author": r["author"],
                "post_time": r["post_time"],
                "score": r["score"],
                "crawl_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "content": r["content"],
            }
            rows.append(row)
            new_this_page += 1

        print(f"  第 {page} 页：{n_this_page} 条容器，新增 {new_this_page} 条")

        # 结束条件：
        # 1) 本页条数 < 20 说明是最后一页
        # 2) 本页所有 id 都已在 seen 里（说明 ?p 越界回退到第 1 页了）
        if n_this_page < 20:
            print(f"  第 {page} 页不足 20 条，已到最后一页，停止")
            break
        if page > 1 and all_seen:
            print(f"  第 {page} 页内容与前面重复（越界回退），停止")
            break

        page += 1
        time.sleep(SLEEP_BETWEEN_PAGES)

    return rows


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    if PROXY:
        print(f"[代理] 使用 Clash 代理 {PROXY}")
    else:
        print("[无代理] 直连")

    existing_ids = load_existing_ids()
    print(f"[续跑] 已有 {len(existing_ids)} 条评论")

    all_rows = []
    for work in WORKS:
        rows = crawl_work(work, existing_ids)
        all_rows.extend(rows)
        time.sleep(1.0)

    # 追加写入 CSV（保留已有 + 新增）
    write_header = not os.path.exists(OUTPUT_CSV)
    with open(OUTPUT_CSV, "a", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        if write_header:
            writer.writeheader()
        for row in all_rows:
            writer.writerow(row)

    print("\n" + "="*60)
    print(f"完成！本次新增 {len(all_rows)} 条")
    print(f"总计（含续跑）: {len(existing_ids)} 条")
    print(f"输出 → {OUTPUT_CSV}")
    print("="*60)


if __name__ == "__main__":
    main()
