import sys
import asyncio
import websockets
from loguru import logger
from datetime import datetime

# 配置日志
logger.remove()
logger.add(
    sys.stdout,
    level="INFO",
    format="<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
           "<level>{level: <8}</level> | "
           "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - "
           "<level>{message}</level>",
)

async def listen():
    url = "wss://bwenews-api.bwe-ws.com/ws"
    async with websockets.connect(url) as ws:
        logger.info("✅ 已连接 WebSocket")
        while True:
            try:
                message = await ws.recv()
                # 记录接收消息时的时间（带毫秒）
                now = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
                logger.info(f"📩 [{now}] 收到消息: {message}")
            except websockets.ConnectionClosed:
                logger.error("❌ 连接关闭，尝试重连...")
                break

if __name__ == "__main__":
    asyncio.run(listen())
