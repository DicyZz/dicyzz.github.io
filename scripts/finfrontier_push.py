import os
import sys
import re
import time
import smtplib
from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import requests
import feedparser
import markdown
from premailer import transform
from openai import OpenAI

# ---------------------------------------------------------------------------
# 读取环境变量
# ---------------------------------------------------------------------------
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY")
DEEPSEEK_MODEL = os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-flash")
EMAIL_HOST = os.environ.get("EMAIL_HOST", "smtp.gmail.com")

try:
    EMAIL_PORT = int(os.environ.get("EMAIL_PORT", "465"))
except ValueError:
    EMAIL_PORT = 465

EMAIL_SENDER = os.environ.get("EMAIL_SENDER", "")
EMAIL_PASSWORD = os.environ.get("EMAIL_PASSWORD", "")
EMAIL_RECEIVER = os.environ.get("EMAIL_RECEIVER", "")

# ---------------------------------------------------------------------------
# 1. 各模块 Top 顶级数据源全量配置（按简报四板块组织）
# ---------------------------------------------------------------------------
# 各方向模块每源抓取上限（差异化，平衡四方向）
CATEGORY_MAX_ITEMS = {
    "Macro_Markets": 6,
    "Quant_Trading": 8,
    "Fintech": 6,
    "Crypto": 8,
}

MODULE_FEEDS = {
    # === 宏观与市场 ===
    "Macro_Markets": {
        "CNBC Top News": "https://www.cnbc.com/id/100003114/device/rss/rss.html",
        "MarketWatch Top Stories": "http://feeds.marketwatch.com/marketwatch/topstories/",
        "Financial Times Home": "https://www.ft.com/rss/home",
        "Bloomberg Markets": "https://feeds.bloomberg.com/markets/news.rss",
        "ArXiv General Finance (q-fin.GN/EC)": "https://export.arxiv.org/api/query?search_query=cat:q-fin.GN+OR+cat:q-fin.EC&sortBy=submittedDate&sortOrder=descending&max_results=15",
    },

    # === 量化与算法交易 ===
    "Quant_Trading": {
        "Quantocracy": "https://quantocracy.com/feed/",
        "QuantPedia": "https://quantpedia.com/feed/",
        "Alpha Architect": "https://alphaarchitect.com/feed/",
        "ArXiv Quant Methods (q-fin.TR/PM/ST/CP/MF/PR/RM)": "https://export.arxiv.org/api/query?search_query=cat:q-fin.TR+OR+cat:q-fin.PM+OR+cat:q-fin.ST+OR+cat:q-fin.CP+OR+cat:q-fin.MF+OR+cat:q-fin.PR+OR+cat:q-fin.RM&sortBy=submittedDate&sortOrder=descending&max_results=20",
    },

    # === 金融科技 ===
    "Fintech": {
        "The Fintech Times": "https://thefintechtimes.com/feed/",
    },

    # === 加密与数字资产 ===
    "Crypto": {
        "CoinDesk": "https://www.coindesk.com/arc/outboundfeeds/rss/",
        "CoinTelegraph": "https://cointelegraph.com/rss",
        "Decrypt": "https://decrypt.co/feed",
    },
}

def clean_html_summary(html_text):
    """清洗 HTML 标签，提炼纯文本"""
    if not html_text:
        return ""
    clean_text = re.sub(r'<[^>]+>', ' ', html_text)
    clean_text = re.sub(r'\s+', ' ', clean_text).strip()
    return clean_text[:400]

def is_recent_entry(entry, max_hours=168):
    """检查文章是否在最近 max_hours 小时内发布"""
    published_struct = entry.get("published_parsed") or entry.get("updated_parsed")
    if not published_struct:
        return True
    try:
        pub_time = datetime.fromtimestamp(time.mktime(published_struct), tz=timezone.utc)
        now_time = datetime.now(timezone.utc)
        return (now_time - pub_time) <= timedelta(hours=max_hours)
    except Exception:
        return True

