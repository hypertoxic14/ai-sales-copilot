import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
from dotenv import load_dotenv
from pathlib import Path
import os, base64

load_dotenv(Path(__file__).resolve().parents[2] / ".env")

SMTP_EMAIL    = os.getenv("SMTP_EMAIL")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD")


def _is_configured() -> bool:
    return bool(SMTP_EMAIL and SMTP_PASSWORD)


def send_email(
    to_email:    str,
    subject:     str,
    body:        str,
    attachments: list = None
) -> dict:
    """
    Send a plain professional email via Gmail SMTP.
    attachments = [{"filename": "doc.pdf", "data": base64_string}]
    Returns {"success": bool, "message": str}
    """
    if not _is_configured():
        return {
            "success": False,
            "message": "SMTP not configured. Add SMTP_EMAIL and SMTP_PASSWORD to .env"
        }

    if not to_email or "@" not in to_email:
        return {
            "success": False,
            "message": f"Invalid recipient email: {to_email}"
        }

    try:
        msg = MIMEMultipart("mixed")
        msg["Subject"] = subject
        msg["From"]    = SMTP_EMAIL
        msg["To"]      = to_email

        # Plain text + HTML body
        body_html = body.replace("\n", "<br>")
        html = f"""
        <div style="font-family:Segoe UI,Arial,sans-serif;max-width:600px;
                    margin:0 auto;padding:32px 20px">
          <p style="color:#1f1f1f;font-size:14px;line-height:1.8">
            {body_html}
          </p>
          <hr style="border:none;border-top:1px solid #e5e5e5;margin:24px 0"/>
          <p style="color:#9ca3af;font-size:11px">
            Sent via AI Sales Copilot
          </p>
        </div>
        """
        msg.attach(MIMEText(body,  "plain"))
        msg.attach(MIMEText(html,  "html"))

        # Attachments
        if attachments:
            for att in attachments:
                part = MIMEBase("application", "octet-stream")
                part.set_payload(base64.b64decode(att["data"]))
                encoders.encode_base64(part)
                part.add_header(
                    "Content-Disposition",
                    f'attachment; filename="{att["filename"]}"'
                )
                msg.attach(part)

        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(SMTP_EMAIL, SMTP_PASSWORD)
            server.sendmail(SMTP_EMAIL, to_email, msg.as_string())

        return {
            "success": True,
            "message": f"Email sent to {to_email}"
        }

    except smtplib.SMTPAuthenticationError:
        return {
            "success": False,
            "message": "Gmail authentication failed. Check your App Password in .env"
        }
    except smtplib.SMTPRecipientsRefused:
        return {
            "success": False,
            "message": f"Recipient refused: {to_email}. Check the email address."
        }
    except Exception as e:
        return {
            "success": False,
            "message": f"Email failed: {str(e)}"
        }


def send_task_notification(
    to_email:     str,
    assignee:     str,
    task:         str,
    deadline:     str,
    priority:     str,
    meeting_title:str = ""
) -> dict:
    """Send a task assignment notification email."""
    subject = f"Action required: {task[:60]}"
    body    = f"""Hi {assignee.split()[0]},

You have been assigned a task{f' from the meeting: {meeting_title}' if meeting_title else ''}.

Task: {task}
Deadline: {deadline or 'As soon as possible'}
Priority: {priority.upper()}

Please confirm receipt and update the status when complete.

Best regards,
AI Sales Copilot"""

    return send_email(to_email, subject, body)