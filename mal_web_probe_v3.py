"""
MAL Web Probe v3 —— 验证 "Show all" 加载机制 + 新结构字段提取（只测 Link Click / 44074）

v2 探针摸清了 MAL 新版结构：
  - 评论容器 = .review-element.js-review-element（不再是 .borderDark）
  - 隐私弹窗 AGREE 按钮 id = #accept-btn
  - 无 URL 分页（?p= 全 0），唯一加载入口 = "Show all" 按钮（.btn-showall）
  - 评论唯一 ID 在 .icon-reaction 的 data-id / permalink reviews.php?id=

v3 要验证：
  1. 正确点掉 AGREE（等弹窗出现再点 #accept-btn）
  2. 初始 .review-element 数（预期 3）
  3. 点击 .btn-showall 后，监听 XHR，看评论怎么加载
  4. 用新结构选择器完整提取字段，验证能拿到
"""
import sys, os, time, json
from pathlib import Path

MAL_ID = 44074  # Link Click
MAL_REVIEW_URL = f"https://myanimelist.net/anime/{MAL_ID}/reviews"
DEBUG_DIR = Path("debug")
LOG_FILE = Path("mal_ajax_log_v3.json")

PROXY = None
try:
    with open(".env", encoding="utf-8") as f:
        for line in f:
            if line.strip().startswith("CLASH_PROXY="):
                PROXY = line.strip().split("=", 1)[1]
except FileNotFoundError:
    pass


def setup():
    os.makedirs(DEBUG_DIR, exist_ok=True)
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass


def wait_and_agree(page, timeout=15000):
    """等隐私弹窗出现，点 AGREE（#accept-btn）。"""
    try:
        page.wait_for_selector("#accept-btn", timeout=timeout)
        page.click("#accept-btn")
        print("  [consent] 已点击 AGREE（#accept-btn）")
        time.sleep(2)
        return True
    except Exception:
        print("  [consent] 未等到 #accept-btn（可能无弹窗或已同意）")
        return False


def count_reviews(page):
    return len(page.query_selector_all(".review-element"))


def collect_mal_xhr(page, log_list):
    """只监听 myanimelist.net 自己的 xhr/fetch（过滤广告域名）。"""
    def on_request(request):
        if request.resource_type not in ("xhr", "fetch"):
            return
        if "myanimelist.net" not in request.url:
            return
        from urllib.parse import urlparse, parse_qs
        parsed = urlparse(request.url)
        log_list.append({
            "phase": "request",
            "url": request.url,
            "path": parsed.path,
            "query": parse_qs(parsed.query),
            "method": request.method,
        })

    def on_response(response):
        if response.request.resource_type not in ("xhr", "fetch"):
            return
        if "myanimelist.net" not in response.url:
            return
        entry = {
            "phase": "response",
            "url": response.url,
            "status": response.status,
            "content_type": response.headers.get("content-type", ""),
        }
        try:
            entry["body_head"] = response.text()[:500]
        except Exception as e:
            entry["body_head"] = f"<read failed: {e}>"
        log_list.append(entry)

    page.on("request", on_request)
    page.on("response", on_response)


def extract_review(container):
    """按 MAL 新版结构提取一条评论的字段。"""
    def text(sel):
        el = container.query_selector(sel)
        if not el:
            return ""
        # 用 textContent 拿到 display:none 折叠里的内容
        return (el.text_content() or "").strip()

    review = {}

    # 评论者
    review["reviewer"] = text(".username a")

    # 日期
    review["review_date"] = text(".update_at")

    # 正文（.text 的 textContent 已含 js-hidden 折叠内容）
    review["review_text"] = text(".text")[:3000]

    # 标签（Recommended / Mixed Feelings / Not Recommended）
    review["review_label"] = text(".tag")

    # 评分（.rating .num，父级 display:none，textContent 仍能拿到）
    review["review_score"] = text(".rating .num")

    # 有用数（data-reactions JSON 的 num）
    helpful = ""
    try:
        raw = container.get_attribute("data-reactions")
        if raw:
            helpful = str(json.loads(raw).get("num", ""))
    except Exception:
        pass
    review["helpful_count"] = helpful

    # 唯一 ID（.icon-reaction 的 data-id）
    rid = ""
    try:
        el = container.query_selector(".icon-reaction")
        if el:
            rid = el.get_attribute("data-id") or ""
    except Exception:
        pass
    if not rid:
        # 兜底：permalink reviews.php?id=
        link = container.query_selector("a[href*='reviews.php?id=']")
        if link:
            href = link.get_attribute("href") or ""
            rid = href.split("reviews.php?id=")[1].split("&")[0]
    review["review_id"] = rid

    return review


def main():
    setup()
    from playwright.sync_api import sync_playwright

    network_log = []

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=False)
        context_kwargs = {}
        if PROXY:
            context_kwargs["proxy"] = {"server": PROXY}
        context = browser.new_context(**context_kwargs)
        page = context.new_page()

        collect_mal_xhr(page, network_log)

        try:
            print(f"目标：Link Click (MAL {MAL_ID})")
            print("=" * 60)

            print("\n[1] 打开页面...")
            page.goto(MAL_REVIEW_URL, wait_until="domcontentloaded", timeout=40000)

            print("\n[2] 处理隐私弹窗（等 #accept-btn）...")
            wait_and_agree(page)

            # 等评论渲染
            print("\n[3] 等待评论渲染...")
            page.wait_for_selector(".review-element", timeout=15000)
            time.sleep(3)
            n_before = count_reviews(page)
            print(f"    点击 Show all 前 .review-element 数 = {n_before}")

            # 提取第一条评论做字段验证
            print("\n[4] 提取第一条评论字段（新结构）...")
            first = page.query_selector(".review-element")
            if first:
                r = extract_review(first)
                for k, v in r.items():
                    print(f"    {k}: {v[:80] if isinstance(v, str) else v}")

            # 点 Show all
            print("\n[5] 点击 'Show all'（.btn-showall）...")
            try:
                page.click(".btn-showall", timeout=10000)
                print("    已点击 Show all，等待 8 秒加载...")
                time.sleep(8)
            except Exception as e:
                print(f"    点击 Show all 失败：{e}")

            n_after = count_reviews(page)
            print(f"    点击后 .review-element 数 = {n_after}")

            # 截图 + HTML
            page.screenshot(path=str(DEBUG_DIR / "link_click_v3_after_showall.png"), full_page=False)
            (DEBUG_DIR / "link_click_v3_after_showall.html").write_text(page.content(), encoding="utf-8")
            print("    已保存 debug 截图 + HTML")

        except Exception as e:
            print(f"\n[FATAL] {e}")
            try:
                page.screenshot(path=str(DEBUG_DIR / "link_click_v3_fatal.png"))
            except Exception:
                pass
        finally:
            browser.close()

    with open(LOG_FILE, "w", encoding="utf-8") as f:
        json.dump(network_log, f, ensure_ascii=False, indent=2)

    print("\n" + "=" * 60)
    print(f"MAL 自己的 xhr/fetch 请求共 {len(network_log)} 条")
    seen = set()
    for e in network_log:
        if e["phase"] == "request" and e["url"] not in seen:
            seen.add(e["url"])
            print(f"  [{e['method']}] {e['url']}")
    print(f"日志已保存 → {LOG_FILE}")
    print("=" * 60)


if __name__ == "__main__":
    main()
