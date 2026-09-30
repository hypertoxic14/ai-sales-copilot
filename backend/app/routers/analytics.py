from fastapi import APIRouter, HTTPException, Header
from app.services.firebase_service import verify_token, db
from firebase_admin import firestore
from datetime import datetime, date

router = APIRouter()

def get_uid(authorization: str):
    try:
        token   = authorization.replace("Bearer ", "")
        decoded = verify_token(token)
        return decoded["uid"]
    except Exception as e:
        raise HTTPException(status_code=401, detail=str(e))

@router.get("/summary")
def get_analytics(authorization: str = Header(...)):
    uid = get_uid(authorization)
    today = date.today().isoformat()

    # Fetch all user data
    leads = [l.to_dict() for l in
             db.collection("users").document(uid)
               .collection("leads").stream()]

    tasks = [t.to_dict() for t in
             db.collection("users").document(uid)
               .collection("tasks").stream()]

    meetings = [m.to_dict() for m in
                db.collection("users").document(uid)
                  .collection("meetings").stream()]

    followups = [f.to_dict() for f in
                 db.collection("users").document(uid)
                   .collection("follow_ups").stream()]

    # Pipeline stats
    pipeline_value  = sum(l.get("value") or 0 for l in leads)
    closed_value    = sum(
        l.get("value") or 0 for l in leads
        if l.get("stage") == "closed_won"
    )
    stage_breakdown = {}
    for l in leads:
        s = l.get("stage", "lead")
        stage_breakdown[s] = stage_breakdown.get(s, 0) + 1

    # Task stats
    total_tasks     = len(tasks)
    done_tasks      = sum(1 for t in tasks if t.get("status") == "done")
    overdue_tasks   = sum(
        1 for t in tasks
        if t.get("deadline","") < today
        and t.get("status") not in ["done"]
        and t.get("deadline")
    )
    completion_rate = round(
        (done_tasks / total_tasks * 100) if total_tasks else 0
    )

    # Follow-up stats
    overdue_followups = sum(
        1 for f in followups
        if f.get("due_date","") < today
        and f.get("status") == "pending"
        and f.get("due_date")
    )

    # Activity by day (last 7 days)
    from collections import defaultdict
    daily_tasks = defaultdict(int)
    for t in tasks:
        created = t.get("created_at","")[:10]
        if created:
            daily_tasks[created] += 1

    return {
        "pipeline": {
            "total_leads":      len(leads),
            "pipeline_value":   pipeline_value,
            "closed_value":     closed_value,
            "stage_breakdown":  stage_breakdown,
            "win_rate": round(
                stage_breakdown.get("closed_won", 0) /
                len(leads) * 100
            ) if leads else 0,
        },
        "tasks": {
            "total":           total_tasks,
            "done":            done_tasks,
            "overdue":         overdue_tasks,
            "completion_rate": completion_rate,
        },
        "meetings": {
            "total": len(meetings),
        },
        "follow_ups": {
            "total":   len(followups),
            "overdue": overdue_followups,
        },
        "daily_tasks": dict(daily_tasks),
    }