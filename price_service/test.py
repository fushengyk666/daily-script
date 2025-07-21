import pandas as pd
import numpy as np
import yfinance as yf
import mplfinance as mpf
from smartmoneyconcepts import smc
import ccxt

# 1. 下载BTC 15分钟K线数据

# ohlc = yf.download('BTC-USD', start='2025-07-15', end='2025-07-18', interval='15m')
# ohlc.columns = ['open', 'high', 'low', 'close', 'volume']
# ohlc.index.name = 'Date'
# ohlc.index = ohlc.index.tz_localize(None)  # 去除时区方便对齐
exchange = ccxt.binance()
ohlcv = exchange.fetch_ohlcv('BTC/USDT', timeframe='15m', since=exchange.parse8601('2025-07-15T00:00:00Z'))

# 转换成 DataFrame
ohlc = pd.DataFrame(ohlcv, columns=["timestamp", "open", "high", "low", "close", "volume"])
ohlc["timestamp"] = pd.to_datetime(ohlc["timestamp"], unit="ms")
ohlc.set_index("timestamp", inplace=True)
ohlc.index.name = "Date"  # 保持一致性
ohlc.index = ohlc.index.tz_localize(None)
# print(f"Fetched {len(ohlc)} K-lines.")
swing_df = smc.swing_highs_lows(ohlc, swing_length=10)

# 2. 模拟多个SMC指标 - 假BOS水平线
bos_levels = {
    (pd.to_datetime('2025-07-16 08:00:00'), pd.to_datetime('2025-07-17 02:00:00')): 120500,
    (pd.to_datetime('2025-07-16 14:00:00'), pd.to_datetime('2025-07-17 08:00:00')): 121000,
    (pd.to_datetime('2025-07-15 20:00:00'), pd.to_datetime('2025-07-16 12:00:00')): 119500
}

# 4. 转换成你类似的区间结构（时间区间 => 价位）
bos_choch_df = smc.bos_choch(ohlc, swing_df, close_break=True)

# 生成CHOCH散点数据
choch_bull = pd.Series(np.nan, index=ohlc.index)
choch_bear = pd.Series(np.nan, index=ohlc.index)

for idx, row in bos_choch_df.iterrows():
    if pd.isna(row['CHOCH']):
        continue
    if row['CHOCH'] == 1:
        # 多头CHOCH，标记为高点附近
        choch_bull.iloc[idx] = row['Level']
    elif row['CHOCH'] == -1:
        # 空头CHOCH，标记为低点附近
        choch_bear.iloc[idx] = row['Level']

# 4. 转换函数：把BrokenIndex排序后做成区间 -> Level字典
def bos_df_to_levels(df, ohlc_index):
    # 过滤有效BOS点（值为1或-1）
    valid = df[(df['BOS'] == 1) | (df['BOS'] == -1)].dropna(subset=['BrokenIndex', 'Level'])
    valid = valid.sort_values(by='BrokenIndex')
    
    levels = {}
    indices = valid['BrokenIndex'].astype(int).values  # 确保是整数索引
    prices = valid['Level'].values
    
    for i in range(len(valid)):
        start_idx = indices[i]
        if i + 1 < len(valid):
            end_idx = indices[i + 1]
        else:
            end_idx = start_idx
        
        # 用索引在ohlc的index中取对应时间戳
        start_time = ohlc_index[start_idx]
        end_time = ohlc_index[end_idx]
        
        levels[(start_time, end_time)] = prices[i]
    return levels

# 调用时传入ohlc.index
bos_levels = bos_df_to_levels(bos_choch_df, ohlc.index)
print(bos_levels)

bos_lines = []
for (start, end), level in bos_levels.items():
    bos_line = pd.Series(np.nan, index=ohlc.index)
    bos_line.loc[start:end] = level
    bos_lines.append(bos_line)

# 3. 模拟多个Swing High/Low点
# swing_points = {
#     'highs': [
#         ('2025-07-16 08:00:00', 1.002),
#         ('2025-07-16 16:00:00', 1.003),
#         ('2025-07-17 04:00:00', 1.002)
#     ],
#     'lows': [
#         ('2025-07-16 12:00:00', 0.998),
#         ('2025-07-17 00:00:00', 0.997),
#         ('2025-07-17 12:00:00', 0.998)
#     ]
# }
# print(smc.swing_highs_lows(ohlc, swing_length = 50))


swing_points = {'highs': [], 'lows': []}

