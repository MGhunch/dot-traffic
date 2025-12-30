from flask import Flask, request, jsonify
import httpx
import os
from datetime import datetime, timedelta

app = Flask(__name__)

# Airtable config
AIRTABLE_API_KEY = os.environ.get('AIRTABLE_API_KEY')
AIRTABLE_BASE_ID = 'app8CI7NAZqhQ4G1Y'
AIRTABLE_PROJECTS_TABLE = 'Projects'
AIRTABLE_CLIENTS_TABLE = 'Clients'


def format_date(date_str):
    """Format date string to 'D MMM' format (e.g., '5 Jan')"""
    if not date_str:
        return ''
    try:
        for fmt in ['%Y-%m-%d', '%d/%m/%Y', '%d-%m-%Y']:
            try:
                date_obj = datetime.strptime(date_str, fmt)
                return date_obj.strftime('%-d %b')
            except ValueError:
                continue
        return date_str
    except:
        return date_str


def get_client_info(client_code):
    """Fetch client info including WIP header image from Clients table"""
    if not AIRTABLE_API_KEY:
        return None
    
    try:
        headers = {
            'Authorization': f'Bearer {AIRTABLE_API_KEY}',
            'Content-Type': 'application/json'
        }
        
        filter_formula = f"{{Client code}}='{client_code}'"
        url = f"https://api.airtable.com/v0/{AIRTABLE_BASE_ID}/{AIRTABLE_CLIENTS_TABLE}"
        params = {'filterByFormula': filter_formula}
        
        response = httpx.get(url, headers=headers, params=params, timeout=30.0)
        response.raise_for_status()
        
        records = response.json().get('records', [])
        
        if not records:
            return None
        
        fields = records[0].get('fields', {})
        
        header_url = 'https://mghunch.github.io/hunch-assets/Header_Wip.png'
        
        return {
            'client_name': fields.get('Client', ''),
            'client_code': fields.get('Client code', ''),
            'header_url': header_url
        }
        
    except Exception as e:
        print(f"Error fetching client info: {e}")
        return None


def normalize_client_code(client_code):
    """Convert client name to client code if needed"""
    name_to_code = {
        'one nz': 'ONE',
        'one nz marketing': 'ONE',
        'one nz - marketing': 'ONE',
        'one nz (marketing)': 'ONE',
        'one nz simplification': 'ONS',
        'one nz - simplification': 'ONS',
        'one nz (simplification)': 'ONS',
        'one nz business': 'ONB',
        'one nz - business': 'ONB',
        'one nz (business)': 'ONB',
        'sky': 'SKY',
        'sky tv': 'SKY',
        'tower': 'TOW',
        'tower insurance': 'TOW',
        'fisher funds': 'FIS',
        'firestop': 'FST',
        'hunch': 'HUN',
        'eon fibre': 'EON',
        'labour': 'LAB',
        'westpac': 'WES',
        'other': 'OTH'
    }
    
    if client_code.lower() in name_to_code:
        return name_to_code[client_code.lower()]
    return client_code


def get_client_projects(client_code):
    """Fetch all active projects for a client from Airtable"""
    if not AIRTABLE_API_KEY:
        return [], []
    
    try:
        headers = {
            'Authorization': f'Bearer {AIRTABLE_API_KEY}',
            'Content-Type': 'application/json'
        }
        
        # Filter by client code (Job Number prefix) and active status
        filter_formula = f"AND(FIND('{client_code}', {{Job Number}})=1, OR({{Status}}='In Progress', {{Status}}='On Hold'))"
        
        url = f"https://api.airtable.com/v0/{AIRTABLE_BASE_ID}/{AIRTABLE_PROJECTS_TABLE}"
        params = {'filterByFormula': filter_formula}
        
        response = httpx.get(url, headers=headers, params=params, timeout=30.0)
        response.raise_for_status()
        
        records = response.json().get('records', [])
        
        active_projects = []
        for record in records:
            fields = record.get('fields', {})
            job_number = fields.get('Job Number', '')
            
            # Skip placeholder job numbers (998, 999)
            if job_number.endswith(('998', '999')):
                continue
                
            active_projects.append({
                'job_number': job_number,
                'job_name': fields.get('Project Name', ''),
                'description': fields.get('Description', ''),
                'stage': fields.get('Stage', ''),
                'status': fields.get('Status', ''),
                'with_client': fields.get('With Client?', False),
                'update_summary': fields.get('Update View', ''),
                'update_due': fields.get('Update due', ''),
                'live_date': fields.get('Live Date', ''),
                'client': fields.get('Client', ''),
                'project_owner': fields.get('Project Owner', '')
            })
        
        # Get recently completed projects (Status = Completed, Status Changed in last 6 weeks)
        six_weeks_ago = (datetime.now() - timedelta(days=42)).strftime('%Y-%m-%d')
        completed_filter = f"AND(FIND('{client_code}', {{Job Number}})=1, {{Status}}='Completed', IS_AFTER({{Status Changed}}, '{six_weeks_ago}'))"
        
        completed_params = {'filterByFormula': completed_filter, 'sort[0][field]': 'Status Changed', 'sort[0][direction]': 'desc'}
        completed_response = httpx.get(url, headers=headers, params=completed_params, timeout=30.0)
        completed_response.raise_for_status()
        
        completed_records = completed_response.json().get('records', [])
        
        completed_projects = []
        for record in completed_records:
            fields = record.get('fields', {})
            job_number = fields.get('Job Number', '')
            
            # Skip placeholder job numbers (998, 999)
            if job_number.endswith(('998', '999')):
                continue
                
            completed_projects.append({
                'job_number': job_number,
                'job_name': fields.get('Project Name', ''),
                'description': fields.get('Description', '')
            })
        
        return active_projects, completed_projects
        
    except Exception as e:
        print(f"Airtable error: {e}")
        return [], []


