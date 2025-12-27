# Dot Traffic
# Intelligent routing layer for Hunch's agency workflow
# Standalone version - no external dependencies

import os
import json
import re
from flask import Flask, request, jsonify
from anthropic import Anthropic
import httpx

app = Flask(__name__)

# ===================
# CONFIG
# ===================

AIRTABLE_API_KEY = os.environ.get('AIRTABLE_API_KEY')
AIRTABLE_BASE_ID = 'app8CI7NAZqhQ4G1Y'
AIRTABLE_PROJECTS_TABLE = 'Projects'
AIRTABLE_CLIENTS_TABLE = 'Clients'

ANTHROPIC_API_KEY = os.environ.get('ANTHROPIC_API_KEY')
ANTHROPIC_MODEL = 'claude-sonnet-4-20250514'

VALID_CLIENT_CODES = ['ONE', 'ONS', 'SKY', 'TOW', 'FIS', 'FST', 'WKA', 'LAB', 'EON', 'OTH']

# Client name to code mapping
CLIENT_NAME_MAPPING = {
    'one nz': 'ONE',
    'one': 'ONE',
    'sky': 'SKY',
    'sky tv': 'SKY',
    'tower': 'TOW',
    'tower insurance': 'TOW',
    'fisher funds': 'FIS',
    'fisherfunds': 'FIS',
    'firestop': 'FST',
    'whakarongorau': 'WKA',
    'healthline': 'WKA',
    'labour': 'LAB',
    'eon fibre': 'EON',
    'eonfibre': 'EON'
}

# Anthropic client
anthropic_client = Anthropic(
    api_key=ANTHROPIC_API_KEY,
    http_client=httpx.Client(timeout=60.0, follow_redirects=True)
)

# Load prompt
PROMPT_PATH = os.path.join(os.path.dirname(__file__), 'prompt.txt')
with open(PROMPT_PATH, 'r') as f:
    TRAFFIC_PROMPT = f.read()


# ===================
# HELPERS
# ===================

def strip_markdown_json(content):
    """Strip markdown code blocks from Claude's JSON response"""
    content = content.strip()
    if content.startswith('```'):
        content = content.split('\n', 1)[1] if '\n' in content else content[3:]
    if content.endswith('```'):
        content = content.rsplit('```', 1)[0]
    return content.strip()


def _get_airtable_headers():
    """Get standard Airtable headers"""
    return {
        'Authorization': f'Bearer {AIRTABLE_API_KEY}',
        'Content-Type': 'application/json'
    }


# ===================
# AIRTABLE FUNCTIONS
# ===================

def get_project_by_job_number(job_number):
    """Look up existing project by job number."""
    if not AIRTABLE_API_KEY:
        return None
    
    try:
        search_url = f"https://api.airtable.com/v0/{AIRTABLE_BASE_ID}/{AIRTABLE_PROJECTS_TABLE}"
        params = {'filterByFormula': f"{{Job Number}}='{job_number}'"}
        
        response = httpx.get(search_url, headers=_get_airtable_headers(), params=params, timeout=10.0)
        response.raise_for_status()
        
        records = response.json().get('records', [])
        
        if not records:
            return None
        
        record = records[0]
        fields = record['fields']
        
        client_name = fields.get('Client', '')
        if isinstance(client_name, list):
            client_name = client_name[0] if client_name else ''
        
        return {
            'recordId': record['id'],
            'jobNumber': fields.get('Job Number', job_number),
            'jobName': fields.get('Project Name', ''),
            'clientName': client_name,
            'stage': fields.get('Stage', ''),
            'status': fields.get('Status', ''),
            'round': fields.get('Round', 0) or 0,
            'withClient': fields.get('With Client?', False),
            'teamsChannelId': fields.get('Teams Channel ID', None)
        }
        
    except Exception as e:
        print(f"Error looking up project: {e}")
        return None


def get_active_jobs_for_client(client_code):
    """Get all active (In Progress, On Hold) jobs for a client."""
    if not AIRTABLE_API_KEY or not client_code:
        return []
    
    try:
        filter_formula = f"AND(FIND('{client_code}', {{Job Number}})=1, OR({{Status}}='In Progress', {{Status}}='On Hold'))"
        
        search_url = f"https://api.airtable.com/v0/{AIRTABLE_BASE_ID}/{AIRTABLE_PROJECTS_TABLE}"
        params = {'filterByFormula': filter_formula}
        
        response = httpx.get(search_url, headers=_get_airtable_headers(), params=params, timeout=10.0)
        response.raise_for_status()
        
        records = response.json().get('records', [])
        
        jobs = []
        for record in records:
            fields = record.get('fields', {})
            jobs.append({
                'jobNumber': fields.get('Job Number', ''),
                'jobName': fields.get('Project Name', ''),
                'description': fields.get('Description', '')
            })
        
        return jobs
        
    except Exception as e:
        print(f"Error getting active jobs: {e}")
        return []


# ===================
# JOB NUMBER EXTRACTION
# ===================

