import os
import io
import base64
import uuid
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
from jinja2 import Template
import pdfkit

# --- UPGRADED DASHBOARD HTML TEMPLATE ---
HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <style>
        body { 
            font-family: {{ theme.font_family | default('Segoe UI, Arial, sans-serif') }}; 
            background-color: #F8F9FA; 
            color: #333; 
            margin: 0; 
            padding: 30px; 
        }
        .page { page-break-after: always; margin-bottom: 40px; background: white; padding: 30px; border-radius: 12px; box-shadow: 0 4px 12px rgba(0,0,0,0.05); }
        
        .header { background-color: #002050; color: white; padding: 25px; border-radius: 8px; margin-bottom: 30px; }
        .header h1 { margin: 0 0 5px 0; font-size: 26px; font-weight: 600; }
        .header p { margin: 0; font-size: 14px; opacity: 0.8; }
        
        h2.section-title { color: #002050; border-bottom: 3px solid #FF9900; padding-bottom: 8px; margin-bottom: 25px; font-size: 22px; }
        
        /* Power BI Style KPI Ribbon */
        .kpi-container { display: flex; gap: 15px; margin-bottom: 30px; flex-wrap: wrap; }
        .kpi-card { 
            background: #ffffff; 
            padding: 15px 20px; 
            border-radius: 6px; 
            border-top: 4px solid #FF9900; 
            flex: 1; 
            min-width: 120px;
            box-shadow: 0 2px 5px rgba(0,0,0,0.08);
            border-left: 1px solid #eee;
            border-right: 1px solid #eee;
            border-bottom: 1px solid #eee;
        }
        .kpi-label { font-size: 11px; color: #777; margin-bottom: 5px; text-transform: uppercase; font-weight: 600; letter-spacing: 0.5px; }
        .kpi-value { font-size: 22px; font-weight: bold; color: #002050; }
        
        /* 2-Column Grid for Dashboard Look */
        .visuals-grid { 
            display: grid; 
            grid-template-columns: 1fr 1fr; 
            gap: 25px; 
        }
        .chart-container { 
            background: white; 
            padding: 15px; 
            border-radius: 8px; 
            box-shadow: 0 2px 8px rgba(0,0,0,0.08); 
            text-align: center;
            border: 1px solid #eaeaea;
        }
        .chart-container h3 { margin-top: 0; color: #002050; font-size: 16px; margin-bottom: 15px; font-weight: 600; text-align: left; }
        .chart-container img { max-width: 100%; height: auto; border-radius: 4px; }
        
        /* Force maps or wide charts to span full width */
        .full-width { grid-column: span 2; }
    </style>
</head>
<body>
    <div class="header">
        <h1>{{ template_name }}</h1>
        <p>Filters Applied: {{ metadata.filters_applied.financial_year }} | Product: {{ metadata.filters_applied.product_type | default('All Products') }}</p>
    </div>

    {% set sections = pages if pages else slides %}
    
    {% for section in sections %}
    <div class="page">
        <h2 class="section-title">{{ section.page_title | default(section.slide_title) }}</h2>
        
        {% if section.kpi_ribbon %}
        <div class="kpi-container">
            {% for kpi in section.kpi_ribbon %}
            <div class="kpi-card">
                <div class="kpi-label">{{ kpi.label }}</div>
                <div class="kpi-value">
                    {% if kpi.format == 'currency' %}₹{% endif %}1,650
                    {% if kpi.format == 'percentage' %}%{% endif %}
                </div>
            </div>
            {% endfor %}
        </div>
        {% endif %}

        {% if section.visualizations %}
        <div class="visuals-grid">
            {% for viz in section.visualizations %}
            <div class="chart-container {% if 'map' in viz.chart_type %}full-width{% endif %}">
                <h3>{{ viz.title }}</h3>
                <img src="data:image/png;base64,{{ viz.base64_image }}" alt="{{ viz.title }}" />
            </div>
            {% endfor %}
        </div>
        {% endif %}
    </div>
    {% endfor %}
</body>
</html>
"""

def _generate_secure_chart(viz_config: dict, mock_data: dict) -> str:
    """
    Secure factory with expanded mocks to handle lines, horizontal bars, and placeholders for maps.
    """
    # Use a cleaner matplotlib style
    plt.style.use('seaborn-v0_8-whitegrid')
    
    # Make figures slightly wider to fit the new HTML grid nicely
    fig, ax = plt.subplots(figsize=(6, 4))
    
    chart_type = viz_config.get("chart_type", "").lower()
    custom_config = viz_config.get("config", {})
    ai_colors = custom_config.get("colors", ['#002050', '#FF9900', '#4CAF50', '#2196F3', '#9C27B0'])
    
    # 1. Bar / Combo (AUM Trend)
    if "bar" in chart_type and "horizontal" not in chart_type or "combo" in chart_type:
        labels = ['FY24', 'FY25', 'FY26']
        values = [1200, 1650, 1801]
        ax.bar(labels, values, color=ai_colors[0], width=0.6)
        
    # 2. Horizontal Bar (State Wise PAR / Bucket Wise)
    elif "horizontal" in chart_type:
        labels = ['0-30', '31-60', '61-90', '90+']
        values = [75, 33, 10, 13]
        ax.barh(labels, values, color=ai_colors[0], height=0.5)
        ax.invert_yaxis() # Highest value at the top
        
    # 3. Multi-Line (Disbursement Trend)
    elif "multi_line" in chart_type or "line" in chart_type:
        months = ['Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep']
        fy24 = [80, 95, 75, 85, 90, 70]
        fy25 = [60, 65, 50, 70, 65, 70]
        fy26 = [110, 90, 120, 100, 110, 85]
        
        ax.plot(months, fy24, marker='o', color=ai_colors[0], label='FY24', linewidth=2)
        ax.plot(months, fy25, marker='o', color=ai_colors[1], label='FY25', linewidth=2)
        ax.plot(months, fy26, marker='o', color=ai_colors[2], label='FY26', linewidth=2)
        ax.legend(loc='upper right', frameon=True)
        
    # 4. Donut / Pie (Loan Portfolio)
    elif "donut" in chart_type or "pie" in chart_type:
        labels = ['MSME', 'Gold', 'Retail', 'Vehicle']
        sizes = [26.6, 23.7, 25.3, 24.3]
        ax.pie(sizes, labels=labels, autopct='%1.1f%%', startangle=90, colors=ai_colors)
        if "donut" in chart_type:
            centre_circle = plt.Circle((0,0), 0.65, fc='white')
            fig.gca().add_artist(centre_circle)
            
    # 5. Scatter Plot (In case AI modifies to this)
    elif "scatter" in chart_type:
        x = np.random.rand(20) * 100
        y = np.random.rand(20) * 100
        sizes = np.random.rand(20) * 500
        ax.scatter(x, y, c=ai_colors[0], s=sizes, alpha=0.7, edgecolors='none')
        
    # 6. Map Placeholder (Total Disbursement by State)
    elif "map" in chart_type:
        # Drawing a literal placeholder since real mapping requires GeoPandas
        ax.text(0.5, 0.6, "🗺️", fontsize=50, ha='center', va='center')
        ax.text(0.5, 0.4, "[Choropleth Map Data Engine]", fontsize=12, ha='center', va='center', color='#666')
        ax.set_xticks([])
        ax.set_yticks([])
        ax.grid(False)
        for spine in ax.spines.values(): spine.set_visible(False)
        
    # 7. Ultimate Fallback
    else:
        ax.text(0.5, 0.5, f"[Unsupported chart: {chart_type}]", ha='center', va='center', fontsize=12)

    # Clean up axes so it looks like a dashboard widget
    if "pie" not in chart_type and "donut" not in chart_type and "map" not in chart_type:
        ax.spines['top'].set_visible(False)
        ax.spines['right'].set_visible(False)

    plt.tight_layout()
    
    # Convert directly to Base64
    buf = io.BytesIO()
    plt.savefig(buf, format='png', bbox_inches='tight', dpi=150, transparent=True)
    plt.close()
    buf.seek(0)
    return base64.b64encode(buf.read()).decode('utf-8')

def create_pdf_report_from_dict(template_data: dict, target_date: str) -> str:
    """
    Accepts the in-memory JSON dictionary, generates charts, renders HTML, and exports PDF.
    """
    mock_dax_data = {"date": target_date}
    
    # Safely ensure metadata exists
    if "metadata" not in template_data:
        template_data["metadata"] = {}
    if "filters_applied" not in template_data["metadata"]:
        template_data["metadata"]["filters_applied"] = {}
        
    template_data['metadata']['filters_applied']['financial_year'] = target_date
    
    # Loop through JSON and inject Base64 images
    sections = template_data.get("pages", template_data.get("slides", []))
    for section in sections:
        for viz in section.get("visualizations", []):
            viz["base64_image"] = _generate_secure_chart(viz, mock_dax_data)
            
    jinja_template = Template(HTML_TEMPLATE)
    rendered_html = jinja_template.render(**template_data)
    
    output_dir = "./generated_reports"
    os.makedirs(output_dir, exist_ok=True)
    
    file_id = uuid.uuid4().hex[:6]
    template_id = template_data.get("template_id", "report")
    safe_date = target_date.replace(' ', '_').replace('/', '-')
    
    pdf_path = os.path.join(output_dir, f"{template_id}_{safe_date}_{file_id}.pdf")
    
    options = {
        'page-size': 'A4',
        'margin-top': '10mm',
        'margin-right': '10mm',
        'margin-bottom': '10mm',
        'margin-left': '10mm',
        'encoding': "UTF-8",
        'enable-local-file-access': None,
        'quiet': '' 
    }
    
    pdfkit.from_string(rendered_html, pdf_path, options=options)
    
    return os.path.abspath(pdf_path)