def fetch_single_feed(source_name, feed_url, category, max_items=6):
    """单源抓取函数（增加超时与 7 天时间过滤）"""
    if not feed_url.startswith("http"):
        feed_url = "https://" + feed_url

    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) FinFrontierBot/1.0'}
    
    try:
        resp = requests.get(feed_url, headers=headers, timeout=8)
        if resp.status_code != 200:
            print(f"⚠️ 源抓取失败 [{source_name}] 状态码 {resp.status_code}")
            return []
        
        feed = feedparser.parse(resp.content)
        fetched_items = []
        count = 0

        for entry in feed.entries:
            if not is_recent_entry(entry, max_hours=168):
                continue

            if count >= max_items:
                break

            title = entry.get("title", "").strip()
            link = entry.get("link", "").strip()
            summary = clean_html_summary(entry.get("summary", entry.get("description", "")))
            
            if title:
                fetched_items.append(
                    f"【模块: {category} | 平台源: {source_name}】\n"
                    f"标题: {title}\n"
                    f"链接: {link}\n"
                    f"摘要: {summary}\n"
                )
                count += 1
        return fetched_items
    except Exception as e:
        print(f"⚠️ 源抓取异常 [{source_name}] {type(e).__name__}: {e}")
        return []

def fetch_all_feeds():
    """并发并行抓取全量 RSS 订阅点"""
    print("1. 正在通过并发线程池拉取全球金融数据源（含超时控制与 7 天过滤）...")
    raw_articles = []
    
    with ThreadPoolExecutor(max_workers=25) as executor:
        future_to_source = {}
        for category, feeds in MODULE_FEEDS.items():
            max_items = CATEGORY_MAX_ITEMS.get(category, 6)
            for source_name, feed_url in feeds.items():
                future = executor.submit(fetch_single_feed, source_name, feed_url, category, max_items=max_items)
                future_to_source[future] = source_name

        for future in as_completed(future_to_source):
            items = future.result()
            if items:
                raw_articles.extend(items)

    if not raw_articles:
        print("⚠️ 未抓取到 7 天内的新资讯，将使用保底逻辑。")
        return "本周暂无 7 天内的新动态更新。"

    print(f"✅ 成功从权威源中抓取并筛选出 {len(raw_articles)} 条最新资讯！")
    return "\n---\n".join(raw_articles)


