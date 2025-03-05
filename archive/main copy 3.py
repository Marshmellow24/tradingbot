# -*- coding: utf-8 -*-

import asyncio
import time
import yaml
from datetime import datetime, timedelta
from fastapi import FastAPI, HTTPException
from contextlib import asynccontextmanager
from pydantic import BaseModel
from ib_insync import *
import ib_insync as ibin
import uvicorn

# --- YAML-Konfiguration laden (falls gewünscht) ---
config = {}
try:
    with open('routes.yaml', 'r') as f:
        config = yaml.safe_load(f)
except Exception as e:
    print("Keine YAML-Konfiguration gefunden, Standardwerte werden verwendet.")
    config = {}

# --- Verbindung zu Interactive Brokers aufbauen ---
ib = IB()

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    ibin.util.patchAsyncio()
    await ib.connectAsync(host='127.0.0.1', port=7497, clientId=1)
    print("Verbindung zu IB steht.")
    
    async def keep_connection_alive():
        while True:
            if not ib.isConnected():
                print("Verbindung zu IB verloren, versuche erneut zu verbinden...")
                await ib.connectAsync(host='127.0.0.1', port=7497, clientId=1)
                print("Verbindung zu IB wiederhergestellt.")
            await asyncio.sleep(10)  # Check connection status every 10 seconds

    keep_alive_task = asyncio.create_task(keep_connection_alive())
    
    yield
    
    # Shutdown
    keep_alive_task.cancel()
    ib.disconnect()

app = FastAPI(lifespan=lifespan)

#
# Pydantic-Datenmodell für die Bracket-Order
#
class BracketOrderModel(BaseModel):
    symbol: str            # z.B. "ES" oder "NQ"
    action: str            # "BUY" oder "SELL"
    quantity: int
    stopPrice: float       # Absoluter Stop-Preis für den Parent (Stop-Entry Order)
    takeProfit: float      # Relativer Wert für Take Profit (in Ticks oder %)
    stopLoss: float        # Relativer Wert für Stop Loss (in Ticks oder %)
    relativeType: str      # "ticks" oder "percent"

async def wait_for_order_id(trade, timeout=5.0):
    """
    Wartet asynchron, bis die vom IB-Server platzierte Order eine gültige OrderID (ungleich 0) hat.
    """
    start = time.time()
    while time.time() - start < timeout:
        if trade.order.orderId != 0:
            return trade.order.orderId
        await asyncio.sleep(0.2)
    return 0  # Timeout

@app.post("/webhook")
async def place_bracket_order(order: BracketOrderModel):
    # Contract creation and qualification
    contract = Future(order.symbol, lastTradeDateOrContractMonth="202503", exchange="CME", currency="USD")
    print(f"🔍 Qualifying contract for {order.symbol}")
    ib.qualifyContracts(contract)
    print(f"✅ Contract qualified: {contract}")

    # Parent order creation
    parent = Order(
        action=order.action.upper(),
        totalQuantity=order.quantity,
        orderType="LMT",
        lmtPrice=order.stopPrice,
        transmit=False,
        outsideRth=True
    )
    print(f"📝 Created parent order: {parent.action} {parent.totalQuantity} @ {order.stopPrice}")
    
    # Place parent order and get ID
    parent_trade = ib.placeOrder(contract, parent)
    print(f"📤 Placed parent order, trade object: {parent_trade}")
    parent_id = await wait_for_order_id(parent_trade, timeout=5.0)
    print(f"🔑 Received parent order ID: {parent_id}")
    
    if parent_id == 0:
        print("❌ ERROR: Failed to get valid parent order ID")
        raise HTTPException(status_code=500, detail="Parent Order hat keine gültige OrderID erhalten.")

    # 3) Berechnung der absoluten Preise für die Child-Orders
    parentStopPrice = order.stopPrice  # Absoluter Stop-Preis des Parent
    if order.relativeType.lower() == "ticks":
        tick_size = 0.01  # Beispiel-Tick-Größe, ggf. anpassen
        if order.action.upper() == "BUY":
            takeProfitPrice = parentStopPrice + order.takeProfit * tick_size
            stopLossPrice = parentStopPrice - order.stopLoss * tick_size
        else:  # SELL
            takeProfitPrice = parentStopPrice - order.takeProfit * tick_size
            stopLossPrice = parentStopPrice + order.stopLoss * tick_size
    elif order.relativeType.lower() == "percent":
        if order.action.upper() == "BUY":
            takeProfitPrice = parentStopPrice * (1 + order.takeProfit / 100)
            stopLossPrice = parentStopPrice * (1 - order.stopLoss / 100)
        else:  # SELL
            takeProfitPrice = parentStopPrice * (1 - order.takeProfit / 100)
            stopLossPrice = parentStopPrice * (1 + order.stopLoss / 100)
    else:
        raise HTTPException(status_code=400, detail="Ungültiger Wert für relativeType. Erlaubt sind 'ticks' oder 'percent'.")

    # Create child orders
    stoploss = Order(
        action="SELL" if order.action.upper() == "BUY" else "BUY",
        totalQuantity=order.quantity,
        orderType="STP",
        auxPrice=stopLossPrice,
        transmit=False,
        outsideRth=True,
        parentId=parent_id
    )
    print(f"📝 Created stop-loss order: {stoploss.action} {stoploss.totalQuantity} @ {stopLossPrice}")
    
    takeprofit = Order(
        action="SELL" if order.action.upper() == "BUY" else "BUY",
        totalQuantity=order.quantity,
        orderType="LMT",
        lmtPrice=takeProfitPrice,
        transmit=True,
        outsideRth=True,
        parentId=parent_id
    )
    print(f"📝 Created take-profit order: {takeprofit.action} {takeprofit.totalQuantity} @ {takeProfitPrice}")
    
    # Place child orders
    sl_trade = ib.placeOrder(contract, stoploss)
    print(f"📤 Placed stop-loss order, trade object: {sl_trade}")
    tp_trade = ib.placeOrder(contract, takeprofit)
    print(f"📤 Placed take-profit order, trade object: {tp_trade}")

    response = {
        "status": "BracketOrder platziert",
        "parentOrderId": parent_id,
        "stopPrice": parentStopPrice,
        "takeProfitPrice": takeProfitPrice,
        "stopLossPrice": stopLossPrice,
        "trades": {
            "parent": str(parent_trade),
            "stopLoss": str(sl_trade),
            "takeProfit": str(tp_trade)
        }
    }
    print(f"✅ Complete bracket order placed successfully: {response}")
    return response


@app.get("/connection_status")
async def connection_status():
    """Endpoint zum Prüfen der IB-Verbindung."""
    return {"connected": ib.isConnected()}


if __name__ == '__main__':
    uvicorn.run(app, host="127.0.0.1", port=8000, lifespan="on")
