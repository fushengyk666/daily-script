import json
import time
from datetime import datetime, date, timedelta
import requests

API_URL = "https://alpha123.uk/api/data?fresh=1"
# === 🔧 你的 Telegram Bot 配置 ===
TELEGRAM_TOKEN = "7980319366:AAGCms_00Uxk74QEYuJln822LFAUOX-idso"  # 替换为你的
TELEGRAM_CHAT_ID = "-4882200173"  # 替换为你的 Chat ID


def send_telegram_message(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "HTML"}
    try:
        response = requests.post(url, data=payload)
        if response.status_code != 200:
            print(f"❗ Telegram 发送失败: {response.text}")
    except Exception as e:
        print(f"❗ Telegram 请求异常: {e}")


def fetch_data():
    """从 API 获取数据"""
    try:
        response = requests.get(API_URL, timeout=10)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        print(f"[错误] 抓取失败: {e}")
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


def classify_airdrops(data):
    """分类今日空投与空投预告"""
    today = date.today()
    tomorrow = today + timedelta(days=1)
    today_list, forecast_list = [], []

    airdrops = adjust_phase_times(data.get("airdrops", []))

    for item in airdrops:
        item_date = item.get("date")
        parsed_date = None
        if item_date:
            try:
                parsed_date = datetime.strptime(item_date, "%Y-%m-%d").date()
            except:
                parsed_date = None

        entry = {
            "token": item.get("token", ""),
            "date": item_date,
            "time": item.get("time", ""),
            "points": item.get("points", ""),
            "amount": item.get("amount", ""),
            "contract_address": item.get("contract_address", ""),
        }

        # 今日空投
        if parsed_date == today:
            today_list.append(entry)
        # 空投预告：明天及以后，或者无日期
        elif parsed_date is None or parsed_date >= tomorrow:
            forecast_list.append(entry)

    return today_list, forecast_list


def detect_changes(old_list, new_list):
    """标记新增或更新"""
    old_map = {i["token"]: i for i in old_list}
    result = []
    for item in new_list:
        token = item["token"]
        if token not in old_map:
            item["status"] = "新增"
        elif json.dumps(old_map[token], ensure_ascii=False) != json.dumps(
            item, ensure_ascii=False
        ):
            item["status"] = "更新"
        else:
            item["status"] = ""
        result.append(item)
    return result


def format_simple(title, airdrops, last_airdrops):
    """控制台文案"""
    if not airdrops:
        return f"【{title}】 无"

    last_map = {i["token"]: i for i in last_airdrops}
    lines = [f"【{title}】"]
    for i in airdrops:
        token = i["token"]
        print(token not in last_map)
        if token not in last_map:
            status_tag = "[新增]"
        elif json.dumps(last_map[token], ensure_ascii=False) != json.dumps(
            i, ensure_ascii=False
        ):
            status_tag = "[更新]"
        else:
            status_tag = ""
        print(status_tag)
        full_time = f"{i.get('date', '')} {i.get('time', '')}".strip()
        lines.append(
            f"🪙{i['token']} {status_tag}\n ⏰时间: {full_time}\n ⭐分数: {i['points']}\n 💰数量: {i['amount']}\n 📍地址: {i['contract_address']}\n"
        )
    return "\n".join(lines)


def main():
    last_today = []
    last_forecast = []

    while True:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        data = fetch_data()
        if not data:
            time.sleep(600)
            continue

        today_data, forecast_data = classify_airdrops(data)

        if today_data != last_today or forecast_data != last_forecast:
            print(today_data)
            print(last_today)
            print(today_data != last_today)
            print(forecast_data)
            print(last_forecast)
            print(forecast_data != last_forecast)

            print(f"[{now}] 今日空投与预告有更新")
            if today_data or forecast_data:
                message = (
                    f"[Alpha网站监控] 今日空投与预告有更新\n\n"
                    + format_simple("今日空投", today_data, last_today)
                    + "\n\n"
                    + format_simple("空投预告", forecast_data, last_forecast)
                )
                # print(message)
                send_telegram_message(message)

            last_today = today_data
            last_forecast = forecast_data
        else:
            print(f"[{now}] 今日空投与预告无变化")

        time.sleep(600)  # 10分钟



if __name__ == "__main__":
    main()
