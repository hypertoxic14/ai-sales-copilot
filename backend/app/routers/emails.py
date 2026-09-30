from fastapi import APIRouter, HTTPException, Header
from pydantic import BaseModel
from typing import Optional, List
from app.services.firebase_service import verify_token
from app.services.email_service import send_email, send_task_notification
from app.services.llm_service import process_transcript
from groq import Groq
from dotenv import load_dotenv
from pathlib import Path
import os, re, json

load_dotenv(Path(__file__).resolve().parents[2] / ".env")
client = Groq(api_key=os.getenv("GROQ_API_KEY"))

router = APIRouter()

def get_uid(authorization: str):
    try:
        token   = authorization.replace("Bearer ", "")
        decoded = verify_token(token)
        return decoded["uid"]
    except Exception as e:
        raise HTTPException(status_code=401, detail=str(e))


class GenerateAndSendRequest(BaseModel):
    to_email:      str
    task:          str
    context:       str = ""
    sender_name:   str = ""
    meeting_title: str = ""

class SendDirectRequest(BaseModel):
    to_email:    str
    subject:     str
    body:        str
    attachments: Optional[List[dict]] = []

class GenerateOnlyRequest(BaseModel):
    task:          str
    context:       str = ""
    sender_name:   str = ""
    to_name:       str = ""
    meeting_title: str = ""


def _generate_email(
    task: str, context: str,
    sender_name: str, to_name: str,
    meeting_title: str
) -> dict:
    """Use LLM to generate a professional email."""
    system = """You are a professional email ghostwriter for a sales team.
Write a clean, professional email as if the sender wrote it themselves.
Return ONLY valid JSON: {"subject": "...", "body": "..."}
Body should be plain text, professional, under 150 words.
Sound human — not robotic. No JSON fences."""

    user = f"""
Task: {task}
Written by: {sender_name or 'Sales Rep'}
Recipient: {to_name or 'the recipient'}
Meeting context: {context or meeting_title or 'recent meeting'}

Write the email the sender needs to send to complete this task.
Figure out who the recipient is from the task description.
Make it sound like {sender_name or 'the sender'} personally wrote it.
Sign off with just their first name.
"""
    res = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[
            {"role":"system","content":system},
            {"role":"user",  "content":user}
        ],
        temperature=0.3,
        max_tokens=400
    )
    raw = res.choices[0].message.content.strip()
    raw = re.sub(r"^```(?:json)?\s*","",raw)
    raw = re.sub(r"\s*```$","",raw)

    try:
        return json.loads(raw)
    except Exception:
        return {
            "subject": f"Follow-up: {task[:60]}",
            "body":    raw
        }


@router.post("/generate")
def generate_email_only(
    req: GenerateOnlyRequest,
    authorization: str = Header(...)
):
    """Generate email draft without sending — for preview."""
    get_uid(authorization)
    result = _generate_email(
        task=req.task,
        context=req.context,
        sender_name=req.sender_name,
        to_name=req.to_name,
        meeting_title=req.meeting_title
    )
    return {
        "subject": result["subject"],
        "body":    result["body"]
    }


@router.post("/generate-and-send")
def generate_and_send(
    req: GenerateAndSendRequest,
    authorization: str = Header(...)
):
    """Generate email with LLM then send immediately."""
    get_uid(authorization)

    # Generate
    result = _generate_email(
        task=req.task,
        context=req.context,
        sender_name=req.sender_name,
        to_name="",
        meeting_title=req.meeting_title
    )

    # Send
    send_result = send_email(
        to_email=req.to_email,
        subject=result["subject"],
        body=result["body"]
    )

    if not send_result["success"]:
        raise HTTPException(
            status_code=500,
            detail=send_result["message"]
        )

    return {
        "success": True,
        "subject": result["subject"],
        "body":    result["body"],
        "message": send_result["message"]
    }


@router.post("/send")
def send_direct(
    req: SendDirectRequest,
    authorization: str = Header(...)
):
    """Send email directly with provided subject + body."""
    get_uid(authorization)

    result = send_email(
        to_email=req.to_email,
        subject=req.subject,
        body=req.body,
        attachments=req.attachments or []
    )

    if not result["success"]:
        raise HTTPException(
            status_code=500,
            detail=result["message"]
        )

    return result


@router.get("/status")
def email_status(authorization: str = Header(...)):
    """Check if SMTP is configured."""
    get_uid(authorization)
    from app.services.email_service import _is_configured, SMTP_EMAIL
    return {
        "configured": _is_configured(),
        "email":      SMTP_EMAIL if _is_configured() else None
    }