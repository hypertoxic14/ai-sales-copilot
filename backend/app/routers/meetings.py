from fastapi import APIRouter, UploadFile, File, HTTPException, Header
from fastapi.responses import StreamingResponse
from app.services.firebase_service import verify_token, db
from app.services.memory_service import (
    save_meeting, save_task, get_user_memory, save_lead
)
from app.services.whisper_service import transcribe_audio
from app.services.llm_service import (
    process_transcript, generate_objection_responses, generate_mom
)
from app.services.assistant_service import _classify_meeting_context
from firebase_admin import firestore
from datetime import datetime
import shutil, os, uuid, re, io

router     = APIRouter()
UPLOAD_DIR = "uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)


def get_uid(authorization: str):
    try:
        token   = authorization.replace("Bearer ", "")
        decoded = verify_token(token)
        return decoded["uid"]
    except Exception as e:
        raise HTTPException(status_code=401, detail=str(e))


def _extract_deal_value(transcript: str, summary: str):
    text = (transcript + " " + summary).lower()
    patterns = [
        (r'\$\s*(\d+(?:\.\d+)?)\s*million', 1_000_000),
        (r'(\d+(?:\.\d+)?)\s*million\s*(?:dollar|usd)', 1_000_000),
        (r'\$\s*(\d+(?:\.\d+)?)\s*m\b(?!onth|onths|inute)', 1_000_000),
        (r'\$\s*(\d+(?:\.\d+)?)\s*k\b', 1_000),
        (r'(\d+(?:\.\d+)?)\s*thousand\s*(?:dollar|usd)', 1_000),
        (r'\$\s*(\d{1,3}(?:,\d{3}){2,})', 1),
        (r'\$\s*(\d{2,3},\d{3})\b', 1),
    ]
    for pattern, multiplier in patterns:
        match = re.search(pattern, text)
        if match:
            val = float(match.group(1).replace(",", ""))
            return val * multiplier
    return None


def _extract_company_from_context(
    transcript: str, summary: str, participants: list
) -> str:
    for p in participants:
        email = p.get("email","") if isinstance(p, dict) else ""
        if email and "@" in email:
            domain = email.split("@")[1].split(".")[0]
            if domain not in [
                "gmail","yahoo","hotmail","outlook",
                "icloud","protonmail","aol"
            ]:
                return domain.capitalize()

    explicit_patterns = [
        r'(?:with|from|for|at|representing)\s+([A-Z][a-zA-Z]+(?:\s+[A-Z][a-zA-Z]+){1,4})\b',
        r'([A-Z][a-zA-Z]+(?:\s+[A-Z][a-zA-Z]+){1,3})\s+(?:Inc|LLC|Ltd|Corp|Holdings|Solutions|Technologies|Group|Services|Systems)\b',
        r'(?:company|client|customer|account)\s+(?:is\s+)?([A-Z][a-zA-Z]+(?:\s+[A-Z][a-zA-Z]+){0,3})\b',
    ]
    skip = {
        "The","This","Our","Your","Their","We","They","Meeting","Team",
        "Client","Customer","Vendor","Monday","Tuesday","Wednesday",
        "Thursday","Friday","Saturday","Sunday"
    }
    for pattern in explicit_patterns:
        match = re.search(pattern, summary)
        if match:
            name = match.group(1).strip()
            if name.split()[0] not in skip and len(name) > 3:
                return name
    for pattern in explicit_patterns:
        match = re.search(pattern, transcript[:800])
        if match:
            name = match.group(1).strip()
            if name.split()[0] not in skip and len(name) > 3:
                return name
    return ""


