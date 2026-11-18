"""Planner core: parse a request, discover agents, verify them, negotiate, book.

Everything talks to agents through a `transport(method, url, body=None) -> dict`
callable, so the same logic runs over real HTTP or in-process for tests.
"""
import datetime as dt, hashlib, json, pathlib, re, threading, time, urllib.parse
from . import trust

CATS = {
    "photography": ["photo", "shoot"],
    "cake": ["cake", "bake"],
    "makeup": ["makeup", "make-up", "make up", "mua"],
}
WEEKDAYS = {n: i for i, n in enumerate(
    ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"])}
BUDGET = re.compile(r"(?:under|below|max|within|less than|<)\s*₦?\s*n?\s*(\d[\d,\.]*)\s*(k|m)?")


def http_transport(method, url, body=None):
    import httpx
    r = httpx.request(method, url, json=body, timeout=10)
    r.raise_for_status()
    return r.json()


# ---------- request parsing ----------

def parse_request(text, today=None, llm=None):
    today = today or dt.date.today()
    if llm:  # optional LLM parsing (e.g. via an Otari router); falls back to rules on any problem
        try:
            r = llm(text, today.isoformat())
            if r and r.get("date") and r.get("needs") and all(n.get("category") in CATS for n in r["needs"]):
                dt.date.fromisoformat(r["date"])
                for n in r["needs"]:
                    n.setdefault("budget_max", None)
                    n["quantity"] = int(n.get("quantity") or 1)
                r.setdefault("cities", [])
                return r
        except Exception:
            pass
    low, date = text.lower(), None
    m = re.search(r"\d{4}-\d{2}-\d{2}", low)
    if m:
        date = m.group()
    elif "tomorrow" in low:
        date = (today + dt.timedelta(days=1)).isoformat()
    else:
        for name, idx in WEEKDAYS.items():
            if re.search(rf"\b{name}\b", low):
                date = (today + dt.timedelta(days=(idx - today.weekday()) % 7 or 7)).isoformat()
                break
    needs: dict = {}
    for clause in re.split(r"\s*\+\s*|,|;|\band\b", low):
        cat = next((c for c, kws in CATS.items() if any(k in clause for k in kws)), None)
        if not cat:
            continue
        n = needs.setdefault(cat, {"category": cat, "budget_max": None, "quantity": 1})
        b = BUDGET.search(clause)
        if b:
            n["budget_max"] = int(float(b.group(1).replace(",", "")) * {"k": 1_000, "m": 1_000_000}.get(b.group(2), 1))
        q = re.search(r"for (\d+)", clause) or re.search(r"(\d+)\s*(?:people|guests|persons|pax)", clause)
        if q:
            n["quantity"] = max(n["quantity"], int(q.group(1)))
    return {"date": date, "needs": list(needs.values()), "cities": re.findall(r"\bin ([a-z]+)", low)}


# ---------- audit log (hash-chained, tamper-evident) ----------

class Audit:
    def __init__(self, path):
        self.path = pathlib.Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lock, self.prev = threading.Lock(), "genesis"
        for e in self.entries():
            self.prev = e["hash"]

    def entries(self):
        if not self.path.exists():
            return []
        return [json.loads(line) for line in self.path.read_text().splitlines() if line.strip()]

    def log(self, frm, to, kind, payload):
        with self.lock:
            e = {"ts": round(time.time(), 3), "from": frm, "to": to, "kind": kind, "payload": payload, "prev": self.prev}
            e["hash"] = hashlib.sha256(trust.canonical(e)).hexdigest()
            with self.path.open("a") as f:
                f.write(json.dumps(e, ensure_ascii=False) + "\n")
            self.prev = e["hash"]

    def verify_chain(self):
        prev = "genesis"
        for e in self.entries():
            body = {k: v for k, v in e.items() if k != "hash"}
            if e["prev"] != prev or hashlib.sha256(trust.canonical(body)).hexdigest() != e["hash"]:
                return False
            prev = e["hash"]
        return True


# ---------- registry (pins each agent's key on first sight) ----------

class Registry:
    def __init__(self, path):
        self.path = pathlib.Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.entries = json.loads(self.path.read_text()) if self.path.exists() else {}

    def all(self):
        return list(self.entries.values())

    def register(self, url, transport, audit=None):
        url = url.rstrip("/")
        m = transport("GET", url + "/agent.json")
        if not trust.verify_manifest(m):
            raise ValueError("manifest signature is invalid")
        pub = m["verification"]["public_key"]
        old = self.entries.get(url)
        if old and old["public_key"] != pub:
            raise ValueError("public key changed since first registration")
        self.entries[url] = {"url": url, "id": m["id"], "name": m["name"], "capabilities": m["capabilities"],
                             "serves": m.get("serves", []), "location": m.get("location"), "public_key": pub}
        self.path.write_text(json.dumps(self.entries, indent=1))
        if audit:
            audit.log(m["name"], "registry", "register", {"id": m["id"], "signature_ok": True})
        return self.entries[url]


# ---------- planning ----------

def _negotiate(e, need, date, transport, audit):
    """Returns (offer, None) or (None, reason). Opens at 90% of budget, accepts any counter within budget."""
    name, base, qty, budget = e["name"], e["url"], need["quantity"], need["budget_max"]
    ask = {"date": date, "quantity": qty}
    audit.log("planner", name, "quote_request", ask)
    q = transport("POST", base + "/quote", ask)
    audit.log(name, "planner", "quote", q)
    if q["status"] != "quoted":
        return None, q.get("reason", "unavailable")
    if budget is None or q["price"] <= budget:
        return {"price": q["price"], "quote_id": q["quote_id"], "list_price": q["price"]}, None
    offer = int(budget * 0.9)
    audit.log("planner", name, "counter_offer", {"offer": offer})
    r = transport("POST", base + "/quote", {**ask, "offer": offer})
    audit.log(name, "planner", "quote", r)
    if r["status"] == "counter" and r["price"] <= budget:
        audit.log("planner", name, "accept", {"price": r["price"]})
        return {"price": r["price"], "quote_id": r["quote_id"], "list_price": q["price"]}, None
    if r["status"] == "accepted":
        return {"price": r["price"], "quote_id": r["quote_id"], "list_price": q["price"]}, None
    return None, "above budget"


def _source(need, date, city, registry, transport, audit):
    cands = [e for e in registry.all() if need["category"] in e["capabilities"]
             and (not city or city in [s.lower() for s in e["serves"]])]
    audit.log("planner", "registry", "discover", {"category": need["category"], "city": city,
                                                  "found": [c["name"] for c in cands]})
    best, notes = None, []
    for e in cands:
        try:
            m = transport("GET", e["url"] + "/agent.json")
            ok = trust.verify_manifest(m) and m["verification"]["public_key"] == e["public_key"]
            safe = "charge-card" not in m.get("permissions", [])
            audit.log("planner", e["name"], "verify", {"ok": bool(ok and safe), "cannot_do": m.get("cannot_do")})
            if not (ok and safe):
                notes.append(f"{e['name']}: failed verification")
                continue
            offer, why = _negotiate(e, need, date, transport, audit)
        except Exception as exc:
            notes.append(f"{e['name']}: {exc}")
            continue
        if offer is None:
            notes.append(f"{e['name']}: {why}")
        elif best is None or offer["price"] < best["price"]:
            best = {**offer, "agent": {"name": e["name"], "url": e["url"], "id": m["id"]},
                    "whatsapp": m.get("contact", {}).get("whatsapp")}
    item = {"category": need["category"], "date": date, "quantity": need["quantity"],
            "budget_max": need["budget_max"], "notes": notes}
    return {**item, "status": "ok", **best} if best else {**item, "status": "unmatched"}


def plan(text, registry, transport, audit, today=None, llm=None):
    req = parse_request(text, today, llm)
    audit.log("customer", "planner", "request", {"text": text})
    if not req["date"]:
        return {"error": "Tell me which day you need this, for example “Saturday”."}
    if not req["needs"]:
        return {"error": "I can book photography, cakes and makeup. Say which one you need."}
    places = {s.lower() for e in registry.all() for s in e["serves"]}
    city = next((c for c in req["cities"] if c in places), None)
    items = [_source(n, req["date"], city, registry, transport, audit) for n in req["needs"]]
    return {"id": hashlib.sha256(f"{text}{time.time()}".encode()).hexdigest()[:10],
            "date": req["date"], "city": city.title() if city else None, "items": items,
            "total": sum(i["price"] for i in items if i["status"] == "ok"), "currency": "NGN",
            "complete": all(i["status"] == "ok" for i in items)}


def whatsapp_link(number, receipt, category):
    text = (f"Hi, this is booking {receipt['booking_id']} made through Agent Bazaar: "
            f"{category} on {receipt['date']}, ₦{receipt['price']:,}.")
    return f"https://wa.me/{number}?text={urllib.parse.quote(text)}"


def confirm(proposal, registry, transport, audit):
    """Books every line of a complete proposal. Only runs after the customer confirms."""
    if not proposal["complete"]:
        return {"error": "Some items could not be matched, so nothing was booked."}
    results = []
    for it in proposal["items"]:
        a = it["agent"]
        audit.log("planner", a["name"], "book_request", {"quote_id": it["quote_id"], "price": it["price"]})
        r = transport("POST", a["url"] + "/book", {"quote_id": it["quote_id"], "price": it["price"]})
        audit.log(a["name"], "planner", "book_response", r)
        if r.get("status") != "confirmed":
            results.append({"category": it["category"], "agent": a["name"], "status": "failed",
                            "reason": r.get("reason", "rejected")})
            continue
        signed = trust.verify(registry.entries[a["url"]]["public_key"], r["receipt"], r["signature"])
        results.append({"category": it["category"], "agent": a["name"],
                        "status": "confirmed" if signed else "bad_receipt", "receipt": r["receipt"],
                        "receipt_signature_ok": signed,
                        "whatsapp": whatsapp_link(it["whatsapp"], r["receipt"], it["category"]) if it.get("whatsapp") else None})
    return {"bookings": results}
