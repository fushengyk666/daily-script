import json
import random
import time
import os
import signal
import sys
from datetime import datetime, date, timedelta
import requests
from loguru import logger

# 配置日志
logger.remove()
logger.add(
    sys.stdout,
    level="INFO",
    format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",
)

API_URL = "https://alpha123.uk/api/data?fresh=1"
# 本地状态文件路径
STATE_FILE = "alpha_monitor_state.json"
# === 🔧 你的 Telegram Bot 配置 ===
TELEGRAM_TOKEN = "7980319366:AAGCms_00Uxk74QEYuJln822LFAUOX-idso"  # 替换为你的
TELEGRAM_CHAT_ID = "-4882200173"  # 替换为你的 Chat ID

TELEGRAM_CHAT_ID_NEW = "-1002888916669"
TELEGRAM_MESSAGE_TREAD_ID_NEW = 15

# 全局变量用于信号处理
current_last_today = []
current_last_forecast = []


def signal_handler(signum, frame):
    """处理程序退出信号，保存当前状态"""
    logger.info(f"[信号] 收到退出信号 {signum}，正在保存状态...")
    save_state(current_last_today, current_last_forecast)
    logger.info("[信号] 状态已保存，程序退出")
    sys.exit(0)


def send_telegram_message(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "HTML"}
    try:
        response = requests.post(url, data=payload)
        if response.status_code != 200:
            logger.error(f"❗ Telegram 发送失败: {response.text}")
    except Exception as e:
        logger.error(f"❗ Telegram 请求异常: {e}")


def send_telegram_message_new(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID_NEW,
        "text": message,
        "parse_mode": "HTML",
        "message_thread_id": TELEGRAM_MESSAGE_TREAD_ID_NEW,
    }
    try:
        response = requests.post(url, data=payload)
        if response.status_code != 200:
            logger.error(f"❗ Telegram 发送失败: {response.text}")
    except Exception as e:
        logger.error(f"❗ Telegram 请求异常: {e}")


def save_state(last_today, last_forecast):
    """保存状态到本地文件"""
    try:
        state = {
            "last_today": last_today,
            "last_forecast": last_forecast,
            "last_update": datetime.now().isoformat(),
        }
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
        logger.info(f"[状态] 已保存到 {STATE_FILE}")
    except Exception as e:
        logger.error(f"[错误] 保存状态失败: {e}")


def load_state():
    """从本地文件加载状态"""
    if not os.path.exists(STATE_FILE):
        logger.info(f"[状态] {STATE_FILE} 不存在，将使用空状态")
        return [], []

    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            state = json.load(f)
        last_today = state.get("last_today", [])
        last_forecast = state.get("last_forecast", [])
        last_update = state.get("last_update", "未知")

        # 清理过期的今日空投数据（只保留今天的）
        today = date.today()
        cleaned_today = []
        for item in last_today:
            item_date = item.get("date")
            if item_date:
                try:
                    parsed_date = datetime.strptime(item_date, "%Y-%m-%d").date()
                    if parsed_date == today:
                        cleaned_today.append(item)
                except:
                    pass

        logger.info(f"[状态] 已从 {STATE_FILE} 加载状态，上次更新: {last_update}")
        logger.info(
            f"[状态] 加载了 {len(cleaned_today)} 个今日空投，{len(last_forecast)} 个预告空投"
        )

        # 如果清理后数据有变化，立即保存
        if len(cleaned_today) != len(last_today):
            logger.info(
                f"[状态] 清理了 {len(last_today) - len(cleaned_today)} 个过期的今日空投"
            )

        return cleaned_today, last_forecast
    except Exception as e:
        logger.error(f"[错误] 加载状态失败: {e}，将使用空状态")
        return [], []


def fetch_data():
    """从 API 获取数据"""
    try:
        headers = {"referer": "https://alpha123.uk/zh/index.html"}
        response = requests.get(API_URL, headers=headers, timeout=10)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        logger.error(f"[错误] 抓取失败: {e}")
        return None


def adjust_phase_times(airdrops):
    """处理多轮空投时间：phase>1 = 第一轮时间 + 18小时"""
    token_map = {}
    for item in airdrops:
        token = item.get("token")
        phase = item.get("phase", 1)
        if token not in token_map:
            token_map[token] = {}
        token_map[token][phase] = item

    for token, phases in token_map.items():
        if 2 in phases and 1 in phases:
            first_round = phases[1]
            second_round = phases[2]

            if first_round.get("date") and first_round.get("time"):
                dt_str = f"{first_round['date']} {first_round['time']}"
                dt = datetime.strptime(dt_str, "%Y-%m-%d %H:%M")
                dt2 = dt + timedelta(hours=18)
                second_round["date"] = dt2.strftime("%Y-%m-%d")
                second_round["time"] = dt2.strftime("%H:%M")
    return airdrops


