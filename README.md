# AI-Powered Sales Copilot & CRM Intelligence Platform

> An AI-first CRM where the pipeline updates itself — built with React, FastAPI, Firebase, Groq LLM, and Faster Whisper.

## What it does

Upload a sales meeting recording → the AI transcribes it, extracts action items, detects objections, updates the pipeline, generates Minutes of Meeting, and answers questions about it forever.

## Key Features

| Feature | Technology |
|---|---|
|  Meeting transcription | Faster Whisper (local, CPU) |
|  AI assistant with memory | Groq llama-3.3-70b + RAG |
|  Pipeline auto-update | Firebase Firestore |
|  Battlecard generator | Tavily web search + LLM |
|  Auto MOM PDF | ReportLab |
|  Funnel Sheet Excel | OpenPyXL |
|  Calendar + task sync | Firebase + React |
|  Manager team dashboard | Multi-user Firebase isolation |
|  Email generation | Gmail SMTP + LLM ghostwriter |

## Tech Stack

**Frontend:** React 18, React Router v6, Axios, Lucide React  
**Backend:** FastAPI (Python), Uvicorn  
**AI:** Groq API (llama-3.3-70b), Faster Whisper, Tavily  
**Database:** Firebase Firestore  
**Auth:** Firebase Authentication  

## Setup

### Backend
```bash
cd backend
pip install fastapi uvicorn python-multipart python-dotenv firebase-admin groq faster-whisper tavily-python reportlab openpyxl
# Add firebase_key.json and .env (see .env.example)
python -m uvicorn app.main:app --reload --port 8000
```

### Frontend
```bash
cd frontend
npm install
# Add .env with Firebase config
npm start
```

### Environment Variables

**backend/.env**

GROQ_API_KEY=your_groq_key
TAVILY_API_KEY=your_tavily_key
SMTP_EMAIL=your_gmail
SMTP_PASSWORD=your_app_password
FIREBASE_KEY_PATH=firebase_key.json


**frontend/.env**

REACT_APP_FIREBASE_API_KEY=...
REACT_APP_FIREBASE_AUTH_DOMAIN=...
REACT_APP_FIREBASE_PROJECT_ID=...


## Architecture

React Frontend (port 3000)
↓
FastAPI Backend (port 8000) ←→ Groq LLM
↓ ←→ Faster Whisper (local)
Firebase Firestore ←→ Tavily Web Search
Firebase Auth ←→ Gmail SMTP


## Project Structure

ai-sales-copilot/
├── backend/
│ ├── app/
│ │ ├── routers/ # 12 API routers
│ │ └── services/ # AI, RAG, email, research services
│ └── main.py
└── frontend/
└── src/
├── pages/ # 10 pages
├── components/ # Layout, Sidebar, Topbar
└── services/ # API, Firebase, Auth

## Screenshots
![Ai Assistant(chatbot)](image.png)
![Auto updated task Sheet](image-1.png)
![auto updated funnel sheet](image-2.png)
![pipeline visability](image-3.png)
![meeting summary](image-4.png)
![MOM generation](image-5.png)
![battlecard genration -1](image-6.png)
![battlecard genration -2](image-7.png)
![manager view](image-8.png)
![adding menbers to team](image-9.png)