def _auto_update_or_create_lead(
    uid, company, context_info, llm_result, transcript, meeting_id
):
    today           = datetime.utcnow().isoformat()[:10]
    suggested_stage = context_info.get("suggested_stage","lead")
    matched_lead    = context_info.get("matched_lead")
    confidence      = context_info.get("confidence", 0)

    deal_value = _extract_deal_value(
        transcript, llm_result.get("summary","")
    )

    notes_parts = []
    if llm_result.get("objections"):
        notes_parts.append(
            "Objections: " + "; ".join(llm_result["objections"][:3])
        )
    if llm_result.get("requirements"):
        notes_parts.append(
            "Requirements: " + "; ".join(llm_result["requirements"][:3])
        )
    if llm_result.get("next_steps"):
        notes_parts.append(
            "Next steps: " + "; ".join(llm_result["next_steps"][:3])
        )
    meeting_notes = " | ".join(notes_parts)

    if matched_lead and confidence >= 0.6:
        lead_id = matched_lead["id"]
        updates = {
            "last_contact":    today,
            "updated_at":      today,
            "last_meeting_id": meeting_id
        }
        stage_order = [
            "lead","prospect","qualified","proposal",
            "negotiation","closed_won","closed_lost"
        ]
        current_idx   = stage_order.index(
            matched_lead.get("stage","lead")
        ) if matched_lead.get("stage","lead") in stage_order else 0
        suggested_idx = stage_order.index(
            suggested_stage
        ) if suggested_stage in stage_order else 0

        if suggested_idx > current_idx:
            updates["stage"] = suggested_stage
        if deal_value and deal_value > (matched_lead.get("value") or 0):
            updates["value"] = deal_value
        if meeting_notes:
            existing = matched_lead.get("notes","") or ""
            updates["notes"] = f"{existing}\n[{today}] {meeting_notes}".strip()

        db.collection("users").document(uid)\
          .collection("leads").document(lead_id).update(updates)

        return {
            "action":    "updated",
            "lead_id":   lead_id,
            "company":   matched_lead["company"],
            "new_stage": updates.get("stage", matched_lead.get("stage")),
            "value":     deal_value
        }

    elif company and confidence >= 0.4:
        participants  = llm_result.get("participants",[])
        contact_name  = ""
        contact_email = ""
        if participants:
            first = participants[0]
            contact_name  = first.get("name","")  if isinstance(first,dict) else str(first)
            contact_email = first.get("email","") if isinstance(first,dict) else ""

        new_lead = save_lead(uid, {
            "company":         company,
            "contact_name":    contact_name or "Unknown",
            "email":           contact_email or None,
            "stage":           suggested_stage,
            "value":           deal_value,
            "notes":           meeting_notes,
            "last_contact":    today,
            "last_meeting_id": meeting_id,
            "source":          "meeting_auto"
        })
        return {
            "action":    "created",
            "lead_id":   new_lead["id"],
            "company":   company,
            "new_stage": suggested_stage,
            "value":     deal_value
        }

    return {"action": "none"}


