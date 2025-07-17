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
import matplotlib.ticker as mticker # 確保導入ticker

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
    arg: Optional[str] = Query(None, description="可选参数，提供任何值以获取合约信息"),
):
    """
    提供幣種的現貨和合約價格資訊。
    - 預設只返回現貨價格和K線圖。
    - 當提供了 'arg' 參數時，會額外返回合約價格和價差。
    """
    symbol = symbol.upper()
    try:
        spot_msg, spot_img_base64, spot_price = get_spot(symbol)

        if arg:
            future_msg, future_price = get_future(symbol)

            msg_parts = []
            if spot_msg:
                msg_parts.append(f"现货: {spot_msg}")
            if future_msg:
                msg_parts.append(f"合约: {future_msg}")

            # 當且僅當現貨和合約價格都可用時，計算並添加價差信息
            if spot_price is not None and future_price is not None:
                spread = future_price - spot_price
                spread_percentage = abs((spread / spot_price) * 100 if spot_price != 0 else 0)
                if spread_percentage != 0:
                    spread_msg = f"价差: {spread_percentage:.2f}%"
                    msg_parts.append(spread_msg)

            if not msg_parts:
                raise HTTPException(status_code=404, detail=f"未找到 {symbol} 的任何價格信息")

            final_msg_body = "\n\n".join(msg_parts)
            final_msg = f"{symbol}\n{final_msg_body}"

            return JSONResponse(content={"text": final_msg, "image_base64": spot_img_base64})
        
        # 預設情況：只返回現貨資訊
        if not spot_msg:
             raise HTTPException(status_code=404, detail=f"未找到 {symbol} 的現貨價格信息")
        return JSONResponse(content={"text": f"{symbol}\n{spot_msg}", "image_base64": spot_img_base64})

    except Exception as e:
        print(f"獲取 {symbol} 價格資訊失敗: {e}")
        raise HTTPException(status_code=500, detail=f"處理 {symbol} 請求時發生內部錯誤")


def get_spot(symbol):
    """獲取現貨價格、K線圖和原始價格"""
    spot_symbol = f"{symbol}/USDT"
    for exchange in exchanges:
        try:
            ticker = exchange.fetch_ticker(spot_symbol)
            if spot_symbol != ticker["symbol"]:
                continue
            price = ticker["last"]
            change = ticker["percentage"]
            msg = (
                f"${exchange.price_to_precision(spot_symbol, price)} "
                + ("📈" if change >= 0 else "📉")
                + f" {change:+.2f}% ({exchange.id})"
            )
            # 調用修改後的K線圖生成函數
            img_base64 = generate_kline_image(exchange, spot_symbol)
            if img_base64:
                return msg, img_base64, price
        except Exception as e:
            print(f"[{exchange.id}] 獲取 {spot_symbol} 失敗: {e}")
            continue
    return None, None, None


def get_future(symbol):
    """獲取合約價格、資金費率等資訊"""
    future_symbol = f"{symbol.upper()}/USDT:USDT"
    for exchange in exchanges:
        try:
            ticker = exchange.fetch_ticker(future_symbol)
            price = ticker["last"]
            change = ticker["percentage"]
            funding_info = exchange.fetch_funding_rate(future_symbol)
            funding_rate = funding_info["fundingRate"]
            next_funding_timestamp = funding_info["fundingTimestamp"]
            tz_utc8 = timezone(timedelta(hours=8))
            next_funding_dt = datetime.fromtimestamp(next_funding_timestamp / 1000, tz=tz_utc8)
            next_funding_str = next_funding_dt.strftime("%H:%M")
            msg = (
                f"${exchange.price_to_precision(future_symbol, price)} "
                + ("📈" if change >= 0 else "📉")
                + f" {change:+.2f}% ({exchange.id})\n"
                f"费率: {funding_rate * 100:.4f}% | 下次结算: {next_funding_str}"
            )
            return msg, price
        except Exception as e:
            print(f"[{exchange.id}] 獲取 {future_symbol} 數據失敗: {e}")
            continue
    return None, None

