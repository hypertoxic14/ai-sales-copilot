from tavily import TavilyClient
from dotenv import load_dotenv
from pathlib import Path
import os

load_dotenv(Path(__file__).resolve().parents[2] / ".env")

API_KEY = os.getenv("TAVILY_API_KEY")
client  = TavilyClient(api_key=API_KEY) if API_KEY else None


def _is_configured() -> bool:
    return bool(API_KEY)


def research_company(company_name: str) -> dict:
    """
    Search the web for recent info about a company.
    Returns structured findings for battlecard generation.
    """
    if not _is_configured():
        return {
            "success": False,
            "message": "Tavily API key not configured. Add TAVILY_API_KEY to .env",
            "results": []
        }

    if not company_name or len(company_name.strip()) < 2:
        return {
            "success": False,
            "message": "Invalid company name",
            "results": []
        }

    try:
        # Search for company overview + recent news
        results = client.search(
            query=f"{company_name} company business overview recent news 2026",
            search_depth="advanced",
            max_results=5,
            include_answer=True
        )

        findings = []
        for r in results.get("results", []):
            findings.append({
                "title":   r.get("title", ""),
                "content": r.get("content", "")[:500],
                "url":     r.get("url", "")
            })

        return {
            "success":     True,
            "answer":      results.get("answer", ""),
            "results":     findings,
            "company":     company_name
        }

    except Exception as e:
        return {
            "success": False,
            "message": f"Research failed: {str(e)}",
            "results": []
        }