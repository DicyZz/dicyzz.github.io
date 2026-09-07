import os
import sys
import requests
from openai import OpenAI

# 环境变量读取
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY") or os.environ.get("LLM_API_KEY")
PUSHPLUS_TOKEN = os.environ.get("PUSHPLUS_TOKEN")

def generate_briefing():
    print("1. 正在通过 DeepSeek 生成 EasyPerf 简报...")
    if not DEEPSEEK_API_KEY:
        print("❌ 错误：未配置 DEEPSEEK_API_KEY 环境变量！")
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
        md_content = response.choices[0].message.content
        print("✅ 简报生成成功！")
        return md_content
    except Exception as e:
        print(f"❌ DeepSeek 生成简报失败: {str(e)}")
        sys.exit(1)

def push_to_personal_wechat(title, content):
    print("2. 正在通过 PushPlus 推送至个人微信...")
    if not PUSHPLUS_TOKEN:
        print("❌ 错误：未配置 PUSHPLUS_TOKEN 环境变量！")
        sys.exit(1)

    url = "http://www.pushplus.plus/send"
    payload = {
        "token": PUSHPLUS_TOKEN,
        "title": title,
        "content": content,
        "template": "markdown"
    }

    try:
        response = requests.post(url, json=payload, timeout=20)
        res_data = response.json()
        if res_data.get("code") == 200:
            print("🎉 简报已成功推送至你的个人微信！")
        else:
            print(f"❌ PushPlus 推送失败: {res_data.get('msg')}")
            sys.exit(1)
    except Exception as e:
        print(f"❌ 连接 PushPlus API 失败: {str(e)}")
        sys.exit(1)

if __name__ == "__main__":
    md_text = generate_briefing()
    push_to_personal_wechat("【EasyPerf】每日硬件与系统性能简报", md_text)
