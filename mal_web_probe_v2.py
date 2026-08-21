"""
MAL Web Probe v2 —— 摸清 AJAX 取数机制（只测 Link Click / 44074）

目标（对应 GPT 方案）：
  1. 处理隐私同意弹窗（AGREE）+ 保存 storage_state
  2. 监听所有 XHR / fetch 请求，记录 URL/method/query/status/content-type/body 前若干字符
  3. 先等久一点，判断"上次只拿到 3 条"到底是「懒加载」还是「页面加载慢没渲染完」
  4. 触发滚动 / 找"加载更多"按钮，观察容器数是否变化
  5. dump 分页链接（?p=N）和每条评论的唯一 ID（reviews.php?id=）
"""
import sys, os, time, json
from pathlib import Path

# === 配置 ===
MAL_ID = 44074  # Link Click
MAL_REVIEW_URL = f"https://myanimelist.net/anime/{MAL_ID}/reviews"

DEBUG_DIR = Path("debug")
STATE_DIR = Path("state")
STATE_FILE = STATE_DIR / "mal_state.json"
LOG_FILE = Path("mal_ajax_log.json")

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


def setup():
    """准备工作：目录 + 控制台 UTF-8"""
    os.makedirs(DEBUG_DIR, exist_ok=True)
    os.makedirs(STATE_DIR, exist_ok=True)
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass


def handle_consent(page):
    """
    处理 MAL 隐私同意弹窗。
    MAL 会在页面顶部/中央弹一条 GDPR 横幅，按钮文本通常是 "AGREE"。
    多选择器 + 多文本兜底，找到就点掉。
    返回是否点到了。
    """
    agree_texts = ["AGREE", "Agree", "I agree", "I Agree", "Accept"]
    clicked = False

    # 优先用 role=button 且文本含 agree
    for txt in agree_texts:
        try:
            btn = page.query_selector(f"button:has-text('{txt}')")
            if btn and btn.is_visible():
                btn.click()
                print(f"  [consent] 点击了按钮：'{txt}'")
                clicked = True
                time.sleep(2)
                break
        except Exception:
            continue

    # 兜底：a 标签 / 其他元素
    if not clicked:
        for txt in agree_texts:
            try:
                el = page.query_selector(f"a:has-text('{txt}')")
                if el and el.is_visible():
                    el.click()
                    print(f"  [consent] 点击了链接：'{txt}'")
                    clicked = True
                    time.sleep(2)
                    break
            except Exception:
                continue

    if not clicked:
        print("  [consent] 未发现 AGREE 按钮（可能已同意过 / 无弹窗）")

    return clicked


def collect_network_log(page, log_list):
    """
    注册 page 级监听，把所有 xhr / fetch 请求记录进 log_list。
    记录：URL、method、query 参数、status、content-type、body 前 400 字符。
    """
    def on_request(request):
        if request.resource_type not in ("xhr", "fetch"):
            return
        from urllib.parse import urlparse, parse_qs
        parsed = urlparse(request.url)
        log_list.append({
            "phase": "request",
            "url": request.url,
            "path": parsed.path,
            "query": parse_qs(parsed.query),
            "method": request.method,
            "resource_type": request.resource_type,
            "post_data": (request.post_data or "")[:500],
        })

    def on_response(response):
        if response.request.resource_type not in ("xhr", "fetch"):
            return
        entry = {
            "phase": "response",
            "url": response.url,
            "status": response.status,
            "content_type": (response.headers.get("content-type", "") or ""),
        }
        # 尝试抓 body 前若干字符（判断是 JSON 还是 HTML fragment）
        try:
            body = response.text()
            entry["body_head"] = body[:400]
        except Exception as e:
            entry["body_head"] = f"<read failed: {e}>"
        log_list.append(entry)

    page.on("request", on_request)
    page.on("response", on_response)


def count_review_containers(page):
    """数当前页面里有多少个 .borderDark 评论容器"""
    return len(page.query_selector_all(".borderDark"))


def dump_links(page):
    """dump 页面里所有 <a>，找出分页链接和评论唯一 ID 链接"""
    from urllib.parse import urlparse, parse_qs
    links = page.evaluate("""
        () => Array.from(document.querySelectorAll('a')).map(a => ({
            text: (a.innerText || '').trim().slice(0, 40),
            href: a.href
        }))
    """)
    pagination = []
    review_ids = []
    for l in links:
        href = l.get("href", "")
        if "reviews.php?id=" in href:
            # 评论唯一 ID：reviews.php?id=xxxx
            rid = href.split("reviews.php?id=")[1].split("&")[0]
            review_ids.append(rid)
        if "/reviews" in href and "p=" in href:
            pagination.append(href)
        # 也记录纯 ?p=N 形式
        if "?p=" in href:
            parsed = urlparse(href)
            q = parse_qs(parsed.query)
            if "p" in q:
                pagination.append(href)
    # 去重保序
    pagination = list(dict.fromkeys(pagination))
    review_ids = list(dict.fromkeys(review_ids))
    return pagination, review_ids


def dump_buttons(page):
    """dump 页面里所有 button 文本，找"加载更多"类按钮"""
    return page.evaluate("""
        () => Array.from(document.querySelectorAll('button')).map(b =>
            (b.innerText || b.getAttribute('aria-label') || '').trim().slice(0, 50)
        ).filter(t => t)
    """)


