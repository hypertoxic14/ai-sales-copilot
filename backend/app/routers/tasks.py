from fastapi import APIRouter, HTTPException, Header
from pydantic import BaseModel
from typing import Optional
from app.services.firebase_service import verify_token, db
from app.services.memory_service import save_task, update_task
from firebase_admin import firestore
from datetime import datetime

router = APIRouter()

class TaskCreate(BaseModel):
    task:     str
    deadline: Optional[str] = None
    priority: str = "medium"
    lead_id:  Optional[str] = None
    type:     str = "other"

class TaskUpdate(BaseModel):
    status:   Optional[str] = None
    deadline: Optional[str] = None
    priority: Optional[str] = None
    notes:    Optional[str] = None

def get_uid(authorization: str):
    try:
        token   = authorization.replace("Bearer ", "")
        decoded = verify_token(token)
        return decoded["uid"]
    except Exception as e:
        raise HTTPException(status_code=401, detail=str(e))

@router.get("/")
def list_tasks(authorization: str = Header(...)):
    uid  = get_uid(authorization)
    docs = db.collection("users").document(uid)\
             .collection("tasks").order_by(
                 "created_at",
                 direction=firestore.Query.DESCENDING
             ).stream()
    return [d.to_dict() for d in docs]

@router.post("/")
def create_task(
    task: TaskCreate,
    authorization: str = Header(...)
):
    uid  = get_uid(authorization)
    data = task.model_dump()
    return save_task(uid, data)

@router.patch("/{task_id}")
def patch_task(
    task_id: str,
    update: TaskUpdate,
    authorization: str = Header(...)
):
    uid     = get_uid(authorization)
    updates = {k: v for k, v in update.model_dump().items()
               if v is not None}
    updates["updated_at"] = datetime.utcnow().isoformat()
    update_task(uid, task_id, updates)
    doc = db.collection("users").document(uid)\
            .collection("tasks").document(task_id).get()
    return doc.to_dict()

@router.delete("/{task_id}")
def delete_task(
    task_id: str,
    authorization: str = Header(...)
):
    uid = get_uid(authorization)
    db.collection("users").document(uid)\
      .collection("tasks").document(task_id).delete()
    return {"message": "Task deleted"}