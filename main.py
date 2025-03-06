# -*- coding: utf-8 -*-

import asyncio
import time
import yaml
from datetime import datetime, timedelta
from fastapi import FastAPI, HTTPException, Response
from contextlib import asynccontextmanager
from pydantic import BaseModel
from ib_insync import *
import uvicorn
from config_watcher import ConfigWatcher

# --- YAML-Konfiguration laden (optional) ---
config = {}
try:
    with open('config.yaml', 'r') as f:
        config = yaml.safe_load(f)
except Exception as e:
    print("❌ Keine YAML-Konfiguration gefunden, Standardwerte werden verwendet.")
    config = {}


# Globales Log-Array für Trade Logs
trade_logs = []

# --- Verbindung zu Interactive Brokers aufbauen ---
ib = IB()

# Create global config instance
config = ConfigWatcher()

@asynccontextmanager
async def lifespan(app: FastAPI):
    util.patchAsyncio()
    await ib.connectAsync(host='127.0.0.1', port=7497, clientId=1)
    print("📡 Connecting to Interactive Brokers...")
    if ib.isConnected():
        print("✅ Connection to IB established successfully!")
    else:
        print("❌ Failed to connect to IB!")
    
    # Start config watcher
    await config.start_watching()

    async def keep_connection_alive():
        while True:
            if not ib.isConnected():
                print("⚡ Verbindung zu IB verloren, versuche erneut zu verbinden...")
                await ib.connectAsync(host='127.0.0.1', port=7497, clientId=1)
                print("✅ Verbindung zu IB wiederhergestellt.")
            await asyncio.sleep(10)
    
    keep_alive_task = asyncio.create_task(keep_connection_alive())
    
    yield

    await config.stop_watching()
    keep_alive_task.cancel()
    ib.disconnect()

app = FastAPI(lifespan=lifespan)

#
# Pydantic-Datenmodell für die Bracket-Order
#
class BracketOrderModel(BaseModel):
    symbol: str            # z.B. "AAPL" oder "NQ"
    action: str            # "BUY" oder "SELL"
    quantity: int
    limitPrice: float      # Absoluter Limitpreis für die Parent Order
    takeProfit: float      # Relativer Wert für Take Profit (in Ticks oder %)
    trailAmt: int           # Relativer Wert für den Trailing Stop (in Ticks)
    stopLoss: float = 20    # Relativer Wert für Stop Loss (Ticks)
    timeframe: str = "None"         # Zeitrahmen für die Chart-Analyse
    relativeType: str = "ticks"  # 'ticks' oder 'percent'

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

