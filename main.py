import os
import json
import uuid
import redis
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import uvicorn
from report_generator import generate_report_file

app = FastAPI(title="Copilot Reporting API", version="1.0.0")

REDIS_URL = os.environ.get("REDIS_CONNECTION_STRING", "redis://localhost:6379/0")
redis_client = redis.StrictRedis.from_url(REDIS_URL, decode_responses=True)

class DraftRequest(BaseModel):
    conversation_id: str
    target_month: str
    target_year: str
    report_type: str = "Loan Tape"

class UpdateRequest(BaseModel):
    conversation_id: str
    target_kpi: str
    action_visual: str

@app.post("/generate-draft", tags=["Reporting Workflow"])
async def generate_draft(req: DraftRequest):
    try:
        # 1. Simulating data retrieved from Power BI DAX
        mock_dataframe = {
            "aum": 7500000, 
            "disbursements": 2300000,
            "month": req.target_month,
            "year": req.target_year
        }
        
        # 2. Store dataset state in Redis
        cache_key = f"draft_report_{req.conversation_id}"
        redis_client.setex(cache_key, 3600, json.dumps(mock_dataframe))
        
        # 3. Generate actual PPTX file
        absolute_file_path = generate_report_file(mock_dataframe, target_kpi="aum")
        
        ai_summary = f"Generated {req.report_type} for {req.target_month} {req.target_year}. Core focus is currently set to AUM."

        return {
            "status": "success",
            "aisummary": ai_summary,
            "reporturl": absolute_file_path  # Now returns the actual local path
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/update-visual", tags=["Reporting Workflow"])
async def update_visual(req: UpdateRequest):
    cache_key = f"draft_report_{req.conversation_id}"
    
    # 1. Pull data back from Redis
    cached_data_str = redis_client.get(cache_key)
    if not cached_data_str:
        raise HTTPException(status_code=404, detail="Session expired or not found.")
    
    cached_data = json.loads(cached_data_str)
    
    # 2. Re-trigger PPTX generation using swapped target KPI configuration
    absolute_file_path = generate_report_file(cached_data, target_kpi=req.target_kpi)
    
    return {
        "status": "success",
        "message": f"Successfully switched target visual slice emphasis to focus on {req.target_kpi}.",
        "reporturl": absolute_file_path
    }

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)