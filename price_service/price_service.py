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

matplotlib.use("Agg")
import matplotlib.ticker as mticker
import time

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

SUPPORTED_TIMEFRAMES = [
    "1m",
    "3m",
    "5m",
    "15m",
    "30m",
    "1h",
    "2h",
    "4h",
    "6h",
    "8h",
    "12h",
    "1d",
    "3d",
    "1w",
    "1M",
]


@app.get("/coin_price_info")
async def coin_price_info(
    symbol: str = Query(..., description="币种名称，如BTC"),
    arg: Optional[str] = Query(None, description="可选参数，提供任何值以获取合约信息"),
    unique_key: Optional[str] = Query(
        None, description="用于追踪请求的唯一ID,可不传"
    ),  # <--- 新增唯一Key参数
):
    """
    提供幣種的現貨和合約價格資訊。
    - 預設只返回現貨價格和K線圖。
    """
    start_time = time.time()
    # 根据 unique_key 生成日志前缀
    log_prefix = f"[{unique_key}] " if unique_key else ""

    print(f"{log_prefix}--- 开始处理请求: {symbol} (arg: {arg}) ---")
    try:
        symbol = symbol.upper()
        try:
            # --- 计时节点: get_spot ---
            t0 = time.time()
            # 将 unique_key 传递下去
            spot_msg, spot_img_base64, spot_price = get_spot(
                symbol, arg, unique_key=unique_key
            )
            t1 = time.time()
            print(f"{log_prefix}  - [节点] get_spot (获取现货) 耗时: {t1 - t0:.4f}s")
            # --------------------------

            # --- 计时节点: get_future ---
            t2 = time.time()
            # 将 unique_key 传递下去
            future_msg, future_price = get_future(symbol, unique_key=unique_key)
            t3 = time.time()
            print(f"{log_prefix}  - [节点] get_future (获取合约) 耗时: {t3 - t2:.4f}s")
            # ----------------------------

            msg_parts = []
            if spot_msg:
                msg_parts.append(f"现货: {spot_msg}")
            if future_msg:
                msg_parts.append(f"合约: {future_msg}")

            if spot_price is not None and future_price is not None:
                spread = future_price - spot_price
                spread_percentage = abs(
                    (spread / spot_price) * 100 if spot_price != 0 else 0
                )
                if spread_percentage != 0:
                    spread_msg = f"价差: {spread_percentage:.2f}%"
                    msg_parts.append(spread_msg)

            if not msg_parts:
                raise HTTPException(
                    status_code=404, detail=f"未找到 {symbol} 的任何價格信息"
                )

            final_msg_body = "\n\n".join(msg_parts)
            final_msg = f"{symbol}\n{final_msg_body}"

            return JSONResponse(
                content={"text": final_msg, "image_base64": spot_img_base64}
            )

        except Exception as e:
            print(f"{log_prefix}獲取 {symbol} 價格資訊失敗: {e}")
            raise HTTPException(
                status_code=500, detail=f"處理 {symbol} 請求時發生內部錯誤"
            )

    finally:
        process_time = time.time() - start_time
        print(f"{log_prefix}--- 请求处理完毕, 总耗时: {process_time:.4f}s ---\n")


def get_spot(
    symbol: str, arg: str, unique_key: Optional[str] = None
):  # <--- 接收 unique_key
    """獲取現貨價格、K線圖和原始價格"""
    log_prefix = f"[{unique_key}] " if unique_key else ""
    spot_symbol = f"{symbol}/USDT"
    for exchange in exchanges:
        try:
            t0 = time.time()
            ticker = exchange.fetch_ticker(spot_symbol)
            t1 = time.time()
            print(
                f"{log_prefix}    - [子节点] {exchange.id}.fetch_ticker (现货) 耗时: {t1 - t0:.4f}s"
            )

            if spot_symbol != ticker["symbol"]:
                continue
            price = ticker["last"]
            change = ticker["percentage"]
            msg = (
                f"${exchange.price_to_precision(spot_symbol, price)} "
                + ("📈" if change >= 0 else "📉")
                + f" {change:+.2f}% ({exchange.id})"
            )

            t2 = time.time()
            # 将 unique_key 传递下去
            img_base64 = generate_kline_image(
                exchange, spot_symbol, arg, unique_key=unique_key
            )
            t3 = time.time()
            print(
                f"{log_prefix}    - [子节点] generate_kline_image (生成K线图) 耗时: {t3 - t2:.4f}s"
            )

            if img_base64:
                return msg, img_base64, price
        except Exception:
            continue
    return None, None, None


