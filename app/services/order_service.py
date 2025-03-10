from fastapi import HTTPException
from ib_insync import *
from ..utils.helpers import wait_for_order_id, wait_for_fill_or_cancel, wait_for_bracket_fill
from ..core.dependencies import config, trade_logger
from ..api.models import BracketOrderModel
import yaml

# --- YAML-Konfiguration laden (optional) ---
config = {}
try:
    with open('config.yaml', 'r') as f:
        config = yaml.safe_load(f)
except Exception as e:
    print("❌ Keine YAML-Konfiguration gefunden, Standardwerte werden verwendet.")
    config = {}



class OrderService:
    def __init__(self, ib_connection):
        """Initialize with IB connection instance"""
        # Store the full connection object, not just the IB client
        self.ib_connection = ib_connection
        self.trade_logger = trade_logger
        

    async def place_bracket_order(self, order: BracketOrderModel):
        # Get IB instance from connection
        ib = self.ib_connection.ib

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
        
        # Use ib instance
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
            ib.cancelOrder(parent_trade.order)
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
        log_entry = self.trade_logger.log_trade(
            order=order,
            parent_fill=parentFill,
            child_fill=childFill,
            child_type=childType
        )
        
        return {
            "status": "BracketOrder with trailing stop fully filled and logged",
            "parentOrderId": parent.orderId,
            "parentFillPrice": parentFill,
            "childOrderType": childType,
            "childFillPrice": childFill,
            "logEntry": log_entry
        }