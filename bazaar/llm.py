"""Optional LLM intent parsing through any OpenAI-compatible endpoint (for example an Otari router).
Set LLM_BASE_URL, LLM_API_KEY and LLM_MODEL. If unset, the planner uses its rule-based parser."""
import json, os


def parse_with_llm(text, today):
    base = os.getenv("LLM_BASE_URL")
    if not base:
        return None
    import httpx
    system = ("Extract a booking request as JSON: {\"date\": \"YYYY-MM-DD\", \"cities\": [lowercase names], "
              "\"needs\": [{\"category\": \"photography|cake|makeup\", \"budget_max\": integer naira or null, "
              "\"quantity\": integer}]}. Today is " + today + ". Reply with JSON only.")
    r = httpx.post(base.rstrip("/") + "/chat/completions", timeout=30,
                   headers={"Authorization": "Bearer " + os.getenv("LLM_API_KEY", "")},
                   json={"model": os.getenv("LLM_MODEL", "gpt-4o-mini"), "response_format": {"type": "json_object"},
                         "messages": [{"role": "system", "content": system}, {"role": "user", "content": text}]})
    r.raise_for_status()
    return json.loads(r.json()["choices"][0]["message"]["content"])