# ---------------------------------------------------------------------------
# 2. DeepSeek 生成文字简报
# ---------------------------------------------------------------------------
def generate_briefing():
    real_news_context = fetch_all_feeds()

    print("2. 正在通过 DeepSeek 提炼专业技术简报...")
    if not DEEPSEEK_API_KEY:
        print("❌ 错误：未配置 DEEPSEEK_API_KEY！")
        sys.exit(1)

    client = OpenAI(
        api_key=DEEPSEEK_API_KEY,
        base_url="https://api.deepseek.com"
    )

    exact_iso_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    briefing_prompt = f"""
你是一位极度严谨的金融市场与量化研究编辑。
当前时间：{exact_iso_time}。

### 核心任务：
基于下方【真实抓取数据上下文】，整理一份【FinFrontier 每周金融、量化与市场前沿简报】。

================【真实抓取数据上下文】================
{real_news_context}
======================================================

### 重点关注的主题（优先提炼以下方向）：
1. **宏观经济与央行政策**：利率决议、通胀/就业/GDP 等关键经济数据、央行政策信号、大宗商品与汇率。
2. **量化与算法交易**：因子投资、统计套利、机器学习在金融中的应用、回测与执行算法、组合构建与风控。
3. **金融科技与市场结构**：支付、数字银行、清算结算、监管科技、市场微观结构变化。
4. **加密与数字资产**：BTC/ETH 等主流资产、DeFi、稳定币、ETF、监管与市场结构。
5. **学术研究 (q-fin)**：资产定价、风险建模、市场微观结构、计算金融、金融机器学习；论文按主题归入「宏观与市场」或「量化与算法交易」方向。

### 内容相关性筛选（逐条判定）：
本简报聚焦「金融市场的实质进展与可验证信号」，每条应至少满足以下之一：
- 有明确数据/数字支撑的市场、政策或宏观事件；
- 关于量化策略、因子、风控、金融机器学习的研究或深度技术文章；
- 有实质内容的金融科技或加密数字资产进展。

凡属于以下类型，一律整条剔除：
- 纯营销软文、广告、招聘信息、会议活动通知；
- 无任何数据或实质内容的标题党、重复性摘要；
- 与金融、市场、量化无关的普通公司动态。

### 核心防幻觉与事实审判法则：
1. **客观语气与进展限定**：严禁将“预测”、“推测”、“初步研究”撰写为“已经发生”或“确定结论”；对前瞻性观点必须标注为预期/预测。
2. **区分官方与第三方**：对于分析师观点、民间量化社区、非官方评测，必须明确标注“第三方/机构观点/预测”。
3. **静默跳过法则**：若某个方向在今日抓取数据中完全没有对应资讯，直接静默忽略该方向标题，严禁输出“无相关内容”。
4. **来源链接强制要求**：每条新闻/论文/发布必须在正文中以 Markdown 链接形式附上【真实抓取数据上下文】中的原始链接，格式为 `[原文](链接)`。若某条资讯在上下文中没有链接，或链接与内容对不上，直接整条剔除，严禁凭记忆补写链接、数字或来源名称。
5. **格式规范**：全局严禁使用任何项目符号（`-`、`*`）或数字列表序号（`1.`、`2.`）。代码片段必须包裹在标准 Markdown 代码块中。

---

### 输出结构（参考 Easyperf Newsletter 的 digest 风格，输出纯 Markdown 内容，切勿包裹全局 ```markdown）：

开头先写一行本期导语（不加标题、不加项目符号，直接一行自然句）：
"本期看点：……，以及更多。" 用 3-4 个短语点出本期最值得关注的点。

随后按「金融方向」分区，只保留真实上下文中确实有内容的方向，缺内容的方向整块标题静默删除：

## 宏观与市场 (Macro & Markets)
## 量化与算法交易 (Quant & Trading)
## 金融科技 (Fintech)
## 加密与数字资产 (Crypto & Digital Assets)

每条统一格式（正文段落，禁止用项目符号或编号列表）：
直接用 2-4 句话依次说明「这是什么 → 核心信息/数据 → 可验证的具体数字或事件（有则写准确数字）→ 局限或适用条件（如有）」，末尾统一用 `[原文](原始链接)` 收尾。

来源类型标注：每个方向内可混有官方新闻、量化博客与学术预印本，请在描述中用自然语言点明来源性质——官方发布直接陈述，第三方量化博客标注「第三方/机构观点」，arXiv 论文标注「预印本研究」；切勿把预印本结论写成确定事实。

链接规范（非常重要）：
- 链接文字一律写固定词 `原文`，**严禁用文章标题作为链接文字**。标题常含 `[`、`]`、`(`、`"` 等特殊字符，会破坏 Markdown 解析。
- 若需点明条目标题，在描述正文中用普通文字自然写出即可，不要加粗、不要做成链接。
- 每个板块标题 `##` 必须独占一行，严禁被前一条的链接或正文吞并。

风格要求：
- 每条都必须是「有实质内容的金融/市场进展」，宁可少而精，不要堆砌无关条目。
- 数据必须逐字取自上下文，严禁编造具体数字；对预测类信息明确标注预测属性。
- 可附一句克制的编辑点评，但必须基于上下文、客观中立，禁止编造观点。
- 所有链接必须逐字取自【真实抓取数据上下文】，缺链接或对不上则整条剔除。
"""

    try:
        briefing_response = client.chat.completions.create(
            model=DEEPSEEK_MODEL,
            messages=[
                {"role": "system", "content": "你是一个严谨、苛刻的金融与市场核查编辑。只提炼真实上下文，绝不夸大事实，没有数据的板块直接跳过。"},
                {"role": "user", "content": briefing_prompt}
            ],
            temperature=0.0,
            stream=False
        )

        md_content = briefing_response.choices[0].message.content.strip()
        if md_content.startswith("```markdown"):
            md_content = md_content[11:]
        elif md_content.startswith("```"):
            md_content = md_content[3:]
        if md_content.endswith("```"):
            md_content = md_content[:-3]

        print("✅ 多源简报文字生成成功！")
        return md_content.strip()
    except Exception as e:
        print(f"❌ DeepSeek 生成失败: {str(e)}")
        sys.exit(1)


# ---------------------------------------------------------------------------
# 3. 邮件渲染与发送 (已移除 MP3 附件逻辑)
# ---------------------------------------------------------------------------
def save_briefing_backup(md_content, today_date):
    out_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "output")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, f"finfrontier_{today_date}.md")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(md_content)
    print(f"💾 简报 Markdown 已备份：{out_path}")
    return out_path


