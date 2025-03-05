# -*- coding: utf-8 -*-

import asyncio
import time
import yaml
from fastapi import FastAPI, HTTPException
from contextlib import asynccontextmanager
from pydantic import BaseModel
from ib_insync import *
import ib_insync as ibin
import uvicorn

# --- YAML-Konfiguration laden ---
config = {}
try:
    with open('routes.yaml', 'r') as f:
        config = yaml.safe_load(f)
except Exception as e:
    print("Keine YAML-Konfiguration gefunden, Standardwerte werden verwendet.")
    config = {}

# Parameter, ob alternatives Orderrouting genutzt werden soll
orderRoutingEnabled = config.get("orderRoutingEnabled", False)
# Falls enabled, Liste der alternativen Routing-Optionen, ansonsten leere Liste
routes = config.get("routes", []) if orderRoutingEnabled else []

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
# Pydantic-Datenmodell um stopPrice erweitert
#
class OrderAlert(BaseModel):
    symbol: str          # z.B. "ES"
    action: str          # "BUY" oder "SELL"
    quantity: int
    takeProfit: float    # Relativer Wert (z.B. 10 Ticks oder 2%)
    stopLoss: float      # Relativer Wert
    relativeType: str    # "ticks" oder "percent"
    stopPrice: float     # <- Der Parent-Stop-Preis kommt jetzt aus dem JSON


#
# Hilfsfunktion zum Erstellen einer Bracket-Order, bei der die Parent-Order eine StopOrder ist.
#
def createBracketStopOrder(
    action: str,
    quantity: int,
    stopPrice: float,
    takeProfitPrice: float,
    stopLossPrice: float
):
    """
    Erzeugt eine Bracket-Order mit einer StopOrder als Parent (transmit=False),
    einer LimitOrder (TakeProfit) und einer StopOrder (StopLoss) als Childs.
    Die letzte Order bekommt transmit=True, damit alle Orders gleichzeitig
    aktiv werden, sobald sie an IB geschickt werden.
    """
    # Parent (Stop-Order)
    parent = StopOrder(
        action=action.upper(),
        totalQuantity=quantity,
        stopPrice=stopPrice,
        transmit=False
    )

    # Take-Profit (LimitOrder)
    tp_order = LimitOrder(
        action="SELL" if action.upper() == "BUY" else "BUY",
        totalQuantity=quantity,
        lmtPrice=takeProfitPrice,
        transmit=False
    )

    # Stop-Loss (StopOrder)
    sl_order = StopOrder(
        action="SELL" if action.upper() == "BUY" else "BUY",
        totalQuantity=quantity,
        stopPrice=stopLossPrice,
        transmit=True
    )

    # Parent/Child-Verknüpfung
    tp_order.parentId = parent.orderId
    sl_order.parentId = parent.orderId

    # OCA-Gruppe
    group_id = f"bracket_{int(time.time())}"
    tp_order.ocaGroup = group_id
    sl_order.ocaGroup = group_id
    tp_order.ocaType = 1
    sl_order.ocaType = 1

    return parent, tp_order, sl_order


#
# Wir platzieren alle drei Orders auf einmal und warten 10s,
# ob die Parent-StopOrder gefüllt wird. Falls nicht, stornieren wir sie.
#
async def try_order_with_route(
    contract: Contract,
    action: str,
    quantity: int,
    stopPrice: float,
    takeProfitPrice: float,
    stopLossPrice: float,
    algoStrategy: str,
    algoParams: list
):
    parent, tp_order, sl_order = createBracketStopOrder(
        action, quantity, stopPrice, takeProfitPrice, stopLossPrice
    )
    # parent.algoStrategy = algoStrategy
    # parent.algoParams = algoParams

    print(f"✅ Erstelle Bracket-StopOrder: StopPrice={stopPrice}, Routing={algoStrategy}/{algoParams}")

    # Zuerst Parent platzieren (damit Childs die parentId haben)
    trades = []
    trades.append(ib.placeOrder(contract, parent))
    trades.append(ib.placeOrder(contract, tp_order))
    trades.append(ib.placeOrder(contract, sl_order))

    # Bis zu 10s warten, ob die Parent-StopOrder gefüllt wird
    filled = False
    start = time.time()
    while time.time() - start < 10:
        if trades[0].orderStatus.status == "Filled":
            filled = True
            break
        ib.sleep(0.2)

    if filled:
        avgFillPrice = trades[0].orderStatus.avgFillPrice
        print(f"✅ StopOrder gefüllt zum Preis {avgFillPrice}")
        return parent, trades[0], avgFillPrice
    else:
        # Fallback: stornieren
        for t in trades:
            ib.cancelOrder(t.order)
        print(f"❌ StopOrder nicht gefüllt nach 10s, storniert.")
        return None, None, None


