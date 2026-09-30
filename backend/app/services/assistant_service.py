from groq import Groq
from dotenv import load_dotenv
from pathlib import Path
from app.services.memory_service import (
    get_user_memory, get_chat_history,
    save_chat_message, save_task,
    save_lead, save_follow_up
)
import os, json, re
from datetime import date, datetime

load_dotenv(Path(__file__).resolve().parents[2] / ".env")
client = Groq(api_key=os.getenv("GROQ_API_KEY"))

ROLE_PERSONAS = {
    "rep": """You are a personal AI sales assistant for a Sales Representative.
Your personality: proactive, concise, action-oriented.
Focus on: own tasks, follow-ups, lead status, email drafting, meeting summaries.
Proactively remind about overdue items. Suggest next concrete actions.
Correct mistakes — if user says wrong stage or wrong contact, flag it.
If a follow-up is missed, escalate with urgency.""",

    "manager": """You are a personal AI sales assistant for a Sales Manager.
Your personality: strategic, data-driven, team-focused.
Focus on: team performance, pipeline health, missed follow-ups, at-risk deals.
Highlight risks. Suggest coaching actions. Monitor accountability.
Alert about inactive leads. Flag deals with no movement.""",

    "closer": """You are a personal AI sales assistant for a Senior Closer.
Your personality: sharp, deal-focused, persuasive.
Focus on: negotiation status, deal risk, proposal follow-ups, closing strategies.
Identify objections. Suggest counter-strategies. Push for closure.
Flag deals that are stalling.""",

    "admin": """You are an AI assistant for a Sales Admin.
Focus on: system health, user activity, reporting, data integrity.
Help with bulk operations and platform management."""
}

def _classify_meeting_context(summary: str, leads: list) -> dict:
    """
    Detect if a meeting relates to a lead, prospect, existing client, or deal closure.
    Returns classification + confidence + suggested stage.
    """
    lead_names = [l.get("company","").lower() for l in leads]
    summary_lower = summary.lower()

    # Check if any known lead/company is mentioned
    matched_lead = None
    for l in leads:
        company      = (l.get("company") or "").lower()
        contact_name = (l.get("contact_name") or "").lower()
        if (company and company in summary_lower) or \
           (contact_name and contact_name in summary_lower):
            matched_lead = l
            break

    # Classify based on keywords
    if any(w in summary_lower for w in
           ["close","signed","contract","deal closed","won","purchase order"]):
        context = "deal_closure"
        suggested_stage = "closed_won"
        confidence = 0.9
    elif any(w in summary_lower for w in
             ["proposal","quote","pricing","commercial","budget","cost"]):
        context = "proposal_stage"
        suggested_stage = "proposal"
        confidence = 0.85
    elif any(w in summary_lower for w in
             ["negotiate","counter","terms","discount","pushback","objection"]):
        context = "negotiation"
        suggested_stage = "negotiation"
        confidence = 0.85
    elif any(w in summary_lower for w in
             ["demo","presentation","showed","walkthrough","product tour"]):
        context = "prospect"
        suggested_stage = "qualified"
        confidence = 0.8
    elif any(w in summary_lower for w in
             ["intro","first call","initial","introduction","cold"]):
        context = "lead"
        suggested_stage = "prospect"
        confidence = 0.75
    elif matched_lead:
        context = "existing_client"
        suggested_stage = matched_lead.get("stage")
        confidence = 0.7
    else:
        context = "unknown"
        suggested_stage = "lead"
        confidence = 0.4

    return {
        "context":         context,
        "suggested_stage": suggested_stage,
        "confidence":      confidence,
        "matched_lead":    matched_lead
    }


def _detect_risks(memory: dict) -> list:
    """Detect deal risks across the pipeline."""
    risks  = []
    today  = date.today().isoformat()

    for l in memory["leads"]:
        stage        = l.get("stage","")
        last_contact = l.get("last_contact")
        company      = l.get("company","?")

        # High value deal with no contact
        if stage in ["negotiation","proposal"] and not last_contact:
            risks.append({
                "level":   "HIGH",
                "type":    "no_contact",
                "company": company,
                "message": f"🔴 HIGH RISK: {company} is in {stage} with no contact recorded"
            })
        # Stalled deals
        elif stage in ["qualified","prospect"] and not last_contact:
            risks.append({
                "level":   "MEDIUM",
                "type":    "stalled",
                "company": company,
                "message": f"🟡 STALLED: {company} has been in {stage} with no activity"
            })

    return risks[:5]


