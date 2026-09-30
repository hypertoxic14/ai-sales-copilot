from fastapi import APIRouter, HTTPException, Header
from pydantic import BaseModel
from typing import Optional
from app.services.firebase_service import verify_token, db
from firebase_admin import firestore
from datetime import datetime
import uuid

router = APIRouter()

class EventCreate(BaseModel):
    title:       str
    date:        str        # YYYY-MM-DD
    time:        Optional[str] = None   # HH:MM
    end_time:    Optional[str] = None
    type:        str = "meeting"        # meeting | task | follow_up | call | other
    description: Optional[str] = None
    lead_id:     Optional[str] = None
    company:     Optional[str] = None
    color:       Optional[str] = None

class EventUpdate(BaseModel):
    title:       Optional[str] = None
    date:        Optional[str] = None
    time:        Optional[str] = None
    end_time:    Optional[str] = None
    description: Optional[str] = None
    type:        Optional[str] = None

def get_uid(authorization: str):
    try:
        token   = authorization.replace("Bearer ", "")
        decoded = verify_token(token)
        return decoded["uid"]
    except Exception as e:
        raise HTTPException(status_code=401, detail=str(e))

TYPE_COLORS = {
    "meeting":   "0078D4",
    "task":      "DC2626",
    "follow_up": "D97706",
    "call":      "16A34A",
    "deadline":  "DC2626",
    "other":     "6366F1",
}

@router.get("/")
def list_events(
    month: Optional[str] = None,  # YYYY-MM
    authorization: str = Header(...)
):
    uid  = get_uid(authorization)
    ref  = db.collection("users").document(uid).collection("events")

    if month:
        start = f"{month}-01"
        year, m = month.split("-")
        end_m = int(m) + 1
        end_y = int(year)
        if end_m > 12:
            end_m = 1
            end_y += 1
        end = f"{end_y}-{str(end_m).zfill(2)}-01"
        docs = ref.where("date", ">=", start)\
                  .where("date", "<",  end).stream()
    else:
        docs = ref.order_by(
            "date", direction=firestore.Query.ASCENDING
        ).stream()

    return [d.to_dict() for d in docs]


@router.post("/")
def create_event(
    event: EventCreate,
    authorization: str = Header(...)
):
    uid      = get_uid(authorization)
    event_id = str(uuid.uuid4())
    color    = event.color or TYPE_COLORS.get(event.type, "6366F1")

    doc = {
        "id":          event_id,
        "title":       event.title,
        "date":        event.date,
        "time":        event.time or "",
        "end_time":    event.end_time or "",
        "type":        event.type,
        "description": event.description or "",
        "lead_id":     event.lead_id or "",
        "company":     event.company or "",
        "color":       color,
        "source":      "manual",
        "created_at":  datetime.utcnow().isoformat()
    }

    db.collection("users").document(uid)\
      .collection("events").document(event_id).set(doc)

    return doc


@router.patch("/{event_id}")
def update_event(
    event_id:      str,
    update:        EventUpdate,
    authorization: str = Header(...)
):
    uid     = get_uid(authorization)
    updates = {
        k: v for k, v in update.model_dump().items()
        if v is not None
    }
    updates["updated_at"] = datetime.utcnow().isoformat()

    db.collection("users").document(uid)\
      .collection("events").document(event_id).update(updates)

    doc = db.collection("users").document(uid)\
            .collection("events").document(event_id).get()
    return doc.to_dict()


@router.delete("/{event_id}")
def delete_event(
    event_id:      str,
    authorization: str = Header(...)
):
    uid = get_uid(authorization)
    db.collection("users").document(uid)\
      .collection("events").document(event_id).delete()
    return {"message": "Event deleted"}


@router.post("/sync-tasks")
def sync_tasks_to_calendar(authorization: str = Header(...)):
    uid = get_uid(authorization)

    # Get ALL existing event task_ids to avoid duplicates
    existing = db.collection("users").document(uid)\
                 .collection("events")\
                 .where("source", "==", "task_sync").stream()
    synced_task_ids = {
        e.to_dict().get("task_id","")
        for e in existing
    }

    # Also get deadline events created by AI chat
    ai_events = db.collection("users").document(uid)\
                  .collection("events")\
                  .where("source", "==", "ai_chat").stream()
    ai_titles = {
        e.to_dict().get("title","").lower()
        for e in ai_events
    }

    # Get all tasks with deadlines — any status
    tasks = db.collection("users").document(uid)\
              .collection("tasks").stream()

    created = 0
    for t in tasks:
        task = t.to_dict()
        if not task.get("deadline"):
            continue
        if task["id"] in synced_task_ids:
            continue
        if task.get("status") == "done":
            continue

        event_id = str(uuid.uuid4())
        db.collection("users").document(uid)\
          .collection("events").document(event_id).set({
              "id":          event_id,
              "title":       task["task"],
              "date":        task["deadline"],
              "time":        "",
              "end_time":    "",
              "type":        "deadline",
              "description": f"Task: {task['task']}",
              "lead_id":     task.get("lead_id",""),
              "company":     "",
              "color":       TYPE_COLORS["deadline"],
              "source":      "task_sync",
              "task_id":     task["id"],
              "priority":    task.get("priority","medium"),
              "created_at":  datetime.utcnow().isoformat()
          })
        created += 1

    return {"synced": created}