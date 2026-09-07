import os
import sys
import requests

# 环境变量读取
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY") or os.environ.get("LLM_API_KEY")
PUSHPLUS_TOKEN = os.environ.get("PUSHPLUS_TOKEN")

def generate_briefing():
    # ... 生成内容逻辑保持不变 ...
    return md_content

def push_to_personal_wechat(title, content):
    print("正在通过 PushPlus 发送到个人微信...")
    if not PUSHPLUS_TOKEN:
        print("❌ 错误：未配置 PUSHPLUS_TOKEN！")
        sys.exit(1)

    url = "http://www.pushplus.plus/send"
    payload = {
        "token": PUSHPLUS_TOKEN,
        "title": title,
        "content": content,
        "template": "markdown"  # 支持直接渲染 Markdown
    }

    response = requests.post(url, json=payload, timeout=15)
    res_data = response.json()

    if res_data.get("code") == 200:
        print("🎉 消息已成功发送至你的个人微信！")
    else:
        print(f"❌ 发送失败，原因: {res_data.get('msg')}")
        sys.exit(1)

if __name__ == "__main__":
    md_text = generate_briefing()
    push_to_personal_wechat("【EasyPerf】每日硬件与系统性能简报", md_text)
