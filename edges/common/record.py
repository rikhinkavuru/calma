"""When CALMA_EDGES_RECORD=1, save every LLM request->response under edges/tests/fixtures/<hash>.json.
Otherwise REPLAY from fixtures (return None on miss so the caller knows to make a live call only when
recording). Key = sha256 of the canonical request minus volatile fields."""
import hashlib, json, os
FIX = os.path.join(os.path.dirname(__file__), "..", "tests", "fixtures")
def _key(req):
    canon = json.dumps(req, sort_keys=True, default=str).encode()
    return hashlib.sha256(canon).hexdigest()[:24]
def replay(req):
    if os.environ.get("CALMA_EDGES_RECORD") == "1": return None   # recording: force live call
    p = os.path.join(FIX, _key(req) + ".json")
    return json.load(open(p))["response"] if os.path.exists(p) else None
def save(req, response):
    if os.environ.get("CALMA_EDGES_RECORD") != "1": return
    os.makedirs(FIX, exist_ok=True)
    json.dump({"request": req, "response": response},
              open(os.path.join(FIX, _key(req) + ".json"), "w"), indent=2, default=str)
