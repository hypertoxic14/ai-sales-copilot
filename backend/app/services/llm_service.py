from groq import Groq
from dotenv import load_dotenv
from pathlib import Path
from datetime import date
import os, json, re

load_dotenv(Path(__file__).resolve().parents[2] / ".env")
client = Groq(api_key=os.getenv("GROQ_API_KEY"))

def process_transcript(transcript: str) -> dict:
    today  = date.today().isoformat()
    system = f"""
You are a precise meeting analyst. Today is {today}.
Return ONLY valid JSON — no markdown, no explanation.

{{
  "summary": "3-4 sentence executive summary",
  "sentiment": "positive | neutral | negative",
  "participants": [{{"name": "string", "email": "string or null"}}],
  "objections": ["list of objections raised by client"],
  "requirements": ["list of client requirements or needs mentioned"],
  "next_steps": ["list of agreed next steps"],
  "action_items": [{{
    "task": "string",
    "assignee": "string or null",
    "deadline": "YYYY-MM-DD or null",
    "priority": "HIGH | MEDIUM | LOW",
    "type": "email | dev | meeting | design | marketing | research | other",
    "confidence": 0.0
  }}]
}}

Rules:
- Convert relative dates using today={today}
- Priority: HIGH=urgent/ASAP/blocking, MEDIUM=this week, LOW=eventually
- Objections: pricing concerns, timeline issues, feature gaps, trust issues
- Requirements: things client explicitly asked for or needs
- Next steps: concrete agreed actions with owners
- Return ONLY JSON, nothing else
"""
    res = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[
            {"role":"system", "content":system},
            {"role":"user",   "content":f"Transcript:\n\n{transcript}"}
        ],
        temperature=0.2
    )
    raw = res.choices[0].message.content.strip()
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)

    try:
        return json.loads(raw)
    except Exception:
        match = re.search(r'\{.*\}', raw, re.DOTALL)
        if match:
            return json.loads(match.group())
        return {
            "summary":      raw,
            "sentiment":    "neutral",
            "participants": [],
            "objections":   [],
            "requirements": [],
            "next_steps":   [],
            "action_items": []
        }
    
def generate_objection_responses(objections: list, company: str, context: str) -> list:
    if not objections:
        return []

    system = """You are an expert sales coach.
For each objection, generate a counter-response.
Return ONLY a valid JSON array. No markdown. No explanation. Start with [ end with ].

Format:
[
  {
    "objection": "exact objection text",
    "category": "pricing",
    "severity": "high",
    "counter_response": "What the sales rep should say",
    "follow_up_question": "Question to re-engage"
  }
]

Category must be one of: pricing, timeline, trust, competition, budget, feature, other
Severity must be one of: high, medium, low"""

    objections_text = "\n".join(f"{i+1}. {o}" for i, o in enumerate(objections))

    user = f"""Company: {company or 'the prospect'}
Context: {context[:200] if context else 'sales meeting'}

Objections:
{objections_text}

Return JSON array only."""

    try:
        res = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role":"system","content":system},
                {"role":"user",  "content":user}
            ],
            temperature=0.2,
            max_tokens=1000
        )
        raw = res.choices[0].message.content.strip()

        # Clean up response
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
        raw = raw.strip()

        # Find JSON array in response
        if not raw.startswith("["):
            match = re.search(r'\[.*\]', raw, re.DOTALL)
            if match:
                raw = match.group()

        result = json.loads(raw)

        # Validate each item has required fields
        validated = []
        for item in result:
            if isinstance(item, dict) and item.get("objection"):
                validated.append({
                    "objection":         str(item.get("objection", "")),
                    "category":          str(item.get("category", "other")),
                    "severity":          str(item.get("severity", "medium")),
                    "counter_response":  str(item.get("counter_response", "")),
                    "follow_up_question":str(item.get("follow_up_question", ""))
                })
        return validated

    except Exception as e:
        print(f"❌ generate_objection_responses error: {e}")
        print(f"   Raw response: {raw[:200] if 'raw' in dir() else 'N/A'}")
        # Return basic fallback
        return [
            {
                "objection":          o,
                "category":           "other",
                "severity":           "medium",
                "counter_response":   "Acknowledge the concern and focus on the unique value you provide. Ask what would need to change for this to work.",
                "follow_up_question": "What would need to be different for you to feel comfortable moving forward?"
            }
            for o in objections
        ]  
    
    
def generate_mom(meeting_data: dict) -> dict:
    """
    Generate structured Minutes of Meeting from meeting data.
    """
    system = """You are a professional meeting secretary.
Generate structured Minutes of Meeting from the provided data.
Return ONLY valid JSON — no markdown, no explanation:
{
  "meeting_title": "string",
  "key_discussion_points": ["point 1", "point 2"],
  "decisions_made": ["decision 1", "decision 2"],
  "risks_identified": ["risk 1"],
  "next_meeting_agenda": ["agenda item 1"]
}"""

    user = f"""
Meeting title: {meeting_data.get('title','Untitled')}
Summary: {meeting_data.get('summary','')}
Transcript excerpt: {meeting_data.get('transcript','')[:1500]}
Objections: {', '.join(meeting_data.get('objections',[]))}
Requirements: {', '.join(meeting_data.get('requirements',[]))}
Next steps: {', '.join(meeting_data.get('next_steps',[]))}
"""
    res = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[
            {"role":"system","content":system},
            {"role":"user",  "content":user}
        ],
        temperature=0.2,
        max_tokens=800
    )
    raw = res.choices[0].message.content.strip()
    raw = re.sub(r"^```(?:json)?\s*","",raw)
    raw = re.sub(r"\s*```$","",raw)

    try:
        return json.loads(raw)
    except Exception:
        return {
            "meeting_title":        meeting_data.get('title','Meeting'),
            "key_discussion_points":[meeting_data.get('summary','')],
            "decisions_made":       meeting_data.get('next_steps',[]),
            "risks_identified":     meeting_data.get('objections',[]),
            "next_meeting_agenda":  []
        }