import os
import sys
import smtplib
from datetime import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from openai import OpenAI
import markdown
from premailer import transform
import feedparser

# 读取环境变量
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY")
EMAIL_HOST = os.environ.get("EMAIL_HOST", "smtp.gmail.com")

try:
    EMAIL_PORT = int(os.environ.get("EMAIL_PORT", "465"))
except ValueError:
    EMAIL_PORT = 465

EMAIL_SENDER = os.environ.get("EMAIL_SENDER", "")
EMAIL_PASSWORD = os.environ.get("EMAIL_PASSWORD", "")
EMAIL_RECEIVER = os.environ.get("EMAIL_RECEIVER", "")

# ---------------------------------------------------------------------------
# 1. 数据采集层：从真实可靠的技术 RSS 源获取最新 Raw Content
# ---------------------------------------------------------------------------
RSS_FEEDS = {
    "LWN (Linux Kernel)": "https://lwn.net/headlines/rss",
    "Phoronix (Hardware/Linux)": "https://www.phoronix.com/rss.php",
    "PyTorch Blog": "https://pytorch.org/feed.xml",
    "ArXiv Computer Architecture (cs.AR)": "http://export.arxiv.org/rss/cs.AR",
    "ArXiv Distributed Computing (cs.DC)": "http://export.arxiv.org/rss/cs.DC",
}

def fetch_real_tech_news(max_items_per_feed=3):
    """从真实 RSS 源拉取最新的文章标题和摘要，彻底消除 LLM 凭空臆造的根源。"""
    print("1. 正在拉取真实权威数据源 (RSS Feeds)...")
    raw_articles = []
    
    for source_name, feed_url in RSS_FEEDS.items():
        try:
            feed = feedparser.parse(feed_url)
            for entry in feed.entries[:max_items_per_feed]:
                title = entry.get("title", "").strip()
                link = entry.get("link", "").strip()
                summary = entry.get("summary", entry.get("description", "")).strip()
                # 简单清洗 HTML 标签
                summary_clean = summary[:300].replace("<p>", "").replace("</p>", "").replace("\n", " ")
                
                raw_articles.append(f"【来源: {source_name}】\n标题: {title}\n链接: {link}\n摘要: {summary_clean}\n")
        except Exception as e:
            print(f"⚠️ 拉取 {source_name} 失败: {e}")

    if not raw_articles:
        print("❌ 未抓取到任何真实新闻，终止以防幻觉生成。")
        sys.exit(1)
        
    print(f"✅ 成功抓取到 {len(raw_articles)} 条真实技术资讯！")
    return "\n---\n".join(raw_articles)


