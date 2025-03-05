# -*- coding: utf-8 -*-

import asyncio
import time
import yaml
from datetime import datetime, timedelta
from fastapi import FastAPI, HTTPException
from contextlib import asynccontextmanager
from pydantic import BaseModel
from ib_insync import *
import uvicorn

# --- YAML-Konfiguration laden (optional) ---
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
    util.patchAsyncio()
    await ib.connectAsync(host='127.0.0.1', port=7497, clientId=1)
    print("Verbindung zu IB steht.")
    
    async def keep_connection_alive():
        while True:
            if not ib.isConnected():
                print("Verbindung zu IB verloren, versuche erneut zu verbinden...")
                await ib.connectAsync(host='127.0.0.1', port=7497, clientId=1)
                print("Verbindung zu IB wiederhergestellt.")
            await asyncio.sleep(10)
    
    keep_alive_task = asyncio.create_task(keep_connection_alive())
    yield
    keep_alive_task.cancel()
    ib.disconnect()

app = FastAPI(lifespan=lifespan)

#
# Pydantic-Datenmodell für die Bracket-Order
#
class BracketOrderModel(BaseModel):
    symbol: str            # z.B. "AAPL"
    action: str            # "BUY" oder "SELL"
    quantity: int
    limitPrice: float      # Absoluter Preis für die Parent-Order (Limit Order)
    takeProfit: float      # Relativer Wert für Take Profit (in Ticks oder %)
    stopLoss: float        # Relativer Wert für Stop Loss (in Ticks oder %)
    relativeType: str = "ticks"  # 'ticks' oder 'percent'

@app.get("/")
async def home():
    return {"message": "Welcome to the Trading Web Server that offers you an API to send signals to IBKR!"}

@app.post("/webhook")
async def place_bracket_order(order: BracketOrderModel):
    # Logge die empfangenen Parameter
    print("Received order:", order.dict())
    
    # 1) Vertrag erstellen und qualifizieren (hier als Beispiel eine US-Aktie)
    contract = Future(order.symbol, lastTradeDateOrContractMonth="202503", exchange="CME", currency="USD")
    ib.qualifyContracts(contract)
    print("Contract qualified:", contract)
    
    # 2) Umrechnung der relativen Werte in absolute Preise
    basePrice = order.limitPrice  # Dieser Preis wird als Basis genommen
    tick_size = 0.25 # Beispiel: Tick-Größe, ggf. anpassen
    
    if order.relativeType.lower() == "ticks":
        if order.action.upper() == "BUY":
            absTakeProfit = basePrice + order.takeProfit * tick_size
            absStopLoss   = basePrice - order.stopLoss * tick_size
        else:  # SELL
            absTakeProfit = basePrice - order.takeProfit * tick_size
            absStopLoss   = basePrice + order.stopLoss * tick_size
    elif order.relativeType.lower() == "percent":
        if order.action.upper() == "BUY":
            absTakeProfit = basePrice * (1 + order.takeProfit / 100)
            absStopLoss   = basePrice * (1 - order.stopLoss / 100)
        else:  # SELL
            absTakeProfit = basePrice * (1 - order.takeProfit / 100)
            absStopLoss   = basePrice * (1 + order.stopLoss / 100)
    else:
        raise HTTPException(status_code=400, detail="Ungültiger relativeType. Erlaubt sind 'ticks' oder 'percent'.")
    
    print(f"Base price: {basePrice}")
    print(f"Calculated absolute takeProfitPrice: {absTakeProfit}")
    print(f"Calculated absolute stopLossPrice: {absStopLoss}")
    
    # 3) Bracket-Order erstellen mittels ib.bracketOrder:
    #    Der Parent wird als LimitOrder angelegt.
    bracket = ib.bracketOrder(
        action=order.action.upper(),
        quantity=order.quantity,
        limitPrice=order.limitPrice,
        takeProfitPrice=absTakeProfit,
        stopLossPrice=absStopLoss,
        outsideRth=True  # Nur während der regulären Handelszeiten
    )
    
    # 4) TIF 'GTD' setzen: Good-Till-Date für 45 Sekunden ab jetzt
    # gtdelta = (datetime.now() + timedelta(seconds=45)).strftime("%Y%m%d %H:%M:%S")
    # bracket.parent.tif = 'GTD'
    # bracket.parent.goodTillDate = gtdelta
    
    print("Bracket order details:")
    print("Parent:", bracket.parent)
    print("TakeProfit:", bracket.takeProfit)
    print("StopLoss:", bracket.stopLoss)
    
    # 5) Alle Orders der Bracket-Gruppe platzieren
    for o in bracket:
        trade = ib.placeOrder(contract, o)
        print("Placed order:", trade)
    
    return {
        "status": "BracketOrder platziert",
        "parentOrderId": bracket.parent.orderId,
        "limitPrice": order.limitPrice,
        "absTakeProfitPrice": absTakeProfit,
        "absStopLossPrice": absStopLoss,
        # "tif": bracket.parent.tif,
        # "goodTillDate": bracket.parent.goodTillDate
    }

@app.get("/connection_status")
async def connection_status():
    """Endpoint zum Prüfen der IB-Verbindung."""
    return {"connected": ib.isConnected()}

if __name__ == '__main__':
    uvicorn.run(app, host="127.0.0.1", port=8000, lifespan="on")
