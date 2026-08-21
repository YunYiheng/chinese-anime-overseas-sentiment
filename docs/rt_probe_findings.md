# RT（Rotten Tomatoes）探针结论

> owner 于 2026-08-13 用 requests + Clash 代理实测，结论如下。**你不需要从零探针，直接照着这个写正式爬虫即可，剩下的唯一 TODO 是分页端点。**

## 1. 结论速览

| 问题 | 结论 |
|------|------|
| 能不能 requests 直连？ | ✅ 能。不需要 Playwright |
| 评论是 SSR 还是 JS 动态加载？ | ✅ **服务端渲染**：评论数据嵌在页面里的 `data-json="reviewsData"` JSON 块里 |
| 反爬？ | 目前没遇到 Cloudflare/验证码，但**必须走代理 + 带 UA + 限速**（RT 对裸 IP 敏感） |
| 分页方式？ | 游标分页（`useCursorPagination = true`），主页面只给前 6 条，其余走 napi 接口 |

## 2. 评论数据在哪

主页面 `https://www.rottentomatoes.com/m/{slug}` 的 HTML 里有这样一段：

```html
<script ... data-json="reviewsData">{"audienceScore":{...},"reviews":[...]}</script>
```

`reviewsData` 是一个 JSON，顶层字段：

```json
{
  "audienceScore": {"reviewCount": 49, "score": "98", "sentiment": "POSITIVE", ...},
  "criticsScore": {"score": "90", ...},
  "reviews": [ ... ],        // 只有前 6 条（首页预览）
  "reviewsUrl": "/m/ne_zha/reviews/all-audience",
  "vanity": {"emsId": "c5aff60d-...", "title": "Ne Zha", "value": "ne_zha"},
  "viewMoreText": "View More"
}
```

单条 review 的字段（**已和 DATA_SPEC 9 列对齐**）：

| RT 字段 | 含义 | 对应 9 列 |
|---------|------|-----------|
| `displayName` | 评论者用户名 | `author` |
| `displayDate` | 发布时间（如 `02/05/2020`） | `post_time` |
| `rating` | 评分（整数 1–5） | `score`（原样存） |
| `ratingRange` | 评分文字（如 `Rated 5/5 Stars`） | 可忽略，或存备注 |
| `ratingId` | 评论唯一 UUID | `comment_id` → 存 `rt:{ratingId}` |
| `review` | 正文（完整） | `content` |
| `isVerified` / `user` | 是否认证用户 | 可忽略 |

`page_url` 用评论页：`https://www.rottentomatoes.com/m/{slug}`（或 `.../reviews/all-audience`）。

## 3. 已确认的电影 URL（requests 实测 200）

| anime_name | RT URL | 状态 |
|------------|--------|------|
| Ne Zha | `/m/ne_zha` | ✅ 200 |
| Ne Zha 2 | `/m/ne_zha_ii`（`/m/ne_zha_2` 会 301 跳转过来） | ✅ |
| White Snake | `/m/white_snake` | ✅ |
| Jiang Ziya | `/m/jiang_ziya` | ✅ |
| New Gods: Nezha Reborn | `/m/new_gods_nezha_reborn` | ✅ |
| New Gods: Yang Jian | `/m/new_gods_yang_jian` | ✅ |
| I Am What I Am | `/m/i_am_what_i_am` | ✅ |
| 长安三万里 | 未找到（`/m/chang_an` 404），站内搜索补 | ❓ |
| 浪浪山小妖怪 | 未找到（`/m/nobody_2024` 404），站内搜索补 | ❓ |

> ⚠️ **命名先和 owner 确认**（DATA_SPEC §2）：`Ne Zha` 和 `Ne Zha 2` 是两个独立 `anime_name`，别合并。新电影命名以 owner 拍板为准。

## 4. 你剩下要做的：分页端点（唯一 TODO）

主页面 `reviewsData.reviews` 只有 **6 条**，但 `audienceScore.reviewCount` 是 49（写文字评论的总数）。要拿全部评论，需要调分页接口。

已排查：

- 全量评论页 `/m/{slug}/reviews/all-audience`：页面 HTML 里 `reviewsData.reviews` 是 **空数组**（0 条），评论是 JS 通过 napi 接口异步拉取的。
- 页面里有 `root.RottenTomatoes.context.review = {..., "emsId":"c5aff60d-...", "useCursorPagination":true}` —— 说明是**游标分页**。
- 试过 `napi/movie/{emsId}/reviews/user`、`/reviews/all`、`/reviews` 都 **404**，说明 napi 需要的不是 emsId，而是**数字 movie id**（页面里没直接暴露，藏在 JS bundle 或另一个 JSON 里）。

**你验证分页的两种办法（任选其一）：**

1. **浏览器抓包**（推荐）：开 DevTools → Network → 在 RT 页面点「View More / 加载更多」，看它实际请求的 URL（形如 `napi/movie/{数字id}/reviews/user?after={cursor}&pageCount=...`），记下请求头里的 `x-` 参数和响应结构。
2. **搜数字 id**：在页面 HTML 里搜 `"id":123456` 这类纯数字、或 `napi/movie/` 字面量，找到正确的 movie id 再试。

拿到正确端点后，分页循环就是「请求 → 取 `pageInfo.endCursor` 作为 `after` → 直到 `pageInfo.hasNextPage=false`」。

## 5. 编码约定（照 DATA_SPEC 和模板）

- CSV `utf-8-sig`；脚本开头 `sys.stdout.reconfigure(encoding="utf-8")`。
- `source = "RT"`，`comment_id = "rt:{ratingId}"`。
- 限速 `time.sleep(1.2)` + 重试 + 按 `comment_id` 续跑去重。
- `score` 原样存 `rating`（整数 1–5），不要归一化。
