# -*- coding: utf-8 -*-

import asyncio
# import time
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
    symbol: str            # z.B. "AAPL"
    action: str            # "BUY" oder "SELL"
    quantity: int
    stopPrice: float      # Limit-Preis für die Parent-Order
    takeProfit: float # Ziel für Gewinnmitnahme
    stopLoss: float   # Stop-Loss-Preis


@app.post("/webhook")
async def place_bracket_order(order: BracketOrderModel):
    """
    Nimmt Order-Parameter als JSON entgegen und platziert eine klassische Bracket-Order
    mit ib.bracketOrder(...). Dabei:
      - Parent-Order = LimitOrder (mit outsideRth=True)
      - Take-Profit-Order (Limit)
      - Stop-Loss-Order (Stop)
    Die Parent-Order bekommt TIF='GTD' (Good-Till-Date) für 45 Sekunden ab jetzt.
    """
    # 1) Vertrag erstellen (hier: US-Aktie) und qualifizieren
    contract = Future(order.symbol, lastTradeDateOrContractMonth="202503", exchange="CME", currency="USD")
    ib.qualifyContracts(contract)

    # Create parent order
    parent = Order(
        action=order.action.upper(),    # "BUY" oder "SELL"
        totalQuantity=order.quantity,
        orderType="STP",                # Stop-Order
        auxPrice=order.stopPrice,       # Stop-Preis
        # algoStrategy="Adaptive",        # Adaptive-Algorithmus
        # algoParams=[TagValue("adaptivePriority", "Normal")],
        transmit=False,                 # Nicht sofort aktivieren
        outsideRth=True                 # Auch außerhalb der Handelszeiten zulassen
    )
    
    # Place parent order first to get orderId
    trade = ib.placeOrder(contract, parent)
    parent_id = trade.order.orderId
    print(parent_id, trade.orderStatus.orderId)

    # Create and place stop loss order
    stoploss = Order(
        action="SELL" if order.action.upper() == "BUY" else "BUY",
        totalQuantity=order.quantity,
        orderType="STP",
        auxPrice=order.stopLoss,
        transmit=False,
        # algoStrategy="Adaptive",        # Adaptive-Algorithmus
        # algoParams=[TagValue("adaptivePriority", "Normal")],
        outsideRth=True,  
        parentId=parent.orderId
    )
    trade2 = ib.placeOrder(contract, stoploss)
    print(str(trade2.orderStatus.orderId) + " " + str(trade2.orderStatus.parentId))
    # Create and place take profit order
    takeprofit = Order(
        action="SELL" if order.action.upper() == "BUY" else "BUY",
        totalQuantity=order.quantity,
        orderType="LMT",
        lmtPrice=order.takeProfit,
        transmit=True,
        # algoStrategy="Adaptive",        # Adaptive-Algorithmus
        # algoParams=[TagValue("adaptivePriority", "Normal")],
        outsideRth=True,
        parentId=parent.orderId
    )
    ib.placeOrder(contract, takeprofit)

    # # 2) Bracket-Order erstellen
    # bracket = ib.bracketOrder(
    #     action=order.action.upper(),          # "BUY" oder "SELL"
    #     quantity=order.quantity,
    #     limitPrice=order.stopPrice,
    #     takeProfitPrice=order.takeProfit,
    #     stopLossPrice=order.stopLoss,
    #     outsideRth=True                      # Auch außerhalb der Handelszeiten zulassen
    # )

    # # 3) Good-Till-Date (45 Sekunden in die Zukunft) für den Parent
    # gtdelta = (datetime.now() + timedelta(seconds=45)).strftime("%Y%m%d %H:%M:%S")
    # bracket.parent.tif = 'GTD'
    # bracket.parent.goodTillDate = gtdelta

    # # 4) Alle Orders platzieren
    # for o in bracket:
    #     ib.placeOrder(contract, o)

    return {
        "status": "BracketOrder platziert",
        "parentOrderId": parent.orderId,
        "limitPrice": order.stopPrice,
        "takeProfitPrice": order.takeProfit,
        "stopLossPrice": order.stopLoss,
        # "tif": parent.tif,
        # "goodTillDate": parent.goodTillDate
    }


@app.get("/connection_status")
async def connection_status():
    """
    Endpoint zum Prüfen der IB-Verbindung.
    """
    return {"connected": ib.isConnected()}


if __name__ == '__main__':
    uvicorn.run(app, host="127.0.0.1", port=8000, lifespan="on")
