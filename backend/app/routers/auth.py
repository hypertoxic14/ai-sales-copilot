from fastapi import APIRouter, HTTPException, Header
from app.services.firebase_service import verify_token, get_user_profile

router = APIRouter()

@router.get("/me")
def get_me(authorization: str = Header(...)):
    """Verify token and return user profile."""
    try:
        token   = authorization.replace("Bearer ", "")
        decoded = verify_token(token)
        uid     = decoded["uid"]
        profile = get_user_profile(uid)
        if not profile:
            raise HTTPException(status_code=404, detail="User profile not found")
        return profile
    except ValueError as e:
        raise HTTPException(status_code=401, detail=str(e))