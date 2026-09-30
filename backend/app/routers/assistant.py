from fastapi import APIRouter, HTTPException, Header
from pydantic import BaseModel
from app.services.firebase_service import verify_token, get_user_profile
from app.services.assistant_service import chat
from app.services.memory_service import get_chat_history

router = APIRouter()

class ChatRequest(BaseModel):
    message: str

def get_uid_and_profile(authorization: str):
    try:
        token   = authorization.replace("Bearer ", "")
        decoded = verify_token(token)
        uid     = decoded["uid"]
        profile = get_user_profile(uid)
        if not profile:
            raise HTTPException(status_code=404, detail="Profile not found")
        return uid, profile
    except ValueError as e:
        raise HTTPException(status_code=401, detail=str(e))

@router.post("/chat")
def chat_with_assistant(
    req: ChatRequest,
    authorization: str = Header(...)
):
    """Main chat endpoint — fully personalised per user."""
    uid, profile = get_uid_and_profile(authorization)
    result = chat(uid, profile, req.message)
    return result

@router.get("/history")
def get_history(authorization: str = Header(...)):
    """Get this user's chat history."""
    uid, _ = get_uid_and_profile(authorization)
    return get_chat_history(uid, limit=50)

@router.get("/nudges")
def get_nudges(authorization: str = Header(...)):
    """Get proactive nudges for this user."""
    uid, profile = get_uid_and_profile(authorization)
    from app.services.memory_service import get_user_memory
    from app.services.assistant_service import _detect_nudges
    memory = get_user_memory(uid)
    return {"nudges": _detect_nudges(memory)}