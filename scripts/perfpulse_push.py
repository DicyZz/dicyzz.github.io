import os
import sys
import re
import asyncio
import smtplib
from datetime import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from openai import OpenAI
import markdown
from premailer import transform
import feedparser
import edge_tts

# ---------------------------------------------------------------------------
# 读取环境变量
# ---------------------------------------------------------------------------
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
# 1. RSS 数据源定义与抓取
# ---------------------------------------------------------------------------
RSS_FEEDS = {
    "LWN (Linux Kernel)": "https://lwn.net/headlines/rss",
    "Phoronix (Hardware & OS)": "https://www.phoronix.com/rss.php",
    "PyTorch Blog": "https://pytorch.org/feed.xml",
    "ArXiv Computer Architecture (cs.AR)": "http://export.arxiv.org/rss/cs.AR",
    "ArXiv Distributed Computing (cs.DC)": "http://export.arxiv.org/rss/cs.DC",
}

def clean_html_summary(html_text):
    """清洗 HTML 标签，保留纯文本内容以提升上下文准确率"""
    if not html_text:
        return ""
    clean_text = re.sub(r'<[^>]+>', ' ', html_text)
    clean_text = re.sub(r'\s+', ' ', clean_text).strip()
    return clean_text[:600]

def fetch_real_tech_news(max_items_per_feed=3):
    """从真实 RSS 源抓取并进行二次清洗"""
    print("1. 正在拉取权威 RSS 数据源...")
    raw_articles = []
    
    for source_name, feed_url in RSS_FEEDS.items():
        try:
            feed = feedparser.parse(feed_url)
            for entry in feed.entries[:max_items_per_feed]:
                title = entry.get("title", "").strip()
                link = entry.get("link", "").strip()
                summary = entry.get("summary", entry.get("description", ""))
                summary_clean = clean_html_summary(summary)
                
                if title:
                    raw_articles.append(
                        f"【数据源: {source_name}】\n"
                        f"原始标题: {title}\n"
                        f"原始链接: {link}\n"
                        f"正文摘要: {summary_clean}\n"
                    )
        except Exception as e:
            print(f"⚠️ 拉取 {source_name} 失败: {e}")

    if not raw_articles:
        print("❌ 未抓取到任何真实新闻，终止程序。")
        sys.exit(1)
        
    print(f"✅ 成功提取并清洗 {len(raw_articles)} 条真实技术资讯！")
    return "\n---\n".join(raw_articles)


