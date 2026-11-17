# Agent Bazaar

An open web where every small business has its own verifiable agent, and a planner agent finds, checks and negotiates with them for a customer. Built for the Open Agentic Web challenge.

## What is real in this version
- Three business agents run as **separate services** on separate ports. Each serves a public page, a signed `agent.json`, `/availability`, `/quote` and `/book`.
- Every manifest is **ed25519-signed** (`bazaar/trust.py`). The planner pins each agent's key when it registers it and rejects a different key later.
- The planner negotiates in two steps: it asks for a quote, and if the price is over budget it opens at 90% of the budget and accepts a counter within the budget. Each agent has a private floor it never reveals.
- Every agent-to-agent message goes into a **hash-chained audit log**. Editing any entry breaks the chain, and the page says so.
- Nothing is booked until the customer clicks confirm. Booking receipts are signed and checked. Agents cannot charge cards.

## What is not (yet) real
- Signatures are **self-signed**. Nothing here claims NANDA verification. Registering with NandaIndex and using Neuro San or Otari are optional next steps; `bazaar/llm.py` accepts any OpenAI-compatible router endpoint.
- Bookings are held in memory, so they reset when an agent restarts. WhatsApp numbers in `agents-data/` are placeholders.

## Run it
```bash
./run_demo.sh          # agents on 8101-8103, planner on http://localhost:8000
python tests/test_core.py   # tests run without a server
python -m bazaar.validate http://localhost:8101/agents/ada-photo
```
The core logic (negotiation, signing, audit) is tested in-process. The FastAPI wrappers are thin, but run the demo once to confirm them on your machine.

## Add your own agent
Copy a file in `agents-data/`, edit it, run `python -m bazaar.business <slug> <port>`, then register its URL:
`curl -X POST localhost:8000/api/registry/register -H 'content-type: application/json' -d '{"base_url":"http://localhost:8104/agents/<slug>"}'`
The manifest format is in `spec/agent.schema.json`.
