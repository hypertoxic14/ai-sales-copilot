from firebase_admin import firestore
from app.services.firebase_service import db
from datetime import datetime
import uuid

def get_user_memory(uid: str) -> dict:
    memory = {
        "leads":      [],
        "tasks":      [],
        "meetings":   [],
        "follow_ups": [],
        "emails":     [],
    }

    # Leads — fetch ALL fields explicitly
    leads_ref = db.collection("users").document(uid)\
                  .collection("leads").stream()
    memory["leads"] = []
    for l in leads_ref:
        ld = l.to_dict()
        # Ensure all fields present
        ld.setdefault("value", None)
        ld.setdefault("contact_name", "Unknown")
        ld.setdefault("email", None)
        ld.setdefault("phone", None)
        ld.setdefault("notes", None)
        ld.setdefault("last_contact", None)
        memory["leads"].append(ld)

    tasks = db.collection("users").document(uid)\
              .collection("tasks")\
              .where("status", "in", ["pending", "in_progress"])\
              .limit(20).stream()
    memory["tasks"] = [t.to_dict() for t in tasks]

    meetings = db.collection("users").document(uid)\
                 .collection("meetings").order_by(
                     "created_at", direction=firestore.Query.DESCENDING
                 ).limit(10).stream()
    memory["meetings"] = [m.to_dict() for m in meetings]

    followups = db.collection("users").document(uid)\
                  .collection("follow_ups")\
                  .where("status", "==", "pending")\
                  .limit(10).stream()
    memory["follow_ups"] = [f.to_dict() for f in followups]

    return memory


def save_lead(uid: str, lead_data: dict) -> dict:
    lead_id = str(uuid.uuid4())
    lead_data["id"]         = lead_id
    lead_data["created_at"] = datetime.utcnow().isoformat()
    lead_data["status"]     = lead_data.get("status", "lead")
    db.collection("users").document(uid)\
      .collection("leads").document(lead_id).set(lead_data)
    return lead_data


def save_task(uid: str, task_data: dict) -> dict:
    task_id = str(uuid.uuid4())
    task_data["id"]         = task_id
    task_data["created_at"] = datetime.utcnow().isoformat()
    task_data["status"]     = "pending"
    db.collection("users").document(uid)\
      .collection("tasks").document(task_id).set(task_data)
    return task_data


def update_task(uid: str, task_id: str, updates: dict):
    db.collection("users").document(uid)\
      .collection("tasks").document(task_id).update(updates)


def save_meeting(uid: str, meeting_data: dict) -> dict:
    meeting_id = str(uuid.uuid4())

    # Ensure all fields are Firestore-safe
    # Convert any nested objects to plain dicts
    action_items = []
    for item in meeting_data.get("action_items", []):
        action_items.append({
            "task":        str(item.get("task", "")),
            "assignee":    str(item.get("assignee", "") or ""),
            "deadline":    str(item.get("deadline", "") or ""),
            "priority":    str(item.get("priority", "medium")),
            "type":        str(item.get("type", "other")),
            "confidence":  float(item.get("confidence", 0.5)),
        })

    participants = []
    for p in meeting_data.get("participants", []):
        if isinstance(p, dict):
            participants.append({
                "name":  str(p.get("name", "")),
                "email": str(p.get("email", "") or "")
            })
        else:
            participants.append({"name": str(p), "email": ""})

    doc = {
        "id":                  meeting_id,
        "title":               str(meeting_data.get("title", "Untitled")),
        "transcript":          str(meeting_data.get("transcript", "")),
        "summary":             str(meeting_data.get("summary", "")),
        "action_items":        action_items,
        "participants":        participants,
        "language":            str(meeting_data.get("language", "en")),
        "duration_seconds":    float(meeting_data.get("duration", 0)),
        "meeting_context":     str(meeting_data.get("meeting_context", "unknown")),
        "suggested_stage":     str(meeting_data.get("suggested_stage", "") or ""),
        "context_confidence":  float(meeting_data.get("context_confidence", 0)),
        "linked_lead_id":      str(meeting_data.get("linked_lead_id", "") or ""),
        "linked_company":      str(meeting_data.get("linked_company", "") or ""),
        "objections":          meeting_data.get("objections", []),
        "requirements":        meeting_data.get("requirements", []),
        "next_steps":          meeting_data.get("next_steps", []),
        "sentiment":           str(meeting_data.get("sentiment", "neutral")),
        "created_at":          datetime.utcnow().isoformat(),
        "status":              "processed"
    }

    db.collection("users").document(uid)\
      .collection("meetings").document(meeting_id).set(doc)

    return doc


def save_follow_up(uid: str, follow_up_data: dict) -> dict:
    fid = str(uuid.uuid4())
    follow_up_data["id"]         = fid
    follow_up_data["created_at"] = datetime.utcnow().isoformat()
    follow_up_data["status"]     = "pending"
    db.collection("users").document(uid)\
      .collection("follow_ups").document(fid).set(follow_up_data)
    return follow_up_data


def get_chat_history(uid: str, limit: int = 20) -> list:
    msgs = db.collection("users").document(uid)\
             .collection("chat_history").order_by(
                 "timestamp", direction=firestore.Query.DESCENDING
             ).limit(limit).stream()
    history = [m.to_dict() for m in msgs]
    return list(reversed(history))


def save_chat_message(uid: str, role: str, content: str):
    msg_id = str(uuid.uuid4())
    db.collection("users").document(uid)\
      .collection("chat_history").document(msg_id).set({
          "id":        msg_id,
          "role":      role,
          "content":   content,
          "timestamp": datetime.utcnow().isoformat()
      })