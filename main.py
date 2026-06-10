import os
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import uvicorn
from dotenv import load_dotenv

# Using Groq exactly as requested
from groq import Groq
import fitz  # PyMuPDF

load_dotenv() 

app = FastAPI(title="Report Service")

client = Groq(api_key=os.environ.get("GROQ_API_KEY"))

# --- THE COMPLETE 4-SLIDE DAX TEMPLATE ---
REPORT_TEMPLATE = {
    "slide_1": {
        "page_index": 0, # Page 1: Portfolio Profile
        "context_name": "Portfolio Profile",
        "visuals": {
            "aum_kpi": "EVALUATE SUMMARIZECOLUMNS(\"AUM\", [Total_AUM])",
            "disbursement_kpi": "EVALUATE SUMMARIZECOLUMNS(\"Disbursement\", [Total_Disbursement])"
        }
    },
    "slide_2": {
        "page_index": 1, # Page 2: Portfolio Quality
        "context_name": "Portfolio Quality",
        "visuals": {
            "bucket_aum": "EVALUATE SUMMARIZECOLUMNS('Bucket'[Type], \"AUM\", [Total_AUM])",
            "state_par": "EVALUATE SUMMARIZECOLUMNS('Geography'[State], \"PAR90\", [PAR_90_Percent])"
        }
    },
    "slide_3": {
        "page_index": 2, # Page 3: Future Projections
        "context_name": "Future Projections",
        "visuals": {
            "future_principal": "EVALUATE SUMMARIZECOLUMNS(\"Future_Principal\", [Future_Principal])",
            "future_aum": "EVALUATE SUMMARIZECOLUMNS(\"Future_AUM\", [Projected_AUM])"
        }
    },
    "slide_4": {
        "page_index": 3, # Page 4: Customer Profile
        "context_name": "Customer Profile",
        "visuals": {
            "collection_efficiency": "EVALUATE SUMMARIZECOLUMNS('Date'[Month], \"CE_Percent\", [Collection_Efficiency])",
            "qoq_disbursement": "EVALUATE SUMMARIZECOLUMNS('Date'[Quarter], \"Disbursement\", [Quarterly_Disbursement])"
        }
    }
}

class MVPRequest(BaseModel):
    selected_date: str = "FY 2025"
    mock_power_bi_pdf: str = "sample_power_bi_export.pdf"

# --- AI Brain ---

def generate_slide_summary(slide_name: str, visual_data_map: dict) -> str:
    """Generates a summary specifically for one slide."""
    context_string = "\n".join([f"- {viz_name}: {data}" for viz_name, data in visual_data_map.items()])
    
    system_prompt = f"""
    You are a Chief Financial Officer. You are looking at a specific slide titled: "{slide_name}".
    Based ONLY on the following visual-level data extracts for this slide, 
    write a high-level, 3-bullet summary explaining these metrics.
    
    Data Extracts:
    {context_string}
    
    CRITICAL INSTRUCTIONS:
    - Keep it strictly professional. 
    - DO NOT use the Rupee symbol (₹), use "INR" or "Rs." instead.
    - DO NOT use markdown formatting like asterisks or bolding.
    - STRICTLY USE ONLY BASIC ASCII CHARACTERS. 
    - DO NOT use smart quotes (use standard ' and "), en-dashes, or em-dashes (use standard hyphen -).
    """
    
    response = client.chat.completions.create(
        model="openai/gpt-oss-120b", 
        messages=[{"role": "system", "content": system_prompt}],
        temperature=0.2
    )
    return response.choices[0].message.content.strip()

# --- Advanced PDF Factory ---

