# Bright Data Twitter（X）数据抓取工具

[![宣传图](https://github.com/bright-cn/Awesome-Web-Scraping/raw/main/Proxies%20and%20scrapers%20GitHub%20bonus%20banner%20CN.png)](https://www.bright.cn/products/web-scraper/twitter)

此代码库提供两种不同的 Twitter 数据采集方法：
1. **免费 Twitter 抓取工具**：适用于小型项目和学习
2. [**企业级 Twitter 爬虫工具 API**](https://www.bright.cn/products/web-scraper/twitter)：适用于生产级数据提取

## 目录
1. [免费 Twitter 抓取工具](#免费-twitter-抓取工具)
    - [个人资料抓取](#1-个人资料抓取)
    - [帖子抓取](#2-帖子抓取)
    - [局限性](#局限性)
2. [Twitter 爬虫工具 API](#twitter-爬虫工具-api)
    - [主要功能](#主要功能)
    - [快速入门指南](#快速入门指南)
    - [按 URL 抓取帖子](#1-按-url-抓取帖子)
    - [抓取个人资料数据](#2-抓取个人资料数据)
    - [按日期范围采集推文](#3-按日期范围采集推文)
3. [无代码抓取工具选项](#无代码抓取工具选项)
4. [数据采集方式](#数据采集方式)
5. [支持与资源](#支持与资源)


## 免费 Twitter 抓取工具
非常适合小型项目、实验和学习。

### 1. 个人资料抓取
从 Twitter 提取公开的个人资料数据，包括姓名、关注者数量、推文数量等。

#### 输入要求：
| 参数  | 类型  | 必填 | 说明                          |
|------------|-------|----------|--------------------------------------|
| usernames  | 列表  | 是      | 要抓取的 Twitter 用户名列表   |

#### 实现：
```python
# free_scraper/twitter_profiles.py
usernames = [
    "satyanadella",
    "BillGates", 
    "elonmusk"
]
```

#### 示例输出（CSV）：
<img width="700" alt="twitter_profiles_data" src="https://github.com/bright-cn/twitter-scraper/blob/main/Images/408877618-450d920a-4760-463b-9670-8ac1264b6409.png" />

### 2. 帖子抓取
采集特定推文的互动指标

#### 输入要求：

| 参数  | 类型  | 必填 | 说明                        |
|------------|-------|----------|------------------------------------|
| tweet_ids  | 列表  | 是      | 要抓取的 Twitter 帖子 ID 列表 |

#### 实现：
```python
# free_scraper/twitter_posts.py
TWEET_IDS = [
    "1882412972414214544",
    "1879604491764297992",
    "1869427646368792599"
]
```

#### 示例输出（JSON）：
```json
{
  "tweet_id": "1882412972414214544",
  "author": "MongoDB",
  "content": "We're excited to announce...",
  "engagement": {
    "likes": 29,
    "retweets": 10,
    "views": 3417
  }
}
```

### 局限性
由于 Twitter 具有严格的反爬虫保护，不建议使用免费方法进行大规模抓取。主要局限性包括：
- **速率限制：** 抓取几次后，Twitter 就会阻止请求。
- **IP 封禁：** 频繁使用同一 IP 进行抓取可能导致封禁。
- **扩展能力有限：** 不适合大规模数据采集。
- **数据字段受限：** 仅提供基本的个人资料和推文数据，不支持高级筛选。

## Twitter 爬虫工具 API
这是一种稳健、可扩展且可靠的大规模 Twitter 数据提取解决方案，专为需要高质量实时数据，又不想处理基础设施难题的企业和开发者而设计。

### 主要功能
- **可扩展且可靠：** 针对大规模实时数据采集进行了优化
- **防封锁：** 内置[代理轮换](https://www.bright.cn/solutions/rotating-proxies)和[验证码破解](https://www.bright.cn/products/web-unlocker/captcha-solver)
- **法律合规：** 完全符合 GDPR 和 CCPA 要求
- **全球覆盖：** 可访问任何地区或语言的数据
- **实时数据：** 以极低延迟获取最新数据
- **高级筛选：** 使用精准筛选条件自定义数据提取
- **按使用量付费：** 仅为成功的响应付费
- **免费试用：** 包含 20 次免费 API 调用，助你快速开始
- **专属支持：** 全天候技术支持

👉 **了解更多：** [Bright Data Twitter 爬虫工具 API](https://www.bright.cn/products/web-scraper/twitter)

### 快速入门指南
- **注册：** 创建 [Bright Data 账户](https://www.bright.cn/)
- **获取 API 令牌：** 从控制面板获取你的 [API 密钥](https://docs.brightdata.com/general/account/api-token)
- **选择端点：** 从下方可用的 API 端点中选择

### 1. 按 URL 抓取帖子
使用推文 URL 提取特定推文的详细互动指标和内容。

<img width="700" alt="twitter-posts-scraper" src="https://github.com/bright-cn/twitter-scraper/blob/main/Images/409213804-9d07a475-2e3b-45fc-ae8e-ebcd7cef367b.png" />


#### 请求参数：
| 字段 | 类型   | 必填 | 说明            |
|-------|--------|----------|------------------------|
| `url`   | 字符串 | 是      | 完整的 Twitter 帖子 URL |

#### 请求示例：
```python
# twitter_api/twitter_posts.py
posts = [
    {"url": "https://x.com/OpenAI/status/1885406586136383634"},
    {"url": "https://x.com/CNN/status/1796673270344810776"}
]
```

#### 响应结构：
```json
{
    "post": {
        "author": {
            "name": "OpenAI",
            "followers": 3930255,
            "profileImage": "https://pbs.twimg.com/profile_images/1885410181409820672/ztsaR0JW_normal.jpg",
            "bio": "OpenAI's mission is to ensure that artificial general intelligence benefits all of humanity. We're hiring: https://t.co/dJGr6Lg202",
        },
        "content": {
            "text": "OpenAI o3-mini is now available in ChatGPT and the API.\n\nPro users will have unlimited access to o3-mini and Plus & Team users will have triple the rate limits (vs o1-mini).\n\nFree users can try o3-mini in ChatGPT by selecting the Reason button under the message composer.",
            "postedAt": "2025-01-31T19:15:33.000Z",
            "id": "1885406586136383634",
        },
        "engagement": {
            "replies": 1004,
            "reposts": 1997,
            "likes": 13420,
            "views": 2858777,
            "quotes": 684,
            "bookmarks": 1546,
        },
    }
}
```
👉 此处仅显示关键字段。有关全部详细信息，请查看[完整 JSON 响应](https://github.com/bright-cn/twitter-scraper/blob/main/twitter_data/twitter_posts.json)。立即试用我们的专用 [Twitter 帖子抓取工具](https://www.bright.cn/products/web-scraper/twitter/posts)。

### 2. 抓取个人资料数据
提取全面的个人资料信息，包括近期帖子和互动指标。

<img width="600" alt="twitter-profile-scraper" src="https://github.com/bright-cn/twitter-scraper/blob/main/Images/409214197-3b3e2f0f-30bc-45d9-b9bc-13358b22a55a.png" />

#### 请求参数：

| 字段      | 类型   | 必填 | 说明                     |
|------------|--------|----------|---------------------------------|
| `url`        | 字符串 | 是      | Twitter 个人资料 URL       |
| `max_number_of_posts`  | 数字 | 否       | 要检索的近期帖子数量 |

#### 请求示例：
```python
# twitter_api/twitter_profile_posts.py
profiles = [
    {"url": "https://x.com/satyanadella", "max_number_of_posts": 50},
    {"url": "https://x.com/BillGates", "max_number_of_posts": 35}
]
```

#### 响应结构：
```json
{
    "profile": {
        "name": "Satya Nadella",
        "handle": "satyanadella",
        "role": "Chairman and CEO at Microsoft",
        "isVerified": true,
        "profileImage": "https://pbs.twimg.com/profile_images/1221837516816306177/_Ld4un5A_normal.jpg",
        "website": "http://www.microsoft.com/ceo",
        "joinedDate": "2009-02-11T04:45:34.000Z",
        "stats": {"following": 286, "followers": 3356268, "postsCount": 1859},
    },
    "posts": [
        {
            "id": "1807114709499523208",
            "content": "What a final!!! Congrats, India, and well played, South Africa. Super World Cup... let us have more cricket in the West Indies and USA!!",
            "postedAt": "2024-06-29T18:11:35.000Z",
            "engagement": {
                "replies": 712,
                "reposts": 10785,
                "likes": 133591,
                "views": 2029775,
            },
        },
        {
            "id": "1726509045803336122",
            "content": "We remain committed to our partnership with OpenAI and have confidence in our product roadmap, our ability to continue to innovate with everything we announced at Microsoft Ignite, and in continuing to support our customers and partners. We look forward to getting to know Emmett",
            "postedAt": "2023-11-20T07:53:28.000Z",
            "engagement": {
                "replies": 4524,
                "reposts": 14480,
                "likes": 89773,
                "views": 41675720,
            }
        },
    ],
}
```
👉 此处仅显示关键字段。有关全部详细信息，请查看[完整 JSON 响应](https://github.com/bright-cn/twitter-scraper/blob/main/twitter_data/twitter_profile_posts.json)。立即试用我们的专用 [Twitter 个人资料爬虫工具](https://www.bright.cn/products/web-scraper/twitter/profile)。 

### 3. 按日期范围采集推文
检索指定日期范围内的帖子。

#### 请求参数：

| 参数  | 类型   | 必填 | 说明                   |
|------------|--------|----------|-------------------------------|
| `url`        | 字符串 | 是      | Twitter 个人资料 URL          |
| `start_date` | 字符串 | 是      | 开始日期（ISO 格式）       |
| `end_date`   | 字符串 | 是      | 结束日期（ISO 格式）         |


#### 请求示例：
```python
# twitter_api/twitter_posts_date_range.py
profiles = [
    {
        "url": "https://x.com/satyanadella",
        "start_date": "2025-01-15T09:00:00.000Z",
        "end_date": "2025-01-31T23:00:00.000Z",
    },
    {"url": "https://x.com/cnn", "start_date": "2025-01-01", "end_date": "2025-01-15"},
    {"url": "https://x.com/fabrizioromano", "start_date": "", "end_date": ""},
]
```

#### 响应结构：
```json
{
    "post": {
        "author": {
            "name": "Satya Nadella",
            "handle": "satyanadella",
            "role": "Chairman and CEO at Microsoft",
            "isVerified": false,
            "profileImage": "https://pbs.twimg.com/profile_images/1221837516816306177/_Ld4un5A_normal.jpg",
            "followers": 3356282,
            "following": 286,
        },
        "content": {
            "text": "For me, cricket is maybe the only thing that could possibly come close to watching the Excel World Champ on ESPN!",
            "images": ["https://pbs.twimg.com/media/GiF4nePaEAAHQg5.jpg"],
            "externalUrl": "https://techcommunity.microsoft.com/blog/excelblog/congrats-to-the-winners-of-this-years-mewc--mecc/4355651",
            "postedAt": "2025-01-24T22:29:46.000Z",
            "id": "1882918743409676719",
        },
        "engagement": {
            "replies": 102,
            "reposts": 208,
            "likes": 3416,
            "views": 286901,
            "quotes": 39,
            "bookmarks": 127,
        },
    }
}
```
👉 此处仅显示关键字段。有关全部详细信息，请查看[完整 JSON 响应](https://github.com/bright-cn/twitter-scraper/blob/main/twitter_data/twitter_date_range_posts.json)。

## 无代码抓取工具选项
对于偏好图形界面的用户，我们通过控制面板提供无代码解决方案：

- 几分钟内完成爬虫工具配置
- 自动完成整个数据采集过程
- 直接下载结果（支持多种格式）

有关使用无代码抓取工具的详细说明，请参阅我们的[入门指南](https://github.com/bright-cn/twitter-scraper/blob/main/no-code-scraper.md)。


## 数据采集方式
你可以使用以下参数微调结果：
| **参数**       | **类型**   | **说明**                                            | **示例**                  |
|---------------------|------------|------------------------------------------------------------|------------------------------|
| `limit`             | `integer`  | 每项输入的最大结果数                                   | `limit=10`                   |
| `include_errors`    | `boolean`  | 获取用于故障排除的错误报告                     | `include_errors=true`        |
| `notify`            | `url`      | 用于在完成时接收通知的 Webhook URL  | `notify=https://notify-me.com/` |
| `format`            | `enum`     | 输出格式（例如 JSON、NDJSON、JSONL、CSV）         | `format=json`                |

💡 **专业提示：** 你还可以选择将数据传送到[外部存储](https://docs.brightdata.com/scraping-automation/web-data-apis/web-scraper-api/overview#via-deliver-to-external-storage)，或传送到 [Webhook](https://docs.brightdata.com/scraping-automation/web-data-apis/web-scraper-api/overview#via-webhook)。

## 支持与资源
- **API 文档：** [Bright Data 文档](https://docs.brightdata.com/scraping-automation/web-scraper-api/trigger-a-collection)
- **抓取最佳实践：** [避免被封锁](https://www.bright.cn/blog/web-data/web-scraping-without-getting-blocked)
- **技术支持：** [联系我们](mailto:support@brightdata.com)

---

**对其他抓取工具感兴趣？请查看以下列表：**

- [LinkedIn 抓取工具](https://github.com/bright-cn/LinkedIn-Scraper)
- [Google 新闻爬虫工具](https://github.com/bright-cn/Google-News-Scraper)
- [Google 地图抓取工具](https://github.com/bright-cn/Google-Maps-Scraper)
- [Amazon 爬虫工具](https://github.com/bright-cn/Amazon-Scraper)
