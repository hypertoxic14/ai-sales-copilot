from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.routers import (
    auth, assistant, leads, tasks,
    meetings, analytics, emails, calendar,
    funnel, battlecards, teams, manager
)

app = FastAPI(title="AI Sales Copilot API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000","http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router,        prefix="/api/auth",        tags=["Auth"])
app.include_router(assistant.router,   prefix="/api/assistant",   tags=["Assistant"])
app.include_router(leads.router,       prefix="/api/leads",       tags=["Leads"])
app.include_router(tasks.router,       prefix="/api/tasks",       tags=["Tasks"])
app.include_router(meetings.router,    prefix="/api/meetings",    tags=["Meetings"])
app.include_router(analytics.router,  prefix="/api/analytics",   tags=["Analytics"])
app.include_router(emails.router,      prefix="/api/emails",      tags=["Emails"])
app.include_router(calendar.router,    prefix="/api/calendar",    tags=["Calendar"])
app.include_router(funnel.router,      prefix="/api/funnel",      tags=["Funnel"])
app.include_router(battlecards.router, prefix="/api/battlecards", tags=["Battlecards"])
app.include_router(teams.router,       prefix="/api/teams",       tags=["Teams"])
app.include_router(manager.router,     prefix="/api/manager",     tags=["Manager"])

@app.get("/")
def health():
    return {"status": "ok", "service": "AI Sales Copilot"}