# ---------------------------------------------------------------------------
# 2. DeepSeek 生成文字简报与音频朗读脚本
# ---------------------------------------------------------------------------
def generate_briefing_and_audio_script():
    real_news_context = fetch_real_tech_news()

    print("2. 正在通过 DeepSeek 严格基于真实数据生成简报与播客脚本...")
    if not DEEPSEEK_API_KEY:
        print("❌ 错误：未配置 DEEPSEEK_API_KEY！")
        sys.exit(1)

    client = OpenAI(
        api_key=DEEPSEEK_API_KEY,
        base_url="https://api.deepseek.com"
    )

    now = datetime.now()
    exact_iso_time = now.strftime("%Y-%m-%d %H:%M:%S")

    # 1. 生成文字简报 Prompt
    briefing_prompt = f"""
你是一位极度严谨的系统与硬件架构师兼科技编辑。
当前时间：{exact_iso_time}。

### 核心任务：
基于下方【真实抓取数据上下文】，整理一份【PerfPulse 每日技术简报】。

================【真实抓取数据上下文】================
{real_news_context}
======================================================

### 核心防幻觉与事实审判法则（CRITICAL RULES - 必须百分之百遵守）：
1. 客观语气与进展限定：严禁将“实验”、“讨论”、“初步探究”撰写为“成功落地”或“重大突破”。
2. 识别第三方项目与官方发布：对于民间第三方开源项目（如 DLSS5VKLayer），必须说明“该项目为第三方社区民间实现，非官方发布”。
3. 严格数据源对齐：绝不凭空臆造未出现的性能数据、代码片段或链接。

---

### 格式与排版规范：
- 全局严禁使用任何项目符号（`-`、`*`）或数字列表序号（`1.`、`2.`）。
- 代码片段必须包裹在标准 Markdown 围栏代码块中（```bash 或 ```cpp）。
- 无对应数据的板块直接忽略。

---

### 输出结构（输出纯 Markdown 内容，切勿包裹全局 ```markdown）：

## 30 秒极速看点 (TL;DR)

### 突破/论文/开源发布
用客观严谨的一句话总结真实发生的最新发布/论文。

### 芯片与 LLM 引擎收益
用客观严谨的一句话总结真实芯片或 AI 系统动态。

### Kernel 与编译调优干货
用客观严谨的一句话总结真实 Linux Kernel 或系统调优动态。

---

## 今日深度剖析 (Today's Deep Dive)
挑选上述数据中最具架构深度的一条新闻，进行客观专业的深度分析（200-300 字）。分清“实验成果”与“生产级落地”的界限。

---

## LLM 系统与推理/训练加速 (LLM Infra & Acceleration)
根据真实上下文整理（若无相关数据则直接跳过）。

---

## 体系结构与芯片动态 (Silicon & Microarchitecture)
根据真实上下文整理（若有第三方项目需明确标注“第三方民间实现”）。

---

## 系统性能调优与 Kernel (Kernel & Performance)
根据真实上下文整理。

---

## 必读前沿论文与开源仓库 (ArXiv & Open Source)
根据真实上下文整理，附原始链接。
"""

    try:
        # 生成简报文字
        briefing_response = client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {"role": "system", "content": "你是一个严谨、苛刻的技术新闻核查编辑。你的任务是基于提供的上下文提炼信息，绝不夸大事实。"},
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

        # 2. 基于生成简报提取播客音频口语化脚本 Prompt
        audio_script_prompt = f"""
请将以下技术简报转换为一段适合 2-3 分钟口语化播客朗读的文本脚本。

要求：
1. 语言通俗自然、适合听觉吸收，去除所有 Markdown 格式符号（如 `#`、`*`、`[链接]` 等）。
2. 开头问好：“大家好，欢迎收听 PerfPulse 每日架构听力解读。”
3. 重点阐述 30 秒极速看点和今日深度剖析的内容。
4. 保持客观严谨，严禁夸大或编造内容。
5. 控制在 400-600 字之间。

=== 简报内容 ===
{md_content}
"""
        audio_response = client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {"role": "system", "content": "你是一位专业的科技播客主持人，擅长将硬核技术转换为自然流畅的口语表达。"},
                {"role": "user", "content": audio_script_prompt}
            ],
            temperature=0.2,
            stream=False
        )
        audio_script = audio_response.choices[0].message.content.strip()

        print("✅ 简报文字与播客脚本生成成功！")
        return md_content.strip(), audio_script
    except Exception as e:
        print(f"❌ DeepSeek 生成失败: {str(e)}")
        sys.exit(1)


# ---------------------------------------------------------------------------
# 3. Edge-TTS 异步音频合成
# ---------------------------------------------------------------------------
async def generate_audio_async(text, output_mp3_path="perf_pulse_podcast.mp3"):
    """使用微软 Edge 神经网络语音合成 MP3"""
    print(f"3. 正在合成 3 分钟播客 MP3 音频文件 ({output_mp3_path})...")
    voice = "zh-CN-YunxiNeural"  # 云希：自然流畅的科技男声
    communicate = edge_tts.Communicate(text, voice)
    await communicate.save(output_mp3_path)
    print("✅ MP3 音频文件合成完成！")

def create_podcast_audio(script_text, output_file="perf_pulse_podcast.mp3"):
    asyncio.run(generate_audio_async(script_text, output_file))


