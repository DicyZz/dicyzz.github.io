#!/bin/bash
# 一键部署：在 Mac mini 上安装「一天一个简报」的 launchd 定时任务。
#
#   周一 08:00  PerfPulse
#   周二 08:00  AIFrontier
#   周三 08:00  FinFrontier
#   周四 08:00  GlobalTech（chinatech）
#   周五 08:00  ChipSchool（芯片通识课）
#   周六 / 周日  不安排
#
# 用法（在 Mac mini 上执行一次即可）：
#     bash scripts/setup_local_scheduler.sh
#
# 做的事：
#   1. 准备独立克隆 ~/briefings（每次运行前 git pull，始终用最新代码）
#   2. 生成密钥模板 ~/.config/briefing-secrets.env（600 权限，请填入真实值）
#   3. 安装并加载一个 LaunchAgent（周一至周五 08:00，按星期几分派）
#   4. 清理旧版的 chipschool 独立 LaunchAgent（如有）
#
# 卸载：launchctl bootout "gui/$UID/com.jianzhang.briefings" && rm ~/Library/LaunchAgents/com.jianzhang.briefings.plist

set -euo pipefail

REPO_URL="git@github.com:DicyZz/dicyzz.github.io.git"
WORK_REPO="${BRIEFINGS_REPO:-$HOME/briefings}"
SECRETS_FILE="${BRIEFINGS_SECRETS:-$HOME/.config/briefing-secrets.env}"
PLIST="$HOME/Library/LaunchAgents/com.jianzhang.briefings.plist"
OLD_CHIP_PLIST="$HOME/Library/LaunchAgents/com.jianzhang.chipschool.plist"

echo "== 1/4 准备独立克隆：${WORK_REPO} =="
if [ -d "${WORK_REPO}/.git" ]; then
  git -C "${WORK_REPO}" pull --ff-only --quiet && echo "   已更新现有克隆"
else
  git clone --quiet "${REPO_URL}" "${WORK_REPO}"
  echo "   已克隆"
fi

echo "== 2/4 准备密钥文件：${SECRETS_FILE} =="
mkdir -p "$(dirname "${SECRETS_FILE}")"
if [ -f "${SECRETS_FILE}" ]; then
  echo "   已存在，保持不变"
else
  cat > "${SECRETS_FILE}" <<'EOF'
# 五个简报 flow 的密钥（本机运行用，勿提交到仓库）
# 与 GitHub Secrets 里的同名变量保持一致即可
DEEPSEEK_API_KEY=
EMAIL_HOST=smtp.gmail.com
EMAIL_PORT=465
EMAIL_SENDER=
EMAIL_PASSWORD=
EMAIL_RECEIVER=
EOF
  echo "   已生成模板，请填入真实值"
fi
chmod 600 "${SECRETS_FILE}"

echo "== 3/4 安装 LaunchAgent（周一至周五 08:00，一天一个 flow）=="
mkdir -p "$HOME/Library/LaunchAgents"
cat > "${PLIST}" <<PLISTEOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.jianzhang.briefings</string>
    <key>ProgramArguments</key>
    <array>
        <!-- caffeinate：跑的时候别让机器睡 -->
        <string>/usr/bin/caffeinate</string>
        <string>-s</string>
        <string>/bin/bash</string>
        <string>${WORK_REPO}/scripts/local_briefings.sh</string>
    </array>
    <key>EnvironmentVariables</key>
    <dict>
        <key>BRIEFINGS_REPO</key>
        <string>${WORK_REPO}</string>
        <key>BRIEFINGS_SECRETS</key>
        <string>${SECRETS_FILE}</string>
        <key>PATH</key>
        <string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
    </dict>
    <key>StartCalendarInterval</key>
    <array>
        <dict><key>Weekday</key><integer>1</integer><key>Hour</key><integer>8</integer><key>Minute</key><integer>0</integer></dict>
        <dict><key>Weekday</key><integer>2</integer><key>Hour</key><integer>8</integer><key>Minute</key><integer>0</integer></dict>
        <dict><key>Weekday</key><integer>3</integer><key>Hour</key><integer>8</integer><key>Minute</key><integer>0</integer></dict>
        <dict><key>Weekday</key><integer>4</integer><key>Hour</key><integer>8</integer><key>Minute</key><integer>0</integer></dict>
        <dict><key>Weekday</key><integer>5</integer><key>Hour</key><integer>8</integer><key>Minute</key><integer>0</integer></dict>
    </array>
    <key>StandardOutPath</key>
    <string>${HOME}/Library/Logs/briefings/launchd.log</string>
    <key>StandardErrPath</key>
    <string>${HOME}/Library/Logs/briefings/launchd.log</string>
</dict>
</plist>
PLISTEOF

mkdir -p "$HOME/Library/Logs/briefings"
launchctl bootout "gui/$UID/com.jianzhang.briefings" 2>/dev/null || true
launchctl bootstrap "gui/$UID" "${PLIST}"

echo "== 4/4 清理旧版 chipschool 独立 LaunchAgent（如有）=="
launchctl bootout "gui/$UID/com.jianzhang.chipschool" 2>/dev/null || true
if [ -f "${OLD_CHIP_PLIST}" ]; then
  mv "${OLD_CHIP_PLIST}" "${OLD_CHIP_PLIST}.disabled"
  echo "   已停用旧版 ${OLD_CHIP_PLIST}（改名 .disabled 备份）"
else
  echo "   无旧版 chipschool plist，跳过"
fi

echo ""
echo "✅ 完成"
echo "   定时（本机时区）："
echo "     周一 08:00  PerfPulse"
echo "     周二 08:00  AIFrontier"
echo "     周三 08:00  FinFrontier"
echo "     周四 08:00  GlobalTech"
echo "     周五 08:00  ChipSchool"
echo "   密钥：把 ${SECRETS_FILE} 填好（现在还是空模板）"
echo "   手动试跑今天的 flow：launchctl kickstart -k gui/$UID/com.jianzhang.briefings"
echo "   手动指定某个 flow：bash ${WORK_REPO}/scripts/local_briefings.sh perfpulse"
echo "   看日志：tail -f $HOME/Library/Logs/briefings/$(date +%Y-%m-%d).log"
echo "   临时停用：launchctl bootout gui/$UID/com.jianzhang.briefings"
