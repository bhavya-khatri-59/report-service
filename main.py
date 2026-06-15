import os
import time
import requests
import msal
import shutil
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import uvicorn
from dotenv import load_dotenv

from groq import Groq
import fitz  # PyMuPDF

import matplotlib.pyplot as plt
import numpy as np
import io
import json

load_dotenv() 

app = FastAPI(title="Enterprise AI Reporting Backend")

client = Groq(api_key=os.environ.get("GROQ_API_KEY"))

# --- THE SCHEMA-COMPLIANT DAX TEMPLATE (WITH DYNAMIC FILTER INJECTION) ---
REPORT_TEMPLATE = {
    "slide_1": {
        "page_index": 0, 
        "context_name": "Portfolio Profile",
        "visuals": {
            "aum_kpi": "EVALUATE CALCULATETABLE(ROW(\"Total_AUM\", [AUM]), 'Dim Date'[FinancialYear] = \"{req_year}\")",
            "disbursement_kpi": "EVALUATE CALCULATETABLE(ROW(\"Total_Disbursement\", SUM('nbfc loan_tape_report_bi'[DisbursementAmount])), 'Dim Date'[FinancialYear] = \"{req_year}\")"
        }
    },
    "slide_2": {
        "page_index": 1, 
        "context_name": "Portfolio Quality",
        "visuals": {
            "bucket_aum": "EVALUATE CALCULATETABLE(SUMMARIZECOLUMNS('as on 31Jul25'[Overdue Bucket], \"AUM\", [AUM]), 'Dim Date'[FinancialYear] = \"{req_year}\")",
            "state_par": "EVALUATE CALCULATETABLE(SUMMARIZECOLUMNS('States'[State], \"PAR_90_Plus\", [PAR 90 +]), 'Dim Date'[FinancialYear] = \"{req_year}\")"
        }
    },
    "slide_3": {
        "page_index": 2, 
        "context_name": "Future Projections",
        "visuals": {
            "future_principal": "EVALUATE CALCULATETABLE(ROW(\"Future_Principal\", SUM('Future_cash_flow'[Amount])), 'Dim Date'[FinancialYear] = \"{req_year}\")",
            "future_aum": "EVALUATE CALCULATETABLE(ROW(\"Projected_AUM\", [AUM]), 'Dim Date'[FinancialYear] = \"{req_year}\")" 
        }
    },
    "slide_4": {
        "page_index": 3, 
        "context_name": "Customer Profile",
        "visuals": {
            "collection_efficiency": "EVALUATE CALCULATETABLE(SUMMARIZECOLUMNS('Dim Date'[MonthName], \"CE_Percent\", SUM('Demandcollectionmatch'[collection_efficiency])), 'Dim Date'[FinancialYear] = \"{req_year}\")",
            "qoq_disbursement": "EVALUATE CALCULATETABLE(SUMMARIZECOLUMNS('Dim Date'[Financial Quarter], \"Disbursement\", SUM('nbfc loan_tape_report_bi'[DisbursementAmount])), 'Dim Date'[FinancialYear] = \"{req_year}\")"
        }
    }
}

# --- Enterprise Payload Structure ---
class EnterpriseRequest(BaseModel):
    # Intent dictates the flow: e.g., "board pack" vs "board pack with summary"
    intent_type: str = "board pack with summary" 
    period: str = "FY 2025" 
    entity: str = "global"
    user_oid: str = "mocked-local-dev-oid"

# Custom Payload Structure
class CustomVisualRequest(BaseModel):
    intent: str = "Show me disbursement amount by product type"
    period: str = "FY 2025"

# --- 1. Power BI Authentication ---
def get_power_bi_token() -> str:
    authority = f"https://login.microsoftonline.com/{os.environ.get('AZURE_DIR_ID')}"
    app = msal.ConfidentialClientApplication(
        os.environ.get("AZURE_APP_ID"),
        authority=authority,
        client_credential=os.environ.get("POWER_BI_CLIENT_SECRET")
    )
    scopes = ["https://analysis.windows.net/powerbi/api/.default"]
    result = app.acquire_token_for_client(scopes=scopes)
    
    if "access_token" in result:
        return result["access_token"]
    else:
        raise Exception(f"Auth Failed: {result.get('error_description')}")