def process_and_sort_airdrops(data):
    """处理并排序空投数据"""
    airdrops = adjust_phase_times(data.get("airdrops", []))

    processed_airdrops = []
    for item in airdrops:
        entry = {
            "token": item.get("token", ""),
            "date": item.get("date"),
            "time": item.get("time", ""),
            "type": item.get("type", ""),
            "phase": item.get("phase", 1),
            "points": item.get("points", ""),
            "amount": item.get("amount", ""),
            "contract_address": item.get("contract_address", ""),
        }
        processed_airdrops.append(entry)

    # 排序函数：先按日期时间，再按token名称
    def sort_key(item):
        date_str = item.get("date", "")
        time_str = item.get("time", "")
        token = item.get("token", "")

        # 如果没有日期或时间，排在最后
        if not date_str or not time_str:
            return ("9999-12-31", "23:59", token)

        try:
            # 尝试解析日期时间
            datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
            return (date_str, time_str, token)
        except:
            # 解析失败，排在最后
            return ("9999-12-31", "23:59", token)

    # 对整个列表排序
    processed_airdrops.sort(key=sort_key)
    return processed_airdrops


def classify_airdrops(data):
    """分类今日空投与空投预告"""
    today = date.today()
    tomorrow = today + timedelta(days=1)
    today_list, forecast_list = [], []

    # 获取处理并排序后的空投数据
    processed_airdrops = process_and_sort_airdrops(data)

    for item in processed_airdrops:
        item_date = item.get("date")
        parsed_date = None
        if item_date:
            try:
                parsed_date = datetime.strptime(item_date, "%Y-%m-%d").date()
            except:
                parsed_date = None

        # 今日空投
        if parsed_date == today:
            today_list.append(item)
        # 空投预告：明天及以后，或者无日期
        elif parsed_date is None or parsed_date >= tomorrow:
            forecast_list.append(item)

    return today_list, forecast_list


def format_simple(title, airdrops, last_airdrops):
    """控制台文案"""
    if not airdrops:
        return f"【{title}】 无"

    last_map = {i["token"]: i for i in last_airdrops}
    lines = [f"【{title}】"]
    for i in airdrops:
        token = i["token"]
        if token not in last_map:
            status_tag = "[新增]"
        elif json.dumps(last_map[token], ensure_ascii=False) != json.dumps(
            i, ensure_ascii=False
        ):
            status_tag = "[更新]"
        else:
            status_tag = ""

        time_desc = ""
        if i["type"] == "tge":
            time_desc = "(TGE)"
        elif str(i["phase"]) == "2":
            time_desc = "(二段)"

        # 格式化时间：只保留月日和小时分钟
        date_str = i.get("date", "")
        time_str = i.get("time", "")
        if date_str and time_str:
            try:
                # 解析日期并重新格式化为 MM-DD HH:MM
                parsed_date = datetime.strptime(date_str, "%Y-%m-%d")
                formatted_date = parsed_date.strftime("%m-%d")
                full_time = f"{formatted_date} {time_str}"
            except:
                # 如果解析失败，使用原始格式
                full_time = f"{date_str} {time_str}"
        else:
            full_time = f"{date_str} {time_str}".strip()

        lines.append(
            f"🪙{i['token']} {status_tag}\n ⏰时间: {full_time}{time_desc}\n ⭐分数: {i['points']}\n 💰数量: {i['amount']}\n 📍地址: {i['contract_address']}\n"
        )
    return "\n".join(lines)


def main():
    global current_last_today, current_last_forecast

    # 注册信号处理器
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # 从本地文件加载之前的状态
    last_today, last_forecast = load_state()
    current_last_today, current_last_forecast = last_today, last_forecast

    logger.info(f"[启动] Alpha 监控程序已启动，监控间隔: 10分钟")
    logger.info(f"[启动] 状态文件: {STATE_FILE}")

    while True:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        data = fetch_data()
        if not data:
            logger.warning(f"[{now}] 获取数据失败，等待下次重试...")
            time.sleep(600)
            continue

        today_data, forecast_data = classify_airdrops(data)

        if today_data != last_today or forecast_data != last_forecast:
            logger.info(f"[{now}] 今日空投与预告有更新")

            if today_data or forecast_data:
                message = (
                    f"[Alpha网站监控] 今日空投与预告有更新\n\n"
                    + format_simple("今日空投", today_data, last_today)
                    + "\n\n"
                    + format_simple("空投预告", forecast_data, last_forecast)
                    + "\n\n"
                    + "数据来源：https://alpha123.uk"
                )
                logger.info(message)
                send_telegram_message_new(message)
                send_telegram_message(message)

            # 更新状态并保存到本地文件
            last_today = today_data
            last_forecast = forecast_data
            current_last_today, current_last_forecast = last_today, last_forecast
            save_state(last_today, last_forecast)
        else:
            logger.info(f"[{now}] 今日空投与预告无变化")

        time.sleep(random.randint(300, 600))  # 10分钟


if __name__ == "__main__":
    main()