def get_future(symbol: str, unique_key: Optional[str] = None):  # <--- 接收 unique_key
    """獲取合約價格、資金費率等資訊"""
    log_prefix = f"[{unique_key}] " if unique_key else ""
    future_symbol = f"{symbol.upper()}/USDT:USDT"
    for exchange in exchanges:
        try:
            t0 = time.time()
            ticker = exchange.fetch_ticker(future_symbol)
            t1 = time.time()
            print(
                f"{log_prefix}    - [子节点] {exchange.id}.fetch_ticker (合约) 耗时: {t1 - t0:.4f}s"
            )

            t2 = time.time()
            funding_info = exchange.fetch_funding_rate(future_symbol)
            t3 = time.time()
            print(
                f"{log_prefix}    - [子节点] {exchange.id}.fetch_funding_rate 耗时: {t3 - t2:.4f}s"
            )

            price = ticker["last"]
            change = ticker["percentage"]
            funding_rate = funding_info["fundingRate"]
            next_funding_timestamp = funding_info["fundingTimestamp"]
            tz_utc8 = timezone(timedelta(hours=8))
            next_funding_dt = datetime.fromtimestamp(
                next_funding_timestamp / 1000, tz=tz_utc8
            )
            next_funding_str = next_funding_dt.strftime("%H:%M")
            msg = (
                f"${exchange.price_to_precision(future_symbol, price)} "
                + ("📈" if change >= 0 else "📉")
                + f" {change:+.2f}% ({exchange.id})\n"
                f"费率: {funding_rate * 100:.4f}% | 下次结算: {next_funding_str}"
            )
            return msg, price
        except Exception:
            continue
    return None, None