def extract_job_number(text):
    """Extract explicit job number from text (e.g., 'TOW 023').
    
    Returns job number string or None.
    """
    if not text:
        return None
    
    # Look for pattern: 3 letters + space + 3 digits
    match = re.search(r'\b([A-Z]{3})\s+(\d{3})\b', text.upper())
    if match:
        code = match.group(1)
        number = match.group(2)
        if code in VALID_CLIENT_CODES:
            return f"{code} {number}"
    
    return None


def extract_client_code_from_content(text):
    """Extract client code from client name mentioned in text."""
    if not text:
        return None
    
    text_lower = text.lower()
    
    # Check for client names in the text
    for name, code in CLIENT_NAME_MAPPING.items():
        if name in text_lower:
            return code
    
    return None


# ===================
# TRAFFIC ENDPOINT
# ===================

@app.route('/traffic', methods=['POST'])
def traffic():
    """Route incoming emails/messages to the correct handler.
    
    Logic:
    1. Job number in subject/body? Use it directly.
    2. No job number? Look for clues:
       - Client name in email content
       - Get active jobs for that client
       - Let Claude match content to job names/descriptions
    """
    try:
        data = request.get_json()
        
        # Required field
        content = data.get('emailContent', '')
        if not content:
            return jsonify({'error': 'No content provided'}), 400
        
        # Optional fields
        subject = data.get('subjectLine', '')
        sender_email = data.get('senderEmail', '')
        sender_name = data.get('senderName', '')
        all_recipients = data.get('allRecipients', [])
        has_attachments = data.get('hasAttachments', False)
        attachment_names = data.get('attachmentNames', [])
        source = data.get('source', 'email')
        
        # STEP 1: Look for explicit job number
        job_number = extract_job_number(subject)
        if not job_number:
            job_number = extract_job_number(content)
        
        # If we have a job number, validate it exists
        project = None
        if job_number:
            project = get_project_by_job_number(job_number)
        
        # STEP 2: If no job number (or invalid), find client and get active jobs
        client_code = None
        active_jobs = []
        
        if job_number:
            # Extract client code from job number
            client_code = job_number.split()[0] if job_number else None
        
        if not client_code:
            # Look for client name in content
            client_code = extract_client_code_from_content(subject)
            if not client_code:
                client_code = extract_client_code_from_content(content)
        
        # Get active jobs for matching
        if client_code:
            active_jobs = get_active_jobs_for_client(client_code)
        
        # Format active jobs for the prompt
        active_jobs_text = ""
        if active_jobs:
            active_jobs_text = "\n".join([
                f"- {job['jobNumber']} - {job['jobName']}: {job['description']}"
                for job in active_jobs
            ])
        else:
            active_jobs_text = "No active jobs found"
        
        # Build content for Claude
        full_content = f"""Source: {source}
Subject: {subject}

From: {sender_name} <{sender_email}>
Recipients: {', '.join(all_recipients) if isinstance(all_recipients, list) else all_recipients}
Has Attachments: {has_attachments}
Attachment Names: {', '.join(attachment_names) if isinstance(attachment_names, list) else attachment_names}

Extracted job number: {job_number if job_number else 'None found'}
Job exists in system: {True if project else False}
Client code: {client_code if client_code else 'Unknown'}

Active jobs for this client:
{active_jobs_text}

Message content:
{content}"""
        
        # Call Claude for routing decision
        response = anthropic_client.messages.create(
            model=ANTHROPIC_MODEL,
            max_tokens=1500,
            temperature=0.1,
            system=TRAFFIC_PROMPT,
            messages=[
                {'role': 'user', 'content': full_content}
            ]
        )
        
        # Parse response
        result_text = response.content[0].text
        result_text = strip_markdown_json(result_text)
        routing = json.loads(result_text)
        
        # If we already validated the project, enrich the response
        if project and routing.get('jobNumber') == job_number:
            routing['jobName'] = project['jobName']
            routing['clientName'] = project['clientName']
            routing['currentRound'] = project['round']
            routing['currentStage'] = project['stage']
            routing['withClient'] = project['withClient']
            routing['teamsChannelId'] = project['teamsChannelId']
            routing['projectRecordId'] = project['recordId']
        
        # If Claude picked a different job number, validate that one
        elif routing.get('jobNumber') and routing.get('jobNumber') != job_number:
            matched_project = get_project_by_job_number(routing['jobNumber'])
            if matched_project:
                routing['jobName'] = matched_project['jobName']
                routing['clientName'] = matched_project['clientName']
                routing['currentRound'] = matched_project['round']
                routing['currentStage'] = matched_project['stage']
                routing['withClient'] = matched_project['withClient']
                routing['teamsChannelId'] = matched_project['teamsChannelId']
                routing['projectRecordId'] = matched_project['recordId']
            else:
                # Claude's job number doesn't exist
                routing['route'] = 'clarify'
                routing['confidence'] = 'low'
                routing['reason'] = f"Matched job {routing['jobNumber']} not found in system"
        
        # Add source and client code to response
        routing['source'] = source
        routing['clientCode'] = client_code
        
        return jsonify(routing)
        
    except json.JSONDecodeError as e:
        return jsonify({
            'error': 'Claude returned invalid JSON',
            'details': str(e),
            'raw_response': result_text if 'result_text' in locals() else 'No response'
        }), 500
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
        'service': 'Dot Traffic',
        'version': '2.0'
    })


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)