# ---------------------------------------------------------------------------
# 2. LLM 总结层：基于真实上下文生成简报
# ---------------------------------------------------------------------------
def generate_briefing():
    real_news_context = fetch_real_tech_news()

    print("2. 正在通过 DeepSeek 基于【真实抓取数据】总结 PerfPulse 技术简报...")
    if not DEEPSEEK_API_KEY:
        print("❌ 错误：未配置 DEEPSEEK_API_KEY！")
        sys.exit(1)

    client = OpenAI(
        api_key=DEEPSEEK_API_KEY,
        base_url="https://api.deepseek.com"
    )

    now = datetime.now()
    today_str = now.strftime("%Y年%m月%d日")
    exact_iso_time = now.strftime("%Y-%m-%d %H:%M:%S")

    # 注意：系统提示词中增加了严格的 Grounding（防幻觉）约束
    prompt = f"""
你是一位专注于计算机体系结构、高性能计算（HPC）、LLM 系统架构与系统性能调优的顶级资深架构师。
当前系统时间：{exact_iso_time}。今天是 {today_str}。

### 核心任务：
请基于下方提供的【真实抓取到的最新技术资讯】，归纳总结一份【PerfPulse 每日技术简报】。

================【真实抓取数据上下文】================
{real_news_context}
======================================================

### 防幻觉与事实对齐强制约束（CRITICAL）：
1. **绝对禁令**：你撰写的所有技术看点、性能提速百分比、内核参数或项目发布，**必须严格且仅来自于上述【真实抓取数据上下文】**！
2. **严禁编造**：如果在抓取数据中没有找到某个领域的动态，直接跳过该板块或明确声明“今日无新增该领域动态”，**严禁自己发明/虚构任何新闻、版本号、性能数据或代码库**！
3. **保留原文链接**：每个看点结尾处的 [来源/链接] 必须原封不动使用抓取数据中提供的原始 URL。

---

### 多媒体与交互元素插入要求：

#### 科技图表
首图：![Banner](https://images.unsplash.com/photo-1518770660439-4636190af475?auto=format&fit=crop&w=1000&q=80)
芯片微架构插图：![Microarchitecture](https://images.unsplash.com/photo-1550751827-4bd374c3f58b?auto=format&fit=crop&w=1000&q=80)
系统调优插图：![System Performance](https://images.unsplash.com/photo-1526374965328-7f61d4dc18c5?auto=format&fit=crop&w=1000&q=80)

#### 音频/播客解读卡片
在“今日深度剖析”之后按以下格式插入：
> 🎙️ **PerfPulse 3分钟音频架构解读**  
> 🎧 **主题**：[填写今日深度剖析的核心主题]  
> 💡 *提示：点击上方播放按钮，在通勤路上听完今日最核心的微架构瓶颈突破逻辑。*

---

### 干货专区与格式规范（必须严格执行）：
1. **干货代码块规范**：所有 perf 诊断命令、sysctl 参数、代码片段，必须且只能包裹在标准的 Markdown 围栏代码块中（例如 ```bash、```cpp）。
2. **绝对禁止符号**：全局严禁使用任何项目符号（如 `-`、`*`、`+`）或数字列表序号（如 `1.`、`2.`）。

---

### 输出结构要求：
严格按以下结构输出 Markdown 内容（切勿在全局包裹 ```markdown 标记）：

## 30 秒极速看点 (TL;DR)

### 突破/论文/开源发布
一句话总结真实数据中的最新突破。

### 芯片与 LLM 引擎收益
一句话总结真实的芯片/AI引擎动态。

### Kernel 与编译调优干货
一句话总结真实的 Kernel/系统动态。

---

## 今日深度剖析 (Today's Deep Dive)
挑选上述真实资讯中最重要的一条，进行架构级别的深度解读（大约 200-300 字）。

---

## LLM 系统与推理/训练加速 (LLM Infra & Acceleration)
根据真实抓取数据整理看点，附真实链接。无数据可少写或不写。

---

## 体系结构与芯片动态 (Silicon & Microarchitecture)
根据真实抓取数据整理看点，附真实链接。

---

## 系统性能调优与 Kernel (Kernel & Performance)
根据真实抓取数据整理看点，附真实链接。

---

## 必读前沿论文与开源仓库 (ArXiv & Open Source)
根据真实抓取数据中的 ArXiv 文章整理，附原始 ArXiv 链接。
"""

    try:
        response = client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {"role": "system", "content": "你是一个严谨的技术简报编辑器。你唯一的职责是根据用户提供的【真实新闻上下文】进行提炼和排版，绝对不捏造任何未在上下文中提及的事实。"},
                {"role": "user", "content": prompt}
            ],
            temperature=0.1,  # 降低 Temperature，进一步压制随机联想与幻觉
            stream=False
        )
        
        content = response.choices[0].message.content.strip()

        if content.startswith("```markdown"):
            content = content[11:]
        elif content.startswith("```"):
            content = content[3:]
        if content.endswith("```"):
            content = content[:-3]

        print("✅ 基于真实数据的 PerfPulse 简报生成成功！")
        return content.strip()
    except Exception as e:
        print(f"❌ DeepSeek 生成简报失败: {str(e)}")
        sys.exit(1)