def build_job_html(job):
    """Build HTML block for a single job"""
    # Handle lookup fields that return as arrays
    update_summary = job['update_summary']
    if isinstance(update_summary, list):
        update_summary = update_summary[0] if update_summary else ''
    if not update_summary:
        update_summary = 'No updates yet'
    
    update_due = job['update_due']
    if isinstance(update_due, list):
        update_due = update_due[0] if update_due else ''
    if update_due:
        update_due = format_date(update_due)
    else:
        update_due = 'TBC'
    
    live_date = job['live_date']
    if not live_date:
        live_date = 'TBC'
    elif live_date.lower() not in ['tbc', 'early', 'late', 'mid'] and not any(x in live_date.lower() for x in ['early', 'late', 'mid']):
        live_date = format_date(live_date) or live_date
    
    return f'''
    <tr>
      <td style="padding: 15px 20px; border-bottom: 1px solid #eee;">
        <p style="margin: 0 0 5px 0; font-size: 16px; font-weight: bold; color: #333;">
          {job['job_number']} &mdash; {job['job_name']}
        </p>
        <p style="margin: 0 0 10px 0; font-size: 14px; color: #666; line-height: 1.4;">
          {job['description']}
        </p>
        <table cellpadding="0" cellspacing="0" style="font-size: 13px;">
          <tr><td style="padding: 2px 10px 2px 0; color: #888;"><strong>Owner:</strong></td><td style="color: #333;">{job['project_owner']}</td></tr>
          <tr><td style="padding: 2px 10px 2px 0; color: #888;"><strong>Update:</strong></td><td style="color: #333;">{update_summary}</td></tr>
          <tr><td style="padding: 2px 10px 2px 0; color: #888;"><strong>Due on:</strong></td><td style="color: #333;">{update_due}</td></tr>
          <tr><td style="padding: 2px 10px 2px 0; color: #888;"><strong>Live by:</strong></td><td style="color: #333;">{live_date}</td></tr>
          <tr><td style="padding: 2px 10px 2px 0; color: #888;"><strong>Job stage:</strong></td><td style="color: #333;">{job['stage']}</td></tr>
        </table>
      </td>
    </tr>'''


def build_section_html(title, jobs, color="#ED1C24"):
    """Build HTML section with header and jobs"""
    if not jobs:
        return ''
    
    section = f'''
    <tr>
      <td style="padding: 20px 20px 0 20px;">
        <div style="background-color: {color}; color: #ffffff; padding: 8px 15px; font-size: 14px; font-weight: bold; border-radius: 3px;">
          {title}
        </div>
      </td>
    </tr>'''
    
    for job in jobs:
        section += build_job_html(job)
    
    return section


def build_completed_section(completed_projects):
    """Build HTML section for recently completed projects"""
    if not completed_projects:
        return ''
    
    items = "".join([
        f"<p style='margin: 0 0 8px 0;'><strong style='color: #888;'>{p['job_number']}</strong> &mdash; <span style='color: #333;'>{p['job_name']}</span></p>"
        for p in completed_projects
    ])
    
    return f'''
    <tr>
      <td style="padding: 20px 20px 0 20px;">
        <div style="background-color: #999999; color: #ffffff; padding: 8px 15px; font-size: 14px; font-weight: bold; border-radius: 3px;">
          RECENTLY COMPLETED
        </div>
      </td>
    </tr>
    <tr>
      <td style="padding: 15px 20px; color: #888; font-size: 13px;">
        {items}
      </td>
    </tr>'''


