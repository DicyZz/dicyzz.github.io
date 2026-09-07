import os
import sys
import re
import json
import requests
import markdown
from premailer import transform
from openai import OpenAI

# 1. 从环境变量读取配置
APP_ID = os.environ.get("WECHAT_APP_ID")
APP_SECRET = os.environ.get("WECHAT_APP_SECRET")
THUMB_MEDIA_ID = os.environ.get("WECHAT_THUMB_MEDIA_ID")
LLM_API_KEY = os.environ.get("LLM_API_KEY")

# 2. 调用大模型生成 EasyPerf 简报
def generate_briefing():
    client = OpenAI(
        api_key=LLM_API_KEY,
        base_url="https://api.deepseek.com"  # 以 DeepSeek 为例，可换成 OpenAI/Gemini
    )
    
    prompt = """
    你是一个专注于计算机体系结构、系统性能优化和 LLM 硬件加速的技术专家。
    请搜集/总结最新的硬件与系统性能动态，并按 EasyPerf 风格生成一篇 Markdown 简报。
    格式要求：
    - 划分为 News 📢、Blog Posts 📝、Research Papers 🎓 三个板块。
    - 每条动态包含 标题、简要技术解读、参考来源链接 [来源](URL)。
    """
    
    response = client.chat.completions.create(
        model="deepseek-chat",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.7
    )
    return response.choices[0].message.content

# 3. 将 Markdown 转为微信兼容的 HTML
def md_to_wechat_html(md_content):
    links = []
    def replace_link(match):
        text, url = match.group(1), match.group(2)
        links.append(url)
        return f"{text}<sup>[{len(links)}]</sup>"

    # 将 [文本](URL) 替换为 文本[序号]
    md_processed = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', replace_link, md_content)
    
    # 底部追加参考文献
    if links:
        md_processed += "\n\n---\n**参考文献 / 链接：**\n"
        for idx, url in enumerate(links, 1):
            md_processed += f"[{idx}] {url}\n\n"

    raw_html = markdown.markdown(md_processed, extensions=['tables', 'fenced_code'])

    # EasyPerf 风格 CSS 样式
    css_style = """
    <style>
        h3 { font-size: 16px; font-weight: bold; color: #1a1a1a; border-left: 4px solid #07c160; padding-left: 8px; margin-top: 18px; margin-bottom: 10px; }
        p, li { font-size: 14px; color: #333333; line-height: 1.75; margin-bottom: 8px; }
        ul { padding-left: 18px; }
        strong { color: #07c160; font-weight: bold; }
        code { background: #f6f8fa; padding: 2px 4px; border-radius: 3px; color: #d73a49; font-size: 13px; }
        sup { color: #576b95; font-weight: bold; padding: 0 2px; }
        hr { border: none; border-top: 1px solid #eee; margin: 20px 0; }
    </style>
    """
    full_html = f"<html><head>{css_style}</head><body>{raw_html}</body></html>"
    return transform(full_html)

# 4. 微信 API 操作
def get_access_token():
    url = f"https://api.weixin.qq.com/cgi-bin/token?grant_type=client_credential&appid={APP_ID}&secret={APP_SECRET}"
    res = requests.get(url).json()
    if "access_token" not in res:
        raise Exception(f"获取 Token 失败: {res}")
    return res["access_token"]

def push_to_draft(access_token, html_content):
    url = f"https://api.weixin.qq.com/cgi-bin/draft/add?access_token={access_token}"
    payload = {
        "articles": [{
            "title": "【EasyPerf】每日硬件与系统性能动态",
            "author": "DicyZz",
            "digest": "体系结构、微架构优化与 LLM 系统最新动态简报",
            "content": html_content,
            "thumb_media_id": THUMB_MEDIA_ID
        }]
    }
    res = requests.post(
        url, 
        data=json.dumps(payload, ensure_ascii=False).encode('utf-8'),
        headers={'Content-Type': 'application/json; charset=utf-8'}
    )
    return res.json()

if __name__ == "__main__":
    print("1. 正在生成简报内容...")
    md_text = generate_briefing()
    
    print("2. 正在转换 HTML 微信排版...")
    html_text = md_to_wechat_html(md_text)
    
    print("3. 推送到微信草稿箱...")
    token = get_access_token()
    result = push_to_draft(token, html_text)
    
    if result.get("errcode") == 0:
        print("✅ 成功存入微信草稿箱！")
    else:
        print(f"❌ 推送失败: {result}")
        sys.exit(1)
