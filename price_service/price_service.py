from datetime import datetime, timedelta, timezone
from typing import Optional
from fastapi import FastAPI, Query, HTTPException
from fastapi.responses import JSONResponse
import ccxt
import pandas as pd
import numpy as np
import io
import base64
import mplfinance as mpf
import matplotlib
from matplotlib.ticker import FuncFormatter

app = FastAPI()

# 初始化交易所
exchanges = [
    ccxt.binance(),
    ccxt.bybit(),
    ccxt.okx(),
    ccxt.bitget(),
    ccxt.gate(),
    ccxt.huobi(),
]


@app.get("/coin_price_info")
async def coin_price_info(
    symbol: str = Query(..., description="币种名称，如BTC"),
    arg: Optional[str] = Query(None, description="可选参数"),
):
    symbol = symbol.upper()
    try:
        if arg:
            spot_msg, spot_img_base64, spot_price = get_spot(symbol)
            future_msg, future_price = get_future(symbol)

            msg_parts = []
            if spot_msg:
                msg_parts.append(f"现货: {spot_msg}")
            if future_msg:
                msg_parts.append(f"合约: {future_msg}")

            # 当且仅当现货和合约价格都可用时，计算并添加价差信息
            if spot_price is not None and future_price is not None:
                spread = future_price - spot_price
                spread_percentage = abs(
                    (spread / spot_price) * 100 if spot_price != 0 else 0
                )
                if spread_percentage != 0:
                    spread_msg = f"价差: {spread_percentage:+.2f}%"
                    msg_parts.append(spread_msg)

            if not msg_parts:
                # 如果现货和合约信息都获取失败
                raise HTTPException(
                    status_code=404, detail=f"未找到 {symbol} 的任何价格信息"
                )

            final_msg_body = "\n\n".join(msg_parts)
            msg = f"{symbol}\n{final_msg_body}"

            return {"text": msg, "image_base64": spot_img_base64}
        else:
            spot_msg, spot_img_base64, price = get_spot(symbol)
            return {"text": spot_msg, "image_base64": spot_img_base64}
    except Exception as e:
        print(f"获取 {symbol} 价格信息失败: {e}")
        raise HTTPException(status_code=404, detail=f"未找到 {symbol} 的价格信息")


def get_spot(symbol):
    spot_symbol = f"{symbol}/USDT"
    for exchange in exchanges:
        try:
            ticker = exchange.fetch_ticker(spot_symbol)
            price = ticker["last"]
            change = ticker["percentage"]
            msg = (
                f"{symbol} ${exchange.price_to_precision(spot_symbol, price)}"
                + ("📈" if change >= 0 else "📉")
                + f"{change:+.2f}% ({exchange.id})"
            )

            img_base64 = generate_kline_image(exchange, spot_symbol)

            return msg, img_base64, price
        except Exception as e:
            print(f"[{exchange.id}] 获取 {spot_symbol} 失败: {e}")
            continue


def get_future(symbol):
    """
    获取单一币种的合约价格、24小时涨跌幅、资金费率和下次结算时间。
    函数会自动遍历支持的交易所，直到成功获取数据为止。

    :param symbol: 币种名称, 如 'BTC'
    :return: 格式化后的信息字符串或 None
    """
    future_symbol = f"{symbol.upper()}/USDT:USDT"

    # 遍历全局定义的交易所字典
    for exchange in exchanges:
        try:
            # 1. 获取 Ticker 数据 (价格、涨跌幅)
            ticker = exchange.fetch_ticker(future_symbol)
            price = ticker["last"]
            change = ticker["percentage"]

            # 2. 获取资金费率数据
            funding_info = exchange.fetch_funding_rate(future_symbol)
            funding_rate = funding_info["fundingRate"]
            next_funding_timestamp = funding_info["fundingTimestamp"]

            # 3. 将下次结算的毫秒时间戳转换为北京时间 (UTC+8)
            tz_utc8 = timezone(timedelta(hours=8))
            next_funding_dt = datetime.fromtimestamp(
                next_funding_timestamp / 1000, tz=tz_utc8
            )
            # 只显示小时和分钟，通常更实用
            next_funding_str = next_funding_dt.strftime("%H:%M")

            # 4. 格式化输出字符串
            msg = (
                f"{symbol} ${exchange.price_to_precision(future_symbol, price)}"
                + ("📈" if change >= 0 else "📉")
                + f"{change:+.2f}% ({exchange.id})\n"
                f"费率: {funding_rate * 100:.4f}% | 下次结算: {next_funding_str} "
            )
            return msg, price

        except Exception as e:
            # 如果当前交易所失败，打印错误并尝试下一个
            print(f"[{exchange.id}] 获取 {future_symbol} 数据失败: {e}")
            continue


def generate_kline_image(exchange, symbol):
    try:
        ohlcv = exchange.fetch_ohlcv(symbol, timeframe="15m", limit=96)

        df = pd.DataFrame(
            ohlcv, columns=["timestamp", "open", "high", "low", "close", "volume"]
        )
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
        df["timestamp"] = (
            df["timestamp"].dt.tz_localize("UTC").dt.tz_convert("Asia/Shanghai")
        )
        df.set_index("timestamp", inplace=True)

        high_price = df["high"].max()
        low_price = df["low"].min()
        current_price = df["close"].iloc[-1]

        marker_high = pd.Series(np.nan, index=df.index)
        marker_low = pd.Series(np.nan, index=df.index)
        marker_current = pd.Series(np.nan, index=df.index)

        marker_high.loc[df[df["high"] == high_price].index[0]] = high_price
        marker_low.loc[df[df["low"] == low_price].index[0]] = low_price
        marker_current.loc[df.index[-1]] = current_price

        high_str = exchange.price_to_precision(symbol, high_price)
        low_str = exchange.price_to_precision(symbol, low_price)
        current_str = exchange.price_to_precision(symbol, current_price)

        addplots = [
            mpf.make_addplot(
                marker_high,
                scatter=True,
                markersize=50,
                marker="^",
                color="red",
                label=f"High: ${high_str}",
            ),
            mpf.make_addplot(
                marker_low,
                scatter=True,
                markersize=50,
                marker="v",
                color="green",
                label=f"Low: ${low_str}",
            ),
            mpf.make_addplot(
                marker_current,
                scatter=True,
                markersize=50,
                marker="o",
                color="purple",
                label=f"Current: ${current_str}",
            ),
        ]

        fig, axlist = mpf.plot(
            df,
            type="candle",
            style="binance",
            addplot=addplots,
            title=f"{symbol} ({exchange.id})",
            ylabel="Price (USDT)",
            datetime_format="%H:%M",
            figsize=(12, 8),
            returnfig=True,
        )

        ax = axlist[0]
        ax.yaxis.set_major_formatter(
            FuncFormatter(lambda x, _: exchange.price_to_precision(symbol, x))
        )

        buf = io.BytesIO()
        fig.savefig(buf, dpi=100, bbox_inches="tight")
        buf.seek(0)

        img_base64 = base64.b64encode(buf.read()).decode("utf-8")

        buf.close()
        matplotlib.pyplot.close(fig)

        return img_base64

    except Exception as e:
        print(f"生成K线图失败: {e}")
        return None