# ==============================================================================
# ✨ 使用與前例相同的邏輯，修改 K 線圖生成函數 ✨
# ==============================================================================
def generate_kline_image(exchange, symbol: str) -> Optional[str]:
    """
    最終修復版：生成帶有完整均線的專業K線圖，並返回base64字串。
    """
    # --- 主要設定 ---
    TIMEFRAME = "15m"
    LIMIT = 96
    MA_PERIODS = (6, 12, 42)
    WATERMARK_TEXT = "Generated by Fushengyk"

    try:
        # 1. 獲取包含額外歷史數據的K線數據
        ohlcv = exchange.fetch_ohlcv(symbol, TIMEFRAME, limit=LIMIT + max(MA_PERIODS))
        df = pd.DataFrame(
            ohlcv, columns=["timestamp", "open", "high", "low", "close", "volume"]
        )
        if df.empty:
            return None

        # 2. 處理時間戳
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
        df["timestamp"] = (
            df["timestamp"].dt.tz_localize("UTC").dt.tz_convert("Asia/Taipei")
        )
        df.set_index("timestamp", inplace=True)
        
        # <<< 修改點 1: 先在完整的 DataFrame 上計算好 MA >>>
        for period in MA_PERIODS:
            df[f'ma{period}'] = df['close'].rolling(window=period).mean()

        # <<< 修改點 2: 在計算完所有指標後，再截取需要繪製的部分 >>>
        df_plot = df.iloc[-LIMIT:]
        
        # 3. 準備統計資訊與Y軸範圍 (使用截斷後的 df_plot)
        high_price = df_plot['high'].max()
        low_price = df_plot['low'].min()
        current_price = df_plot['close'].iloc[-1]
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
        
        # 4. 定義專業的「報告級」淺色風格
        mc = mpf.make_marketcolors(
            up='#00B050', down='#C70039', edge='inherit', wick='inherit',
            volume={'up': '#00B050', 'down': '#C70039'}
        )
        mav_colors = ['#00BFFF', '#FF8C00', '#DA70D6']
        pro_light_style = mpf.make_mpf_style(
            base_mpf_style='yahoo', marketcolors=mc,
            facecolor='#FFFFFF', figcolor='#F6F6F6',
            gridcolor='#E0E0E0', gridstyle='-',
            y_on_right=False,
            rc={'axes.labelcolor': 'black', 'xtick.color': 'black', 'ytick.color': 'black', 'text.color': 'black'}
        )
        
        # <<< 修改點 3: 使用 addplot 參數來繪製我們手動計算好的 MA >>>
        addplots = [
            mpf.make_addplot(df_plot[f'ma{period}'], color=mav_colors[i])
            for i, period in enumerate(MA_PERIODS)
        ]

        # 5. 繪製圖表 (使用 addplot 替代 mav)
        fig, axlist = mpf.plot(
            df_plot, # 使用截斷後的 df_plot 進行繪圖
            type="candle", 
            style=pro_light_style,
            ylabel="Price (USDT)", 
            ylabel_lower="Volume",
            addplot=addplots, # <<< 使用 addplot 繪製額外指標
            # mav=MA_PERIODS, # <<< 不再需要此參數
            volume=True, 
            ylim=(ylim_bottom, ylim_top),
            datetime_format="%H:%M", 
            xrotation=0, 
            figsize=(14, 9),
            panel_ratios=(10, 3), 
            returnfig=True, 
            tight_layout=True
        )

        # 6. 手動設置面板、座標軸和文字
        main_ax, volume_ax = axlist[0], axlist[2]
        volume_ax.set_facecolor('#F5F5F5')
        fig.subplots_adjust(hspace=0.0)
        
        locator = mticker.MaxNLocator(nbins=5, prune='both')
        main_ax.xaxis.set_major_locator(locator)

        fig.suptitle(f"{symbol} ({exchange.id})", y=0.97, fontsize=16, color='black')
        bbox_props = dict(boxstyle="round,pad=0.4", facecolor="#E0E0E0", alpha=0.7)
        main_ax.text(0.02, 0.98, stats_text, transform=main_ax.transAxes, fontsize=10,
                     verticalalignment='top', bbox=bbox_props, color='black')
        main_ax.yaxis.set_major_formatter(
            matplotlib.ticker.FuncFormatter(lambda x, p: exchange.price_to_precision(symbol, x))
        )

        fig.text(0.5, 0.5, WATERMARK_TEXT,
                 fontsize=40, color='darkgray', alpha=0.15,
                 ha='center', va='center', rotation=30)

        # 7. 將圖表保存到記憶體中並進行Base64編碼
        buf = io.BytesIO()
        fig.savefig(buf, format='png', dpi=120, bbox_inches='tight', facecolor=fig.get_facecolor())
        buf.seek(0)
        img_base64 = base64.b64encode(buf.getvalue()).decode('utf-8')
        buf.close()
        matplotlib.pyplot.close(fig) # 釋放記憶體

        return img_base64

    except Exception as e:
        print(f"生成K線圖失敗 for {symbol}: {e}")
        # 可以在這裡加入更詳細的錯誤日誌，例如 import traceback; traceback.print_exc()
        return None