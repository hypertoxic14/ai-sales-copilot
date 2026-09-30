from pydantic import BaseModel
from typing import Optional
from datetime import datetime

class UserProfile(BaseModel):
    uid:   str
    name:  str
    email: str
    role:  str = "rep"

class Lead(BaseModel):
    company:      str
    contact_name: str
    email:        Optional[str] = None
    phone:        Optional[str] = None
    stage:        str = "lead"
    last_contact: Optional[str] = None
    notes:        Optional[str] = None
    value:        Optional[float] = None

class Task(BaseModel):
    task:     str
    deadline: Optional[str] = None
    priority: str = "medium"
    lead_id:  Optional[str] = None
    assignee: Optional[str] = None