def main():
    setup()
    from playwright.sync_api import sync_playwright

    network_log = []  # 存放所有 xhr/fetch 记录

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=False)

        # 如果已有 storage_state 就用（跳过同意）
        context_kwargs = {}
        if PROXY:
            context_kwargs["proxy"] = {"server": PROXY}
        if STATE_FILE.exists():
            context_kwargs["storage_state"] = str(STATE_FILE)
            print("[state] 发现旧 storage_state，复用（跳过同意）")
        else:
            print("[state] 无 storage_state，首次访问需处理同意弹窗")

        context = browser.new_context(**context_kwargs)
        page = context.new_page()

        # 注册网络监听（必须在 goto 之前）
        collect_network_log(page, network_log)

        try:
            print(f"\n目标：Link Click (MAL {MAL_ID})")
            print(f"URL ：{MAL_REVIEW_URL}")
            print("=" * 60)

            # 1. 打开页面
            print("\n[1] 打开页面...")
            page.goto(MAL_REVIEW_URL, wait_until="domcontentloaded", timeout=40000)
            print(f"    当前 URL: {page.url}")

            # 2. 处理隐私同意弹窗
            print("\n[2] 处理隐私同意弹窗...")
            handle_consent(page)

            # 3. 先等 8 秒（比上次 4 秒久），判断是不是"加载慢"
            print("\n[3] 等待 8 秒，观察容器数...")
            time.sleep(8)
            n_after_wait = count_review_containers(page)
            print(f"    等待 8 秒后 .borderDark 容器数 = {n_after_wait}")

            # 保存一次截图 + HTML
            page.screenshot(path=str(DEBUG_DIR / "link_click_v2_after_wait.png"), full_page=False)
            (DEBUG_DIR / "link_click_v2_after_wait.html").write_text(page.content(), encoding="utf-8")
            print("    已保存 debug 截图 + HTML")

            # 4. dump 分页链接 + review 唯一 ID
            print("\n[4] dump 分页链接 & 评论 ID...")
            pagination, review_ids = dump_links(page)
            print(f"    分页链接（含 p=）: {pagination[:10]}")
            print(f"    reviews.php?id= 评论唯一 ID（前 10）: {review_ids[:10]}")

            # 5. dump 按钮，找"加载更多"
            print("\n[5] dump 按钮文本...")
            buttons = dump_buttons(page)
            print(f"    页面按钮: {buttons}")

            # 6. 触发滚动到底部，看容器数是否增加
            print("\n[6] 滚动到底部，观察是否懒加载...")
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            time.sleep(4)
            n_after_scroll = count_review_containers(page)
            print(f"    滚动后 .borderDark 容器数 = {n_after_scroll}")

            # 7. 尝试点击"加载更多"类按钮
            print("\n[7] 尝试点击'加载更多'类按钮...")
            more_clicked = False
            for txt in ["More", "Load more", "Show more", "See more", "更多"]:
                try:
                    btn = page.query_selector(f"button:has-text('{txt}'), a:has-text('{txt}')")
                    if btn and btn.is_visible():
                        btn.click()
                        print(f"    点击了 '{txt}'，等待 4 秒...")
                        more_clicked = True
                        time.sleep(4)
                        break
                except Exception:
                    continue
            if not more_clicked:
                print("    未找到'加载更多'按钮")

            n_final = count_review_containers(page)
            print(f"    最终 .borderDark 容器数 = {n_final}")

            # 8. dump 一条评论容器的 outerHTML 前 800 字符，找 data 属性里的 ID
            print("\n[8] dump 单条评论容器结构（找唯一 ID / data 属性）...")
            containers = page.query_selector_all(".borderDark")
            if containers:
                sample_html = containers[0].evaluate("el => el.outerHTML")
                print("    第一条容器 outerHTML 前 800 字符：")
                print("    " + sample_html[:800].replace("\n", " ")[:800])
            else:
                print("    无容器可 dump")

            # 9. 保存 storage_state（供下次复用，跳过同意）
            print("\n[9] 保存 storage_state...")
            context.storage_state(path=str(STATE_FILE))
            print(f"    已保存 → {STATE_FILE}")

        except Exception as e:
            print(f"\n[FATAL] {e}")
            try:
                page.screenshot(path=str(DEBUG_DIR / "link_click_v2_fatal.png"))
            except Exception:
                pass

        finally:
            browser.close()

    # 10. 落盘网络日志
    with open(LOG_FILE, "w", encoding="utf-8") as f:
        json.dump(network_log, f, ensure_ascii=False, indent=2)

    # 控制台摘要
    xhr_reqs = [e for e in network_log if e["phase"] == "request"]
    print("\n" + "=" * 60)
    print(f"网络日志共记录 {len(network_log)} 条（xhr/fetch）")
    print(f"其中请求 {len(xhr_reqs)} 条，响应 {len(network_log) - len(xhr_reqs)} 条")
    print("xhr/fetch 请求 URL 一览：")
    seen = set()
    for e in xhr_reqs:
        if e["url"] not in seen:
            seen.add(e["url"])
            print(f"  [{e['method']}] {e['url']}")
    print(f"\n日志已保存 → {LOG_FILE}")
    print("=" * 60)


if __name__ == "__main__":
    main()
