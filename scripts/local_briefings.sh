#!/bin/bash
# 本机（Mac mini）按星期几分派「一天一个 flow」，由 launchd 每周一至周五 08:00 调起。
#
#   周一 08:00  PerfPulse      （性能 / 芯片 / 编译器 / 底层系统）
#   周二 08:00  AIFrontier     （AI 模型 / Agent / 多模态）
#   周三 08:00  FinFrontier    （金融 / 量化 / 市场）
#   周四 08:00  GlobalTech     （全球科技资讯，脚本名 chinatech）
#   周五 08:00  ChipSchool     （芯片通识课 · 半导体基础科普）
#   周六 / 周日  不安排
#
# 为什么不用 GitHub 的 schedule：实测该仓库的定时任务稳定迟到 4.5–5.5 小时，
# 做不到北京时间 8:00，因此改由本机 launchd 触发（见 scripts/setup_local_scheduler.sh）。
#
# 手动指定某个 flow（不按星期几）：
#     bash scripts/local_briefings.sh perfpulse
#     bash scripts/local_briefings.sh aifrontier
#     bash scripts/local_briefings.sh finfrontier
#     bash scripts/local_briefings.sh chinatech
#     bash scripts/local_briefings.sh chipschool
#
# 芯片通识课指定讲次 / 预览 / 强制推进（不推进进度 / 不发信等特殊用法）：
#     python scripts/chipschool_push.py --lesson 3
#     python scripts/chipschool_push.py --dry-run
#     python scripts/chipschool_push.py --force
#
# 依赖的密钥放在 ~/.config/briefing-secrets.env（600 权限，不进仓库）：
#     DEEPSEEK_API_KEY=...
#     EMAIL_SENDER=...
#     EMAIL_PASSWORD=...
#     EMAIL_RECEIVER=...        # 可省略，默认等于 EMAIL_SENDER
#     EMAIL_HOST=smtp.gmail.com # 可省略
#     EMAIL_PORT=465            # 可省略

set -uo pipefail

REPO_DIR="${BRIEFINGS_REPO:-$HOME/briefings}"
SECRETS_FILE="${BRIEFINGS_SECRETS:-$HOME/.config/briefing-secrets.env}"
LOG_DIR="${BRIEFINGS_LOG_DIR:-$HOME/Library/Logs/briefings}"
PYTHON="${BRIEFINGS_PYTHON:-/opt/homebrew/bin/python3}"

mkdir -p "${LOG_DIR}"
LOG_FILE="${LOG_DIR}/$(date +%Y-%m-%d).log"
exec >>"${LOG_FILE}" 2>&1

# 周一=1 … 周日=7；索引 0/6/7 留空（周六周日不安排）
WEEKDAY_FLOWS=("" "perfpulse" "aifrontier" "finfrontier" "chinatech" "chipschool" "")
DOW="$(date +%u)"
TODAY="$(date +%Y-%m-%d)"

if [ "${1:-}" != "" ]; then
  FLOW="$1"
  MODE="手动指定"
else
  FLOW="${WEEKDAY_FLOWS[$DOW]:-}"
  MODE="定时分派"
  if [ -z "${FLOW}" ]; then
    echo "===== $(date '+%F %T') 今天星期${DOW}，不安排简报，跳过 ====="
    exit 0
  fi
fi

echo "===== $(date '+%F %T') ${MODE}：今天星期${DOW}，跑 ${FLOW} ====="

# 当天已经成功发过信的 flow 会留下标记，避免重复发信
# （例如手动跑过一次后，08:00 的定时任务会跳过；想强制重跑就删掉对应标记文件）
STATE_DIR="${LOG_DIR}/.state"
mkdir -p "${STATE_DIR}"
MARKER="${STATE_DIR}/${TODAY}-${FLOW}.ok"
if [ -f "${MARKER}" ]; then
  echo "⏭  ${FLOW} 今天（${TODAY}）已成功跑过，跳过"
  echo "   如需强制重跑：删除 ${MARKER} 后重试"
  exit 0
fi

if [ ! -f "${SECRETS_FILE}" ]; then
  echo "❌ 缺少密钥文件 ${SECRETS_FILE}"
  echo "   参考 docs/weekly-briefings.md 填写后重试"
  exit 1
fi

# shellcheck disable=SC1090
set -a
. "${SECRETS_FILE}"
set +a

missing=""
for key in DEEPSEEK_API_KEY EMAIL_SENDER EMAIL_PASSWORD; do
  if [ -z "$(printenv "${key}" || true)" ]; then
    missing="${missing} ${key}"
  fi
done
if [ -n "${missing}" ]; then
  echo "❌ 密钥文件里缺少：${missing}"
  echo "   填好后可手动执行：bash ${REPO_DIR}/scripts/local_briefings.sh"
  exit 1
fi

if [ ! -x "${PYTHON}" ]; then
  PYTHON="$(command -v python3 || true)"
fi
if [ -z "${PYTHON}" ]; then
  echo "❌ 找不到 python3"
  exit 1
fi

cd "${REPO_DIR}" || { echo "❌ 仓库目录不存在：${REPO_DIR}"; exit 1; }

echo "→ 拉取最新代码（失败则用本地代码继续）"
/usr/bin/git pull --ff-only --quiet || echo "⚠️ git pull 失败，使用当前代码"

echo ""
echo "----- ${FLOW} 开始 $(date '+%T') -----"
if [ "${FLOW}" = "chipschool" ]; then
  # 芯片通识课：无参数 = 自动跑当前讲（内部已做「仅周五 + 当天已发」校验）
  "${PYTHON}" "scripts/chipschool_push.py"
else
  "${PYTHON}" "scripts/${FLOW}_push.py"
fi
code=$?
echo "----- ${FLOW} 结束 exit=${code} $(date '+%T') -----"

if [ "${code}" -eq 0 ]; then
  touch "${MARKER}"
  echo "✅ ${FLOW} 发送成功，已记录 ${MARKER}"
  exit 0
fi

echo "❌ ${FLOW} 发送失败（exit=${code}），未记录完成标记"
echo "日志：${LOG_FILE}"
exit "${code}"