def generate_kline_image(
    exchange, symbol: str, arg: str, unique_key: Optional[str] = None
) -> Optional[str]:  # <--- 接收 unique_key
    """
    [带详细计时版]：生成帶有完整均線的專業K線圖，並返回base64字串。
    """
    log_prefix = f"[{unique_key}] " if unique_key else ""
    TIMEFRAME = arg if arg in SUPPORTED_TIMEFRAMES else "15m"
    LIMIT = 96
    MA_PERIODS = (6, 12, 42)
    WATERMARK_TEXT = "Generated by Fushengyk"

    try:
        t0 = time.time()
        ohlcv = exchange.fetch_ohlcv(symbol, TIMEFRAME, limit=LIMIT + max(MA_PERIODS))
        t1 = time.time()
        print(
            f"{log_prefix}      - [K线图-节点1] fetch_ohlcv 获取K线数据耗时: {t1 - t0:.4f}s"
        )

        df = pd.DataFrame(
            ohlcv, columns=["timestamp", "open", "high", "low", "close", "volume"]
        )
        if df.empty:
            return None

        t2 = time.time()
        df["timestamp"] = (
            pd.to_datetime(df["timestamp"], unit="ms")
            .dt.tz_localize("UTC")
            .dt.tz_convert("Asia/Taipei")
        )
        df.set_index("timestamp", inplace=True)
        for period in MA_PERIODS:
            df[f"ma{period}"] = df["close"].rolling(window=period).mean()
        df_plot = df.iloc[-LIMIT:]
        t3 = time.time()
        print(f"{log_prefix}      - [K线图-节点2] Pandas 数据处理耗时: {t3 - t2:.4f}s")

        # ... (准备统计信息和样式) ...
        high_price = df_plot["high"].max()
        low_price = df_plot["low"].min()
        current_price = df_plot["close"].iloc[-1]
        high_price_str = exchange.price_to_precision(symbol, high_price)
        low_price_str = exchange.price_to_precision(symbol, low_price)
        current_price_str = exchange.price_to_precision(symbol, current_price)
        stats_text = (
            f"High: ${high_price_str}\n"
            f"Low:  ${low_price_str}\n"
            f"Now:  ${current_price_str}"
        )
        price_range = high_price - low_price
        padding = price_range * 0.04
        ylim_bottom = low_price - padding
        ylim_top = high_price + padding
        mc = mpf.make_marketcolors(
            up="#00B050",
            down="#C70039",
            edge="inherit",
            wick="inherit",
            volume={"up": "#00B050", "down": "#C70039"},
        )
        mav_colors = ["#00BFFF", "#FF8C00", "#DA70D6"]
        pro_light_style = mpf.make_mpf_style(
            base_mpf_style="yahoo",
            marketcolors=mc,
            facecolor="#FFFFFF",
            figcolor="#F6F6F6",
            gridcolor="#E0E0E0",
            gridstyle="-",
            y_on_right=False,
            rc={
                "axes.labelcolor": "black",
                "xtick.color": "black",
                "ytick.color": "black",
                "text.color": "black",
            },
        )
        addplots = [
            mpf.make_addplot(df_plot[f"ma{period}"], color=mav_colors[i])
            for i, period in enumerate(MA_PERIODS)
        ]

        t4 = time.time()
        if TIMEFRAME.endswith("m"):
            datetime_format = "%m-%d\n%H:%M"
        else:
            datetime_format = "%Y-%m-%d"
        fig, axlist = mpf.plot(
            df_plot,
            type="candle",
            style=pro_light_style,
            addplot=addplots,
            volume=True,
            returnfig=True,
            ylabel="Price (USDT)",
            ylabel_lower="Volume",
            ylim=(ylim_bottom, ylim_top),
            datetime_format=datetime_format,
            xrotation=0,
            figsize=(14, 9),
            panel_ratios=(10, 3),
            tight_layout=True,
        )
        t5 = time.time()
        print(
            f"{log_prefix}      - [K线图-节点3] mplfinance.plot 绘图耗时: {t5 - t4:.4f}s"
        )

        # ... (设置坐标轴和文字) ...
        main_ax, volume_ax = axlist[0], axlist[2]
        volume_ax.set_facecolor("#F5F5F5")
        fig.subplots_adjust(hspace=0.0)
        locator = mticker.MaxNLocator(nbins=5, prune="both")
        main_ax.xaxis.set_major_locator(locator)
        fig.suptitle(f"{symbol} ({exchange.id})", y=0.97, fontsize=16, color="black")
        bbox_props = dict(boxstyle="round,pad=0.4", facecolor="#E0E0E0", alpha=0.7)
        main_ax.text(
            0.02,
            0.98,
            stats_text,
            transform=main_ax.transAxes,
            fontsize=10,
            verticalalignment="top",
            bbox=bbox_props,
            color="black",
        )
        main_ax.yaxis.set_major_formatter(
            matplotlib.ticker.FuncFormatter(
                lambda x, p: exchange.price_to_precision(symbol, x)
            )
        )
        fig.text(
            0.5,
            0.5,
            WATERMARK_TEXT,
            fontsize=40,
            color="darkgray",
            alpha=0.15,
            ha="center",
            va="center",
            rotation=30,
        )

        t6 = time.time()
        buf = io.BytesIO()
        # 注意：您之前的代码已经优化为jpeg，我将它改了回来以匹配您提供的代码。如需提速，可改回jpeg。
        fig.savefig(
            buf,
            format="jpeg",
            dpi=120,
            bbox_inches="tight",
            facecolor=fig.get_facecolor(),
        )
        buf.seek(0)
        img_base64 = base64.b64encode(buf.getvalue()).decode("utf-8")
        buf.close()
        matplotlib.pyplot.close(fig)
        t7 = time.time()
        print(
            f"{log_prefix}      - [K线图-节点4] savefig & b64encode 保存和编码耗时: {t7 - t6:.4f}s"
        )

        return img_base64

    except Exception as e:
        print(f"{log_prefix}生成K線圖失敗 for {symbol}: {e}")
        return None