# --- 2. Live DAX Execution ---
def execute_live_dax(token: str, dax_query: str) -> str:
    workspace_id = os.environ.get("POWER_BI_WORKSPACE_ID")
    dataset_id = os.environ.get("POWER_BI_DATASET_ID")
    url = f"https://api.powerbi.com/v1.0/myorg/groups/{workspace_id}/datasets/{dataset_id}/executeQueries"
    
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    payload = {"queries": [{"query": dax_query}], "serializerSettings": {"includeNulls": True}}
    
    response = requests.post(url, headers=headers, json=payload)
    if response.status_code == 200:
        rows = response.json().get('results', [{}])[0].get('tables', [{}])[0].get('rows', [])
        return str(rows)
    else:
        print(f"DAX Error: {response.text}")
        return "Data fetch failed."

# --- 3. Filtered PDF Export ---
def export_filtered_pdf(token: str, requested_year: str, output_path: str):
    workspace_id = os.environ.get("POWER_BI_WORKSPACE_ID")
    report_id = os.environ.get("POWER_BI_REPORT_ID")
    
    base_report_url = f"https://api.powerbi.com/v1.0/myorg/groups/{workspace_id}/reports/{report_id}"
    export_trigger_url = f"{base_report_url}/ExportTo"
    
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    
    export_payload = {
        "format": "PDF",
        "powerBIReportConfiguration": {
            "reportLevelFilters": [
                {"filter": f"Dim Date/FinancialYear eq '{requested_year}'"}
            ]
        }
    }
    
    print(f"Initiating PDF Export for {requested_year}...")
    trigger_resp = requests.post(export_trigger_url, headers=headers, json=export_payload)
    trigger_resp.raise_for_status() 
    export_id = trigger_resp.json().get("id")
    
    poll_url = f"{base_report_url}/exports/{export_id}"
    file_url = f"{base_report_url}/exports/{export_id}/file"
    
    while True:
        poll_resp = requests.get(poll_url, headers=headers)
        poll_resp.raise_for_status() 
        
        status = poll_resp.json().get("status")
        if status == "Succeeded":
            break
        elif status == "Failed":
            raise Exception("Power BI Export failed on Microsoft's servers.")
            
        print("Waiting for Power BI servers to render PDF...")
        time.sleep(4)
        
    print("Downloading rendered PDF...")
    file_resp = requests.get(file_url, headers=headers)
    file_resp.raise_for_status()
    
    with open(output_path, 'wb') as f:
        f.write(file_resp.content)

# --- 4. AI Brain (Consolidated Executive Summary) ---
def generate_executive_summary(all_data_map: dict) -> str:
    context_lines = []
    for slide_name, visual_data in all_data_map.items():
        context_lines.append(f"\n--- {slide_name} ---")
        for viz_name, data in visual_data.items():
            context_lines.append(f"- {viz_name}: {data}")
            
    context_string = "\n".join(context_lines)
    
    system_prompt = f"""
    You are a Chief Financial Officer. Based ONLY on the following visual-level data extracts from the complete report, 
    write a single, cohesive 5-6 line executive summary paragraph explaining the overall health, quality, and projections of the portfolio.
    
    Data Extracts:
    {context_string}
    
    CRITICAL INSTRUCTIONS:
    - Keep it strictly professional and in a single paragraph (5-6 lines).
    - DO NOT use the Rupee symbol (₹), use "INR" or "Rs." instead.
    - STRICTLY USE ONLY BASIC ASCII CHARACTERS. 
    - DO NOT use smart quotes (use standard ' and "), en-dashes, or em-dashes (use standard hyphen -).
    - DO NOT use bullet points.
    """
    
    response = client.chat.completions.create(
        model="openai/gpt-oss-120b", 
        messages=[{"role": "system", "content": system_prompt}],
        temperature=0.2
    )
    return response.choices[0].message.content.strip()

# --- 5. Document Stitching Engine (Append Page) ---
def append_summary_page(input_pdf_path: str, output_pdf_path: str, summary_text: str):
    doc = fitz.open(input_pdf_path)
    
    # Grab dimensions of the first page to ensure the new page matches perfectly
    rect = doc[0].rect
    new_page = doc.new_page(width=rect.width, height=rect.height)
    
    # Draw a clean white background
    new_page.draw_rect(new_page.rect, color=(1, 1, 1), fill=(1, 1, 1))
    
    # Clean ASCII characters just in case
    clean_text = summary_text.replace('—', '-').replace('–', '-').replace('‘', "'").replace('’', "'").replace('“', '"').replace('”', '"').replace('\u202F', ' ').replace('\u00A0', ' ')
    
    # Draw Header
    new_page.insert_text((50, 60), "Executive Summary", fontsize=50, fontname="hebo", color=(0, 0.12, 0.31))
    
    # Draw Paragraph
    text_rect = fitz.Rect(50, 110, rect.width - 50, rect.height - 50)
    new_page.insert_textbox(text_rect, clean_text, fontsize=40, fontname="helv", color=(0.2, 0.2, 0.2))
        
    doc.save(output_pdf_path)
    doc.close()