def send_email(subject, md_content):
    print("3. 正在渲染适配微信公众号排版的高颜值 HTML 邮件...")

    sender = EMAIL_SENDER.strip() if EMAIL_SENDER else ""
    receiver = EMAIL_RECEIVER.strip() if EMAIL_RECEIVER else sender

    if not sender or not EMAIL_PASSWORD:
        print("❌ 错误：缺少邮箱环境变量配置（EMAIL_SENDER / EMAIL_PASSWORD）！")
        sys.exit(1)

    raw_html = markdown.markdown(
        md_content, 
        extensions=['tables', 'fenced_code', 'codehilite', 'nl2br', 'toc']
    )

    today_date = datetime.now().strftime("%Y-%m-%d")

    styled_html = f"""
<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <style>
    *, *:before, *:after {{
      box-sizing: border-box !important;
    }}
    body {{
      font-family: -apple-system-font, BlinkMacSystemFont, "Helvetica Neue", "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei UI", "Microsoft YaHei", Arial, sans-serif;
      background-color: #ffffff;
      color: #24292e;
      margin: 0;
      padding: 0;
      width: 100% !important;
      -webkit-text-size-adjust: 100%;
    }}
    .container {{
      width: 100% !important;
      max-width: 100% !important;
      margin: 0 auto;
      background: #ffffff;
      overflow: hidden;
    }}
    .header {{
      background: linear-gradient(135deg, #0f172a 0%, #1e293b 100%);
      color: #ffffff;
      padding: 24px 16px;
      border-bottom: 3px solid #6366f1;
    }}
    .header h1 {{
      margin: 0;
      font-size: 20px;
      font-weight: 700;
      color: #ffffff;
      letter-spacing: 0.5px;
      line-height: 1.4;
    }}
    .header .subtitle {{
      margin-top: 10px;
      font-size: 12px;
      color: #a5b4fc;
      line-height: 1.5;
    }}
    .content {{
      padding: 16px 12px;
      font-size: 15px;
      line-height: 1.75;
      color: #334155;
      word-break: break-word;
    }}
    h2 {{
      color: #0f172a;
      font-size: 17px;
      background: #f1f5f9;
      border-left: 4px solid #4f46e5;
      padding: 8px 12px;
      border-radius: 0 4px 4px 0;
      margin-top: 36px;
      margin-bottom: 20px;
    }}
    h3 {{
      font-size: 16px;
      color: #0f172a;
      margin-top: 28px;
      margin-bottom: 12px;
      font-weight: 600;
      border-bottom: 1px solid #e2e8f0;
      padding-bottom: 6px;
    }}
    p {{
      margin: 12px 0 16px 0;
      color: #334155;
      word-wrap: break-word;
      line-height: 1.75;
      text-align: justify;
    }}
    img {{
      display: block !important;
      max-width: 100% !important;
      height: auto !important;
      margin: 20px auto !important;
      border-radius: 8px !important;
      box-shadow: 0 4px 12px rgba(0, 0, 0, 0.08) !important;
      border: 1px solid #e2e8f0 !important;
    }}
    a {{
      color: #4f46e5 !important;
      text-decoration: none !important;
      font-weight: 500 !important;
      border-bottom: 1px dashed #6366f1 !important;
      word-break: break-all !important;
    }}
    code {{
      background-color: #f1f5f9;
      color: #4f46e5;
      padding: 2px 5px;
      border-radius: 4px;
      font-family: "SFMono-Regular", Consolas, "Liberation Mono", Menlo, monospace;
      font-size: 88%;
      font-weight: 600;
    }}
    pre {{
      background-color: #0f172a !important;
      color: #f8fafc !important;
      padding: 14px !important;
      border-radius: 6px !important;
      overflow-x: auto !important;
      font-family: "SFMono-Regular", Consolas, "Liberation Mono", Menlo, monospace !important;
      font-size: 12px !important;
      line-height: 1.6 !important;
      margin: 16px 0 !important;
      border: 1px solid #1e293b !important;
      white-space: pre-wrap !important;
      word-break: break-all !important;
    }}
    pre code {{
      background-color: transparent !important;
      color: #f8fafc !important;
      padding: 0 !important;
      font-weight: normal !important;
    }}
    blockquote {{
      margin: 20px 0;
      padding: 12px 14px;
      color: #1e293b;
      border-left: 4px solid #4f46e5;
      background-color: #f8fafc;
      border-radius: 0 6px 6px 0;
      font-size: 14px;
    }}
    blockquote p {{
      margin: 4px 0;
      color: #334155;
    }}
    hr {{
      border: none;
      border-top: 1px dashed #cbd5e1;
      margin: 32px 0;
    }}
    .footer {{
      background-color: #f8fafc;
      border-top: 1px solid #e2e8f0;
      padding: 20px 12px;
      text-align: center;
      font-size: 12px;
      color: #94a3b8;
    }}
  </style>
</head>
<body>
  <div class="container">
    <div class="header">
      <h1>⚡ PerfPulse 每日技术与架构简报</h1>
      <div class="subtitle">发布日期：{today_date} | 聚焦真实 LLM 系统加速 · CPU/GPU 微架构 · Linux Kernel</div>
    </div>
    <div class="content">
      {raw_html}
    </div>
    <div class="footer">
      基于真实权威数据源 (RAG) & DeepSeek 自动化构建
    </div>
  </div>
</body>
</html>
"""

    print("4. 正在使用 Premailer 自动将 CSS 样式转换为内联属性...")
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
        print("🎉 包含真实权威数据源的真实 PerfPulse 简报已成功发送！")
    except Exception as e:
        print(f"❌ 邮件发送失败: {str(e)}")
        sys.exit(1)

if __name__ == "__main__":
    content = generate_briefing()
    send_email("【PerfPulse】每日硬件、系统与 LLM 性能简报", content)