for idx, row in swing_df.iterrows():
    if pd.isna(row['HighLow']):
        continue
    timestamp = ohlc.index[idx].strftime('%Y-%m-%d %H:%M:%S')
    if row['HighLow'] == 1:
        # 高点，乘以一个因子(示例给的是1.002/1.003等，这里用1.002示例)
        swing_points['highs'].append((timestamp, 1.002))
    elif row['HighLow'] == -1:
        # 低点，乘以一个因子(示例给的是0.998/0.997等，这里用0.998示例)
        swing_points['lows'].append((timestamp, 0.998))
print(swing_points)


swing_highs = pd.Series(np.nan, index=ohlc.index)
swing_lows = pd.Series(np.nan, index=ohlc.index)

for time_str, mult in swing_points['highs']:
    time = pd.to_datetime(time_str)
    if time in ohlc.index:
        swing_highs.loc[time] = ohlc.loc[time, 'high'] * mult

for time_str, mult in swing_points['lows']:
    time = pd.to_datetime(time_str)
    if time in ohlc.index:
        swing_lows.loc[time] = ohlc.loc[time, 'low'] * mult

# 4. 模拟多个Order Block区域
def create_ob_fill(start_time, end_time, top_price, bottom_price):
    fill_array = np.full(len(ohlc.index), np.nan)
    mask = (ohlc.index >= pd.to_datetime(start_time)) & (ohlc.index <= pd.to_datetime(end_time))
    fill_array[mask] = bottom_price
    top_array = np.full(len(ohlc.index), np.nan)
    top_array[mask] = top_price
    return dict(y1=fill_array, y2=top_array)

# order_blocks = [
#     {
#         'start': '2025-07-15 14:00:00',
#         'end': '2025-07-15 15:00:00',
#         'top': 119000.0,
#         'bottom': 118500.0,
#         'color': 'blue'
#     },
#     {
#         'start': '2025-07-16 10:00:00',
#         'end': '2025-07-16 11:00:00',
#         'top': 120000.0,
#         'bottom': 119700.0,
#         'color': 'red'
#     }
# ]
# print(smc.ob(ohlc, swing_df, close_mitigation = False))
ob_df = smc.ob(ohlc, swing_df, close_mitigation=False)

order_blocks = []

# 过滤有效的order block行（OB列不为NaN）
valid_obs = ob_df.dropna(subset=['OB'])

for idx, row in valid_obs.iterrows():
    start_idx = idx  # 这里假设当前idx是order block的起始索引，可能需根据具体逻辑调整
    # 找结束时间，这里假设“MitigatedIndex”列存的是结束蜡烛的索引
    if pd.notna(row['MitigatedIndex']):
        end_idx = int(row['MitigatedIndex'])
    else:
        end_idx = start_idx  # 没有MitigatedIndex时，暂定只覆盖当前idx

    # 时间戳转字符串
    end_time = ohlc.index[start_idx].strftime('%Y-%m-%d %H:%M:%S')
    start_time = ohlc.index[end_idx].strftime('%Y-%m-%d %H:%M:%S')

    order_blocks.append({
        'start': start_time,
        'end': end_time,
        'top': float(row['Top']),
        'bottom': float(row['Bottom']),
        'color': 'blue' if row['OB'] == 1 else 'red'  # 1代表看涨，-1看跌
    })

print(order_blocks)

ob_fills = []
for ob in order_blocks:
    fb_dict = create_ob_fill(ob['start'], ob['end'], ob['top'], ob['bottom'])
    fb_dict.update({'alpha': 0.3, 'color': ob['color']})
    ob_fills.append(fb_dict)

# 5. 绘制图表
ap = []
for bos_line in bos_lines:
    ap.append(mpf.make_addplot(bos_line, color='orange', linestyle='--'))
ap.extend([
    mpf.make_addplot(swing_highs, type='scatter', marker='v', color='red', markersize=100),
    mpf.make_addplot(swing_lows, type='scatter', marker='^', color='green', markersize=100),
    mpf.make_addplot(choch_bull, type='scatter', marker='o', color='green', markersize=80, panel=0),
    mpf.make_addplot(choch_bear, type='scatter', marker='o', color='purple', markersize=80, panel=0)  
])

fig, axes = mpf.plot(
    ohlc,
    type='candle',
    style='yahoo',
    volume=True,
    title='BTC-USD 15m with Multiple SMC Indicators',
    ylabel='Price ($)',
    ylabel_lower='Volume',
    addplot=ap,
    fill_between=ob_fills,
    figsize=(20, 10),
    returnfig=True,
    panel_ratios=(3, 1)
)

# 添加更详细的图例
axes[0].legend(['BOS 1', 'BOS 2', 'BOS 3', 'Swing High', 'Swing Low'])

# 6. 保存图片（可选）
fig.savefig('btc_fake_smc.png', bbox_inches='tight')
print("Saved figure as btc_fake_smc.png")
