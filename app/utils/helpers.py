import asyncio
import time

async def wait_for_order_id(trade, timeout=5.0):
    """
    Wartet asynchron darauf, dass die platzierte Order eine gültige OrderID erhält.
    """
    start = time.time()
    while time.time() - start < timeout:
        if trade.order.orderId != 0:
            return trade.order.orderId
        await asyncio.sleep(0.2)
    return 0

# Add this new function near your other wait_for functions
async def wait_for_fill_or_cancel(trade, timeout=10.0):
    """
    Wartet maximal timeout Sekunden auf die Ausführung einer Order.
    Storniert die Order, falls sie nicht innerhalb des Timeouts ausgeführt wird.
    Returns:
        tuple: (filled, avgFillPrice)
        - filled: True wenn Order ausgeführt wurde, False wenn storniert
        - avgFillPrice: Durchschnittlicher Ausführungspreis oder None
    """
    start = time.time()
    while time.time() - start < timeout:
        if trade.orderStatus.status == "Filled":
            return True, trade.orderStatus.avgFillPrice
        await asyncio.sleep(0.1)
    
    # Timeout erreicht - Order stornieren
    print(f"⚠️ Timeout erreicht für Order {trade.order.orderId} nach {timeout} Sekunden, storniere...")
    ib.cancelOrder(trade.order)
    return False, None

async def wait_for_bracket_fill(parent_trade, tp_trade, ts_trade, timeout=3600.0):
    """
    Wartet darauf, dass zunächst die Parent-Order gefüllt wird und danach mindestens
    eine der Child-Orders (Take Profit oder Trailing Stop) gefüllt wird.
    Gibt ein Dictionary mit Fill-Preisen zurück:
      - parentFill: Fill Price der Parent-Order
      - childType: "takeProfit" oder "trailingStop", je nachdem, welcher zuerst gefüllt wurde
      - childFill: Fill Price der gefüllten Child-Order
    """
    start = time.time()
    parentFilled = False
    parentFill = None
    childType = None
    childFill = None

    while time.time() - start < timeout:
        # Parent füllt sich
        if not parentFilled:
            parentFill = parent_trade.orderStatus.avgFillPrice
            if parent_trade.orderStatus.status == "Filled":
                parentFilled = True
                print("✅ Parent Order gefüllt zum Preis:", parentFill)
        else:
            # Prüfe, ob eine der Child-Orders gefüllt wurde
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