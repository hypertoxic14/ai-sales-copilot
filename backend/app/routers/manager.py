from fastapi import APIRouter, HTTPException, Header
from pydantic import BaseModel
from typing import Optional
from app.services.firebase_service import verify_token, db
from app.services.assistant_service import calculate_win_probability
from firebase_admin import firestore
from datetime import datetime

router = APIRouter()

def get_uid(authorization: str):
    try:
        token   = authorization.replace("Bearer ", "")
        decoded = verify_token(token)
        return decoded["uid"]
    except Exception as e:
        raise HTTPException(status_code=401, detail=str(e))

def get_profile(uid: str) -> dict:
    doc = db.collection("users").document(uid).get()
    return doc.to_dict() if doc.exists else {}

def get_team_member_uids(uid: str, profile: dict) -> list:
    """Return list of UIDs this manager/admin can see."""
    role = profile.get("role","rep")

    if role == "admin":
        # Admin sees everyone
        all_users = db.collection("users").stream()
        return [u.to_dict()["uid"] for u in all_users if u.to_dict().get("uid")]

    if role in ["manager","closer"]:
        # Manager sees their team members + themselves
        teams = db.collection("teams")\
                  .where("manager_uid","==",uid).stream()
        member_uids = [uid]  # include self
        for t in teams:
            member_uids.extend(t.to_dict().get("members",[]))
        return list(set(member_uids))

    return [uid]  # rep sees only themselves


def get_user_data(uid: str) -> dict:
    """Fetch all data for a single user."""
    profile = get_profile(uid)

    leads = [l.to_dict() for l in
             db.collection("users").document(uid)
               .collection("leads").stream()]
    tasks = [t.to_dict() for t in
             db.collection("users").document(uid)
               .collection("tasks").stream()]
    meetings = [m.to_dict() for m in
                db.collection("users").document(uid)
                  .collection("meetings").order_by(
                      "created_at",
                      direction=firestore.Query.DESCENDING
                  ).limit(10).stream()]

    today = datetime.utcnow().isoformat()[:10]

    return {
        "uid":          uid,
        "name":         profile.get("name","Unknown"),
        "email":        profile.get("email",""),
        "role":         profile.get("role","rep"),
        "leads":        leads,
        "tasks":        tasks,
        "meetings":     meetings,
        "pipeline_value": sum(
            l.get("value") or 0 for l in leads
            if l.get("stage") not in ["closed_won","closed_lost"]
        ),
        "closed_value": sum(
            l.get("value") or 0 for l in leads
            if l.get("stage") == "closed_won"
        ),
        "total_leads":  len(leads),
        "active_leads": len([
            l for l in leads
            if l.get("stage") not in ["closed_won","closed_lost"]
        ]),
        "total_tasks":     len(tasks),
        "done_tasks":      len([t for t in tasks if t.get("status") == "done"]),
        "overdue_tasks":   len([
            t for t in tasks
            if (t.get("deadline") or "") < today
            and t.get("status") not in ["done"]
            and t.get("deadline")
        ]),
        "meetings_count": len(meetings),
        "completion_rate": round(
            len([t for t in tasks if t.get("status") == "done"]) /
            len(tasks) * 100
        ) if tasks else 0
    }


@router.get("/team-overview")
def get_team_overview(authorization: str = Header(...)):
    """
    Returns overview of all team members for manager/admin.
    """
    uid     = get_uid(authorization)
    profile = get_profile(uid)

    if profile.get("role") not in ["manager","admin","closer"]:
        raise HTTPException(
            status_code=403,
            detail="Only managers and admins can view team overview"
        )

    member_uids = get_team_member_uids(uid, profile)
    members     = []
    for muid in member_uids:
        try:
            data = get_user_data(muid)
            members.append(data)
        except Exception as e:
            print(f"Error fetching data for {muid}: {e}")

    # Sort by pipeline value descending
    members.sort(key=lambda x: x["pipeline_value"], reverse=True)

    return {
        "members":        members,
        "total_members":  len(members),
        "team_pipeline":  sum(m["pipeline_value"] for m in members),
        "team_closed":    sum(m["closed_value"]   for m in members),
        "total_overdue":  sum(m["overdue_tasks"]  for m in members),
        "total_leads":    sum(m["total_leads"]    for m in members),
        "total_meetings": sum(m["meetings_count"] for m in members),
    }


@router.get("/team-leads")
def get_team_leads(authorization: str = Header(...)):
    """All leads across the team — for pipeline view."""
    uid     = get_uid(authorization)
    profile = get_profile(uid)

    if profile.get("role") not in ["manager","admin","closer"]:
        raise HTTPException(status_code=403, detail="Access denied")

    member_uids = get_team_member_uids(uid, profile)
    all_leads   = []
    memory_stub = {"meetings":[], "tasks":[]}

    for muid in member_uids:
        mprofile = get_profile(muid)
        leads    = db.collection("users").document(muid)\
                     .collection("leads").stream()
        for l in leads:
            ld = l.to_dict()
            ld["_owner_uid"]  = muid
            ld["_owner_name"] = mprofile.get("name","Unknown")
            ld["win_probability"] = calculate_win_probability(ld, memory_stub)
            all_leads.append(ld)

    return all_leads


@router.patch("/rep-lead/{rep_uid}/{lead_id}")
def update_rep_lead(
    rep_uid: str,
    lead_id: str,
    update:  dict,
    authorization: str = Header(...)
):
    """Manager updates a lead belonging to a rep."""
    uid     = get_uid(authorization)
    profile = get_profile(uid)

    if profile.get("role") not in ["manager","admin"]:
        raise HTTPException(status_code=403, detail="Access denied")

    # Verify rep is in manager's team
    member_uids = get_team_member_uids(uid, profile)
    if rep_uid not in member_uids:
        raise HTTPException(status_code=403, detail="Rep not in your team")

    ALLOWED = {
        "stage","value","notes","last_contact",
        "email","phone","contact_name"
    }
    updates = {k:v for k,v in update.items() if k in ALLOWED}
    updates["updated_at"] = datetime.utcnow().isoformat()
    updates["_updated_by_manager"] = uid

    db.collection("users").document(rep_uid)\
      .collection("leads").document(lead_id)\
      .update(updates)

    return {"message": "Lead updated"}


@router.patch("/rep-task/{rep_uid}/{task_id}")
def update_rep_task(
    rep_uid: str,
    task_id: str,
    update:  dict,
    authorization: str = Header(...)
):
    """Manager updates a task belonging to a rep."""
    uid     = get_uid(authorization)
    profile = get_profile(uid)

    if profile.get("role") not in ["manager","admin"]:
        raise HTTPException(status_code=403, detail="Access denied")

    member_uids = get_team_member_uids(uid, profile)
    if rep_uid not in member_uids:
        raise HTTPException(status_code=403, detail="Rep not in your team")

    ALLOWED = {"status","priority","deadline","notes"}
    updates = {k:v for k,v in update.items() if k in ALLOWED}
    updates["updated_at"] = datetime.utcnow().isoformat()

    db.collection("users").document(rep_uid)\
      .collection("tasks").document(task_id)\
      .update(updates)

    return {"message": "Task updated"}