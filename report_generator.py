import os
import io
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from pptx import Presentation
from pptx.util import Inches, Pt

def create_chart_bytes(data: dict, target_kpi: str) -> io.BytesIO:
    plt.figure(figsize=(5, 4))
    
    labels = ['AUM', 'Disbursements']
    values = [data['aum'], data['disbursements']]
    
    # We use "in" to safely catch typos like "disimbursement"
    if 'disburse' in target_kpi.lower():
        explode = (0, 0.1) 
        colors = ['#E0E0E0', '#FF9900'] # Grey out AUM, highlight Disbursements in Orange
    else:
        explode = (0.1, 0)
        colors = ['#003366', '#E0E0E0'] # Highlight AUM in Navy, grey out Disbursements

    plt.pie(
        values, 
        explode=explode, 
        labels=labels, 
        autopct='%1.1f%%', 
        startangle=140,
        colors=colors
    )
    
    # Dynamic chart title
    kpi_name = "Disbursements" if 'disburse' in target_kpi.lower() else "AUM"
    plt.title(f"Focus: {kpi_name} ({data['month']} {data['year']})")
    
    image_stream = io.BytesIO()
    plt.savefig(image_stream, format='png', bbox_inches='tight', dpi=150)
    plt.close()
    image_stream.seek(0)
    
    return image_stream

def generate_report_file(data: dict, target_kpi: str = "aum") -> str:
    prs = Presentation()
    blank_slide_layout = prs.slide_layouts[6]
    slide = prs.slides.add_slide(blank_slide_layout)
    
    # Check KPI to make text dynamic
    kpi_name = "Disbursements" if 'disburse' in target_kpi.lower() else "AUM"

    # Dynamic Title
    txBox = slide.shapes.add_textbox(Inches(0.5), Inches(0.5), Inches(9), Inches(1))
    tf = txBox.text_frame
    p = tf.add_paragraph()
    p.text = f"{kpi_name} Analysis: {data['month']} {data['year']}"
    p.font.size = Pt(28)
    p.font.bold = True
    
    # Generate Chart
    chart_stream = create_chart_bytes(data, target_kpi)
    slide.shapes.add_picture(chart_stream, Inches(0.5), Inches(1.5), width=Inches(5))
    
    # Summary Bullet Points
    txBox_summary = slide.shapes.add_textbox(Inches(5.8), Inches(1.8), Inches(4), Inches(4))
    tf_summary = txBox_summary.text_frame
    tf_summary.word_wrap = True
    
    p1 = tf_summary.paragraphs[0]
    p1.text = f"• Active Assets Under Management: ${data['aum']:,}"
    p1.font.size = Pt(14)
    # Bold AUM if it's the target
    if kpi_name == "AUM": p1.font.bold = True 
    
    p2 = tf_summary.add_paragraph()
    p2.text = f"• Total Monthly Disbursements: ${data['disbursements']:,}"
    p2.font.size = Pt(14)
    # Bold Disbursements if it's the target
    if kpi_name == "Disbursements": p2.font.bold = True
    
    output_dir = "./generated_reports"
    os.makedirs(output_dir, exist_ok=True)
    
    file_name = f"Report_{data['month']}_{data['year']}_{kpi_name}.pptx"
    file_path = os.path.join(output_dir, file_name)
    prs.save(file_path)
    
    return os.path.abspath(file_path)