@app.post("/webhook")
async def webhook(alert: OrderAlert):
    """
    Dieser Endpunkt verarbeitet eingehende JSON-Daten, platziert
    eine Bracket-Order, bei der der Parent eine StopOrder ist.
    Der Stop-Preis wird aus alert.stopPrice übernommen.
    """
    # Für Futures-Beispiel
    contract = Future(symbol=alert.symbol, lastTradeDateOrContractMonth="202503", exchange="CME", currency="USD")
    ib.qualifyContracts(contract)

    # Wir verwenden den StopPrice aus dem Request:
    parentStopPrice = alert.stopPrice

    # Berechne TakeProfit/StopLoss relativ zum StopPrice (oder passe die Logik an).
    # Hier nehmen wir an, du wolltest Ticks (0.01) oder Prozent etc.
    # Du kannst die Logik beliebig anpassen.
    if alert.relativeType.lower() == "ticks":
        tick_size = 0.01
        if alert.action.upper() == "BUY":
            takeProfitPrice = parentStopPrice + alert.takeProfit * tick_size
            stopLossPrice = parentStopPrice - alert.stopLoss * tick_size
        else:  # SELL
            takeProfitPrice = parentStopPrice - alert.takeProfit * tick_size
            stopLossPrice = parentStopPrice + alert.stopLoss * tick_size
    elif alert.relativeType.lower() == "percent":
        if alert.action.upper() == "BUY":
            takeProfitPrice = parentStopPrice * (1 + alert.takeProfit / 100)
            stopLossPrice = parentStopPrice * (1 - alert.stopLoss / 100)
        else:  # SELL
            takeProfitPrice = parentStopPrice * (1 - alert.takeProfit / 100)
            stopLossPrice = parentStopPrice * (1 + alert.stopLoss / 100)
    else:
        raise HTTPException(status_code=400, detail="❌ Ungültiger Wert für relativeType. Erlaubt sind 'ticks' oder 'percent'.")

    # Standardroute: z.B. Adaptive, Normal Priority
    default_algoStrategy = "Adaptive"
    default_algoParams = [TagValue("adaptivePriority", "Normal")]

    parentOrder, parentTrade, avgFillPrice = await try_order_with_route(
        contract=contract,
        action=alert.action,
        quantity=alert.quantity,
        stopPrice=parentStopPrice,
        takeProfitPrice=takeProfitPrice,
        stopLossPrice=stopLossPrice,
        algoStrategy=default_algoStrategy,
        algoParams=default_algoParams
    )

    # Falls nicht gefüllt, Fallback
    if parentOrder is None:
        if orderRoutingEnabled and routes:
            for route in routes:
                route_algoStrategy = route.get("algoStrategy", default_algoStrategy)
                route_algoParams = route.get("algoParams", default_algoParams)

                parentOrder, parentTrade, avgFillPrice = await try_order_with_route(
                    contract=contract,
                    action=alert.action,
                    quantity=alert.quantity,
                    stopPrice=parentStopPrice,
                    takeProfitPrice=takeProfitPrice,
                    stopLossPrice=stopLossPrice,
                    algoStrategy=route_algoStrategy,
                    algoParams=route_algoParams
                )
                if parentOrder is not None:
                    break
            else:
                raise HTTPException(status_code=500, detail="❌ StopOrder konnte über keine Routing-Option gefüllt werden.")
        else:
            raise HTTPException(status_code=500, detail="❌ StopOrder nicht innerhalb von 10 Sekunden gefüllt und Orderrouting ist deaktiviert.")

    return {
        "status": "Bracket-StopOrder platziert (inkl. Child-Orders)",
        "parentOrder": {
            "orderId": parentOrder.orderId if parentOrder else None,
            "stopPrice": parentStopPrice,
            "fillPrice": avgFillPrice or 0.0
        }
    }


@app.get("/connection_status")
async def connection_status():
    """Endpoint to check the connection status to Interactive Brokers."""
    return {"connected": ib.isConnected()}


if __name__ == '__main__':
    uvicorn.run(app, host="127.0.0.1", port=8000, lifespan="on")
