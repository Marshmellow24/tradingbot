from ib_insync import IB, util
import asyncio

class IBConnection:
    def __init__(self, ib):
        self.ib = ib
        self._keep_alive_task = None

    async def connect(self):
        util.patchAsyncio()
        await self.ib.connectAsync(host='127.0.0.1', port=7497, clientId=1)
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

    async def _keep_alive(self):
        while True:
            if not self.ib.isConnected():
                await self.ib.connectAsync(host='127.0.0.1', port=7497, clientId=1)
            await asyncio.sleep(10)