from fastapi import APIRouter, HTTPException, Header
from pydantic import BaseModel
from app.services.firebase_service import verify_token, db
from app.services.research_service import research_company, _is_configured
from groq import Groq
from dotenv import load_dotenv
from pathlib import Path
from datetime import datetime
import os, json, re, uuid

load_dotenv(Path(__file__).resolve().parents[2] / ".env")
client = Groq(api_key=os.getenv("GROQ_API_KEY"))

router = APIRouter()

def get_uid(authorization: str):
    try:
        token   = authorization.replace("Bearer ", "")
        decoded = verify_token(token)
        return decoded["uid"]
    except Exception as e:
        raise HTTPException(status_code=401, detail=str(e))


class ProductKnowledge(BaseModel):
    content: str

class BattlecardRequest(BaseModel):
    company: str
    lead_id: str = ""


@router.post("/product-knowledge")
def save_product_knowledge(
    data: ProductKnowledge,
    authorization: str = Header(...)
):
    """Save the user's product info — used to generate battlecards."""
    uid = get_uid(authorization)
    db.collection("users").document(uid).collection("settings")\
      .document("product_knowledge").set({
          "content":    data.content,
          "updated_at": datetime.utcnow().isoformat()
      })
    return {"message": "Product knowledge saved"}


@router.get("/product-knowledge")
def get_product_knowledge(authorization: str = Header(...)):
    uid = get_uid(authorization)
    doc = db.collection("users").document(uid).collection("settings")\
            .document("product_knowledge").get()
    if doc.exists:
        return doc.to_dict()
    return {"content": ""}


@router.get("/research-status")
def research_status(authorization: str = Header(...)):
    get_uid(authorization)
    return {"configured": _is_configured()}


@router.post("/generate")
def generate_battlecard(
    req: BattlecardRequest,
    authorization: str = Header(...)
):
    """
    Generate a battlecard for a company:
    1. Research company via Tavily
    2. Pull user's product knowledge
    3. LLM combines both into talking points, questions, battlecard
    """
    uid = get_uid(authorization)

    # Step 1: Web research
    research = research_company(req.company)
    if not research["success"] and "not configured" in research.get("message",""):
        raise HTTPException(status_code=400, detail=research["message"])

    # Step 2: Get product knowledge
    pk_doc = db.collection("users").document(uid).collection("settings")\
                .document("product_knowledge").get()
    product_knowledge = pk_doc.to_dict().get("content","") if pk_doc.exists else ""

    if not product_knowledge:
        raise HTTPException(
            status_code=400,
            detail="No product knowledge found. Add your product info in Settings first."
        )

    # Step 3: Get any existing meeting history for this company
    meetings = db.collection("users").document(uid).collection("meetings").stream()
    company_lower = req.company.lower()
    past_context = []
    for m in meetings:
        md = m.to_dict()
        if company_lower in (md.get("linked_company","") or "").lower():
            past_context.append(md.get("summary",""))

    # Step 4: Build research summary
    research_text = ""
    if research["success"]:
        research_text = research.get("answer","") + "\n\n"
        for r in research["results"][:4]:
            research_text += f"- {r['title']}: {r['content'][:200]}\n"
    else:
        research_text = "No web research available — generate based on general knowledge."

    # Step 5: LLM generates battlecard
    system = """You are a sales enablement expert. Generate a complete battlecard
for a sales rep preparing to meet with a prospect company.
Return ONLY valid JSON matching this exact structure:
{
  "company_snapshot": {
    "what_they_do": "1-2 sentences",
    "size": "employee count / revenue if known, else 'Unknown'",
    "industry": "their industry",
    "headquarters": "city, country if known, else 'Unknown'"
  },
  "recent_news": ["news item 1", "news item 2"],
  "their_products": {
    "core_offerings": ["offering 1", "offering 2"],
    "key_features": ["feature 1", "feature 2"],
    "pricing_notes": "public pricing info if known, else 'Not publicly available'"
  },
  "competitor_analysis": [
    {
      "competitor": "name of a tool/vendor this company might currently use or compare against",
      "strengths": "what that competitor does well",
      "weaknesses": "where that competitor falls short",
      "our_differentiator": "how our product wins against this specific competitor"
    }
  ],
  "objection_prep": [
    {"likely_objection": "objection", "suggested_response": "response"}
  ],
  "probing_questions": ["question 1", "question 2", "question 3", "question 4", "question 5"],
  "talk_tracks": {
    "elevator_pitch": "30-second pitch tailored to this company",
    "value_propositions": ["value prop 1", "value prop 2", "value prop 3"],
    "key_messaging": ["message 1", "message 2"]
  },
  "landmines": ["situation where competitor/status quo is genuinely stronger and rep should not oversell"]
}

Be honest in landmines and competitor weaknesses — do not always make our product look superior.
If information is not available from research, say so rather than inventing facts."""

    user = f"""
Company: {req.company}

Web research findings:
{research_text}

Our product/service info:
{product_knowledge[:1500]}

Past meeting history with this company:
{chr(10).join(past_context[:3]) if past_context else "No prior meetings."}

Generate a complete battlecard. For competitor_analysis, infer 2-3 likely
competing solutions in this space based on the company's industry and our
product category — even if not explicitly mentioned in research, use
reasonable domain knowledge, but flag inferred items by keeping the
analysis general rather than inventing specific false facts.
"""

    try:
        res = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role":"system","content":system},
                {"role":"user",  "content":user}
            ],
            temperature=0.3,
            max_tokens=1200
        )
        raw = res.choices[0].message.content.strip()
        raw = re.sub(r"^```(?:json)?\s*","",raw)
        raw = re.sub(r"\s*```$","",raw)
        battlecard = json.loads(raw)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Battlecard generation failed: {str(e)}")

    # Save battlecard
    bc_id = str(uuid.uuid4())
    doc = {
        "id":         bc_id,
        "company":    req.company,
        "lead_id":    req.lead_id,
        **battlecard,
        "sources":    [r["url"] for r in research.get("results",[])],
        "created_at": datetime.utcnow().isoformat()
    }
    db.collection("users").document(uid).collection("battlecards")\
      .document(bc_id).set(doc)

    return doc


@router.get("/")
def list_battlecards(authorization: str = Header(...)):
    uid  = get_uid(authorization)
    from firebase_admin import firestore
    docs = db.collection("users").document(uid).collection("battlecards")\
             .order_by("created_at", direction=firestore.Query.DESCENDING).stream()
    return [d.to_dict() for d in docs]