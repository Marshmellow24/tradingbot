from fastapi import FastAPI, Response
from contextlib import asynccontextmanager
from fastapi.staticfiles import StaticFiles

# Import dependencies
from .core.dependencies import ib_connection, config, trade_logger, templates
from .api.router import router

@asynccontextmanager
async def lifespan(app: FastAPI):
    
    await ib_connection.connect()
    await config.start_watching()
    yield
    await config.stop_watching()
    await ib_connection.disconnect()

app = FastAPI(lifespan=lifespan)
app.mount("/static", StaticFiles(directory="static"), name="static")
app.include_router(router)

@app.get("/_ah/health")
async def health_check():
    """Health check endpoint for App Engine"""
    return Response(status_code=200)
