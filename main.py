import os
import json
import uuid
import redis
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import uvicorn

app = FastAPI(
    title="Copilot Reporting API",
    description="Microservice for generating and updating dynamic financial reports.",
    version="1.0.0"
)

# --- Connect to Redis ---
# Locally, this connects to localhost:6379. 
# In production, you will change this environment variable to your Azure Redis connection string.
REDIS_URL = os.environ.get("REDIS_CONNECTION_STRING", "redis://localhost:6379/0")
redis_client = redis.StrictRedis.from_url(REDIS_URL, decode_responses=True)

# --- Pydantic Models ---
class DraftRequest(BaseModel):
    conversation_id: str
    target_month: str
    target_year: str
    report_type: str = "Loan Tape"

class UpdateRequest(BaseModel):
    conversation_id: str
    target_kpi: str
    action_visual: str

# --- Endpoints ---
@app.post("/generate-draft", tags=["Reporting Workflow"])
async def generate_draft(req: DraftRequest):
    try:
        # 1. Mocked Power BI Data
        mock_dataframe = {
            "aum": 5000000, 
            "disbursements": 1200000,
            "month": req.target_month,
            "year": req.target_year
        }
        
        # 2. Store state in REAL Redis with a 1-hour TTL (3600 seconds)
        cache_key = f"draft_report_{req.conversation_id}"
        redis_client.setex(cache_key, 3600, json.dumps(mock_dataframe))
        
        ai_summary = f"Executive Summary: The {req.report_type} for {req.target_month} {req.target_year} shows strong performance."
        draft_url = f"https://mock-storage.azure.com/draft_{req.conversation_id}.pptx"

        return {
            "status": "success",
            "aisummary": ai_summary,
            "reporturl": draft_url
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/update-visual", tags=["Reporting Workflow"])
async def update_visual(req: UpdateRequest):
    cache_key = f"draft_report_{req.conversation_id}"
    
    # 1. Pull state back from real Redis
    cached_data_str = redis_client.get(cache_key)
    if not cached_data_str:
        raise HTTPException(
            status_code=404, 
            detail="Session expired or not found. Please request a new report."
        )
    
    # 2. Parse the JSON back into a Python dictionary
    cached_data = json.loads(cached_data_str)
    
    # 3. Simulate surgical update
    updated_url = f"https://mock-storage.azure.com/updated_{req.target_kpi}_{uuid.uuid4().hex[:6]}.pptx"
    
    return {
        "status": "success",
        "message": f"Successfully updated the {req.target_kpi} visual to a {req.action_visual} utilizing cached data from {cached_data['month']}.",
        "reporturl": updated_url
    }

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)