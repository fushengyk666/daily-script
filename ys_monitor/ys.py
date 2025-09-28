import sys
import requests
import time
from datetime import datetime, timezone, timedelta
from loguru import logger

# 配置日志
logger.remove()
logger.add(
    sys.stdout,
    level="INFO",
    format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",
)

API_URL = "https://api.tzevaadom.co.il/alerts-history/"
POLL_INTERVAL = 30  # 秒
processed_alerts = set()

# === 🔧 你的 Telegram Bot 配置 ===
TELEGRAM_TOKEN = ""  # 替换为你的
TELEGRAM_CHAT_ID = ""  # 替换为你的 Chat ID


def send_telegram_message(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "HTML"}
    try:
        response = requests.post(url, data=payload)
        if response.status_code != 200:
            print(f"❗ Telegram 发送失败: {response.text}")
    except Exception as e:
        print(f"❗ Telegram 请求异常: {e}")


def get_latest_alert():
    try:
        response = requests.get(API_URL, headers={"User-Agent": "Mozilla/5.0"})
        if response.status_code == 200:
            alerts = response.json()
            if alerts:
                return alerts[0]
        else:
            logger.error(f"[{datetime.now()}] 请求失败，状态码: {response.status_code}")
    except Exception as e:
        logger.error(f"[{datetime.now()}] 请求异常: {e}")
    return None


def process_alert(alert):
    alert_items = alert.get("alerts", [])
    now_utc_ts = datetime.now(timezone.utc).timestamp()

    # 按时间倒序排序，最新的排在前面
    alert_items_sorted = sorted(
        alert_items, key=lambda x: x.get("time", 0), reverse=True
    )

    for alert_data in alert_items_sorted:
        if alert_data.get("isDrill", True):
            continue

        timestamp = alert_data.get("time")
        if timestamp is None or abs(now_utc_ts - timestamp) > 3 * 60:
            continue

        if timestamp in processed_alerts:
            continue

        tz_gmt8 = timezone(timedelta(hours=8))
        alert_time = datetime.fromtimestamp(timestamp, tz_gmt8).strftime(
            "%Y-%m-%d %H:%M:%S GMT+8"
        )

        cities = alert_data.get("cities", [])
        threat = alert_data.get("threat", -1)

        # 构造报警信息
        message = (
            f"🚨 <b>以色列真实警报</b>\n"
            f"🕒 时间: {alert_time}\n"
            f"📍 区域（前5个）: {', '.join(cities[:5])} 等共 {len(cities)} 地区\n"
            f"⚠️ 威胁等级: {threat}"
        )
        logger.info("\n" + message + "\n")
        send_telegram_message(message)

        processed_alerts.add(timestamp)


def main():
    logger.info("📡 正在启动以色列空袭实时监控...")
    # send_telegram_message("📡 正在启动以色列空袭实时监控...")
    while True:
        alert = get_latest_alert()
        if alert:
            process_alert(alert)
        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()
