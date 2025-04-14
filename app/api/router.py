from fastapi import APIRouter, HTTPException, Request, Response
from .models import BracketOrderModel
from ..services.order_service import OrderService
from ..core.dependencies import ib_connection, config, trade_logger, templates

router = APIRouter()

@router.post("/webhook")
async def place_bracket_order(order: BracketOrderModel):
    if not ib_connection:  # Add safety check
        raise HTTPException(status_code=503, detail="Service not initialized")
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

@router.get("/config")
async def get_config():
    return {"config": config.config}

@router.post("/config/update")
async def update_config(updates: dict):
    try:
        await config.update(updates)
        return {"status": "success", "message": "Configuration updated"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/open_orders")
async def get_open_orders():
    """Get all open orders from IBKR"""
    if not ib_connection:
        raise HTTPException(status_code=503, detail="Service not initialized")
    orders = await ib_connection.get_open_orders()
    return {"orders": orders}

@router.get("/open_positions")
async def get_open_positions():
    """Get all open positions from IBKR"""
    if not ib_connection:
        raise HTTPException(status_code=503, detail="Service not initialized")
    positions = await ib_connection.get_open_positions()
    return {"positions": positions}

@router.get("/")
@router.get("/dashboard")
async def dashboard(request: Request):
    return templates.TemplateResponse("dashboard.html", {"request": request})

@router.get("/favicon.ico", response_class=Response)
async def favicon():
    with open("static/favicon.ico", "rb") as f:
        return Response(content=f.read(), media_type="image/x-icon")