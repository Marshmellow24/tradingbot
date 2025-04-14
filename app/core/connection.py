import os
from ib_insync import IB, util
import asyncio

class IBConnection:
    def __init__(self, ib):
        self.ib = ib
        self._keep_alive_task = None
        # Store connection params for reuse
        self.host = os.getenv('IB_HOST', '127.0.0.1')
        self.port = int(os.getenv('IB_PORT', '7497'))
        self.client_id = int(os.getenv('IB_CLIENT_ID', '1'))

    async def connect(self):
        util.patchAsyncio()
        await self.ib.connectAsync(
            host=self.host, 
            port=self.port, 
            clientId=self.client_id
        )
        self._keep_alive_task = asyncio.create_task(self._keep_alive())

    async def disconnect(self):
        if self._keep_alive_task:
            self._keep_alive_task.cancel()
        self.ib.disconnect()

    def is_connected(self):
        return self.ib.isConnected()

    async def reset_orders(self):
        self.ib.reqGlobalCancel()
        return {"status": "Orders cancelled"}

    async def get_open_orders(self):
        """Get all open orders from IBKR with detailed information"""
        if not self.is_connected():
            return []
            
        try:
            orders = self.ib.reqAllOpenOrders()
            formatted_orders = []
            
            for order in orders:
                # Create formatted order without timestamp
                formatted_order = {
                    "orderId": order.order.orderId,
                    "symbol": order.contract.symbol,
                    "secType": order.contract.secType,
                    "action": order.order.action,
                    "orderType": order.order.orderType,
                    "totalQuantity": order.order.totalQuantity,
                    "lmtPrice": order.order.lmtPrice if hasattr(order.order, 'lmtPrice') else 0,
                    "auxPrice": order.order.auxPrice if hasattr(order.order, 'auxPrice') else 0,
                    "status": order.orderStatus.status,
                    "filled": order.orderStatus.filled,
                    "remaining": order.orderStatus.remaining,
                    "avgFillPrice": order.orderStatus.avgFillPrice,
                    "parentId": order.order.parentId if hasattr(order.order, 'parentId') else None
                }
                
                # Only add timestamp if it exists
                if hasattr(order.orderStatus, 'lastTouchTime'):
                    formatted_order["timestamp"] = order.orderStatus.lastTouchTime
                
                formatted_orders.append(formatted_order)
            
            return formatted_orders
            
        except Exception as e:
            print(f"Error fetching open orders: {e}")
            return []

    async def get_trades(self):
        """Get all trades from IBKR"""
        trades = self.ib.reqTrades()
        return [trade.execution.execId for trade in trades]

    async def get_open_positions(self):
        """Get all open positions from IBKR"""
        if not self.is_connected():
            return []
            
        try:
            positions = self.ib.positions()  # Get current positions
            formatted_positions = []
            
            for position in positions:
                contract = position.contract
                
                # Qualify the contract first
                try:
                    self.ib.qualifyContracts(contract)
                except Exception as e:
                    print(f"Error qualifying contract {contract.symbol}: {e}")
                    continue
                    
                # Create basic position info
                pos_info = {
                    "symbol": contract.symbol,
                    "secType": contract.secType,
                    "exchange": contract.exchange,
                    "currency": contract.currency,
                    "position": self._safe_float(position.position),
                    "avgCost": self._safe_float(position.avgCost)
                }
                
                # Try to get market data
                try:
                    # Request market data with a qualified contract
                    ticker = self.ib.reqMktData(contract)
                    await asyncio.sleep(0.1)  # Brief delay for data to arrive
                    
                    # Add market-related data
                    pos_info.update({
                        "marketPrice": self._safe_float(ticker.last if ticker.last else ticker.close),
                        "marketValue": self._safe_float(pos_info["position"] * pos_info["marketPrice"]),
                        "unrealizedPNL": self._safe_float((pos_info["marketPrice"] - pos_info["avgCost"]) * pos_info["position"]),
                        "realizedPNL": 0.0  # Initialize to 0 since we can't get this directly
                    })
                    
                except Exception as e:
                    print(f"Error getting market data for {contract.symbol}: {e}")
                    # Add default values
                    pos_info.update({
                        "marketPrice": 0.0,
                        "marketValue": 0.0,
                        "unrealizedPNL": 0.0,
                        "realizedPNL": 0.0
                    })
                
                formatted_positions.append(pos_info)
                
                # Cancel market data subscription to avoid memory leaks
                try:
                    self.ib.cancelMktData(contract)
                except:
                    pass
            
            return formatted_positions
            
        except Exception as e:
            print(f"Error fetching open positions: {e}")
            return []

    def _safe_float(self, value):
        """Safely convert value to float, handling None and infinity"""
        try:
            if value is None:
                return 0.0
            float_val = float(value)
            # Handle infinity and NaN
            if not float_val or float_val == float('inf') or float_val == float('-inf') or float_val != float_val:  # last check is for NaN
                return 0.0
            return round(float_val, 2)  # Round to 2 decimal places
        except (TypeError, ValueError):
            return 0.0

    async def _keep_alive(self):
        while True:
            if not self.ib.isConnected():
                try:
                    await self.ib.connectAsync(
                        host=self.host,
                        port=self.port,
                        clientId=self.client_id
                    )
                    print(f"Reconnected to IB at {self.host}:{self.port}")
                except Exception as e:
                    print(f"Reconnection failed: {e}")
            await asyncio.sleep(10)