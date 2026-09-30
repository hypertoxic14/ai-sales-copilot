from fastapi import APIRouter, HTTPException, Header
from pydantic import BaseModel
from typing import Optional
from app.services.firebase_service import verify_token, get_user_profile
from app.services.memory_service import save_lead, get_user_memory
from firebase_admin import firestore
from app.services.firebase_service import db
import uuid
from datetime import datetime

router = APIRouter()

class LeadCreate(BaseModel):
    company:      str
    contact_name: str
    email:        Optional[str] = None
    phone:        Optional[str] = None
    stage:        str = "lead"
    value:        Optional[float] = None
    notes:        Optional[str] = None

class LeadUpdate(BaseModel):
    stage:        Optional[str] = None
    notes:        Optional[str] = None
    last_contact: Optional[str] = None
    value:        Optional[float] = None

def get_uid(authorization: str):
    try:
        token   = authorization.replace("Bearer ", "")
        decoded = verify_token(token)
        return decoded["uid"]
    except Exception as e:
        raise HTTPException(status_code=401, detail=str(e))

@router.get("/")
def list_leads(authorization: str = Header(...)):
    uid   = get_uid(authorization)
    leads = db.collection("users").document(uid)\
              .collection("leads").stream()
    all_leads = [l.to_dict() for l in leads]

    # Add win probability to each lead
    from app.services.assistant_service import calculate_win_probability
    from app.services.memory_service import get_user_memory
    memory = get_user_memory(uid)

    for lead in all_leads:
        lead["win_probability"] = calculate_win_probability(lead, memory)

    return all_leads

@router.post("/")
def create_lead(
    lead: LeadCreate,
    authorization: str = Header(...)
):
    uid  = get_uid(authorization)
    data = lead.model_dump()
    return save_lead(uid, data)

@router.patch("/{lead_id}")
def update_lead(
    lead_id: str,
    update: LeadUpdate,
    authorization: str = Header(...)
):
    uid     = get_uid(authorization)
    updates = {k: v for k, v in update.model_dump().items() if v is not None}
    updates["updated_at"] = datetime.utcnow().isoformat()
    db.collection("users").document(uid)\
      .collection("leads").document(lead_id).update(updates)
    doc = db.collection("users").document(uid)\
            .collection("leads").document(lead_id).get()
    return doc.to_dict()

@router.delete("/{lead_id}")
def delete_lead(
    lead_id: str,
    authorization: str = Header(...)
):
    uid = get_uid(authorization)
    db.collection("users").document(uid)\
      .collection("leads").document(lead_id).delete()
    return {"message": "Lead deleted"}