# Dot Traffic
# Intelligent routing layer for Hunch's agency workflow
# Version 3.1 - Added ONS/ONB client codes

import os
import json
import re
from datetime import datetime
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
AIRTABLE_TRAFFIC_TABLE = 'Traffic'

ANTHROPIC_API_KEY = os.environ.get('ANTHROPIC_API_KEY')
ANTHROPIC_MODEL = 'claude-sonnet-4-20250514'

VALID_CLIENT_CODES = ['ONE', 'ONS', 'ONB', 'SKY', 'TOW', 'FIS', 'FST', 'WKA', 'HUN', 'LAB', 'EON', 'OTH']

# Client name to code mapping
CLIENT_NAME_MAPPING = {
    'one nz': 'ONE',
    'one': 'ONE',
    'ons': 'ONS',
    'onb': 'ONB',
    'simplification': 'ONS',
    'one nz simplification': 'ONS',
    'one nz - simplification': 'ONS',
    'business': 'ONB',
    'one nz business': 'ONB',
    'one nz - business': 'ONB',
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
    'eonfibre': 'EON',
    'hunch': 'HUN'
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
# TRAFFIC TABLE FUNCTIONS
# ===================

def check_duplicate_email(internet_message_id):
    """Check if we've already processed this email (deduplication).
    
    Returns the existing record if found, None otherwise.
    """
    if not AIRTABLE_API_KEY or not internet_message_id:
        return None
    
    try:
        search_url = f"https://api.airtable.com/v0/{AIRTABLE_BASE_ID}/{AIRTABLE_TRAFFIC_TABLE}"
        params = {'filterByFormula': f"{{internetMessageId}}='{internet_message_id}'"}
        
        response = httpx.get(search_url, headers=_get_airtable_headers(), params=params, timeout=10.0)
        response.raise_for_status()
        
        records = response.json().get('records', [])
        
        if records:
            return records[0]  # Already processed
        return None
        
    except Exception as e:
        print(f"Error checking duplicate: {e}")
        return None


def check_pending_clarify(conversation_id):
    """Check if this conversation has a pending clarify request.
    
    Returns the pending record if found, None otherwise.
    """
    if not AIRTABLE_API_KEY or not conversation_id:
        return None
    
    try:
        search_url = f"https://api.airtable.com/v0/{AIRTABLE_BASE_ID}/{AIRTABLE_TRAFFIC_TABLE}"
        # Look for pending clarify with matching conversationId
        filter_formula = f"AND({{conversationId}}='{conversation_id}', {{Status}}='pending')"
        params = {'filterByFormula': filter_formula}
        
        response = httpx.get(search_url, headers=_get_airtable_headers(), params=params, timeout=10.0)
        response.raise_for_status()
        
        records = response.json().get('records', [])
        
        if records:
            return records[0]
        return None
        
    except Exception as e:
        print(f"Error checking pending clarify: {e}")
        return None


def log_to_traffic_table(internet_message_id, conversation_id, route, status, job_number, sender_email, subject):
    """Log email to Traffic table.
    
    Returns the created record ID or None.
    """
    if not AIRTABLE_API_KEY:
        return None
    
    try:
        create_url = f"https://api.airtable.com/v0/{AIRTABLE_BASE_ID}/{AIRTABLE_TRAFFIC_TABLE}"
        
        record_data = {
            'fields': {
                'internetMessageId': internet_message_id or '',
                'conversationId': conversation_id or '',
                'Route': route,
                'Status': status,
                'JobNumber': job_number or '',
                'SenderEmail': sender_email or '',
                'Subject': subject or '',
                'CreatedAt': datetime.utcnow().isoformat()
            }
        }
        
        response = httpx.post(create_url, headers=_get_airtable_headers(), json=record_data, timeout=10.0)
        response.raise_for_status()
        
        return response.json().get('id')
        
    except Exception as e:
        print(f"Error logging to Traffic table: {e}")
        return None


def update_traffic_record(record_id, updates):
    """Update an existing Traffic table record.
    
    updates: dict of field names to values
    """
    if not AIRTABLE_API_KEY or not record_id:
        return False
    
    try:
        update_url = f"https://api.airtable.com/v0/{AIRTABLE_BASE_ID}/{AIRTABLE_TRAFFIC_TABLE}/{record_id}"
        
        response = httpx.patch(update_url, headers=_get_airtable_headers(), json={'fields': updates}, timeout=10.0)
        response.raise_for_status()
        
        return True
        
    except Exception as e:
        print(f"Error updating Traffic record: {e}")
        return False


# ===================
# AIRTABLE FUNCTIONS (Projects)
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
    """Extract client code from client name mentioned in text.
    
    Also checks for direct client codes (ONS, ONB, etc).
    """
    if not text:
        return None
    
    text_lower = text.lower()
    text_upper = text.upper()
    
    # First check for direct client codes as standalone words
    for code in VALID_CLIENT_CODES:
        # Look for the code as a standalone word (not part of another word)
        if re.search(r'\b' + code + r'\b', text_upper):
            return code
    
    # Then check for client names in the text
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
    1. Check for duplicate (internetMessageId already processed)
    2. Check for pending clarify reply (conversationId matches pending)
    3. Job number in subject/body? Validate against Projects.
    4. No job number? Look for clues and let Claude route.
    5. Log to Traffic table.
    """
    try:
        data = request.get_json()
        
        # Required field
        content = data.get('emailContent', '')
        if not content:
            return jsonify({'error': 'No content provided'}), 400
        
        # Email metadata fields
        subject = data.get('subjectLine', '')
        sender_email = data.get('senderEmail', '')
        sender_name = data.get('senderName', '')
        all_recipients = data.get('allRecipients', [])
        has_attachments = data.get('hasAttachments', False)
        attachment_names = data.get('attachmentNames', [])
        source = data.get('source', 'email')
        
        # New fields for deduplication and thread tracking
        internet_message_id = data.get('internetMessageId', '')
        conversation_id = data.get('conversationId', '')
        
        # ===================
        # STEP 0: DEDUPLICATION CHECK
        # ===================
        if internet_message_id:
            existing = check_duplicate_email(internet_message_id)
            if existing:
                return jsonify({
                    'route': 'duplicate',
                    'reason': 'Email already processed',
                    'originalRoute': existing['fields'].get('Route', ''),
                    'originalRecordId': existing['id']
                })
        
        # ===================
        # STEP 1: CHECK FOR PENDING CLARIFY REPLY
        # ===================
        pending_clarify = None
        if conversation_id:
            pending_clarify = check_pending_clarify(conversation_id)
        
        if pending_clarify:
            # This is a reply to a previous clarify request
            pending_fields = pending_clarify['fields']
            original_route = pending_fields.get('Route', 'clarify')
            
            # Extract job number from the reply
            reply_job_number = extract_job_number(subject)
            if not reply_job_number:
                reply_job_number = extract_job_number(content)
            
            # Check for YES confirmation (various affirmative replies)
            content_upper = content.strip().upper()
            affirmatives = [
                'YES', 'YES.', 'YES!', 'YEP', 'YUP', 'YEAH', 
                'CONFIRM', 'CONFIRMED', 'CORRECT', 'THAT\'S RIGHT', 
                'THATS RIGHT', 'THAT\'S THE ONE', 'THATS THE ONE',
                'THAT\'S IT', 'THATS IT', 'BINGO', 'SPOT ON', 'PERFECT'
            ]
            is_yes = content_upper in affirmatives or content_upper.startswith('YES')
            
            # Check for TRIAGE request
            is_triage = content_upper in ['TRIAGE', 'TRIAGE.', 'NEW JOB', 'NEW']
            
            if is_triage:
                # User wants to triage as new job
                log_to_traffic_table(
                    internet_message_id, conversation_id, 'triage', 'processed',
                    None, sender_email, subject
                )
                # Mark original clarify as resolved
                update_traffic_record(pending_clarify['id'], {'Status': 'resolved'})
                
                return jsonify({
                    'route': 'triage',
                    'confidence': 'high',
                    'jobNumber': None,
                    'reason': 'User requested triage in clarify reply',
                    'senderEmail': sender_email,
                    'senderName': sender_name,
                    'source': source
                })
            
            elif reply_job_number:
                # User provided a job number - validate it
                project = get_project_by_job_number(reply_job_number)
                
                if project:
                    # Valid job number provided
                    log_to_traffic_table(
                        internet_message_id, conversation_id, 'update', 'processed',
                        reply_job_number, sender_email, subject
                    )
                    # Mark original clarify as resolved
                    update_traffic_record(pending_clarify['id'], {
                        'Status': 'resolved',
                        'JobNumber': reply_job_number
                    })
                    
                    return jsonify({
                        'route': 'update',
                        'confidence': 'high',
                        'jobNumber': reply_job_number,
                        'jobName': project['jobName'],
                        'clientName': project['clientName'],
                        'clientCode': reply_job_number.split()[0],
                        'currentRound': project['round'],
                        'currentStage': project['stage'],
                        'withClient': project['withClient'],
                        'teamsChannelId': project['teamsChannelId'],
                        'projectRecordId': project['recordId'],
                        'reason': 'Job number provided in clarify reply',
                        'senderEmail': sender_email,
                        'senderName': sender_name,
                        'source': source
                    })
                else:
                    # Invalid job number
                    return jsonify({
                        'route': 'clarify',
                        'confidence': 'low',
                        'reason': f"Job {reply_job_number} not found in system",
                        'senderEmail': sender_email,
                        'senderName': sender_name,
                        'source': source,
                        'clarifyEmail': f"<p>Hi {sender_name or 'there'},</p><p>I couldn't find job <strong>{reply_job_number}</strong> in the system.</p><p>Please check the job number and try again, or reply <strong>TRIAGE</strong> if this is a new job.</p><p>Dot</p>"
                    })
            
            elif is_yes:
                # User confirmed suggested job - get it from the pending record
                suggested_job = pending_fields.get('JobNumber', '')
                
                if suggested_job:
                    # Validate the suggested job still exists
                    project = get_project_by_job_number(suggested_job)
                    
                    if project:
                        # Confirmed! Log and route
                        log_to_traffic_table(
                            internet_message_id, conversation_id, 'update', 'processed',
                            suggested_job, sender_email, subject
                        )
                        update_traffic_record(pending_clarify['id'], {'Status': 'resolved'})
                        
                        return jsonify({
                            'route': 'update',
                            'confidence': 'high',
                            'jobNumber': suggested_job,
                            'jobName': project['jobName'],
                            'clientName': project['clientName'],
                            'clientCode': suggested_job.split()[0],
                            'currentRound': project['round'],
                            'currentStage': project['stage'],
                            'withClient': project['withClient'],
                            'teamsChannelId': project['teamsChannelId'],
                            'projectRecordId': project['recordId'],
                            'reason': 'User confirmed suggested job',
                            'senderEmail': sender_email,
                            'senderName': sender_name,
                            'source': source
                        })
                
                # No suggested job stored, ask for it
                return jsonify({
                    'route': 'clarify',
                    'confidence': 'low',
                    'reason': 'Confirmation received but no job was suggested',
                    'senderEmail': sender_email,
                    'senderName': sender_name,
                    'source': source,
                    'clarifyEmail': f"<p>Hi {sender_name or 'there'},</p><p>Thanks! Could you reply with the job number?</p><p>Dot</p>"
                })
        
        # ===================
        # STEP 2: EXTRACT JOB NUMBER
        # ===================
        job_number = extract_job_number(subject)
        if not job_number:
            job_number = extract_job_number(content)
        
        # If we have a job number, validate it exists
        project = None
        if job_number:
            project = get_project_by_job_number(job_number)
        
        # ===================
        # STEP 3: IDENTIFY CLIENT AND GET ACTIVE JOBS
        # ===================
        client_code = None
        active_jobs = []
        
        if job_number:
            client_code = job_number.split()[0] if job_number else None
        
        if not client_code:
            client_code = extract_client_code_from_content(subject)
            if not client_code:
                client_code = extract_client_code_from_content(content)
        
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
        
        # ===================
        # STEP 4: CALL CLAUDE FOR ROUTING
        # ===================
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
        
        response = anthropic_client.messages.create(
            model=ANTHROPIC_MODEL,
            max_tokens=1500,
            temperature=0.1,
            system=TRAFFIC_PROMPT,
            messages=[
                {'role': 'user', 'content': full_content}
            ]
        )
        
        result_text = response.content[0].text
        result_text = strip_markdown_json(result_text)
        routing = json.loads(result_text)
        
        # ===================
        # STEP 5: ENRICH AND VALIDATE RESPONSE
        # ===================
        
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
                routing['route'] = 'clarify'
                routing['confidence'] = 'low'
                routing['reason'] = f"Matched job {routing['jobNumber']} not found in system"
        
        routing['source'] = source
        routing['clientCode'] = client_code
        
        # ===================
        # STEP 6: LOG TO TRAFFIC TABLE
        # ===================
        route = routing.get('route', 'unknown')
        status = 'pending' if route in ['clarify', 'confirm'] else 'processed'
        final_job_number = routing.get('jobNumber')
        
        log_to_traffic_table(
            internet_message_id, conversation_id, route, status,
            final_job_number, sender_email, subject
        )
        
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
        'version': '3.1',
        'features': ['deduplication', 'clarify-loop', 'ons-onb-support']
    })


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)
