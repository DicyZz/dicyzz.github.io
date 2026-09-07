import os
import sys
import requests
from openai import OpenAI

# 1. 安全读取环境变量（同时兼容 DEEPSEEK_API_KEY 与 LLM_API_KEY）
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY") or os.environ.get("LLM_API_KEY")
SCF_PROXY_URL = os.environ.get("SCF_PROXY_URL")
WECHAT_APP_ID = os.environ.get("WECHAT_APP_ID")
WECHAT_APP_SECRET = os.environ.get("WECHAT_APP_SECRET")
WECHAT_THUMB_MEDIA_ID = os.environ.get("WECHAT_THUMB_MEDIA_ID")

def generate_briefing():
    print("1. 正在生成简报...")
    
    # 前置检查
    if not DEEPSEEK_API_KEY:
        print("❌ 错误：未读取到 DEEPSEEK_API_KEY，请检查 GitHub Secrets 配置！")
        sys.exit(1)

    # 初始化 OpenAI 客户端调用 DeepSeek API
    client = OpenAI(
        api_key=DEEPSEEK_API_KEY,
        base_url="https://api.deepseek.com"
    )

    try:
        response = client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {"role": "system", "content": "你是一个专业的 EasyPerf 技术简报分析专家。"},
                {"role": "user", "content": "请生成一份精简的 EasyPerf 和系统性能优化每日技术简报。"}
            ],
            stream=False
        )
        content = response.choices[0].message.content
        print("✅ 简报生成成功！")
        return content
    except Exception as e:
        print(f"❌ 调用 DeepSeek API 失败: {e}")
        sys.exit(1)

def push_to_wechat(content):
    print("2. 正在通过 SCF 代理发送推送...")
    if not SCF_PROXY_URL:
        print("⚠️ 警告: 未配置 SCF_PROXY_URL，跳过推送步骤。")
        return

    payload = {
        "app_id": WECHAT_APP_ID,
        "app_secret": WECHAT_APP_SECRET,
        "thumb_media_id": WECHAT_THUMB_MEDIA_ID,
        "content": content
    }

    try:
        response = requests.post(SCF_PROXY_URL, json=payload, timeout=30)
        print(f"推送状态码: {response.status_code}")
        print(f"推送返回结果: {response.text}")
    except Exception as e:
        print(f"❌ 推送请求失败: {e}")

if __name__ == "__main__":
    md_text = generate_briefing()
    push_to_wechat(md_text)
