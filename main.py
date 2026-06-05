import os
import json
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import uvicorn
from dotenv import load_dotenv

load_dotenv() 

from groq import Groq 
from report_generator import create_pdf_report_from_dict 

app = FastAPI(title="Stateless AI Reporting API")
client = Groq(api_key=os.environ.get("GROQ_API_KEY"))

# --- The "Report Itself" (Power BI Semantic Model) ---
# This is the hardcoded schema the LLM actually needs to write valid DAX.
# When you connect to the real database later, you can fetch this dynamically from Power BI's Data Dictionary.
POWER_BI_SCHEMA = """
Table: 'Financials'
Columns:
- Date (Datetime)
- Product_Type (String: 'Gold Loan', 'MSME', 'Retail', 'Vehicle Loan')
- Customer_Name (String)
- State (String)

Measures:
- [Total_AUM] (Currency)
- [Total_Disbursement] (Currency)
- [Total_Collection] (Currency)
- [PAR_90_Percent] (Percentage)
- [Active_Loans] (Integer)
"""

class ReportRequest(BaseModel):
    user_prompt: str
    selected_date: str = "FY 2025"
    template_type: str = "investor_report"

class UpdateVisualRequest(BaseModel):
    user_prompt: str
    selected_date: str = "FY 2025"
    template_type: str = "investor_report"
    target_chart_id: str  

# --- AI Helper Functions ---

def generate_dax_query(prompt: str, target_date: str) -> str:
    """Uses LLM to generate the DAX query grounded strictly in the Power BI Semantic Model."""
    system_prompt = f"""
    You are a Power BI DAX expert. The user wants a report for {target_date}. 
    
    Here is the exact schema of our Power BI dataset:
    {POWER_BI_SCHEMA}
    
    CRITICAL: Generate ONLY a valid DAX query (e.g., EVALUATE SUMMARIZECOLUMNS...) using exactly these table and measure names. 
    Do not hallucinate column names. No markdown, no explanations.
    """
    
    response = client.chat.completions.create(
        model="openai/gpt-oss-120b",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt}
        ],
        temperature=0.1
    )
    return response.choices[0].message.content.strip()

def generate_visual_config(prompt: str) -> dict:
    """Uses LLM to generate the secure JSON configuration for matplotlib."""
    system_prompt = """
    You are a data visualization expert. The user wants to update a chart.
    Output ONLY a raw JSON object matching this schema. Do not use markdown blocks (```json).
    Schema:
    {
      "chart_type": "string (bar, line, pie, combo, scatter)",
      "title": "string",
      "x_axis": "string",
      "y_axis": "string",
      "colors": ["#HexCode"]
    }
    """
    
    response = client.chat.completions.create(
        model="llama3-70b-8192",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt}
        ],
        temperature=0.1,
        response_format={"type": "json_object"}
    )
    
    try:
        return json.loads(response.choices[0].message.content)
    except json.JSONDecodeError:
        raise ValueError("LLM failed to return valid JSON.")

# --- API Endpoints ---

@app.post("/generate-report", tags=["Reporting Workflow"])
async def generate_report(req: ReportRequest):
    try:
        # 1. AI Generates DAX using the backend Power BI Schema
        dax_query = generate_dax_query(req.user_prompt, req.selected_date)
        print(f"Executing DAX: \n{dax_query}") 
        
        # 2. Load the base JSON Template for the frontend
        template_path = os.path.join("templates", f"{req.template_type}.json")
        with open(template_path, 'r') as f:
            template_data = json.load(f)
            
        # 3. Render the PDF
        pdf_file_path = create_pdf_report_from_dict(
            template_data=template_data, 
            target_date=req.selected_date
        )
        
        return {
            "status": "success",
            "dax_used": dax_query,
            "local_pdf_path": pdf_file_path
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/update-visual", tags=["Reporting Workflow"])
async def update_visual(req: UpdateVisualRequest):
    try:
        # 1. AI Generates the new visual configuration
        new_chart_config = generate_visual_config(req.user_prompt)
        print(f"New Chart Config: {new_chart_config}")
        
        # 2. Load the base JSON template
        template_path = os.path.join("templates", f"{req.template_type}.json")
        with open(template_path, 'r') as f:
            template_data = json.load(f)
            
        # 3. Traverse the template and PATCH the target chart
        chart_found = False
        sections = template_data.get("pages", template_data.get("slides", []))
        for section in sections:
            for viz in section.get("visualizations", []):
                if viz.get("chart_id") == req.target_chart_id:
                    viz["chart_type"] = new_chart_config.get("chart_type", viz["chart_type"])
                    viz["title"] = new_chart_config.get("title", viz["title"])
                    if "x_axis" in new_chart_config: viz["x_axis"] = new_chart_config["x_axis"]
                    if "y_axis" in new_chart_config: viz["y_axis"] = new_chart_config["y_axis"]
                    
                    viz["config"] = new_chart_config 
                    chart_found = True
                    break
            if chart_found: break
                
        if not chart_found:
            raise HTTPException(status_code=404, detail="Target chart ID not found.")

        # 4. Generate DAX (Based on the prompt and the Power BI Schema)
        dax_query = generate_dax_query(req.user_prompt, req.selected_date)
        print(f"Executing Updated DAX: \n{dax_query}")
        
        # 5. Render the new PDF
        pdf_file_path = create_pdf_report_from_dict(
            template_data=template_data, 
            target_date=req.selected_date
        )
        
        return {
            "status": "success",
            "message": f"Successfully patched {req.target_chart_id}.",
            "local_pdf_path": pdf_file_path
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    uvicorn.run(
        "main:app", 
        host="0.0.0.0", 
        port=8000, 
        reload=True,
        reload_excludes=["generated_reports/*", "*.pdf", "*.html"]
    )