# Update the order placement logic in place_bracket_order function
@app.post("/webhook")
async def place_bracket_order(order: BracketOrderModel):
    # Load settings from YAML
    settings = config.get('order_settings', {})
    overrides = settings.get('overrides', {})
    timeouts = settings.get('timeouts', {})
    
    # Apply overrides if they exist
    quantity = overrides.get('quantity', order.quantity) if overrides.get('quantity') is not None else order.quantity
    trail_amt = overrides.get('trail_amount', order.trailAmt) if overrides.get('trail_amount') is not None else order.trailAmt
    stop_loss = overrides.get('stop_loss', order.stopLoss) if overrides.get('stop_loss') is not None else order.stopLoss 
    take_profit = overrides.get('take_profit', order.takeProfit) if overrides.get('take_profit') is not None else order.takeProfit
    tp_quantity = overrides.get('tp_quantity', quantity) if overrides.get('tp_quantity') is not None else quantity
    ts_quantity = overrides.get('ts_quantity', quantity) if overrides.get('ts_quantity') is not None else quantity

    # Get timeouts from YAML or use defaults
    fill_timeout = timeouts.get('fill_or_cancel', 10.0)
    bracket_timeout = timeouts.get('bracket_fill', 3600.0)

    print("✅ Received order:", order.model_dump())
    # 1) Vertrag erstellen und qualifizieren (hier z. B. als US-Aktie)
    
    if order.symbol == "NQ1!":
        contract = Future(symbol="NQ", lastTradeDateOrContractMonth="202503", exchange="CME", currency="USD")
    else:
        contract = Future(symbol=order.symbol, lastTradeDateOrContractMonth="202503", exchange="CME", currency="USD")
    ib.qualifyContracts(contract)
    print("✅ Contract qualified:", contract)
    
    # 2) Berechne die absoluten Zielpreise aus den relativen Werten.
    basePrice = round(order.limitPrice * 4, 0)/4  # Basis für die Umrechnung, muss gerundet werden auf Vielfaches von 0.25
    tick_size = 0.25  # Tick-Größe (Preise müssen ein Vielfaches von 0.25 sein)
    
    if order.relativeType.lower() == "ticks":
        if order.action.upper() == "BUY":
            absTakeProfit = basePrice + take_profit * tick_size
            absStopLoss   = basePrice - stop_loss * tick_size
        else:
            absTakeProfit = basePrice - take_profit * tick_size
            absStopLoss   = basePrice + stop_loss * tick_size
    else:
        raise HTTPException(status_code=400, detail="❌ Ungültiger relativeType. Erlaubt sind 'ticks' oder 'percent'.")
    
    print(f"⚙️ Base price: {basePrice}")
    print(f"⚙️ Calculated absolute takeProfit: {absTakeProfit}")     
    print(f"⚙️ Calculated absolute stopLoss (target): {absStopLoss}")

    # Runden auf Vielfaches der Tick-Größe:
    print(f"⚙️ Trailing amount (rounded): {trail_amt}")
    
    # 3) Parent Order erstellen: Limit Order
    parent = Order(
        action=order.action.upper(),
        totalQuantity=quantity,  # Use potentially overridden quantity
        orderType="LMT",
        lmtPrice=basePrice,
        transmit=False,
        outsideRth=True
    )
    print("🔄 Creating parent order:", parent)
    
    # 4) Parent Order platzieren und auf gültige OrderID warten
    parent_trade = ib.placeOrder(contract, parent)
    parent_id = await wait_for_order_id(parent_trade, timeout=5.0)
    if parent_id == 0:
        raise HTTPException(status_code=500, detail="❌ Parent Order hat keine gültige OrderID erhalten.")
    print("✅ Parent order placed. OrderID:", parent_id)
    
    tp_trade = None
    if settings.get("use_take_profit", True):
        # 5) Child Order für Take Profit erstellen (Limit Order)
        takeprofit = Order(
            action="SELL" if order.action.upper() == "BUY" else "BUY",
            totalQuantity=tp_quantity,
            orderType="LMT",
            lmtPrice=absTakeProfit,
            transmit= not settings.get("use_trailing_stop", True),  # Nicht sofort senden
            outsideRth=True,
            parentId=parent_id
        )
        tp_trade = ib.placeOrder(contract, takeprofit)
        print("✅ Created and placed take profit order:", takeprofit)
    
    # 6) Child Order für Trailing Stop erstellen (Trailing Stop Order)
    if settings.get("use_trailing_stop", True):
        trailing_stop = Order(
            action="SELL" if order.action.upper() == "BUY" else "BUY",
            totalQuantity=ts_quantity,
            orderType="TRAIL LIMIT",
            trailStopPrice=absStopLoss,  # Trailing Stop-Preis relativ zum Entry
            auxPrice=trail_amt, 
            lmtPriceOffset= 4 * tick_size,  # Mindestabstand zum Limit-Preis
            transmit=True,  # Mit dieser Order wird die gesamte Gruppe aktiviert
            outsideRth=True,
            parentId=parent_id
        )
        ts_trade = ib.placeOrder(contract, trailing_stop)
        print("✅ Created trailing stop order:", trailing_stop)
    
    parent_filled, parent_fill_price = await wait_for_fill_or_cancel(parent_trade, timeout=fill_timeout)
    
    if not parent_filled:
        raise HTTPException(
            status_code=408,
            detail=f"❌ Parent Order wurde nicht innerhalb von {fill_timeout} Sekunden ausgeführt."
        )
    
    print(f"✅ Parent order filled at price: {parent_fill_price}")

    # 8) Warten, bis der Parent gefüllt wird und einer der Child Orders ebenfalls gefüllt wird
    parentFilled, childType, parentFill, childFill = await wait_for_bracket_fill(parent_trade, tp_trade if tp_trade else None, ts_trade if ts_trade else None, timeout=bracket_timeout)
    
    if not parentFilled or childType is None:
        raise HTTPException(status_code=500, detail="❌ Order wurde nicht innerhalb des Zeitlimits vollständig gefüllt.")
    
    print(f"✅ Bracket order filled. ParentFill: {parentFill}, Child '{childType}' Fill: {childFill}")
    
    # 9) Gewinn/Verlust berechnen
    if parentFill is not None and childFill is not None:
        if order.action.upper() == "BUY":
            profit = childFill - parentFill
        else:
            profit = parentFill - childFill
    else:
        profit = 0.0

    if profit > 0:
        result_flag = "Profit"
    elif profit < 0:
        result_flag = "Loss"
    else:
        result_flag = "Neutral"

    # 10) Log-Eintrag erstellen – nur die wichtigsten Daten
    log_entry = {
        "timestamp": datetime.now().isoformat(),
        "symbol": order.symbol,
        "side": order.action.upper(),
        "contracts": order.quantity,
        "parentFillPrice": parentFill,
        "childFillPrice": childFill,
        "commision per contract" : 2.25,
        "timeframe (min)": order.timeframe,
        "hitType": childType,        # "takeProfit" oder "trailingStop"
        "profit": (round(profit, 2) * order.quantity * 20) - (2.25 * order.quantity * 2),   # auf 2 Nachkommastellen gerundet
        "result": result_flag         # "Profit", "Loss" oder "Neutral"
    }
    
    trade_logs.append(log_entry)
    print("📝 Logged trade entry:", log_entry)
    
    return {
        "status": "BracketOrder with trailing stop fully filled and logged",
        "parentOrderId": parent.orderId,
        "parentFillPrice": parentFill,
        "childOrderType": childType,
        "childFillPrice": childFill,
        "logEntry": log_entry
    }

@app.get("/reset_orders")
async def reset_orders():
    print("Storniere alle offenen Orders...")   
    ib.reqGlobalCancel()
    return {"status": "Remaining orders: " + str(ib.pendingTickers())}

@app.get("/trade_logs")
async def get_trade_logs():
    """Endpoint zum Abrufen der gespeicherten Trade-Logs."""
    return {"trade_logs": trade_logs}


@app.get("/connection_status")
async def connection_status():
    return {"connected": ib.isConnected()}

@app.get("/pending_orders")
async def pending_orders():
    return {"orders": ib.pendingTickers()}

@app.get("/favicon.ico", response_class=Response)
async def favicon():
    with open("static/favicon.ico", "rb") as f:
        return Response(content=f.read(), media_type="image/x-icon")
    
if __name__ == '__main__':
    uvicorn.run(app, host="127.0.0.1", port=8000, lifespan="on")
