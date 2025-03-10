from datetime import datetime
from typing import Optional

class TradeLogger:
    def __init__(self):
        self.logs = []

    def log_trade(
        self,
        order,
        parent_fill: float,
        child_fill: float,
        child_type: str,
        commission_per_contract: float = 2.25,
        tick_value: float = 20.0
    ) -> dict:
        """
        Log a completed trade with all necessary information.
        
        Args:
            order: The original bracket order
            parent_fill: Entry price
            child_fill: Exit price
            child_type: Type of exit ("takeProfit" or "trailingStop")
            commission_per_contract: Commission cost per contract
            tick_value: Dollar value per tick
        """
        # Calculate profit/loss
        profit = (child_fill - parent_fill) if order.action.upper() == "BUY" else (parent_fill - child_fill)
        total_commission = commission_per_contract * order.quantity * 2  # Entry and exit
        total_profit = (round(profit, 2) * order.quantity * tick_value) - total_commission
        
        # Determine result
        result_flag = (
            "Profit" if total_profit > 0
            else "Loss" if total_profit < 0
            else "Neutral"
        )

        log_entry = {
            "timestamp": datetime.now().isoformat(),
            "symbol": order.symbol,
            "side": order.action.upper(),
            "contracts": order.quantity,
            "parentFillPrice": parent_fill,
            "childFillPrice": child_fill,
            "commission_per_contract": commission_per_contract,
            "timeframe": order.timeframe,
            "hitType": child_type,
            "profit": total_profit,
            "result": result_flag
        }
        
        self.logs.append(log_entry)
        print(f"📝 Logged trade entry: {log_entry}")
        return log_entry