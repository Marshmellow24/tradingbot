from fastapi import FastAPI
from contextlib import asynccontextmanager
import uvicorn

from app.core.connection import IBConnection
from app.core.config import ConfigWatcher
from app.api.router import router
from app.services.trade_logger import TradeLogger

# Global instances
ib_connection = IBConnection()
config = ConfigWatcher()
trade_logger = TradeLogger()

@asynccontextmanager
async def lifespan(app: FastAPI):
    await ib_connection.connect()
    await config.start_watching()
    yield
    await config.stop_watching()
    await ib_connection.disconnect()

app = FastAPI(lifespan=lifespan)
app.include_router(router)

if __name__ == '__main__':
    uvicorn.run(app, host="127.0.0.1", port=8000)