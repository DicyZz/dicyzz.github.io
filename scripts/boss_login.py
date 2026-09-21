#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""在 Mac mini 上手动登录 BOSS 直聘，保存持久化浏览器 profile。

登录态保存在 ~/boss_chrome_profile，之后 perfpulse_job_analysis.py 会复用该
profile，无需再注入 Cookie。需要图形界面（有显示器，且当前用户已登录桌面）。

用法：
    python scripts/boss_login.py
步骤：
    1. 弹出 Chrome 窗口后，用 BOSS 直聘 App 扫码完成登录。
    2. 回到终端按回车，脚本会自动验证登录态并保存 profile。
"""

import os
import sys

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    print(
        "缺少 playwright，请先运行：pip install playwright && python -m"
        " playwright install chromium",
        file=sys.stderr,
    )
    sys.exit(2)

PROFILE_DIR = os.getenv("BOSS_PROFILE_DIR") or os.path.expanduser(
    "~/boss_chrome_profile"
)
LOGIN_URL = "https://www.zhipin.com/web/user/?ka=header-login"


def main():
    os.makedirs(PROFILE_DIR, exist_ok=True)
    print(f"📂 登录态目录：{PROFILE_DIR}")
    print("即将打开浏览器，请在窗口中扫码登录 BOSS 直聘...\n")

    with sync_playwright() as p:
        # 1. 启动持久化上下文，注入伪装参数规避反爬检测
        context = p.chromium.launch_persistent_context(
            user_data_dir=PROFILE_DIR,
            headless=False,
            viewport={"width": 1280, "height": 800},
            locale="zh-CN",
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"
                " AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0"
                " Safari/537.36"
            ),
            args=[
                "--disable-blink-features=AutomationControlled",  # 隐藏自动化控制特征
                "--no-sandbox",
                "--start-maximized",
            ],
            ignore_default_args=["--enable-automation"],  # 移除受控制的警告条
        )

        # 2. 复用已创建的页面或新建页面
        page = context.pages[0] if len(context.pages) > 0 else context.new_page()

        # 3. 抹除 navigator.webdriver 标记
        page.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () =>"
            " undefined})"
        )

        try:
            print("正在导航至 BOSS 直聘登录页...")
            # 使用 commit 或 domcontentloaded 避免因为部分第三方追踪脚本加载慢导致超时
            page.goto(LOGIN_URL, timeout=60000, wait_until="commit")
            page.wait_for_load_state("domcontentloaded")
        except Exception as e:
            print(f"⚠️ 页面加载超时或遇到异常: {e}")
            print("请检查网络连接或科学上网代理配置。")

        # 4. 阻塞终端，等待用户完成扫码
        input("\n👉 在浏览器中用 BOSS 直聘 App 扫码登录完成后，回到终端按【回车键】继续...\n")

        # 5. 验证登录态
        print("正在验证登录状态...")
        try:
            page.goto(
                "https://www.zhipin.com/web/geek/job?query=Python&city=101010100",
                timeout=60000,
                wait_until="domcontentloaded",
            )
            page.wait_for_timeout(3000)

            # 判断 URL 是否被重定向回登录界面
            current_url = page.url
            if "/web/user/" in current_url or "passport" in current_url:
                print("❌ 验证未通过：未成功登录，请重新运行本脚本进行登录。")
                context.close()
                sys.exit(1)
            else:
                print("✅ 登录态验证成功！Profile 已成功持久化保存。")

        except Exception as e:
            print(f"❌ 验证过程出错: {e}")
            context.close()
            sys.exit(1)

        context.close()


if __name__ == "__main__":
    main()
