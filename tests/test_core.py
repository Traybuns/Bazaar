import sys, pathlib as _p; sys.path.insert(0, str(_p.Path(__file__).resolve().parent.parent))
import datetime as dt, json, pathlib, tempfile
from bazaar import planner, trust
from bazaar.business import BusinessAgent

ROOT = pathlib.Path(__file__).resolve().parent.parent
MONDAY = dt.date(2026, 11, 16)
DEMO = "Book my birthday shoot in Abuja for Saturday, photographer under ₦80k + cake for 20 people"


def make_agents():
    agents = {}
    for i, slug in enumerate(["ada-photo", "lagos-cakes", "enugu-makeup"]):
        profile = json.loads((ROOT / "agents-data" / f"{slug}.json").read_text())
        a = BusinessAgent(profile, f"http://host{i}", trust.new_private_key())
        agents[a.url] = a
    return agents


def make_transport(agents):
    def t(method, url, body=None):
        for base, a in agents.items():
            if url.startswith(base):
                path = url[len(base):]
                if path == "/agent.json": return a.manifest()
                if path == "/quote": return a.quote(body)
                if path == "/book": return a.book(body)
        raise KeyError(url)
    return t


def setup():
    agents, tmp = make_agents(), pathlib.Path(tempfile.mkdtemp())
    t = make_transport(agents)
    reg, audit = planner.Registry(tmp / "r.json"), planner.Audit(tmp / "a.jsonl")
    for url in agents:
        reg.register(url, t, audit)
    return agents, t, reg, audit


def test_manifest_signature_and_tamper():
    a = next(iter(make_agents().values()))
    m = a.manifest()
    assert trust.verify_manifest(m)
    m["price_range"]["from"] = 1
    assert not trust.verify_manifest(m)


def test_parse_demo_request():
    r = planner.parse_request(DEMO, MONDAY)
    assert r["date"] == "2026-11-21"
    needs = {n["category"]: n for n in r["needs"]}
    assert needs["photography"]["budget_max"] == 80000
    assert needs["cake"]["quantity"] == 20 and "abuja" in r["cities"]


def test_plan_negotiates_and_confirm_books():
    agents, t, reg, audit = setup()
    p = planner.plan(DEMO, reg, t, audit, today=MONDAY)
    assert p["complete"] and p["city"] == "Abuja"
    price = {i["category"]: i["price"] for i in p["items"]}
    assert price == {"photography": 76500, "cake": 40000}  # list 90000 negotiated down inside the 80k budget
    out = planner.confirm(p, reg, t, audit)["bookings"]
    assert all(b["status"] == "confirmed" and b["receipt_signature_ok"] for b in out)
    assert all(b["whatsapp"].startswith("https://wa.me/") for b in out)
    again = planner.plan(DEMO, reg, t, audit, today=MONDAY)  # photographer is now booked that Saturday
    assert not again["complete"]
    assert audit.verify_chain()


def test_impostor_with_different_key_is_rejected():
    agents, t, reg, audit = setup()
    url = "http://host0/agents/ada-photo"
    profile = agents[url].p
    agents[url] = BusinessAgent(profile, "http://host0", trust.new_private_key())  # same URL, new key
    p = planner.plan("photographer on Saturday", reg, t, audit, today=MONDAY)
    assert p["items"][0]["status"] == "unmatched"
    assert "failed verification" in p["items"][0]["notes"][0]


def test_audit_tamper_detected():
    agents, t, reg, audit = setup()
    planner.plan(DEMO, reg, t, audit, today=MONDAY)
    lines = audit.path.read_text().splitlines()
    e = json.loads(lines[3]); e["payload"] = {"forged": True}; lines[3] = json.dumps(e)
    audit.path.write_text("\n".join(lines) + "\n")
    assert not audit.verify_chain()


def test_missing_date_asks_for_it():
    agents, t, reg, audit = setup()
    assert "error" in planner.plan("I need a cake", reg, t, audit, today=MONDAY)


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn(); print("ok", name)