def _generate_email_draft(task_description: str, context: str,
                          assignee_name: str, profile: dict) -> str:
    """Generate a professional email draft."""
    system = """You are a professional email ghostwriter for a sales team.
Write a clean, professional sales email based on the task.
Return ONLY the email text — no subject line, no JSON, just the body.
Sound human, not robotic. Under 120 words."""

    user = f"""
Task: {task_description}
Context: {context}
Written by: {profile.get('name', 'Sales Rep')}
Role: {profile.get('role', 'rep')}

Write the email body only.
"""
    res = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[
            {"role":"system","content":system},
            {"role":"user",  "content":user}
        ],
        temperature=0.3,
        max_tokens=300
    )
    return res.choices[0].message.content.strip()


def build_system_prompt(profile: dict, memory: dict, rag_context: str = "") -> str:
    role    = profile.get("role", "rep")
    name    = profile.get("name", "User")
    persona = ROLE_PERSONAS.get(role, ROLE_PERSONAS["rep"])
    today   = date.today().isoformat()

    leads_summary = "\n".join([
        f"- ID:{l.get('id','?')} | Company:{l.get('company','?')} | "
        f"Contact:{l.get('contact_name','?')} | "
        f"Email:{l.get('email','none')} | "
        f"Stage:{l.get('stage','lead')} | "
        f"Value:${l.get('value') or 'unknown'} | "
        f"Last contact:{l.get('last_contact','never')} | "
        f"Notes:{l.get('notes','none')}"
        for l in memory["leads"][:10]
    ]) or "No active leads."

    tasks_summary = "\n".join([
        f"- {t.get('task','?')} | "
        f"Due:{t.get('deadline','no deadline')} | "
        f"Priority:{t.get('priority','medium')} | "
        f"Status:{t.get('status','pending')}"
        for t in memory["tasks"][:10]
    ]) or "No pending tasks."

    followups_summary = "\n".join([
        f"- {f.get('contact_name','?')} at {f.get('company','?')} | "
        f"Due:{f.get('due_date','?')} | "
        f"Notes:{f.get('notes','none')}"
        for f in memory["follow_ups"][:5]
    ]) or "No follow-ups."

    meetings_summary = "\n".join([
        f"- {m.get('title','Meeting')} ({m.get('created_at','?')[:10]}): "
        f"{m.get('summary','no summary')[:150]}"
        for m in memory["meetings"][:5]
    ]) or "No recent meetings."

    risks        = _detect_risks(memory)
    risks_summary = "\n".join([r["message"] for r in risks]) \
        or "No risks detected."

    rag_section = f"""
=== RELEVANT MEETING CONTEXT (RAG) ===
{rag_context}
""" if rag_context else ""

    return f"""{persona}

=== USER CONTEXT ===
Name: {name}
Role: {role}
Today: {today}

=== ACTIVE LEADS ===
{leads_summary}

=== PENDING TASKS ===
{tasks_summary}

=== FOLLOW-UPS ===
{followups_summary}

=== RECENT MEETINGS ===
{meetings_summary}

=== DEAL RISKS ===
{risks_summary}
{rag_section}
=== CRITICAL INSTRUCTION ===
Respond ONLY with a raw JSON object. Start with {{ end with }}.
No text before or after. No markdown fences.

Available action types:
- create_task: {{"type":"create_task","data":{{"task":"string","deadline":"YYYY-MM-DD or null","priority":"high|medium|low","type":"email|call|meeting|follow_up|proposal|other"}}}}
- create_lead: {{"type":"create_lead","data":{{"company":"string","contact_name":"string","email":"null","stage":"lead|prospect|qualified|proposal|negotiation|closed_won|closed_lost","notes":"string"}}}}
- update_lead: {{"type":"update_lead","data":{{"company":"string","stage":"string or null","value":0,"notes":"string or null","last_contact":"{today}","email":"string or null","phone":"string or null","contact_name":"string or null"}}}}
- create_follow_up: {{"type":"create_follow_up","data":{{"contact_name":"string","company":"string","due_date":"YYYY-MM-DD","notes":"string"}}}}
- schedule_meeting: {{"type":"schedule_meeting","data":{{"title":"Meeting title","date":"YYYY-MM-DD","time":"HH:MM","end_time":"HH:MM or null","company":"company name","description":"optional notes"}}}}
- generate_email: {{"type":"generate_email","data":{{"task":"string","context":"string","to":"recipient name"}}}}


Special queries:
- "what pending tasks" → list from PENDING TASKS above
- "which leads need follow-up" → check FOLLOW-UPS + leads with no contact
- "summarize last [company] meeting" → find in RECENT MEETINGS and RAG CONTEXT
- "what did client say about X" → search RAG CONTEXT above
- "which deals are at risk" → use DEAL RISKS above
- "generate [type] email" → use generate_email action
- "show overdue" → filter tasks/follow-ups by date vs today={today}
- "schedule meeting with X on Y at Z" → use schedule_meeting action
- "book a call with X" → use schedule_meeting action
- "set up a meeting" → use schedule_meeting action
- "what objections" → find in RAG CONTEXT objections field
- "what did client require" → find in RAG CONTEXT requirements field
- correct user mistakes → if they say wrong info vs context, politely correct
- "how do I handle [objection]" → search RAG CONTEXT for similar objections and counter-responses
- "what objections did X raise" → find in RAG CONTEXT objections field
- "give me a response to [objection]" → generate counter-response using your sales expertise

CORRECT response format:
{{"reply":"Your response here, {name}","actions":[]}}

Rules:
- Always address user as {name}
- "actions" can be empty []
- Only save actions when user explicitly requests OR clear intent detected
- Proactively warn about risks from DEAL RISKS section
- When answering about past meetings use RAG CONTEXT if available
- today = {today}
- ONLY output JSON, nothing else
- If an action fails (type contains "failed" or "not_found"), tell the user exactly what failed and suggest they do it manually in the relevant page
- Never say "updated" or "done" unless the action type returned is "lead_updated", "task_created" etc — not "failed"
- Be honest about limitations — if you cannot update something, say so clearly
"""

