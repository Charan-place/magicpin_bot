"""Generate submission.jsonl — pre-compute all 25 (merchant, trigger) pairs."""
import json
import time
from pathlib import Path
from urllib import request as urlrequest

BOT_URL = "http://localhost:8099"
DATASET = Path(__file__).parent.parent / "dataset"

def post(path, body):
    data = json.dumps(body).encode()
    req = urlrequest.Request(
        BOT_URL + path, data=data,
        headers={"Content-Type": "application/json"}, method="POST"
    )
    resp = urlrequest.urlopen(req, timeout=30)
    return json.loads(resp.read())

def push(scope, cid, version, payload):
    return post("/v1/context", {"scope": scope, "context_id": cid, "version": version, "payload": payload})

print("Loading dataset...")
cats = {}
for f in (DATASET / "categories").glob("*.json"):
    c = json.load(open(f))
    cats[c["slug"]] = c

merchants_data = json.load(open(DATASET / "merchants_seed.json"))
merchants = {m["merchant_id"]: m for m in merchants_data["merchants"]}

customers_data = json.load(open(DATASET / "customers_seed.json"))
customers = {c["customer_id"]: c for c in customers_data.get("customers", [])}

triggers_data = json.load(open(DATASET / "triggers_seed.json"))
triggers = {t["id"]: t for t in triggers_data["triggers"]}

print(f"Loaded: {len(cats)} categories, {len(merchants)} merchants, {len(triggers)} triggers")

# Push all contexts
print("\nPushing contexts to bot...")
for slug, cat in cats.items():
    push("category", slug, 1, cat)
    print(f"  category/{slug}")

for mid, m in merchants.items():
    push("merchant", mid, 1, m)
    print(f"  merchant/{mid[:20]}")

for cid, c in customers.items():
    push("customer", cid, 1, c)

for tid, t in triggers.items():
    push("trigger", tid, 1, t)

print("\nGenerating messages...")
results = []

for i, (tid, trigger) in enumerate(triggers.items(), 1):
    test_id = f"T{i:02d}"
    print(f"\n{test_id} — {trigger['kind']} → {trigger.get('merchant_id', '?')}")

    try:
        resp = post("/v1/tick", {
            "now": "2026-04-30T10:00:00Z",
            "available_triggers": [tid]
        })

        actions = resp.get("actions", [])
        if actions:
            a = actions[0]
            entry = {
                "test_id": test_id,
                "trigger_id": tid,
                "trigger_kind": trigger["kind"],
                "merchant_id": trigger.get("merchant_id", ""),
                "body": a.get("body", ""),
                "cta": a.get("cta", "open_ended"),
                "send_as": a.get("send_as", "vera"),
                "suppression_key": a.get("suppression_key", ""),
                "rationale": a.get("rationale", ""),
            }
            print(f"  ✓ body: {a.get('body','')[:80]}...")
        else:
            # Re-trigger with teardown to clear suppression
            post("/v1/teardown", {})
            # Re-push
            push("category", cats.get(merchants.get(trigger.get("merchant_id",""), {}).get("category_slug",""), {}).get("slug",""), 1,
                 cats.get(merchants.get(trigger.get("merchant_id",""), {}).get("category_slug",""), {}))
            push("merchant", trigger.get("merchant_id",""), 1, merchants.get(trigger.get("merchant_id",""), {}))
            push("trigger", tid, 1, trigger)
            resp2 = post("/v1/tick", {"now": "2026-04-30T10:05:00Z", "available_triggers": [tid]})
            actions2 = resp2.get("actions", [])
            if actions2:
                a = actions2[0]
                entry = {
                    "test_id": test_id,
                    "trigger_id": tid,
                    "trigger_kind": trigger["kind"],
                    "merchant_id": trigger.get("merchant_id", ""),
                    "body": a.get("body", ""),
                    "cta": a.get("cta", "open_ended"),
                    "send_as": a.get("send_as", "vera"),
                    "suppression_key": a.get("suppression_key", ""),
                    "rationale": a.get("rationale", ""),
                }
                print(f"  ✓ (retry) body: {a.get('body','')[:80]}...")
            else:
                entry = {
                    "test_id": test_id,
                    "trigger_id": tid,
                    "trigger_kind": trigger["kind"],
                    "merchant_id": trigger.get("merchant_id", ""),
                    "body": "",
                    "cta": "none",
                    "send_as": "vera",
                    "suppression_key": trigger.get("suppression_key", ""),
                    "rationale": "No action taken — trigger suppressed or below threshold.",
                }
                print(f"  ⚠ no action")

        results.append(entry)

    except Exception as e:
        print(f"  ✗ ERROR: {e}")
        results.append({
            "test_id": test_id,
            "trigger_id": tid,
            "trigger_kind": trigger["kind"],
            "merchant_id": trigger.get("merchant_id", ""),
            "body": "",
            "cta": "none",
            "send_as": "vera",
            "suppression_key": trigger.get("suppression_key", ""),
            "rationale": f"Error: {e}",
        })

    time.sleep(1.5)  # rate limit free model

# Save
out_path = Path(__file__).parent / "submission.jsonl"
with open(out_path, "w") as f:
    for r in results:
        f.write(json.dumps(r, ensure_ascii=False) + "\n")

print(f"\n✅ Saved {len(results)} entries → {out_path}")
print(f"Non-empty bodies: {sum(1 for r in results if r['body'])}/{len(results)}")
