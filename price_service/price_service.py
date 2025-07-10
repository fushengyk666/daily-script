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
exchanges = {
    "binance": ccxt.binance(),
    "okx": ccxt.okx(),
    "gate": ccxt.gate(),
    "huobi": ccxt.huobi(),
}


@app.get("/coin_price_info")
async def coin_price_info(symbol: str = Query(..., description="币种名称，如BTC")):
    symbol = symbol.upper()
    full_symbol = f"{symbol}/USDT"

    for name, exchange in exchanges.items():
        try:
            ticker = exchange.fetch_ticker(full_symbol)
            price = ticker["last"]
            change = ticker["percentage"]
            msg = f"{symbol} ${exchange.price_to_precision(full_symbol, price)} " + \
                  ("📈" if change >= 0 else "📉") + f"{change:+.2f}% ({exchange.id})"

            img_base64 = generate_kline_image(exchange, full_symbol)

            return {
                "text": msg,
                "image_base64": img_base64
            }
        except Exception as e:
            print(f"[{name}] 获取 {full_symbol} 失败: {e}")
            continue

    raise HTTPException(status_code=404, detail=f"未找到 {full_symbol} 的价格信息")


def generate_kline_image(exchange, symbol):
    try:
        ohlcv = exchange.fetch_ohlcv(symbol, timeframe="15m", limit=96)

        df = pd.DataFrame(ohlcv, columns=["timestamp", "open", "high", "low", "close", "volume"])
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
        df["timestamp"] = df["timestamp"].dt.tz_localize("UTC").dt.tz_convert("Asia/Shanghai")
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
            mpf.make_addplot(marker_high, scatter=True, markersize=50, marker="^", color="red", label=f"High: ${high_str}"),
            mpf.make_addplot(marker_low, scatter=True, markersize=50, marker="v", color="green", label=f"Low: ${low_str}"),
            mpf.make_addplot(marker_current, scatter=True, markersize=50, marker="o", color="purple", label=f"Current: ${current_str}")
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
            returnfig=True
        )

        ax = axlist[0]
        ax.yaxis.set_major_formatter(FuncFormatter(lambda x, _: exchange.price_to_precision(symbol, x)))

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
