from fastapi import APIRouter, HTTPException, Header
from pydantic import BaseModel
from typing import List, Optional
from app.services.firebase_service import verify_token, db
from firebase_admin import firestore, auth as fb_auth
from datetime import datetime
import uuid

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

def require_role(uid: str, allowed: list):
    profile = get_profile(uid)
    if profile.get("role") not in allowed:
        raise HTTPException(
            status_code=403,
            detail=f"Access denied. Required role: {allowed}"
        )
    return profile


class TeamCreate(BaseModel):
    name: str

class TeamAddMember(BaseModel):
    email: str

class TeamRemoveMember(BaseModel):
    member_uid: str


# ── Create team ───────────────────────────────────────────
@router.post("/")
def create_team(
    data: TeamCreate,
    authorization: str = Header(...)
):
    uid     = get_uid(authorization)
    profile = require_role(uid, ["manager","admin"])

    # Check if manager already has a team
    existing = db.collection("teams")\
                 .where("manager_uid","==",uid).stream()
    for _ in existing:
        raise HTTPException(
            status_code=400,
            detail="You already have a team. Update it instead."
        )

    team_id = str(uuid.uuid4())
    team    = {
        "id":          team_id,
        "name":        data.name,
        "manager_uid": uid,
        "manager_name":profile.get("name","Manager"),
        "members":     [],
        "created_at":  datetime.utcnow().isoformat()
    }
    db.collection("teams").document(team_id).set(team)

    # Save team_id to manager's profile
    db.collection("users").document(uid)\
      .update({"team_id": team_id})

    return team


# ── Get my team ───────────────────────────────────────────
@router.get("/my-team")
def get_my_team(authorization: str = Header(...)):
    uid = get_uid(authorization)
    profile = get_profile(uid)

    # Admin sees all teams
    if profile.get("role") == "admin":
        docs  = db.collection("teams").stream()
        teams = [d.to_dict() for d in docs]
        return {"teams": teams, "role": "admin"}

    # Manager sees their team
    if profile.get("role") in ["manager","closer"]:
        docs = db.collection("teams")\
                 .where("manager_uid","==",uid).stream()
        teams = [d.to_dict() for d in docs]
        if not teams:
            return {"teams": [], "role": profile.get("role"), "has_team": False}
        return {"teams": teams, "role": profile.get("role"), "has_team": True}

    # Rep sees the team they belong to
    team_id = profile.get("team_id")
    if team_id:
        doc = db.collection("teams").document(team_id).get()
        if doc.exists:
            return {"teams": [doc.to_dict()], "role": "rep"}
    return {"teams": [], "role": "rep"}


# ── Add member by email ───────────────────────────────────
@router.post("/{team_id}/add-member")
def add_member(
    team_id: str,
    data:    TeamAddMember,
    authorization: str = Header(...)
):
    uid = get_uid(authorization)
    require_role(uid, ["manager","admin"])

    # Get team
    team_doc = db.collection("teams").document(team_id).get()
    if not team_doc.exists:
        raise HTTPException(status_code=404, detail="Team not found")
    team = team_doc.to_dict()

    # Only manager of this team or admin can add
    profile = get_profile(uid)
    if profile.get("role") != "admin" and team["manager_uid"] != uid:
        raise HTTPException(status_code=403, detail="Not your team")

    # Find user by email in Firestore
    users = db.collection("users")\
              .where("email","==",data.email.lower().strip()).stream()
    member = None
    for u in users:
        member = u.to_dict()
        break

    if not member:
        raise HTTPException(
            status_code=404,
            detail=f"No user found with email {data.email}. They must register first."
        )

    member_uid = member["uid"]

    if member_uid in team["members"]:
        raise HTTPException(status_code=400, detail="User already in team")

    if member_uid == uid:
        raise HTTPException(status_code=400, detail="Cannot add yourself")

    # Add to team
    db.collection("teams").document(team_id)\
      .update({"members": firestore.ArrayUnion([member_uid])})

    # Save team_id to member's profile
    db.collection("users").document(member_uid)\
      .update({"team_id": team_id})

    return {
        "message":     f"{member['name']} added to team",
        "member_name": member["name"],
        "member_uid":  member_uid
    }


# ── Remove member ─────────────────────────────────────────
@router.post("/{team_id}/remove-member")
def remove_member(
    team_id: str,
    data:    TeamRemoveMember,
    authorization: str = Header(...)
):
    uid = get_uid(authorization)
    require_role(uid, ["manager","admin"])

    team_doc = db.collection("teams").document(team_id).get()
    if not team_doc.exists:
        raise HTTPException(status_code=404, detail="Team not found")

    db.collection("teams").document(team_id)\
      .update({"members": firestore.ArrayRemove([data.member_uid])})

    db.collection("users").document(data.member_uid)\
      .update({"team_id": firestore.DELETE_FIELD})

    return {"message": "Member removed"}