def attach_summaries_to_sides(input_pdf_path: str, output_pdf_path: str, slide_summaries: dict):
    """
    Takes a dictionary mapping page_index to summary_text.
    Expands the canvas and draws the sidebar ONLY on pages that have a summary.
    """
    doc_pbi = fitz.open(input_pdf_path)
    doc_final = fitz.open()
    PANEL_WIDTH = 350 
    
    for page_num in range(len(doc_pbi)):
        page = doc_pbi[page_num]
        rect = page.rect 
        
        # Check if we generated a summary for this specific page
        if page_num in slide_summaries:
            raw_text = slide_summaries[page_num]
            
            # Ironclad ASCII sanitizer to kill typographic characters causing ? marks
            clean_text = raw_text.replace('—', '-').replace('–', '-').replace('‘', "'").replace('’', "'").replace('“', '"').replace('”', '"').replace('\u202F', ' ').replace('\u00A0', ' ')
            
            new_width = rect.width + PANEL_WIDTH
            new_height = rect.height
            new_page = doc_final.new_page(width=new_width, height=new_height)
            
            # Stamp Power BI on the left
            new_page.show_pdf_page(rect, doc_pbi, page_num)
            
            # Draw Sidebar on the right
            panel_rect = fitz.Rect(rect.width, 0, new_width, new_height)
            new_page.draw_rect(panel_rect, color=(0.96, 0.96, 0.96), fill=(0.96, 0.96, 0.96))
            
            # Add Header
            new_page.insert_text((rect.width + 25, 40), "Slide Insights", fontsize=18, fontname="hebo", color=(0, 0.12, 0.31))
            
            # Add AI Text
            text_rect = fitz.Rect(rect.width + 25, 70, new_width - 25, new_height - 20)
            new_page.insert_textbox(text_rect, clean_text, fontsize=12, fontname="helv", color=(0.2, 0.2, 0.2))
            
        else:
            # Fallback just in case a page gets missed
            new_page = doc_final.new_page(width=rect.width, height=rect.height)
            new_page.show_pdf_page(rect, doc_pbi, page_num)
            
    doc_final.save(output_pdf_path)
    doc_pbi.close()
    doc_final.close()
    
# --- Core Endpoint ---

@app.post("/generate-mvp-report", tags=["MVP Workflow"])
async def generate_mvp_report(req: MVPRequest):
    try:
        if not os.path.exists(req.mock_power_bi_pdf):
            raise HTTPException(status_code=404, detail=f"Missing mock file: {req.mock_power_bi_pdf}")

        slide_summaries = {}

        print("\n--- INITIATING SLIDE-BY-SLIDE EXTRACTION ---")
        
        # Loop through all 4 slides defined in the template
        for slide_key, slide_info in REPORT_TEMPLATE.items():
            page_index = slide_info["page_index"]
            slide_name = slide_info["context_name"]
            
            print(f"\nProcessing {slide_name} (Page {page_index + 1})...")
            visual_data_map = {}
            
            # Extract data for just this slide (Mocked strictly from your PDF data)
            for viz_id, dax_query in slide_info["visuals"].items():
                print(f" -> Mocking DAX for {viz_id}")
                
                # Slide 1 Data
                if viz_id == "aum_kpi":
                    visual_data_map[viz_id] = "Total AUM stands at INR 1,650.99."
                elif viz_id == "disbursement_kpi":
                    visual_data_map[viz_id] = "Total Disbursement for the period is INR 3,342.86."
                
                # Slide 2 Data
                elif viz_id == "bucket_aum":
                    visual_data_map[viz_id] = "PAR 0 accounts for INR 308.75, while the PAR 90+ bucket sits at INR 13.20."
                elif viz_id == "state_par":
                    visual_data_map[viz_id] = "Himachal Pradesh shows the highest PAR 90+ incidence at 12, followed closely by Kerala at 11."
                
                # Slide 3 Data
                elif viz_id == "future_principal":
                    visual_data_map[viz_id] = "Future Principal is projected at INR 1,750.00."
                elif viz_id == "future_aum":
                    visual_data_map[viz_id] = "Projected AUM is expected to reach INR 1,801.89."
                
                # Slide 4 Data
                elif viz_id == "collection_efficiency":
                    visual_data_map[viz_id] = "Month-over-Month Collection Efficiency started strong at 96.9 percent but trended downwards to 86.2 percent."
                elif viz_id == "qoq_disbursement":
                    visual_data_map[viz_id] = "Quarter-over-Quarter disbursement dropped significantly from 883,884 in Q1 to 255,321 in Q4."

            # Generate the summary for THIS specific slide
            print(f" -> Generating AI Summary via Groq for Page {page_index + 1}...")
            ai_summary = generate_slide_summary(slide_name, visual_data_map)
            slide_summaries[page_index] = ai_summary

        print("\n--- STITCHING 4-PAGE PDF ---")
        output_filename = f"PerSlide_Report_Complete.pdf"
        
        # Pass the populated dictionary of 4 summaries to the layout factory
        attach_summaries_to_sides(req.mock_power_bi_pdf, output_filename, slide_summaries)
        
        return {
            "status": "success", 
            "local_file": output_filename,
            "summarized_pages": [p + 1 for p in slide_summaries.keys()] # Returning 1-indexed for readability
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)