# ── UPLOAD ────────────────────────────────────────────────
@router.post("/upload")
async def upload_meeting(
    file:          UploadFile = File(...),
    authorization: str        = Header(...)
):
    uid = get_uid(authorization)

    allowed = ["audio/mpeg","audio/wav","audio/mp4","audio/x-m4a","audio/webm"]
    if file.content_type not in allowed:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid file type: {file.content_type}"
        )

    ext             = os.path.splitext(file.filename)[1]
    unique_filename = f"{uuid.uuid4()}{ext}"
    file_path       = os.path.join(UPLOAD_DIR, unique_filename)

    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    # Step 1: Transcribe
    try:
        transcription = transcribe_audio(file_path)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Transcription failed: {e}")

    # Step 2: LLM extraction
    try:
        llm_result = process_transcript(transcription["transcript"])
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"LLM failed: {e}")

    # Step 3: Classify context
    memory       = get_user_memory(uid)
    context_info = _classify_meeting_context(
        llm_result.get("summary",""),
        memory["leads"]
    )

    # Step 4: Get linked company
    matched_lead   = context_info.get("matched_lead")
    linked_company = (matched_lead.get("company","") if matched_lead else "") or ""
    if not linked_company:
        linked_company = _extract_company_from_context(
            transcription["transcript"],
            llm_result.get("summary",""),
            llm_result.get("participants",[])
        )
    linked_lead_id = matched_lead.get("id","") if matched_lead else ""

    # Step 5: Generate objection counter-responses
    objection_responses = []
    if llm_result.get("objections"):
        try:
            objection_responses = generate_objection_responses(
                objections=llm_result["objections"],
                company=linked_company,
                context=llm_result.get("summary","")
            )
            print(f"✅ Generated {len(objection_responses)} objection responses")
        except Exception as e:
            print(f"❌ Objection response generation failed: {e}")

    # Step 6: Save meeting to Firestore
    meeting = save_meeting(uid, {
        "title":               file.filename,
        "transcript":          transcription["transcript"],
        "summary":             llm_result.get("summary",""),
        "action_items":        llm_result.get("action_items",[]),
        "participants":        llm_result.get("participants",[]),
        "objections":          llm_result.get("objections",[]),
        "requirements":        llm_result.get("requirements",[]),
        "next_steps":          llm_result.get("next_steps",[]),
        "sentiment":           llm_result.get("sentiment","neutral"),
        "language":            transcription["language"],
        "duration":            transcription["duration"],
        "meeting_context":     context_info["context"],
        "suggested_stage":     context_info["suggested_stage"],
        "context_confidence":  context_info["confidence"],
        "linked_lead_id":      linked_lead_id,
        "linked_company":      linked_company,
        "objection_responses": objection_responses,
    })

    # Step 6b: Generate MOM
    mom_data = {}
    try:
        mom_data = generate_mom({
            "title":        file.filename,
            "summary":      llm_result.get("summary",""),
            "transcript":   transcription["transcript"],
            "objections":   llm_result.get("objections",[]),
            "requirements": llm_result.get("requirements",[]),
            "next_steps":   llm_result.get("next_steps",[]),
        })
        db.collection("users").document(uid)\
          .collection("meetings").document(meeting["id"])\
          .update({"mom": mom_data})
        print(f"✅ MOM generated for {file.filename}")
    except Exception as e:
        print(f"❌ MOM generation failed: {e}")

    # Step 7: Auto-save tasks
    saved_tasks = []
    for item in llm_result.get("action_items",[]):
        task = save_task(uid, {
            "task":       item.get("task",""),
            "deadline":   item.get("deadline"),
            "priority":   item.get("priority","medium").lower(),
            "type":       item.get("type","other"),
            "meeting_id": meeting["id"],
            "source":     "meeting"
        })
        saved_tasks.append(task)

    # Step 8: Auto-update or create lead
    lead_result = _auto_update_or_create_lead(
        uid=uid,
        company=linked_company,
        context_info=context_info,
        llm_result=llm_result,
        transcript=transcription["transcript"],
        meeting_id=meeting["id"]
    )

    stage_suggestion = None
    if (lead_result["action"] == "updated" and
            lead_result.get("new_stage") and matched_lead):
        if lead_result["new_stage"] != matched_lead.get("stage"):
            stage_suggestion = {
                "lead":      linked_company,
                "current":   matched_lead.get("stage",""),
                "suggested": lead_result["new_stage"]
            }

    return {
        "message":             "Meeting processed",
        "meeting_id":          meeting["id"],
        "transcript":          transcription["transcript"],
        "summary":             llm_result.get("summary",""),
        "tasks_saved":         len(saved_tasks),
        "action_items":        llm_result.get("action_items",[]),
        "objections":          llm_result.get("objections",[]),
        "requirements":        llm_result.get("requirements",[]),
        "next_steps":          llm_result.get("next_steps",[]),
        "objection_responses": objection_responses,
        "mom":                 mom_data,
        "meeting_context":     context_info["context"],
        "stage_suggestion":    stage_suggestion,
        "linked_company":      linked_company,
        "lead_action":         lead_result,
    }


# ── LIST MEETINGS ─────────────────────────────────────────
@router.get("/")
def list_meetings(authorization: str = Header(...)):
    uid  = get_uid(authorization)
    docs = db.collection("users").document(uid)\
             .collection("meetings").order_by(
                 "created_at", direction=firestore.Query.DESCENDING
             ).stream()
    return [d.to_dict() for d in docs]


