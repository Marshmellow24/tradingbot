from pydantic import BaseModel

class BracketOrderModel(BaseModel):
    symbol: str            
    action: str            
    quantity: int
    limitPrice: float      
    takeProfit: float      
    trailAmt: int          
    stopLoss: float = 20    
    timeframe: str = "None" 
    relativeType: str = "ticks"