def _parse_response(raw: str) -> dict:
    raw = raw.strip()
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)

    try:
        parsed = json.loads(raw)
        if "reply" in parsed:
            return parsed
    except Exception:
        pass

    match = re.search(r'\{[\s\S]*"reply"[\s\S]*\}', raw)
    if match:
        try:
            parsed = json.loads(match.group())
            if "reply" in parsed:
                return parsed
        except Exception:
            pass

    reply_match = re.search(
        r'"reply"\s*:\s*"(.*?)"(?=\s*[,}])', raw, re.DOTALL
    )
    reply   = reply_match.group(1) if reply_match else raw.split("{")[0].strip()
    actions = []
    actions_match = re.search(r'"actions"\s*:\s*(\[[\s\S]*?\])', raw)
    if actions_match:
        try:
            actions = json.loads(actions_match.group(1))
        except Exception:
            pass

    return {"reply": reply or raw, "actions": actions}


def _execute_actions(uid: str, actions: list, profile: dict, memory: dict) -> list:
    from app.services.firebase_service import db
    from datetime import datetime

    executed = []

    for action in actions:
        try:
            atype = action.get("type")
            data  = action.get("data", {})

            # ── CREATE TASK ──────────────────────────────────────
            if atype == "create_task":
                try:
                    result = save_task(uid, data)
                    executed.append({
                        "type":    "task_created",
                        "message": f"Task saved: {data.get('task','?')}",
                        "id":      result.get("id")
                    })
                except Exception as e:
                    executed.append({
                        "type":    "task_create_failed",
                        "message": f"Could not save task '{data.get('task','?')}': {str(e)}. Please add it manually in Activities."
                    })

            # ── CREATE LEAD ──────────────────────────────────────
            elif atype == "create_lead":
                try:
                    result = save_lead(uid, data)
                    executed.append({
                        "type":    "lead_created",
                        "message": f"Lead saved: {data.get('company','?')}",
                        "id":      result.get("id")
                    })
                except Exception as e:
                    executed.append({
                        "type":    "lead_create_failed",
                        "message": f"Could not create lead '{data.get('company','?')}': {str(e)}. Please add it manually in Leads."
                    })

            # ── UPDATE LEAD ──────────────────────────────────────
            elif atype == "update_lead":
                company = data.get("company", "").lower().strip()

                if not company:
                    executed.append({
                        "type":    "lead_update_failed",
                        "message": "Could not update lead — no company name provided."
                    })
                    continue

                # Find matching lead
                try:
                    leads_stream = db.collection("users").document(uid)\
                                     .collection("leads").stream()
                    matched = None
                    for l in leads_stream:
                        ld = l.to_dict()
                        ld_company = ld.get("company", "").lower().strip()
                        if company in ld_company or ld_company in company:
                            matched = ld
                            break
                except Exception as e:
                    executed.append({
                        "type":    "lead_update_failed",
                        "message": f"Could not search leads: {str(e)}. Please update manually in the Leads page."
                    })
                    continue

                if not matched:
                    executed.append({
                        "type":    "lead_not_found",
                        "message": f"Could not find lead '{data.get('company','?')}' in your pipeline. Check the company name or update manually in the Leads page."
                    })
                    continue

                # Build updates — only allowed fields
                ALLOWED_FIELDS = {
                    "stage", "value", "notes",
                    "last_contact", "email", "phone",
                    "contact_name", "company"
                }
                updates = {}
                for k, v in data.items():
                    if k in ALLOWED_FIELDS and v is not None and str(v).strip() != "":
                        updates[k] = v

                if not updates:
                    executed.append({
                        "type":    "lead_update_failed",
                        "message": f"Nothing valid to update for '{matched['company']}'. Fields like id/created_at cannot be changed."
                    })
                    continue

                updates["updated_at"] = datetime.utcnow().isoformat()

                try:
                    db.collection("users").document(uid)\
                      .collection("leads").document(matched["id"])\
                      .update(updates)

                    updated_fields = [
                        k for k in updates if k != "updated_at"
                    ]
                    executed.append({
                        "type":    "lead_updated",
                        "message": f"Lead updated: {matched['company']} — changed: {', '.join(updated_fields)}",
                        "id":      matched["id"]
                    })
                except Exception as e:
                    executed.append({
                        "type":    "lead_update_failed",
                        "message": f"Database error updating '{matched['company']}': {str(e)}. Please update manually in the Leads page."
                    })

            # ── CREATE FOLLOW UP ─────────────────────────────────
            elif atype == "create_follow_up":
                try:
                    result = save_follow_up(uid, data)
                    executed.append({
                        "type":    "follow_up_created",
                        "message": f"Follow-up saved: {data.get('contact_name','?')} at {data.get('company','?')}",
                        "id":      result.get("id")
                    })
                except Exception as e:
                    executed.append({
                        "type":    "follow_up_failed",
                        "message": f"Could not save follow-up: {str(e)}. Please add it manually."
                    })

            elif atype == "schedule_meeting":
                try:
                    import uuid

                    event_doc = {
                        "id":          str(uuid.uuid4()),
                        "title":       data.get("title", "Meeting"),
                        "date":        data.get("date", ""),
                        "time":        data.get("time", ""),
                        "end_time":    data.get("end_time", ""),
                        "type":        "meeting",
                        "description": data.get("description", ""),
                        "lead_id":     data.get("lead_id", ""),
                        "company":     data.get("company", ""),
                        "color":       "0078D4",
                        "source":      "ai_chat",
                        "created_at":  datetime.utcnow().isoformat()
                    }
                    db.collection("users").document(uid)\
                      .collection("events").document(event_doc["id"]).set(event_doc)
                    executed.append({
                        "type":    "meeting_scheduled",
                        "message": f"Meeting scheduled: {data.get('title','?')} on {data.get('date','?')} at {data.get('time','?')}",
                        "id":      event_doc["id"]
                    })
                except Exception as e:
                    executed.append({
                        "type":    "schedule_failed",
                        "message": f"Could not schedule meeting: {str(e)}. Add it manually in the Calendar."
                    })

            # ── GENERATE EMAIL ───────────────────────────────────
            elif atype == "generate_email":
                try:
                    # Find meeting context for this company/topic
                    meeting_context = ""
                    for m in memory.get("meetings", []):
                        topic = data.get("context", "").lower()
                        if topic and topic in m.get("summary", "").lower():
                            meeting_context = m.get("summary", "")
                            break

                    email_body = _generate_email_draft(
                        task_description=data.get("task", ""),
                        context=meeting_context or data.get("context", ""),
                        assignee_name=data.get("to", ""),
                        profile=profile
                    )
                    executed.append({
                        "type":    "email_generated",
                        "message": f"Email drafted for: {data.get('to','?')}",
                        "email":   email_body
                    })
                except Exception as e:
                    executed.append({
                        "type":    "email_failed",
                        "message": f"Could not generate email: {str(e)}. Please write it manually."
                    })

            # ── UNKNOWN ACTION ───────────────────────────────────
            else:
                executed.append({
                    "type":    "unknown_action",
                    "message": f"Unknown action type '{atype}' — could not execute. Please do this manually."
                })

        except Exception as e:
            print(f"Unexpected action error: {action} — {e}")
            executed.append({
                "type":    "action_error",
                "message": f"Unexpected error processing action: {str(e)}. Please try again or do it manually."
            })

    return executed

