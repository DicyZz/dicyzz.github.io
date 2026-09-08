import os
import sys
import smtplib
from datetime import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from openai import OpenAI
import markdown
from premailer import transform

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

def generate_briefing():
    print("1. 正在通过 DeepSeek 生成 PerfPulse 技术简报...")
    if not DEEPSEEK_API_KEY:
        print("❌ 错误：未配置 DEEPSEEK_API_KEY！")
        sys.exit(1)

    client = OpenAI(
        api_key=DEEPSEEK_API_KEY,
        base_url="https://api.deepseek.com"
    )

    today_str = datetime.now().strftime("%Y年%m月%d日")

    prompt = f"""
你是一位专注于计算机体系结构、高性能计算（HPC）、LLM 系统架构与系统性能调优的顶级资深架构师。
今天是 {today_str}。请生成一份专业的【PerfPulse 每日技术简报】。

---

### 强制对标来源领域：

#### LLM 系统与 AI Infra
vLLM / SGLang GitHub & Blog, PyTorch Engineering Blog, NVIDIA Technical Blog, Tri Dao (FlashAttention) 动态, ArXiv (`cs.AR`, `cs.DC`, `cs.CL`), SemiAnalysis.
Understanding AI, TechCrunch AI, Ars Technica.

---

#### 体系结构与芯片/IP 微架构
Chips and Cheese, ServeTheHome, RISC-V International, ACM SIGARCH, IEEE Micro.
SemiEngineering, Hardware Times, WikiChip ARM, AnandTech, Design & Reuse, EET China, Doulos, Tom's Hardware, ASCII.jp.

---

#### HPC 与编译优化
LLVM Discourse/Commits, GCC Mailing List, MLIR News, TVM Discourse, OneAPI / ROCm Release Notes.

---

#### Linux 内核与系统性能调优
LWN.net, LKML, Brendan Gregg's Blog, ebpf.io, Cloudflare / Netflix TechBlog.
Phoronix, It's FOSS News, Slashdot, Alltop Linux, Narkive, DZone, Packet Storm Security.

---

### 多媒体与交互元素插入要求：

#### 科技图表
首图：![Banner](https://images.unsplash.com/photo-1518770660439-4636190af475?auto=format&fit=crop&w=1000&q=80)

芯片微架构插图：![Microarchitecture](https://images.unsplash.com/photo-1550751827-4bd374c3f58b?auto=format&fit=crop&w=1000&q=80)

系统调优插图：![System Performance](https://images.unsplash.com/photo-1526374965328-7f61d4dc18c5?auto=format&fit=crop&w=1000&q=80)

---

#### 音频/播客解读卡片
在“今日深度剖析”之后按以下格式插入：
> 🎙️ **PerfPulse 3分钟音频架构解读**  
> 🎧 **主题**：[填写今日深度剖析的核心主题]  
> 💡 *提示：点击上方播放按钮，在通勤路上听完今日最核心的微架构瓶颈突破逻辑。*

---

#### 视频/论文演示卡片
若有视频/ Talk，按以下格式插入：
> 🎬 **视频演示 / Talk 推荐**：  
> 🔗 **视频标题**：[视频/讲座名称]  
> 📌 **核心看点**：[1句话说明视频展示的 benchmark 跑分或 CPU/GPU 内存火焰图] [查看视频/演示链接](链接地址)

---

### 排版与输出结构要求：
严格按以下结构输出 Markdown 内容（切勿在全局包裹 ```markdown 标记）：
注意：禁止使用任何列表项目符号（如 -、*）或数字序号（如 1.、2.）。请将每一项的开头直接提炼并升级为独立标题（使用 ### 或 ####），且不同板块和卡片之间留出充足的垂直间距。

## 30 秒极速看点 (TL;DR)

### 突破/论文/开源发布
一句话总结今日最震撼的突破/论文/开源发布。

### 芯片与 LLM 引擎收益
一句话总结芯片或 LLM 引擎的核心性能收益。

### Kernel 与编译调优干货
一句话总结 Kernel 或编译调优干货。

---

## 今日深度剖析 (Today's Deep Dive)
挑选 1 个最具有架构影响力的技术突破/论文/开源重构，进行 300 字左右的架构级深度分析（微架构影响、Bottleneck 突破逻辑与性能收益）。

---

## LLM 系统与推理/训练加速 (LLM Infra & Acceleration)

---

## 体系结构与芯片动态 (Silicon & Microarchitecture)

---

## 高性能计算与编译优化 (HPC & Compilers)

---

## 系统性能调优与 Kernel (Kernel & Performance)

---

## 必读前沿论文与开源仓库 (ArXiv & Open Source)

---

### 代码与干货要求：
代码与命令包裹：所有 perf 诊断脚本、vLLM 参数、LLVM 编译 Flag 和代码片段，必须明确包裹在 Markdown 代码块中。

拒绝陈旧科普：直奔主题，输出具体参数、指令集、Patch 号、性能提升百分比数据。

出处标注：每条资讯末尾须带上 [来源/GitHub/ArXiv] 链接。
"""

    try:
        response = client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {"role": "system", "content": "你是一个极具技术深度的系统与大模型硬件性能架构师，善于追踪并精炼最前沿的技术情报，且熟知公众号与极客社区的高质量排版习惯。"},
                {"role": "user", "content": prompt}
            ],
            temperature=0.6,
            stream=False
        )
        
        content = response.choices[0].message.content.strip()

        # 清理外层可能多余包裹的代码块标记
        if content.startswith("```markdown"):
            content = content[11:]
        elif content.startswith("```"):
            content = content[3:]
        if content.endswith("```"):
            content = content[:-3]

        print("✅ 最新 PerfPulse 简报生成成功！")
        return content.strip()
    except Exception as e:
        print(f"❌ DeepSeek 生成简报失败: {str(e)}")
        sys.exit(1)

