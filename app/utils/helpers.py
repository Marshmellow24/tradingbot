import asyncio
import time

async def wait_for_order_id(trade, timeout=5.0):
    """Wait for order to receive valid order ID"""
    start = time.time()
    while time.time() - start < timeout:
        if trade.order.orderId != 0:
            return trade.order.orderId
        await asyncio.sleep(0.2)
    return 0

async def wait_for_fill_or_cancel(trade, timeout=10.0):
    """Wait for order fill or cancel after timeout"""
    start = time.time()
    while time.time() - start < timeout:
        if trade.orderStatus.status == "Filled":
            return True, trade.orderStatus.avgFillPrice
        await asyncio.sleep(0.1)
    return False, None

async def wait_for_bracket_fill(parent_trade, tp_trade, ts_trade, timeout=3600.0):
    """Wait for bracket order components to fill"""
    start = time.time()
    parentFilled = False
    parentFill = None
    childType = None
    childFill = None

    while time.time() - start < timeout:
        if not parentFilled:
            if parent_trade.orderStatus.status == "Filled":
                parentFilled = True
                parentFill = parent_trade.orderStatus.avgFillPrice
        else:
            if tp_trade and tp_trade.orderStatus.status == "Filled":
                childType = "takeProfit"
                childFill = tp_trade.orderStatus.avgFillPrice
                break
            elif ts_trade and ts_trade.orderStatus.status == "Filled":
                childType = "trailingStop"
                childFill = ts_trade.orderStatus.avgFillPrice
                break
        await asyncio.sleep(0.5)
    
    return parentFilled, childType, parentFill, childFill