# Matplot Lib Custom Chart Generator

def generate_matplotlib_chart(chart_spec: dict) -> str:
    """
    Takes a JSON blueprint and renders a branded Matplotlib chart.
    Returns the file path to the generated PNG.
    """
    plt.style.use('seaborn-v0_8-whitegrid') # Clean, modern base
    
    chart_type = chart_spec.get("chart_type", "bar")
    title = chart_spec.get("title", "Custom Insight")
    labels = chart_spec.get("labels", [])
    values = chart_spec.get("values", [])
    
    fig, ax = plt.subplots(figsize=(8, 5))
    
    # Open Terrace Brand Colors (Deep Blue, Orange, Light Blue)
    brand_colors = ['#001f4f', '#f47c36', '#2a9df4', '#9370db', '#a9a9a9']
    
    if chart_type == "bar":
        bars = ax.bar(labels, values, color=brand_colors[:len(labels)])
        ax.set_ylabel(chart_spec.get("y_label", "Value"))
        
    elif chart_type == "line":
        ax.plot(labels, values, marker='o', color='#f47c36', linewidth=2)
        ax.set_ylabel(chart_spec.get("y_label", "Value"))
        
    elif chart_type == "pie":
        ax.pie(values, labels=labels, autopct='%1.1f%%', startangle=90, colors=brand_colors)
        ax.axis('equal') # Equal aspect ratio ensures pie is circular
        
    plt.title(title, fontsize=16, fontweight='bold', color='#001f4f', pad=15)
    plt.xticks(rotation=45, ha='right')
    plt.tight_layout()
    
    output_path = f"custom_visual_{int(time.time())}.png"
    plt.savefig(output_path, dpi=300, transparent=True)
    plt.close()
    
    return output_path

def get_ad_hoc_blueprint(user_intent: str, requested_year: str) -> dict:
    # We pass the schema explicitly so the AI knows exact table/column names
    schema_context = """
    TABLES AND MEASURES:
    - 'Dim Date'[FinancialYear], 'Dim Date'[MonthName], 'Dim Date'[Financial Quarter]
    - 'Product wise'[ProductType]
    - 'States'[State]
    - 'Key_insights'[AUM], 'Key_insights'[PAR 90 +]
    - 'nbfc loan_tape_report_bi'[DisbursementAmount]
    """
    
    system_prompt = f"""
    You are a Power BI Data Engineer. The user wants a custom chart for {requested_year}.
    Based on the schema below, generate a JSON object containing the DAX query to get this data, 
    and the Matplotlib configuration to render it.
    
    {schema_context}
    
    User Request: "{user_intent}"
    
    CRITICAL INSTRUCTIONS:
    - Output ONLY valid JSON. No markdown, no conversational text.
    - The dax_query MUST be a valid EVALUATE SUMMARIZECOLUMNS statement.
    - chart_type MUST be one of: "bar", "line", or "pie".
    
    REQUIRED JSON FORMAT:
    {{
        "dax_query": "EVALUATE CALCULATETABLE(SUMMARIZECOLUMNS(...), 'Dim Date'[FinancialYear] = \"{requested_year}\")",
        "chart_type": "bar",
        "title": "Chart Title",
        "x_column_name": "Exact Name of X column in DAX results",
        "y_column_name": "Exact Name of Y column in DAX results",
        "y_label": "Y-Axis Label"
    }}
    """
    
    response = client.chat.completions.create(
        model="openai/gpt-oss-120b",
        messages=[{"role": "system", "content": system_prompt}],
        temperature=0.0, # Zero creativity, strictly factual output
        response_format={"type": "json_object"} # Forces Groq to return pure JSON
    )
    
    return json.loads(response.choices[0].message.content)

