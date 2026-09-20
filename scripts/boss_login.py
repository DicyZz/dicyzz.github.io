#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""在 Mac mini 上手动登录 BOSS 直聘，保存持久化浏览器 profile。

登录态保存在 ~/boss_chrome_profile，之后 perfpulse_job_analysis.py 会复用该
profile，无需再注入 Cookie。需要图形界面（有显示器，且当前用户已登录桌面）。

用法：
    python scripts/boss_login.py
步骤：
    1. 弹出 Chrome 窗口后，点右上角「登录」。
    2. 用 BOSS 直聘 App 扫码，完成登录。
    3. 回到终端按回车，脚本会自动验证登录态并保存 profile。
"""

import os
import sys

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    print("缺少 playwright，请先运行：pip install playwright && python -m playwright install chromium", file=sys.stderr)
    sys.exit(2)

PROFILE_DIR = os.getenv("BOSS_PROFILE_DIR") or os.path.expanduser("~/boss_chrome_profile")
LOGIN_URL = "https://www.zhipin.com/web/user/?ka=header-login"


def main():
    os.makedirs(PROFILE_DIR, exist_ok=True)
    print(f"📂 登录态目录：{PROFILE_DIR}")
    print("即将打开浏览器，请在窗口中扫码登录 BOSS 直聘...\n")

    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=PROFILE_DIR,
            headless=False,
            viewport={"width": 1280, "height": 800},
            locale="zh-CN",
        )
        page = context.pages[0] if context.pages else context.new_page()
        page.goto(LOGIN_URL, timeout=60000, wait_until="domcontentloaded")

        input("\n👉 登录完成后回到终端，按回车继续...\n")

        # 打开一个需要登录的页面验证登录态
        page.goto("https://www.zhipin.com/web/geek/job?query=测试&city=100010000", timeout=60000, wait_until="domcontentloaded")
        page.wait_for_timeout(5000)
        if "/web/user/" in page.url or "passport" in page.url:
            print("❌ 似乎未登录成功，请重新运行本脚本再试。")
            context.close()
            sys.exit(1)

        print("✅ 登录态验证通过，profile 已保存。")
        context.close()


if __name__ == "__main__":
    main()