def _detect_nudges(memory: dict) -> list:
    nudges = []
    today  = date.today().isoformat()

    for f in memory["follow_ups"]:
        due = f.get("due_date","")
        if due and due < today:
            nudges.append({
                "type":    "warning",
                "message": f"Overdue follow-up: {f.get('contact_name','?')} "
                           f"at {f.get('company','?')} — was due {due}"
            })

    for t in memory["tasks"]:
        due = t.get("deadline","")
        if due and due < today and t.get("status") not in ["done"]:
            nudges.append({
                "type":    "warning",
                "message": f"Overdue task: {t.get('task','?')} — was due {due}"
            })

    risks = _detect_risks(memory)
    for r in risks:
        if r["level"] == "HIGH":
            nudges.append({
                "type":    "warning",
                "message": r["message"]
            })

    return nudges[:3]


def chat(uid: str, profile: dict, user_message: str) -> dict:
    from app.services.rag_service import build_rag_context

    memory        = get_user_memory(uid)

    # RAG — retrieve relevant meeting context for this query
    rag_context   = build_rag_context(uid, user_message)

    system_prompt = build_system_prompt(profile, memory, rag_context)

    history  = get_chat_history(uid, limit=10)
    messages = [{"role":"system","content":system_prompt}]
    for msg in history:
        messages.append({
            "role":    msg["role"],
            "content": msg["content"]
        })
    messages.append({"role":"user","content":user_message})

    response = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=messages,
        temperature=0.3,
        max_tokens=800
    )
    raw      = response.choices[0].message.content.strip()
    parsed   = _parse_response(raw)
    reply    = parsed.get("reply", raw)
    actions  = parsed.get("actions", [])
    executed = _execute_actions(uid, actions, profile, memory)
    nudges   = _detect_nudges(memory)

    save_chat_message(uid, "user",      user_message)
    save_chat_message(uid, "assistant", reply)

    email_drafts = [
        e for e in executed
        if e.get("type") == "email_generated"
    ]

    return {
        "reply":        reply,
        "actions":      executed,
        "nudges":       nudges,
        "email_drafts": email_drafts
    }