def build_wip_email(client_name, projects, completed_projects, header_url=''):
    """Build complete WIP email HTML"""
    today = datetime.now().strftime('%d %B %Y')
    
    # Sort projects into categories
    with_us = [p for p in projects if p['status'] == 'In Progress' and not p['with_client']]
    with_you = [p for p in projects if p['status'] == 'In Progress' and p['with_client']]
    on_hold = [p for p in projects if p['status'] == 'On Hold']
    
    # Build header - use image if available, otherwise text
    if header_url:
        header_content = f'''<img src="{header_url}" width="600" style="width: 100%; max-width: 600px; height: auto; display: block;" alt="{client_name} WIP Header">'''
    else:
        header_content = f'''<span style="font-size: 28px; font-weight: bold; color: #ED1C24;">HUNCH &mdash; WIP</span>'''
    
    html = f'''<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <meta http-equiv="X-UA-Compatible" content="IE=edge">
  <!--[if mso]>
  <style type="text/css">
    table {{border-collapse: collapse; border-spacing: 0; margin: 0;}}
    div, td {{padding: 0;}}
    div {{margin: 0 !important;}}
  </style>
  <noscript>
    <xml>
      <o:OfficeDocumentSettings>
        <o:PixelsPerInch>96</o:PixelsPerInch>
      </o:OfficeDocumentSettings>
    </xml>
  </noscript>
  <![endif]-->
  <style>
    @media screen and (max-width: 600px) {{
      .wrapper {{
        width: 100% !important;
        padding: 12px !important;
      }}
    }}
  </style>
</head>
<body style="margin: 0; padding: 0; font-family: Calibri, Arial, sans-serif; background-color: #f5f5f5; width: 100% !important; -webkit-text-size-adjust: 100%; -ms-text-size-adjust: 100%;">
  
  <table class="wrapper" width="600" cellpadding="0" cellspacing="0" style="width: 600px; max-width: 100%; margin: 0 0 0 20px; background-color: #ffffff;">
    
    <!-- Header -->
    <tr>
      <td style="border-bottom: 4px solid #ED1C24; padding: 0 20px 20px 20px;">
        {header_content}
        <p style="margin: 15px 0 0 0; font-size: 22px; font-weight: bold; color: #333;">{client_name}</p>
        <p style="margin: 5px 0 0 0; font-size: 12px; color: #999;">{today}</p>
      </td>
    </tr>
    
    {build_section_html("IN PROGRESS", with_us)}
    {build_section_html("JOBS WITH YOU", with_you)}
    {build_section_html("ON HOLD", on_hold, "#999999")}
    {build_completed_section(completed_projects)}
    
    <!-- Footer -->
    <tr>
      <td style="padding: 25px 20px; border-top: 1px solid #eee; text-align: center;">
        <p style="margin: 0; font-size: 13px; color: #888; font-weight: bold;">Any questions or queries, <a href="mailto:michael@hunch.co.nz" style="color: #888;">get in touch</a></p>
        <p style="margin: 8px 0 0 0; font-size: 12px; color: #999;">Agency Intuition X Artificial Intelligence = AI&sup2;</p>
      </td>
    </tr>
    
  </table>
  
</body>
</html>'''
    
    return html


# ===================
# WIP ENDPOINT
# ===================
@app.route('/wip', methods=['POST'])
def wip():
    """Generate WIP email HTML for a client"""
    try:
        data = request.get_json()
        client_code = data.get('clientCode', data.get('client', ''))
        
        if not client_code:
            return jsonify({'error': 'No client code provided'}), 400
        
        # Normalize client code (convert name to code if needed)
        client_code = normalize_client_code(client_code)
        
        # Get projects from Airtable
        active_projects, completed_projects = get_client_projects(client_code)
        
        if not active_projects and not completed_projects:
            return jsonify({
                'error': 'No projects found',
                'clientCode': client_code
            }), 404
        
        # Get client info (including header image) from Clients table
        client_info = get_client_info(client_code)
        header_url = client_info.get('header_url', '') if client_info else ''
        
        # Get client name from first project or client info
        if active_projects:
            client_name = active_projects[0].get('client', client_code)
        elif client_info:
            client_name = client_info.get('client_name', client_code)
        else:
            client_name = client_code
        
        # Build HTML
        html = build_wip_email(client_name, active_projects, completed_projects, header_url)
        
        return jsonify({
            'clientCode': client_code,
            'clientName': client_name,
            'activeCount': len(active_projects),
            'completedCount': len(completed_projects),
            'html': html
        })
        
    except Exception as e:
        return jsonify({
            'error': 'Internal server error',
            'details': str(e)
        }), 500


# ===================
# HEALTH CHECK
# ===================
@app.route('/health', methods=['GET'])
def health():
    """Health check endpoint"""
    return jsonify({
        'status': 'healthy',
        'service': 'Dot WIP',
        'endpoints': ['/wip', '/health']
    })


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)