# ── DOWNLOAD MOM PDF ──────────────────────────────────────
@router.get("/{meeting_id}/mom/pdf")
def download_mom_pdf(
    meeting_id:    str,
    authorization: str = Header(...)
):
    uid = get_uid(authorization)
    doc = db.collection("users").document(uid)\
            .collection("meetings").document(meeting_id).get()

    if not doc.exists:
        raise HTTPException(status_code=404, detail="Meeting not found")

    m   = doc.to_dict()
    mom = m.get("mom", {})

    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import cm
    from reportlab.lib import colors
    from reportlab.platypus import (
        SimpleDocTemplate, Paragraph, Spacer,
        Table, TableStyle, HRFlowable
    )

    buffer = io.BytesIO()
    pdf    = SimpleDocTemplate(
        buffer, pagesize=A4,
        rightMargin=2*cm, leftMargin=2*cm,
        topMargin=2*cm,   bottomMargin=2*cm
    )

    styles = getSampleStyleSheet()
    BLUE   = colors.HexColor("#0078D4")
    DARK   = colors.HexColor("#1F1F1F")
    GRAY   = colors.HexColor("#616161")

    title_style = ParagraphStyle(
        "Title", parent=styles["Title"],
        textColor=BLUE, fontSize=22, spaceAfter=6
    )
    h2_style = ParagraphStyle(
        "H2", parent=styles["Heading2"],
        textColor=BLUE, fontSize=13,
        spaceBefore=14, spaceAfter=6
    )
    body_style = ParagraphStyle(
        "Body", parent=styles["Normal"],
        fontSize=10, textColor=DARK,
        leading=16, spaceAfter=4
    )
    meta_style = ParagraphStyle(
        "Meta", parent=styles["Normal"],
        fontSize=10, textColor=GRAY, spaceAfter=2
    )

    story = []

    # Header
    story.append(Paragraph("MINUTES OF MEETING", title_style))
    story.append(HRFlowable(width="100%", thickness=2, color=BLUE))
    story.append(Spacer(1, 8))

    # Meta info
    title = m.get("title","Untitled").replace(".mp3","").replace(".wav","")
    story.append(Paragraph(f"<b>Meeting:</b> {title}", meta_style))
    story.append(Paragraph(f"<b>Date:</b> {m.get('created_at','')[:10]}", meta_style))
    story.append(Paragraph(
        f"<b>Duration:</b> {int(m.get('duration_seconds',0)//60)} minutes",
        meta_style
    ))
    story.append(Paragraph(
        f"<b>Context:</b> {m.get('meeting_context','').replace('_',' ').title()}",
        meta_style
    ))

    participants = m.get("participants",[])
    if participants:
        names = ", ".join([
            p.get("name","") if isinstance(p,dict) else str(p)
            for p in participants
        ])
        story.append(Paragraph(f"<b>Participants:</b> {names}", meta_style))

    story.append(Spacer(1, 12))
    story.append(HRFlowable(
        width="100%", thickness=0.5,
        color=colors.HexColor("#E5E5E5")
    ))

    # Summary
    story.append(Paragraph("Executive Summary", h2_style))
    story.append(Paragraph(
        m.get("summary","No summary available."), body_style
    ))

    # Key discussion points
    for point in mom.get("key_discussion_points",[]):
        story.append(Paragraph(f"• {point}", body_style))

    # Decisions
    decisions = mom.get("decisions_made",[])
    if decisions:
        story.append(Paragraph("Decisions Made", h2_style))
        for d in decisions:
            story.append(Paragraph(f"• {d}", body_style))

    # Objections
    objections = m.get("objections",[])
    if objections:
        story.append(Paragraph("Objections / Concerns Raised", h2_style))
        for o in objections:
            story.append(Paragraph(f"• {o}", body_style))

    # Requirements
    requirements = m.get("requirements",[])
    if requirements:
        story.append(Paragraph("Client Requirements", h2_style))
        for r in requirements:
            story.append(Paragraph(f"• {r}", body_style))

    # Action items table
    action_items = m.get("action_items",[])
    if action_items:
        story.append(Paragraph("Action Items", h2_style))
        table_data = [["Task","Owner","Deadline","Priority"]]
        for item in action_items:
            table_data.append([
                Paragraph(item.get("task",""), body_style),
                item.get("assignee","—") or "—",
                item.get("deadline","—") or "—",
                item.get("priority","medium").upper()
            ])
        t = Table(
            table_data,
            colWidths=[9*cm, 3*cm, 3*cm, 2.5*cm]
        )
        t.setStyle(TableStyle([
            ("BACKGROUND",    (0,0),  (-1,0),  BLUE),
            ("TEXTCOLOR",     (0,0),  (-1,0),  colors.white),
            ("FONTNAME",      (0,0),  (-1,0),  "Helvetica-Bold"),
            ("FONTSIZE",      (0,0),  (-1,0),  10),
            ("ROWBACKGROUNDS",(0,1),  (-1,-1), [
                colors.white,
                colors.HexColor("#F9FAFB")
            ]),
            ("GRID",          (0,0),  (-1,-1), 0.5,
             colors.HexColor("#E5E5E5")),
            ("VALIGN",        (0,0),  (-1,-1), "TOP"),
            ("FONTSIZE",      (0,1),  (-1,-1), 9),
            ("TOPPADDING",    (0,0),  (-1,-1), 6),
            ("BOTTOMPADDING", (0,0),  (-1,-1), 6),
            ("LEFTPADDING",   (0,0),  (-1,-1), 8),
        ]))
        story.append(t)

    # Next steps
    next_steps = m.get("next_steps",[])
    if next_steps:
        story.append(Paragraph("Next Steps", h2_style))
        for ns in next_steps:
            story.append(Paragraph(f"• {ns}", body_style))

    # Next meeting agenda
    for a in mom.get("next_meeting_agenda",[]):
        story.append(Paragraph(f"• {a}", body_style))

    # Risks
    for r in mom.get("risks_identified",[]):
        story.append(Paragraph(f"• {r}", body_style))

    # Footer
    story.append(Spacer(1, 20))
    story.append(HRFlowable(
        width="100%", thickness=0.5,
        color=colors.HexColor("#E5E5E5")
    ))
    story.append(Paragraph(
        f"Generated by AI Sales Copilot — {m.get('created_at','')[:10]}",
        ParagraphStyle(
            "Footer", parent=styles["Normal"],
            fontSize=8, textColor=GRAY, alignment=1
        )
    ))

    pdf.build(story)
    buffer.seek(0)

    filename = f"MOM_{title.replace(' ','_')[:30]}.pdf"
    return StreamingResponse(
        buffer,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"'
        }
    )


