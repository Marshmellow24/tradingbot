# app/core/dependencies.py
from fastapi.templating import Jinja2Templates
from ib_insync import IB
from ..services.trade_logger import TradeLogger
from .config import ConfigWatcher
from .connection import IBConnection

# Initialize global instances
templates = Jinja2Templates(directory="templates")
ib = IB()
ib_connection = IBConnection(ib)
config = ConfigWatcher()
trade_logger = TradeLogger()

# Export all dependencies
__all__ = ['templates', 'ib', 'ib_connection', 'config', 'trade_logger']