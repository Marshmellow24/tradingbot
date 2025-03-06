from fastapi import APIRouter, HTTPException, Response
from .models import BracketOrderModel
from ..services.order_service import OrderService
from ..core.connection import ib_connection
from ..services.trade_logger import trade_logger

router = APIRouter()

@router.post("/webhook")
async def place_bracket_order(order: BracketOrderModel):
    order_service = OrderService(ib_connection)
    return await order_service.place_bracket_order(order)

@router.get("/trade_logs")
async def get_trade_logs():
    return {"trade_logs": trade_logger.logs}

@router.get("/reset_orders")
async def reset_orders():
    return await ib_connection.reset_orders()

@router.get("/connection_status")
async def connection_status():
    return {"connected": ib_connection.is_connected()}