# --- THE CORE ENDPOINT ---
@app.post("/generate-report", tags=["Enterprise Workflow"])
async def generate_enterprise_report(req: EnterpriseRequest):
    try:
        print(f"\n--- INITIATING RUN FOR {req.period.upper()} ---")
        token = get_power_bi_token()
        print("✅ Azure Entra ID Token Acquired")
        
        # 1. Fetch the cleanly filtered native PDF
        native_pdf_path = f"temp_native_{req.period.replace(' ', '_')}.pdf"
        export_filtered_pdf(token, req.period, native_pdf_path)
        print("✅ Native PDF Exported")

        output_filename = f"{req.entity}_{req.intent_type.replace(' ', '_')}_{req.period.replace(' ', '_')}.pdf"
        
        # Determine if the user actually wants the AI summary
        needs_summary = "summary" in req.intent_type.lower()
        
        if needs_summary:
            # 2. Execute Data Extraction and AI Summarization
            all_extracted_data = {}
            print("\n--- EXTRACTING LIVE DAX & GENERATING AI INSIGHTS ---")
            
            for slide_key, slide_info in REPORT_TEMPLATE.items():
                slide_name = slide_info["context_name"]
                visual_data_map = {}
                
                if not slide_info["visuals"]:
                    continue
                    
                print(f"Extracting data for {slide_name}...")
                for viz_id, base_dax in slide_info["visuals"].items():
                    formatted_dax = base_dax.replace("{req_year}", req.period)
                    live_data = execute_live_dax(token, formatted_dax)
                    visual_data_map[viz_id] = live_data
                    
                all_extracted_data[slide_name] = visual_data_map
                
            print("Generating Consolidated Executive Summary...")
            ai_summary = generate_executive_summary(all_extracted_data)
            print("✅ AI Summary Generated")

            # 3. Append Summary Page to PDF
            append_summary_page(native_pdf_path, output_filename, ai_summary)
            print("✅ Final Document Assembled with Summary Page")
            
            commentary_preview = ai_summary[:150] + "..."
            
        else:
            # Default Export: Just rename the native PDF and skip the DAX/AI workload
            print("\n--- DEFAULT EXPORT REQUESTED (SKIPPING AI SUMMARY) ---")
            shutil.copy(native_pdf_path, output_filename)
            print("✅ Native Document Finalized")
            commentary_preview = "Standard export. No AI summary requested."

        # Cleanup temp file
        if os.path.exists(native_pdf_path): 
            os.remove(native_pdf_path)
        
        # 4. Return Power Automate Payload
        return {
            "status": "success",
            "kpi_summary": f"Report finalized for {req.period}", 
            "commentary_preview": commentary_preview,
            "sas_download_url": f"https://mock-azure-storage.com/{output_filename}", 
            "user_oid_processed": req.user_oid,
            "summary_included": needs_summary
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/generate-custom-visual", tags=["Enterprise Workflow"])
async def generate_custom_visual(req: CustomVisualRequest):
    try:
        token = get_power_bi_token()
        
        # 1. Ask Groq for the DAX and Chart Blueprint
        print("Generating Blueprint...")
        blueprint = get_ad_hoc_blueprint(req.intent, req.period)
        
        # 2. Execute the DAX against Power BI
        print(f"Executing Live DAX: {blueprint['dax_query']}")
        raw_data_string = execute_live_dax(token, blueprint['dax_query'])
        
        # safely evaluate the string representation of the list of dicts returned by Power BI
        import ast
        try:
            live_rows = ast.literal_eval(raw_data_string)
        except Exception:
            live_rows = []
            
        if not live_rows:
            raise HTTPException(status_code=400, detail="DAX query returned empty data.")

        # 3. Parse the dynamic Power BI rows into Matplotlib arrays
        x_col = f"[{blueprint['x_column_name']}]"
        y_col = f"[{blueprint['y_column_name']}]"
        
        labels = [str(row.get(x_col, "Unknown")) for row in live_rows]
        values = [float(row.get(y_col, 0)) for row in live_rows]
        
        # 4. Inject the actual data into the blueprint and render
        blueprint["labels"] = labels
        blueprint["values"] = values
        
        print("Rendering Matplotlib Vector...")
        image_path = generate_matplotlib_chart(blueprint)
        
        return {
            "status": "success",
            "message": "Custom visual generated.",
            "image_url": image_path, # In production, upload this to Azure Blob and return the URL
            "underlying_dax": blueprint["dax_query"]
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)