def send_email(subject, md_content):
    print("2. 正在渲染适配微信公众号排版的高颜值 HTML 邮件...")

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
  <style>
    body {{
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
      background-color: #f4f6f8;
      color: #24292e;
      margin: 0;
      padding: 12px;
    }}
    .container {{
      max-width: 680px;
      margin: 0 auto;
      background: #ffffff;
      border-radius: 12px;
      box-shadow: 0 4px 20px rgba(0, 0, 0, 0.05);
      overflow: hidden;
    }}
    .header {{
      background: linear-gradient(135deg, #0f172a 0%, #1e293b 100%);
      color: #ffffff;
      padding: 32px 28px;
      border-bottom: 3px solid #6366f1;
    }}
    .header h1 {{
      margin: 0;
      font-size: 22px;
      font-weight: 700;
      color: #ffffff;
      letter-spacing: 0.5px;
      line-height: 1.4;
    }}
    .header .subtitle {{
      margin-top: 12px;
      font-size: 13px;
      color: #a5b4fc;
      line-height: 1.6;
    }}
    .content {{
      padding: 28px 30px;
      font-size: 15px;
      line-height: 1.8;
      color: #334155;
    }}
    h2 {{
      color: #0f172a;
      font-size: 18px;
      background: #f1f5f9;
      border-left: 5px solid #4f46e5;
      padding: 10px 14px;
      border-radius: 0 6px 6px 0;
      margin-top: 48px;
      margin-bottom: 24px;
    }}
    h3 {{
      font-size: 16px;
      color: #0f172a;
      margin-top: 32px;
      margin-bottom: 12px;
      font-weight: 600;
      border-bottom: 1px solid #e2e8f0;
      padding-bottom: 6px;
    }}
    h4 {{
      font-size: 15px;
      color: #1e293b;
      margin-top: 24px;
      margin-bottom: 10px;
      font-weight: 600;
    }}
    p {{
      margin: 16px 0 24px 0;
      color: #334155;
      word-wrap: break-word;
      line-height: 1.8;
    }}
    img {{
      max-width: 100%;
      height: auto;
      border-radius: 8px;
      margin: 28px 0;
      display: block;
      box-shadow: 0 2px 8px rgba(0,0,0,0.08);
    }}
    code {{
      background-color: #e2e8f0;
      color: #0f172a;
      padding: 2px 6px;
      border-radius: 4px;
      font-family: "SFMono-Regular", Consolas, "Liberation Mono", Menlo, monospace;
      font-size: 85%;
      font-weight: 600;
    }}
    pre {{
      background-color: #0f172a;
      color: #f8fafc;
      padding: 18px;
      border-radius: 8px;
      overflow-x: auto;
      font-family: "SFMono-Regular", Consolas, "Liberation Mono", Menlo, monospace;
      font-size: 12.5px;
      line-height: 1.65;
      margin: 24px 0;
      border: 1px solid #1e293b;
    }}
    pre code {{
      background-color: transparent;
      color: #f8fafc;
      padding: 0;
      font-weight: normal;
    }}
    blockquote {{
      margin: 28px 0;
      padding: 16px 20px;
      color: #1e293b;
      border-left: 4px solid #4f46e5;
      background-color: #f8fafc;
      border-radius: 0 8px 8px 0;
      font-size: 14px;
    }}
    blockquote p {{
      margin: 6px 0;
      color: #334155;
    }}
    a {{
      color: #4f46e5;
      text-decoration: none;
      font-weight: 500;
      border-bottom: 1px dashed #6366f1;
    }}
    hr {{
      border: none;
      border-top: 1px dashed #cbd5e1;
      margin: 40px 0;
    }}
    .footer {{
      background-color: #f8fafc;
      border-top: 1px solid #e2e8f0;
      padding: 24px;
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
      <div class="subtitle">发布日期：{today_date} | 聚焦 LLM 系统加速 · CPU/GPU 微架构 · HPC 编译优化 · Linux Kernel</div>
    </div>
    <div class="content">
      {raw_html}
    </div>
    <div class="footer">
      由 DeepSeek & PerfPulse 自动化驱动构建 | 保持对底层技术的终极好奇
    </div>
  </div>
</body>
</html>
"""

    print("3. 正在使用 Premailer 自动将 CSS 样式转换为内联属性...")
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
        print("🎉 包含全量 News 书签数据源的 PerfPulse 简报已成功发送！")
    except Exception as e:
        print(f"❌ 邮件发送失败: {str(e)}")
        sys.exit(1)

if __name__ == "__main__":
    content = generate_briefing()
    send_email("【PerfPulse】每日硬件、系统与 LLM 性能简报", content)
