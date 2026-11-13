# 网络解锁器 API

[![推广](https://github.com/bright-cn/Awesome-Web-Scraping/raw/main/Proxies%20and%20scrapers%20GitHub%20bonus%20banner%20CN.png)](https://www.bright.cn/) 

[网络解锁器](https://www.bright.cn/products/web-unlocker)是一款功能强大的爬虫 API，可绕过复杂的反爬虫保护，访问任何网站。你无需管理复杂的反机器人基础设施，只需一次 API 调用即可获取整洁的 HTML/JSON 响应。

# 目录
- [功能](#功能)
- [快速开始](#快速开始)
   - [直接访问 API](#直接访问-api)
   - [原生代理访问](#原生代理访问)
- [实践示例：抓取 G2 评论](#实践示例抓取-g2-评论)
   - [基本请求（不使用网络解锁器）](#基本请求不使用网络解锁器)
   - [增强请求（使用网络解锁器）](#增强请求使用网络解锁器)
      - [直接访问 API](#直接访问-api)
      - [代理访问](#代理访问)
      - [等待特定元素](#等待特定元素)
      - [移动端 User-Agent 定向](#移动端-user-agent-定向)
      - [地理位置定向](#地理位置定向)
      - [调试请求](#调试请求)
      - [成功率统计](#成功率统计)
- [最后说明](#最后说明)

## 功能
网络解锁器提供全面的网页爬虫功能：
- 自动代理管理和验证码破解
- 模拟真实用户行为
- 内置 JavaScript 渲染
- 全球地理位置定向
- 自动重试机制
- 按成功请求计费模式

## 快速开始
使用网络解锁器之前，请按照[快速入门指南](https://docs.brightdata.com/scraping-automation/web-unlocker/quickstart)完成设置。

### 直接访问 API
集成网络解锁器的推荐方式。


**示例：cURL 命令**
```bash
curl -X POST "https://api.brightdata.com/request" \
-H "Content-Type: application/json" \
-H "Authorization: Bearer INSERT_YOUR_API_TOKEN" \
-d '{
  "zone": "INSERT_YOUR_WEB_UNLOCKER_ZONE_NAME",
  "url": "http://lumtest.com/myip.json",
  "format": "raw"
}'
```

1. API 端点：`https://api.brightdata.com/request`
2. Authorization 请求头：来自网络解锁器 API 区域的 [API 令牌](https://docs.brightdata.com/scraping-automation/web-unlocker/send-your-first-request#generating-your-bright-data-api-token)
3. 请求载荷：
   - `zone`：你的网络解锁器 API 区域名称
   - `url`：要访问的目标 URL
   - `format`：响应格式（使用 `raw` 获取网站直接响应）

**示例：Python 脚本**
```python
import requests

API_URL = "https://api.brightdata.com/request"
API_TOKEN = "INSERT_YOUR_API_TOKEN"
ZONE_NAME = "INSERT_YOUR_WEB_UNLOCKER_ZONE_NAME"
TARGET_URL = "http://lumtest.com/myip.json"

headers = {
    "Content-Type": "application/json",
    "Authorization": f"Bearer {API_TOKEN}"
}

payload = {
    "zone": ZONE_NAME,
    "url": TARGET_URL,
    "format": "raw"
}

response = requests.post(API_URL, headers=headers, json=payload)

if response.status_code == 200:
    print("Success:", response.text)
else:
    print(f"Error {response.status_code}: {response.text}")
```

### 原生代理访问

使用代理路由的替代方法。

**示例：cURL 命令**
```bash
curl "http://lumtest.com/myip.json" \
--proxy "brd.superproxy.io:33335" \
--proxy-user "brd-customer-<CUSTOMER_ID>-zone-<ZONE_NAME>:<ZONE_PASSWORD>"
```

所需凭据：
1. 客户 ID：可在[账户设置](https://www.bright.cn/cp/setting/customer_details)中找到
2. 网络解锁器 API 区域名称：可在概览选项卡中找到
3. 网络解锁器 API 密码：可在概览选项卡中找到

**示例：Python 脚本**
```python
import requests

customer_id = "<customer_id>"
zone_name = "<zone_name>"
zone_password = "<zone_password>"

host = "brd.superproxy.io"
port = 33335
proxy_url = f"http://brd-customer-{customer_id}-zone-{zone_name}:{zone_password}@{host}:{port}"

proxies = {"http": proxy_url, "https": proxy_url}

response = requests.get("http://lumtest.com/myip.json", proxies=proxies)

if response.status_code == 200:
    print(response.json())
else:
    print(f"Error: {response.status_code}")
```

## 实践示例：抓取 G2 评论
下面看看如何从受 Cloudflare 严密保护的网站 [G2.com](https://www.g2.com/) 抓取评论。

### 基本请求（不使用网络解锁器）
使用简单的 Python 脚本抓取 [G2 评论](https://www.g2.com/products/mongodb/reviews)：
```python
import requests
from bs4 import BeautifulSoup

url = 'https://www.g2.com/products/mongodb/reviews'
response = requests.get(url)

if response.status_code == 200:
    soup = BeautifulSoup(response.text, "lxml")
    headings = soup.find_all('h2')
    
    if headings:
        print("\nHeadings Found:")
        for heading in headings:
            print(f"- {heading.get_text(strip=True)}")
    else:
        print("No headings found")
else:
    print("Request blocked")
```

<strong>结果：</strong>由于 Cloudflare 的反机器人措施，脚本失败（`403` 错误）。


### 增强请求（使用网络解锁器）
要绕过此类限制，请使用网络解锁器。以下是 Python 实现：

#### 直接访问 API
```python
import requests
from bs4 import BeautifulSoup

API_URL = "https://api.brightdata.com/request"
API_TOKEN = "INSERT_YOUR_API_TOKEN"
ZONE_NAME = "INSERT_YOUR_ZONE"
TARGET_URL = "https://www.g2.com/products/mongodb/reviews"

headers = {
    "Content-Type": "application/json",
    "Authorization": f"Bearer {API_TOKEN}"
}
payload = {"zone": ZONE_NAME, "url": TARGET_URL, "format": "raw"}

response = requests.post(API_URL, headers=headers, json=payload)

if response.status_code == 200:
    soup = BeautifulSoup(response.text, "lxml")
    headings = [h.get_text(strip=True) for h in soup.find_all('h2')]
    print("\nExtracted Headings:", headings)
else:
    print(f"Error {response.status_code}: {response.text}")
```
<strong>结果：</strong>成功绕过保护，并以 `200` 状态获取内容。

#### 代理访问
或者，也可以使用代理方式：
```python
import requests
from bs4 import BeautifulSoup

proxy_url = "http://brd-customer-<customer_id>-zone-<zone_name>:<zone_password>@brd.superproxy.io:33335"
proxies = {"http": proxy_url, "https": proxy_url}

url = "https://www.g2.com/products/mongodb/reviews"
response = requests.get(url, proxies=proxies, verify=False)

if response.status_code == 200:
    soup = BeautifulSoup(response.text, "lxml")
    headings = [h.get_text(strip=True) for h in soup.find_all('h2')]
    print("\nExtracted Headings:", headings)
else:
    print(f"Error {response.status_code}: {response.text}")
```

<strong>注意：</strong>添加以下内容以忽略 SSL 证书警告：
```python
from requests.packages.urllib3.exceptions import InsecureRequestWarning
requests.packages.urllib3.disable_warnings(InsecureRequestWarning)
```

#### 等待特定元素
使用 `x-unblock-expect` 请求头等待特定元素或文本：
```python
headers["x-unblock-expect"] = '{"element": ".star-wrapper__desc"}'
# or
headers["x-unblock-expect"] = '{"text": "reviews"}'
```

👉 你可以在 [g2_wait.py](https://github.com/bright-cn/web-unlocker-api/blob/main/src/g2_wait.py) 中查看完整代码

#### 移动端 User-Agent 定向
要使用移动端 User-Agent 而非桌面端 User-Agent，请将 `-ua-mobile` 附加到你的用户名：
```python
username = f"brd-customer-{customer_id}-zone-{zone_name}-ua-mobile"
```
👉 你可以在 [g2_mobile.py](https://github.com/bright-cn/web-unlocker-api/blob/main/src/g2_mobile.py) 中查看完整代码

#### 地理位置定向
虽然网络解锁器会自动选择最佳 IP 位置，但你也可以指定目标位置：
```python
username = f"brd-customer-{customer_id}-zone-{zone_name}-country-us"
username = f"brd-customer-{customer_id}-zone-{zone_name}-country-us-city-sanfrancisco"
```

👉 你可以在[此处](https://docs.brightdata.com/api-reference/proxy/geolocation-targeting)了解更多信息。

#### 调试请求
添加 `-debug-full` 标志以启用详细的调试信息：
```python
username = f"brd-customer-{customer_id}-zone-{zone_name}-debug-full"
```
👉 你可以在 [g2_debug.py](https://github.com/bright-cn/web-unlocker-api/blob/main/src/g2_debug.py) 中查看完整代码

#### 成功率统计
监控特定域名的 API 成功率：
```python
import requests

API_TOKEN = "INSERT_YOUR_API_TOKEN"

def get_success_rate(domain):
    url = f"https://api.brightdata.com/unblocker/success_rate/{domain}"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {API_TOKEN}"
    }
    response = requests.get(url, headers=headers)
    print(response.json() if response.status_code == 200 else response.text)

get_success_rate("g2.com") # Get statistics for specific domain
get_success_rate("g2.*") # Get statistics for all top-level domains
```

## 最后说明
网络解锁器让你可以轻松抓取防护最严密的网站。请牢记以下要点：

1. **不兼容以下工具**：  
   - 浏览器（Chrome、Firefox、Edge）  
   - 防关联浏览器（Adspower、Multilogin）  
   - 自动化工具（Puppeteer、Playwright、Selenium）  

2. **使用抓取浏览器**：  
   如需基于浏览器进行自动化，请使用 Bright Data 的[抓取浏览器](https://www.bright.cn/products/scraping-browser)。

3. **高级域名**：  
   使用[高级域名](https://docs.brightdata.com/scraping-automation/web-unlocker/features#web-unlocker-api-premium-domains)功能访问难以抓取的网站。

4. **CAPTCHA 破解**：  
   系统会自动破解验证码，但你也可以[将其禁用](https://docs.brightdata.com/scraping-automation/web-unlocker/features#disable-captcha-solving)。详细了解 Bright Data 的[验证码破解](https://www.bright.cn/products/web-unlocker/captcha-solver)。
   
5. **自定义请求头和 Cookie**：  
   发送你自己的请求头和 Cookie，以访问特定的网站版本。[了解更多](https://docs.brightdata.com/scraping-automation/web-unlocker/features#manual-headers-and-cookies)。

如需更多详细信息，请访问[官方文档](https://docs.brightdata.com/scraping-automation/web-unlocker/introduction)。
