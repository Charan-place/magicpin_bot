# Vera Bot — magicpin AI Challenge Submission

**Team**: Satya Sai Charan Narra  
**Contact**: nsatyasaicharan@gmail.com  
**Model**: google/gemma-4-26b-a4b-it (via OpenRouter free tier)  
**Deploy**: Render free tier — https://magicpin-bot.onrender.com

---

## Approach

### Core insight: Vera is a pay-per-conversion product, not a chatbot

Every design decision reflects magicpin's doctrine — merchants pay only on outcome.
Generic "increase your visibility" messages fail this test. Every composed message
must drive a specific, measurable merchant action.

### Architecture: 3-layer prompt stack

```
Layer 1 — System prompt (constant):
  Vera identity + magicpin doctrine + hard constraints (no URLs, no fabrication, no generic discounts)

Layer 2 — Mode prompt (per trigger-kind):
  OPERATOR mode: counter-intuitive peer insight, may disagree with trigger
  ASSISTANT mode: effort externalization, draft artifact ready to go

Layer 3 — Context block (per request):
  All 4 contexts + derived features computed before LLM call
```

### Trigger-kind dispatch

Each `trigger.kind` maps to a composition mode:

| Kind | Mode | Why |
|---|---|---|
| `research_digest` | Assistant | Draft patient-ed artifact, cite source |
| `perf_dip` | Operator | Counter-intuitive insight (seasonal = skip ad spend) |
| `competitor_opened` | Operator | Voyeur-curiosity framing |
| `recall_due` | Assistant | Slot + price + language-pref honored |
| `ipl_match_today` | Operator | May recommend AGAINST promo if Saturday |
| `festival_upcoming` | Operator | Category-appropriate angle, not generic |

### Derived features computed before LLM call

- **CTR vs peer median**: `"ctr 0.021 vs peer 0.030 (-30%)"` — gives LLM a specific number to anchor loss-aversion framing
- **Lapsed revenue estimate**: `"₹23,322/qtr (78 lapsed × ₹299)"` — cost-of-inaction quantified
- **Language register**: `use_hindi=True` → Hinglish code-mix enforced with example style

### State machine for multi-turn

```
Auto-reply detection (3-strike):
  Turn 1: send probe ("Looks like auto-reply — owner dekhe, reply YES")
  Turn 2: wait 14400s (4h)
  Turn 3: end conversation

Intent transition detection:
  Keywords: "yes", "let's do it", "ok karo", "go ahead", "confirm", "haan"
  → Force ACTION mode prompt (no qualifying questions, draft artifact immediately)

Hostile detection:
  "stop messaging", "not interested", "band karo", "nahi chahiye"
  → action: end + suppress merchant 30 days

Anti-repetition:
  Track sent bodies per conversation_id — never repeat verbatim
```

---

## Tradeoffs

**Model choice**: Using `google/gemma-4-26b-a4b-it:free` via OpenRouter.
Free tier model gives inconsistent output on edge cases (sometimes drifts category voice).
A frontier model (Claude Sonnet, GPT-4o) would score +1-2 on specificity and category fit.
Tradeoff accepted to keep zero API cost.

**Fallback chain**: 3 free models tried in sequence on rate limit (gemma-4 → gpt-oss-120b → gemma-3-12b).
Ensures bot stays responsive during evaluation even under rate limits.

**Stateful in-memory**: Context stored in Python dicts. Works for single-instance evaluation.
Would need Redis for multi-instance production.

**Suppression dedup**: `suppression_key` tracked per session. Prevents re-sending same trigger
within test window. Restraint rewarded over spam.

---

## What additional context would have helped most

1. **Real merchant language corpus**: Knowing how Dr. Meera actually texts (short Hindi bursts? formal English?) would sharpen voice-fingerprinting.
2. **Peer benchmark by locality** (not just city): "3 dentists in Lajpat Nagar ran recall sweep this month" is more compelling than "metro peers".
3. **Historical engagement rates per trigger-kind**: Which trigger types get the highest reply rates in production? Would reprioritize the mode dispatch.
4. **Actual suppression window from production**: Brief says dedup but not how long production Vera suppresses. Would tune the 7-day default.

---

## Files

| File | Purpose |
|---|---|
| `main.py` | FastAPI server — all 5 required endpoints |
| `composer.py` | 3-layer LLM prompt stack, trigger dispatch, model fallback |
| `conversation.py` | State machine: auto-reply, intent, hostile detection |
| `state.py` | In-memory context store with version-aware upsert |
| `conversation_handlers.py` | Multi-turn respond() — tiebreaker submission |
| `submission.jsonl` | 25 pre-computed (merchant, trigger) pairs |
