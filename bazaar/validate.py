"""Check any agent's manifest against the Agent Bazaar spec:  python -m bazaar.validate <agent-url>"""
import json, sys, urllib.request
from . import trust

REQUIRED = ["name", "id", "version", "capabilities", "location", "serves", "endpoints",
            "permissions", "cannot_do", "contact", "verification"]


def check(manifest):
    problems = [f"missing field: {k}" for k in REQUIRED if k not in manifest]
    if not trust.verify_manifest(manifest):
        problems.append("signature does not verify")
    if "charge-card" in manifest.get("permissions", []):
        problems.append("agents must not hold the charge-card permission")
    return problems


if __name__ == "__main__":
    url = sys.argv[1].rstrip("/") + "/agent.json"
    problems = check(json.load(urllib.request.urlopen(url, timeout=10)))
    print("\n".join(problems) if problems else "valid")
    sys.exit(1 if problems else 0)
