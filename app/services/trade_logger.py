from datetime import datetime

class TradeLogger:
    def __init__(self):
        self.logs = []

    def log_trade(self, order, parent_fill, child_fill, child_type):
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
        
        self.logs.append(log_entry)
        return log_entry