# ---------------------------------------------------------------------------
# 4. 邮件渲染与发送
# ---------------------------------------------------------------------------
def send_email(subject, md_content, audio_script, mp3_path="perf_pulse_podcast.mp3"):
    print("4. 正在渲染适配公众号与邮件样式的 HTML 邮件...")

    sender = EMAIL_SENDER.strip() if EMAIL_SENDER else ""
    receiver = EMAIL_RECEIVER.strip() if EMAIL_RECEIVER else sender

    if not sender or not EMAIL_PASSWORD:
        print("❌ 错误：缺少邮箱环境变量配置！")
        sys.exit(1)

    raw_html = markdown.markdown(
        md_content, 
        extensions=['tables', 'fenced_code', 'codehilite', 'nl2br', 'toc']
    )

    today_date = datetime.now().strftime("%Y-%m-%d")

    # 构建带播客音频脚本展示与在线/附件音频播放提示的头部组件
    audio_header_html = f"""
    <div style="background-color: #f8fafc; border: 1px solid #e2e8f0; border-left: 4px solid #6366f1; padding: 16px; border-radius: 6px; margin-bottom: 24px;">
      <div style="font-weight: bold; font-size: 15px; color: #0f172a; margin-bottom: 8px;">
        🎧 PerfPulse 3分钟音频架构解读
      </div>
      <div style="font-size: 13px; color: #475569; line-height: 1.6; margin-bottom: 10px;">
        {audio_script[:120]}...
      </div>
      <div style="font-size: 12px; color: #6366f1; font-weight: 500;">
        💡 提示：今日音频文件（{mp3_path}）已自动合成并作为邮件附件随信附带，也可在 Github Releases / 播客端播放。
      </div>
    </div>
    """

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
      <h1>⚡ PerfPulse 每日技术与架构简报</h1>
      <div class="subtitle">发布日期：{today_date} | 真实硬件、体系结构与 Linux Kernel 严谨跟踪</div>
    </div>
    <div class="content">
      {audio_header_html}
      {raw_html}
    </div>
    <div class="footer">
      基于真实 RSS 订阅源 (RAG) & DeepSeek 零幻觉模式 & Edge-TTS 音频构建
    </div>
  </div>
</body>
</html>
"""

    print("5. 正在进行 CSS 内联化转换...")
    inlined_html = transform(styled_html)

    message = MIMEMultipart()
    message["From"] = sender
    message["To"] = receiver
    message["Subject"] = f"{subject} ({today_date})"
    
    # 添加 HTML 正文
    message.attach(MIMEText(inlined_html, "html", "utf-8"))

    # 将生成的 MP3 作为邮件附件发送
    if os.path.exists(mp3_path):
        try:
            with open(mp3_path, "rb") as f:
                audio_data = f.read()
            audio_attachment = MIMEText(audio_data, "base64", "utf-8")
            audio_attachment["Content-Type"] = "audio/mpeg"
            audio_attachment["Content-Disposition"] = f'attachment; filename="{os.path.basename(mp3_path)}"'
            message.attach(audio_attachment)
            print("✅ 已成功添加 MP3 音频为邮件附件！")
        except Exception as e:
            print(f"⚠️ 添加音频附件失败: {e}")

    try:
        if EMAIL_PORT == 465:
            server = smtplib.SMTP_SSL(EMAIL_HOST, EMAIL_PORT, timeout=20)
        else:
            server = smtplib.SMTP(EMAIL_HOST, EMAIL_PORT, timeout=20)
            server.starttls()

        server.login(sender, EMAIL_PASSWORD.strip())
        server.sendmail(sender, [receiver], message.as_string())
        server.quit()
        print("🎉 简报正文与 MP3 播客附件已成功发送！")
    except Exception as e:
        print(f"❌ 邮件发送失败: {str(e)}")
        sys.exit(1)


# ---------------------------------------------------------------------------
# 主流程入口
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # 1. 生成简报与播客脚本
    md_content, audio_script = generate_briefing_and_audio_script()
    
    # 2. 生成 MP3 音频文件
    mp3_file = "perf_pulse_podcast.mp3"
    create_podcast_audio(audio_script, mp3_file)
    
    # 3. 发送邮件（含附件与文本）
    send_email("【PerfPulse】每日硬件、系统与 LLM 性能简报", md_content, audio_script, mp3_file)