def calculate_win_probability(lead: dict, memory: dict) -> int:
    """
    Score a lead 0-100% win probability.
    """
    today = date.today().isoformat()

    # Terminal stages — return immediately
    stage = lead.get("stage") or "lead"
    if stage == "closed_won":  return 100
    if stage == "closed_lost": return 0

    stage_scores = {
        "lead":        10,
        "prospect":    20,
        "qualified":   40,
        "proposal":    55,
        "negotiation": 70,
    }
    score = stage_scores.get(stage, 10)

    # Last contact recency ───────────────────────────
    last_contact = lead.get("last_contact") or ""
    if last_contact and isinstance(last_contact, str) and len(last_contact) >= 10:
        try:
            from datetime import datetime as dt
            days_ago = (dt.now() - dt.fromisoformat(last_contact[:10])).days
            if days_ago <= 3:   score += 15
            elif days_ago <= 7: score += 10
            elif days_ago <= 14:score += 5
            elif days_ago > 30: score -= 15
            else:               score -= 5
        except Exception:
            pass
    else:
        score -= 10

    # Deal value presence ────────────────────────────
    value = lead.get("value")
    if value and isinstance(value, (int, float)) and value > 0:
        score += 5

    # Meeting sentiment ──────────────────────────────
    lead_id      = lead.get("id") or ""
    company_name = (lead.get("company") or "").lower()
    for m in memory.get("meetings", []):
        linked_id      = m.get("linked_lead_id") or ""
        linked_company = (m.get("linked_company") or "").lower()
        if linked_id == lead_id or (company_name and company_name in linked_company):
            sentiment = m.get("sentiment") or "neutral"
            if sentiment == "positive":  score += 10
            elif sentiment == "negative":score -= 10
            break

    # Overdue tasks penalty ──────────────────────────
    overdue = 0
    for t in memory.get("tasks", []):
        deadline = t.get("deadline") or ""
        status   = t.get("status") or ""
        if deadline and isinstance(deadline, str) and deadline < today and status != "done":
            overdue += 1
    score -= min(overdue * 3, 15)

    return max(0, min(score, 99))