def send_email(subject, md_content):
    print("3. 正在渲染适配邮件样式的 HTML 正文...")

    today_date = datetime.now().strftime("%Y-%m-%d")
    save_briefing_backup(md_content, today_date)

    sender = EMAIL_SENDER.strip() if EMAIL_SENDER else ""
    receiver = EMAIL_RECEIVER.strip() if EMAIL_RECEIVER else sender

    if not sender or not EMAIL_PASSWORD:
        print("❌ 错误：缺少邮箱环境变量配置！")
        sys.exit(1)

    raw_html = markdown.markdown(
        md_content,
        extensions=['tables', 'fenced_code', 'codehilite', 'nl2br', 'toc']
    )

    styled_html = f"""
<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <style>
    *, *:before, *:after {{ box-sizing: border-box !important; }}
    body {{
      font-family: -apple-system-font, BlinkMacSystemFont, "Helvetica Neue", "PingFang SC", "Hiragino Sans GB", Arial, sans-serif;
      background-color: #ffffff;
      color: #24292e;
      margin: 0;
      padding: 0;
      width: 100% !important;
    }}
    .container {{
      width: 100% !important;
      margin: 0 auto;
      background: #ffffff;
    }}
    .header {{
      background: linear-gradient(135deg, #0f172a 0%, #1e293b 100%);
      color: #ffffff;
      padding: 24px 16px;
      border-bottom: 3px solid #6366f1;
    }}
    .header h1 {{ margin: 0; font-size: 20px; font-weight: 700; color: #ffffff; }}
    .header .subtitle {{ margin-top: 10px; font-size: 12px; color: #a5b4fc; }}
    .content {{ padding: 16px 12px; font-size: 15px; line-height: 1.75; color: #334155; }}
    h2 {{
      color: #0f172a;
      font-size: 17px;
      background: #f1f5f9;
      border-left: 4px solid #4f46e5;
      padding: 8px 12px;
      margin-top: 36px;
      margin-bottom: 20px;
    }}
    h3 {{ font-size: 16px; color: #0f172a; margin-top: 28px; margin-bottom: 12px; font-weight: 600; border-bottom: 1px solid #e2e8f0; padding-bottom: 6px; }}
    p {{ margin: 12px 0 16px 0; color: #334155; line-height: 1.75; text-align: justify; }}
    a {{ color: #4f46e5 !important; text-decoration: none !important; font-weight: 500 !important; border-bottom: 1px dashed #6366f1 !important; }}
    code {{ background-color: #f1f5f9; color: #4f46e5; padding: 2px 5px; border-radius: 4px; font-size: 88%; font-weight: 600; }}
    pre {{
      background-color: #0f172a !important;
      color: #f8fafc !important;
      padding: 14px !important;
      border-radius: 6px !important;
      overflow-x: auto !important;
      font-size: 12px !important;
      line-height: 1.6 !important;
      margin: 16px 0 !important;
    }}
    pre code {{ background-color: transparent !important; color: #f8fafc !important; padding: 0 !important; }}
    blockquote {{ margin: 20px 0; padding: 12px 14px; color: #1e293b; border-left: 4px solid #4f46e5; background-color: #f8fafc; font-size: 14px; }}
    .footer {{ background-color: #f8fafc; border-top: 1px solid #e2e8f0; padding: 20px 12px; text-align: center; font-size: 12px; color: #94a3b8; }}
  </style>
</head>
<body>
  <div class="container">
    <div class="header">
      <h1>💰 FinFrontier 每周金融、量化与市场前沿简报</h1>
      <div class="subtitle">发布日期：{today_date} | 金融、量化与市场前沿严谨跟踪</div>
    </div>
    <div class="content">
      {raw_html}
    </div>
    <div class="footer">
      基于顶级数据源 & DeepSeek 零幻觉模式构建
    </div>
  </div>
</body>
</html>
"""

    print("4. 正在进行 CSS 内联化转换并发送邮件...")
    inlined_html = transform(styled_html)

    message = MIMEMultipart()
    message["From"] = sender
    message["To"] = receiver
    message["Subject"] = f"{subject} ({today_date})"

    message.attach(MIMEText(inlined_html, "html", "utf-8"))

    try:
        if EMAIL_PORT == 465:
            server = smtplib.SMTP_SSL(EMAIL_HOST, EMAIL_PORT, timeout=20)
        else:
            server = smtplib.SMTP(EMAIL_HOST, EMAIL_PORT, timeout=20)
            server.starttls()

        server.login(sender, EMAIL_PASSWORD.strip())
        server.sendmail(sender, [receiver], message.as_string())
        server.quit()
        print("🎉 简报正文已成功发送至邮箱！")
    except Exception as e:
        print(f"❌ 邮件发送失败: {str(e)}")
        sys.exit(1)


# ---------------------------------------------------------------------------
# 主流程入口
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    md_content = generate_briefing()
    send_email("【FinFrontier】每周金融、量化与市场前沿简报", md_content)
