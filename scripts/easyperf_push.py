import os
import sys
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from openai import OpenAI
import markdown

# 读取环境变量
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY")
EMAIL_HOST = os.environ.get("EMAIL_HOST", "smtp.gmail.com")
EMAIL_PORT = int(os.environ.get("EMAIL_PORT", "465"))
EMAIL_SENDER = os.environ.get("EMAIL_SENDER")
EMAIL_PASSWORD = os.environ.get("EMAIL_PASSWORD")
EMAIL_RECEIVER = os.environ.get("EMAIL_RECEIVER") or EMAIL_SENDER

def generate_briefing():
    print("1. 正在通过 DeepSeek 生成 EasyPerf 简报...")
    if not DEEPSEEK_API_KEY:
        print("❌ 错误：未配置 DEEPSEEK_API_KEY！")
        sys.exit(1)

    client = OpenAI(
        api_key=DEEPSEEK_API_KEY,
        base_url="https://api.deepseek.com"
    )

    prompt = (
        "请生成一份专业的【EasyPerf】每日技术简报。内容涵盖：体系结构/微架构动态、"
        "高性能计算/编译优化、系统性能调优技术。使用排版整洁、结构清晰的 Markdown 格式输出。"
    )

    try:
        response = client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {"role": "system", "content": "你是一位专注于计算机体系结构与系统性能优化的资深专家。"},
                {"role": "user", "content": prompt}
            ],
            temperature=0.7,
            stream=False
        )
        print("✅ 简报生成成功！")
        return response.choices[0].message.content
    except Exception as e:
        print(f"❌ DeepSeek 生成简报失败: {str(e)}")
        sys.exit(1)

def send_email(subject, md_content):
    print("2. 正在通过 Gmail SMTP 发送邮件...")
    if not all([EMAIL_SENDER, EMAIL_PASSWORD, EMAIL_RECEIVER]):
        print("❌ 错误：缺少邮箱环境变量配置（EMAIL_SENDER / EMAIL_PASSWORD）！")
        sys.exit(1)

    # 将 Markdown 转换为易读的 HTML 格式
    html_body = markdown.markdown(md_content, extensions=['tables', 'fenced_code'])
    styled_html = f"""
    <html>
      <body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; line-height: 1.6; color: #24292e; padding: 20px; max-width: 800px; margin: 0 auto;">
        {html_body}
      </body>
    </html>
    """

    message = MIMEMultipart()
    message["From"] = EMAIL_SENDER
    message["To"] = EMAIL_RECEIVER
    message["Subject"] = subject
    message.attach(MIMEText(styled_html, "html", "utf-8"))

    try:
        if EMAIL_PORT == 465:
            server = smtplib.SMTP_SSL(EMAIL_HOST, EMAIL_PORT, timeout=20)
        else:
            server = smtplib.SMTP(EMAIL_HOST, EMAIL_PORT, timeout=20)
            server.starttls()

        server.login(EMAIL_SENDER, EMAIL_PASSWORD)
        server.sendmail(EMAIL_SENDER, [EMAIL_RECEIVER], message.as_string())
        server.quit()
        print("🎉 简报已成功发送至你的 Gmail 邮箱！")
    except Exception as e:
        print(f"❌ 邮件发送失败: {str(e)}")
        sys.exit(1)

if __name__ == "__main__":
    content = generate_briefing()
    send_email("【EasyPerf】每日硬件与系统性能简报", content)
