from app.services.firebase_service import db
from groq import Groq
from dotenv import load_dotenv
from pathlib import Path
import os, re

load_dotenv(Path(__file__).resolve().parents[2] / ".env")
client = Groq(api_key=os.getenv("GROQ_API_KEY"))

def _keyword_match(text: str, query: str) -> float:
    """
    Simple keyword relevance score — no embeddings needed.
    Returns 0.0 to 1.0 relevance score.
    """
    if not text or not query:
        return 0.0

    query_words = set(re.findall(r'\w+', query.lower()))
    text_words  = set(re.findall(r'\w+', text.lower()))

    # Remove stop words
    stops = {
        "the","a","an","is","are","was","were","be","been",
        "have","has","had","do","does","did","will","would",
        "could","should","may","might","i","you","we","they",
        "he","she","it","this","that","these","those","and",
        "or","but","in","on","at","to","for","of","with","by"
    }
    query_words -= stops
    text_words  -= stops

    if not query_words:
        return 0.0

    matches = query_words & text_words
    return len(matches) / len(query_words)


def retrieve_relevant_meetings(
    uid: str,
    query: str,
    limit: int = 3
) -> list:
    """
    Retrieve meetings most relevant to the query.
    Uses keyword matching across title + summary + transcript.
    Returns top N most relevant meetings.
    """
    docs = db.collection("users").document(uid)\
             .collection("meetings").stream()

    scored = []
    for doc in docs:
        m     = doc.to_dict()
        score = 0.0

        # Weight different fields
        title_score       = _keyword_match(m.get("title",""),      query) * 2.0
        summary_score     = _keyword_match(m.get("summary",""),    query) * 1.5
        transcript_score  = _keyword_match(m.get("transcript",""), query) * 1.0
        company_score     = _keyword_match(
            m.get("linked_company",""), query
        ) * 2.5

        # Boost for participant name matches
        participant_text = " ".join([
            p.get("name","") if isinstance(p, dict) else str(p)
            for p in m.get("participants",[])
        ])
        participant_score = _keyword_match(participant_text, query) * 2.0

        score = (title_score + summary_score +
                 transcript_score + company_score +
                 participant_score)

        if score > 0:
            scored.append((score, m))

    # Sort by relevance
    scored.sort(key=lambda x: x[0], reverse=True)
    return [m for _, m in scored[:limit]]


def get_meetings_for_lead(uid: str, company: str) -> list:
    """Get all meetings linked to a specific company/lead."""
    docs = db.collection("users").document(uid)\
             .collection("meetings").stream()

    company_lower = company.lower()
    results       = []

    for doc in docs:
        m = doc.to_dict()
        if (company_lower in m.get("linked_company","").lower() or
            company_lower in m.get("title","").lower() or
            company_lower in m.get("summary","").lower()):
            results.append(m)

    # Sort by date
    results.sort(
        key=lambda x: x.get("created_at",""),
        reverse=True
    )
    return results[:5]


def build_rag_context(uid: str, query: str) -> str:
    """
    Build RAG context string to inject into AI system prompt.
    Retrieves relevant meetings and formats them for the LLM.
    """
    relevant = retrieve_relevant_meetings(uid, query, limit=3)

    if not relevant:
        return ""

    context_parts = []
    for m in relevant:
        part = f"""
--- Meeting: {m.get('title','?')} ({m.get('created_at','?')[:10]}) ---
Context type: {m.get('meeting_context','unknown')}
Linked company: {m.get('linked_company','unknown')}
Summary: {m.get('summary','')[:300]}
"""
        if m.get('objections'):
            part += f"Objections raised: {', '.join(m['objections'][:3])}\n"

        if m.get('requirements'):
            part += f"Client requirements: {', '.join(m['requirements'][:3])}\n"

        if m.get('next_steps'):
            part += f"Agreed next steps: {', '.join(m['next_steps'][:3])}\n"

        if m.get('action_items'):
            tasks = [
                f"{a.get('task','')} → {a.get('assignee','?')}"
                for a in m['action_items'][:3]
            ]
            part += f"Action items: {'; '.join(tasks)}\n"

        context_parts.append(part)

    return "\n".join(context_parts)