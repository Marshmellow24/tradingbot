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
                formatted_positions.append({
                    "symbol": position.contract.symbol,
                    "secType": position.contract.secType,
                    "exchange": position.contract.exchange,
                    "currency": position.contract.currency,
                    "position": position.position,  # Number of contracts
                    "avgCost": position.avgCost,    # Average entry price
                    "marketPrice": position.marketPrice,
                    "marketValue": position.marketValue,
                    "unrealizedPNL": position.unrealizedPNL,
                    "realizedPNL": position.realizedPNL
                })
            
            return formatted_positions
            
        except Exception as e:
            print(f"Error fetching open positions: {e}")
            return []

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