# Dot Traffic

Intelligent email/message routing for Hunch agency workflow.

## What it does

Routes incoming emails and Teams messages to the correct handler:
- **triage** - New job setup
- **update** - Status updates on existing jobs
- **wip** - Work In Progress reports
- **tracker** - Finance reports
- **work-to-client** - Deliverables being sent
- **feedback** - Client feedback processing
- **clarify** - Needs more information

## Endpoint

`POST /traffic`

### Input

```json
{
  "emailContent": "The email body or Teams message",
  "subjectLine": "Email subject",
  "senderEmail": "sender@example.com",
  "senderName": "Sarah",
  "allRecipients": ["recipient@example.com"],
  "hasAttachments": true,
  "attachmentNames": ["file.pdf"],
  "source": "email"
}
```

### Output

```json
{
  "route": "update",
  "confidence": "high",
  "jobNumber": "TOW 087",
  "clientCode": "TOW",
  "clientName": "Tower Insurance",
  "intent": "Status update on newsletter",
  "reason": "Job number in subject, clear update intent"
}
```

## Environment Variables

- `ANTHROPIC_API_KEY` - Claude API key
- `AIRTABLE_API_KEY` - Airtable API key

## Deployment

Deploy to Railway with root directory `/` (this is a standalone app).
