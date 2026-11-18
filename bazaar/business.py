"""A business agent: serves a signed agent.json and answers quote/book requests.

Run one per business:  python -m bazaar.business ada-photo 8101
The core class has no web dependency, so it can be tested without a server.
"""
import datetime as dt, hashlib, html
from urllib.parse import urlparse
from . import trust

DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


class BusinessAgent:
    def __init__(self, profile: dict, base_url: str, private_key: str):
        self.p, self.key = profile, private_key
        self.base_url = base_url.rstrip("/")
        self.url = f"{self.base_url}/agents/{profile['slug']}"
        self.booked = set(profile.get("booked_dates", []))
        self.quotes: dict = {}

    def manifest(self) -> dict:
        p, host = self.p, urlparse(self.base_url).netloc.replace(":", "%3A")
        return trust.sign_manifest({
            "name": p["name"],
            "id": f"did:web:{host}:agents:{p['slug']}",
            "version": "1.0",
            "description": p["description"],
            "capabilities": p["capabilities"],
            "location": p["location"],
            "serves": p["serves"],
            "price_range": {"from": p["base_price"], "currency": "NGN"},
            "availability": f"{self.url}/availability",
            "endpoints": {"quote": f"{self.url}/quote", "book": f"{self.url}/book"},
            "contact": {"whatsapp": p["whatsapp"]},
            "permissions": ["read-availability", "propose-price", "accept-booking"],
            "cannot_do": ["charge-card", "access-contacts"],
        }, self.key)

    def is_free(self, date: str) -> bool:
        try:
            d = dt.date.fromisoformat(date)
        except (TypeError, ValueError):
            return False
        return DAYS[d.weekday()] in self.p["working_days"] and date not in self.booked

    def list_price(self, qty: int) -> int:
        p = self.p
        return p["base_price"] + p["per_unit_price"] * max(qty - p["included_units"], 0)

    def quote(self, req: dict) -> dict:
        date, qty, offer = req.get("date"), int(req.get("quantity") or 1), req.get("offer")
        if not self.is_free(date):
            return {"status": "unavailable", "reason": "not available on that date"}
        price = self.list_price(qty)
        floor = round(price * (1 - self.p["max_discount"]))  # never sent to the caller
        qid = hashlib.sha256(f"{self.p['slug']}|{date}|{qty}|{len(self.quotes)}".encode()).hexdigest()[:12]
        self.quotes[qid] = {"date": date, "qty": qty, "floor": floor, "list": price}
        if offer is None:
            status, out = "quoted", price
        elif offer >= floor:
            status, out = "accepted", min(int(offer), price)
        else:
            status, out = "counter", floor
        return {"status": status, "quote_id": qid, "price": out, "currency": "NGN", "date": date, "quantity": qty}

    def book(self, req: dict) -> dict:
        q = self.quotes.get(req.get("quote_id"))
        if not q:
            return {"status": "rejected", "reason": "unknown quote"}
        price = int(req.get("price") or 0)
        if price < q["floor"]:
            return {"status": "rejected", "reason": "price below agreed range"}
        if not self.is_free(q["date"]):
            return {"status": "rejected", "reason": "date no longer available"}
        self.booked.add(q["date"])
        receipt = {"booking_id": "BZ-" + req["quote_id"][:8].upper(), "agent": self.manifest()["id"],
                   "date": q["date"], "quantity": q["qty"], "price": min(price, q["list"]), "currency": "NGN"}
        return {"status": "confirmed", "receipt": receipt, "signature": trust.sign(self.key, receipt)}


def create_app(agent: BusinessAgent):
    from fastapi import FastAPI
    from fastapi.responses import HTMLResponse
    app = FastAPI(title=agent.p["name"])
    base = f"/agents/{agent.p['slug']}"

    @app.get(base + "/agent.json")
    @app.get(base + "/.well-known/agent")
    def manifest():
        return agent.manifest()

    @app.get(base + "/availability")
    def availability(date: str):
        return {"date": date, "available": agent.is_free(date)}

    @app.post(base + "/quote")
    def quote(req: dict):
        return agent.quote(req)

    @app.post(base + "/book")
    def book(req: dict):
        return agent.book(req)

    @app.get(base, response_class=HTMLResponse)
    def page():
        m, e = agent.manifest(), html.escape
        return (f"<!doctype html><meta charset=utf-8><title>{e(m['name'])}</title>"
                f"<body style='font:16px system-ui;max-width:36rem;margin:3rem auto;padding:0 1rem'>"
                f"<h1>{e(m['name'])}</h1><p>{e(m['description'])}</p>"
                f"<p>Serves: {e(', '.join(m['serves']))}. From ₦{m['price_range']['from']:,}.</p>"
                f"<p>This agent can: {e(', '.join(m['permissions']))}.<br>"
                f"It cannot: {e(', '.join(m['cannot_do']))}.</p>"
                f"<p><a href='{base}/agent.json'>agent.json</a> (signed manifest)</p></body>")
    return app


def main():
    import json, os, pathlib, sys
    import uvicorn
    slug, port = sys.argv[1], int(sys.argv[2])
    root = pathlib.Path(__file__).resolve().parent.parent
    profile = json.loads((root / "agents-data" / f"{slug}.json").read_text())
    keyfile = root / "keys" / f"{slug}.key"
    if not keyfile.exists():
        keyfile.parent.mkdir(exist_ok=True)
        keyfile.write_text(trust.new_private_key())
    agent = BusinessAgent(profile, os.getenv("PUBLIC_URL", f"http://localhost:{port}"), keyfile.read_text().strip())
    uvicorn.run(create_app(agent), host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()