# ── BACKFILL OBJECTIONS ───────────────────────────────────
@router.post("/backfill-objections")
def backfill_objections(authorization: str = Header(...)):
    """Re-process all existing meetings to add objection_responses."""
    uid  = get_uid(authorization)
    docs = db.collection("users").document(uid)\
             .collection("meetings").stream()
    updated = 0
    skipped = 0

    for doc in docs:
        m = doc.to_dict()
        if m.get("objection_responses"):
            skipped += 1
            continue
        objections = m.get("objections", [])
        if not objections:
            skipped += 1
            continue
        try:
            responses = generate_objection_responses(
                objections=objections,
                company=m.get("linked_company",""),
                context=m.get("summary","")
            )
            db.collection("users").document(uid)\
              .collection("meetings").document(m["id"])\
              .update({"objection_responses": responses})
            updated += 1
            print(f"✅ Backfilled objections: {m.get('title','?')}")
        except Exception as e:
            print(f"❌ Backfill failed for {m.get('id','?')}: {e}")

    return {"updated": updated, "skipped": skipped}


# ── BACKFILL MOM ──────────────────────────────────────────
@router.post("/backfill-mom")
def backfill_mom(authorization: str = Header(...)):
    """Generate MOM for all existing meetings that don't have one."""
    uid  = get_uid(authorization)
    docs = db.collection("users").document(uid)\
             .collection("meetings").stream()
    updated = 0
    skipped = 0

    for doc in docs:
        m = doc.to_dict()
        if m.get("mom"):
            skipped += 1
            continue
        try:
            mom_data = generate_mom(m)
            db.collection("users").document(uid)\
              .collection("meetings").document(m["id"])\
              .update({"mom": mom_data})
            updated += 1
            print(f"✅ MOM: {m.get('title','?')}")
        except Exception as e:
            print(f"❌ MOM failed for {m.get('id','?')}: {e}")

    return {"updated": updated, "skipped": skipped}