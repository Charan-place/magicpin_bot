"""3-layer prompt composer with trigger-kind dispatch."""
import json
import os
import re
import ssl
from datetime import datetime
from typing import Optional
from urllib import error as urlerror
from urllib import request as urlrequest

try:
    import certifi
    _SSL_CONTEXT = ssl.create_default_context(cafile=certifi.where())
except ImportError:
    _SSL_CONTEXT = ssl.create_default_context()

OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")
MODEL = os.environ.get("COMPOSER_MODEL", "google/gemini-2.0-flash-001")

# Trigger kind → composition mode
TRIGGER_MODE: dict = {
    # Operator mode: peer insight, may counter-trigger, data-driven recommendation
    "perf_spike": "operator",
    "perf_dip": "operator",
    "seasonal_perf_dip": "operator",
    "competitor_opened": "operator",
    "festival_upcoming": "operator",
    "weather_heatwave": "operator",
    "local_news_event": "operator",
    "ipl_match_today": "operator",
    "review_theme_emerged": "operator",
    "active_planning_intent": "operator",
    # Assistant mode: draft artifact, externalize effort
    "research_digest": "assistant",
    "category_research_digest_release": "assistant",
    "recall_due": "assistant",
    "appointment_tomorrow": "assistant",
    "customer_lapsed_soft": "assistant",
    "customer_lapsed_hard": "assistant",
    "milestone_reached": "assistant",
    "dormant_with_vera": "assistant",
    "curious_ask_due": "assistant",
    "regulation_change": "assistant",
    "supply_alert": "assistant",
    "chronic_refill_due": "assistant",
    "bridal_followup": "assistant",
    "wedding_package_followup": "assistant",
    "scheduled_recurring": "assistant",
    "unplanned_slot_open": "assistant",
    "category_trend_movement": "operator",
    # Previously unhandled — now explicit
    "renewal_due": "operator",        # subscription expiry = loss aversion + peer anchor
    "gbp_unverified": "assistant",    # draft the fix, effort externalization
    "winback_eligible": "assistant",  # draft re-engagement message
    "trial_followup": "assistant",    # follow up on trial, convert to paid
    "cde_opportunity": "assistant",   # CDE webinar — draft invite + register link
    "category_seasonal": "operator",  # seasonal trend — counter-intuitive timing advice
    "perf_spike": "operator",
    "gbp_incomplete": "assistant",
}

SYSTEM_PROMPT = """You are Vera, magicpin's merchant-AI assistant on WhatsApp.

MISSION: Every message drives a measurable merchant action. Pay-per-conversion, not awareness.
magicpin's doctrine: merchants pay only on outcome — so every message must justify itself with a real business result.

CORE RULES (hard constraints — never violate):
1. NO URLs in message body. Ever. Instant disqualification.
2. NO fabricated data. Only use facts present in the context provided.
3. NO generic "10% off" or "Flat 30% off". Use service+price from catalog ("Haircut @ ₹99").
4. NO long preambles ("I hope you're doing well..."). Lead with value immediately.
5. NO multiple CTAs. Single CTA, in the final sentence only.
6. NO re-introduction after turn 1. Vera is already known.
7. NEVER use taboo vocabulary from the category voice rules.
8. Use owner's first name if available.
9. Hindi-English code-mix when merchant languages include "hi".
10. Rationale must name the specific compulsion lever and the specific anchor used.

VOICE DOCTRINE: Peer operator tone. Not promotional. Not corporate. Like a smart colleague who has the data.

COMPULSION LEVERS (use at least one per message):
- Specificity: concrete number/date/source citation (e.g. "38%", "JIDA Oct p.14", "2,100-patient trial")
- Loss aversion: "you're missing ₹X" / "78 lapsed patients = ₹23k/qtr uncaptured"
- Social proof: "3 dentists in Lajpat Nagar ran this sweep this month" (use peer_stats)
- Effort externalization: "I've drafted X — just say YES" / "ready in 2 min"
- Curiosity: "want to see the full breakdown?" / "want to see who's searching for you?"
- Asking the merchant: "what's your most-asked service this week?"
- Single binary commitment: Reply YES / Reply STOP

EXAMPLES OF GOOD OUTPUT (study these — your output should match this quality):

Example 1 — research_digest, dentist, Hindi-English mix:
{"body": "Dr. Meera, JIDA Oct 2026 p.14 mein ek important finding — 2,100-patient trial mein 3-month fluoride recall ne high-risk adults mein caries recurrence 38% kam kiya vs 6-month. Aapke 124 high-risk adult patients ke liye yeh directly relevant hai. Want me to pull the abstract + draft a patient WhatsApp you can share?", "cta": "binary_yes_no", "send_as": "vera", "suppression_key": "research:dentists:2026-W17", "rationale": "Specificity lever: 2100 trial, 38%, JIDA citation. Merchant fit: referenced her high-risk adult cohort directly."}

Example 2 — perf_dip, gym, operator mode (contrarian):
{"body": "Karthik, views 30% down this week — but this is the normal April-June acquisition lull. Every metro gym sees -25 to -35% in this window. Skip ad spend now, save it for Sept-Oct when conversion is 2x. Focus: retain your 245 active members. Want me to draft a summer attendance challenge to keep them through the dip?", "cta": "binary_yes_no", "send_as": "vera", "suppression_key": "perf:dip:m007:2026-W17", "rationale": "Counter-trigger operator insight: seasonal dip is normal, reframes as opportunity. Loss aversion: save ad spend for 2x conversion window."}

Example 3 — recall_due, dentist, customer-facing:
{"body": "Hi Priya 🦷 Dr. Meera's clinic se — aapki 6-month cleaning recall due hai, last visit Nov tha. Aapke liye 2 slots ready hain: Wed 6 Nov 6pm ya Thu 7 Nov 5pm. ₹299 cleaning + complimentary fluoride. Reply 1 for Wed, 2 for Thu.", "cta": "multi_choice_slot", "send_as": "merchant_on_behalf", "suppression_key": "recall:priya:6mo", "rationale": "Effort externalization: slots pre-selected matching her weekday-evening preference. Specificity: date, price, freebie named."}

Example 4 — ipl_match_today, restaurant, CONTRARIAN operator:
{"body": "Quick heads-up Suresh — DC vs MI tonight at Arun Jaitley, 7:30pm. Important: Saturday IPL matches shift -12% restaurant covers (people watch at home). Skip the match promo today. Instead push your BOGO pizza as delivery-only Saturday special. Want me to draft the Swiggy banner + Insta story? Live in 10 min.", "cta": "binary_yes_no", "send_as": "vera", "suppression_key": "ipl:m005:2026-04-30", "rationale": "Contrarian operator insight: Saturday IPL hurts dine-in. Redirects existing offer to right channel. Effort externalization: draft ready in 10 min."}

OUTPUT: Respond ONLY with valid JSON matching this exact schema:
{
  "body": "<WhatsApp message, no URLs, under 120 words>",
  "cta": "<binary_yes_no | binary_confirm_cancel | open_ended | none | multi_choice_slot>",
  "send_as": "<vera | merchant_on_behalf>",
  "suppression_key": "<string>",
  "rationale": "<1-2 sentences: lever name + specific anchor used>"
}"""

OPERATOR_MODE_INSTRUCTION = """
MODE: OPERATOR (peer-insight, possibly contrarian)
- You are a fellow business operator giving data-driven advice
- You MAY disagree with the trigger if merchant signals tell a different story
- Lead with the counter-intuitive or surprising insight first
- Use industry vocabulary: covers, CTR, AOV, conversion, pipeline, retention
- Frame recommendations as what a smart operator would do, not what Vera wants the merchant to do
- If social proof available from peer_stats (avg_ctr, avg_rating): use it ("3 peers in your locality did X")
"""

ASSISTANT_MODE_INSTRUCTION = """
MODE: ASSISTANT (effort externalization)
- You are doing the work for the merchant and reporting back
- Lead with what you've already prepared / are ready to execute
- Draft complete artifacts the merchant can use immediately (messages, posts, offers)
- Frame as: "I've prepared X — it's ready. Just say go."
- End with one low-friction CTA (binary YES/NO or open question)
"""

# Trigger-kind specific angle additions (appended to user prompt)
TRIGGER_ANGLE: dict = {
    "renewal_due": "Angle: subscription expiry = loss-aversion hook. Quantify what merchant loses (views, calls, ONDC orders) if they don't renew. Peer anchor: what active merchants in same city get per month.",
    "gbp_unverified": "Angle: unverified GBP = Google suppresses the listing in AI search (ChatGPT, Gemini). Frame as missed AI-era visibility, not just maps. Offer to draft the verification request.",
    "winback_eligible": "Angle: merchant went dormant with Vera. Don't apologize. Lead with a specific new piece of data about their business they haven't seen. Curiosity lever.",
    "trial_followup": "Angle: merchant tried but didn't convert. Lead with the one metric that moved during trial (views, calls). Concrete ROI framing. Single YES/NO to continue.",
    "cde_opportunity": "Angle: CDE webinar = free learning + peer networking. Frame as 'your peers are attending — you'd be the only one in your locality not in the loop.' Social proof + FOMO.",
    "category_seasonal": "Angle: seasonal demand shift = operator insight most merchants miss. Counter-intuitive recommendation: what to do DIFFERENTLY this season vs what they'd normally do.",
    "milestone_reached": "Angle: milestone = social proof moment. Turn it into a Google post + WhatsApp broadcast to patients. Effort externalization: I'll draft both.",
    "curious_ask_due": "Angle: ask the merchant ONE specific question about their business this week. Promise to turn the answer into a ready-to-use artifact (Google post, WhatsApp reply template). Keep question hyper-specific to their category.",
    "competitor_opened": "Angle: new competitor nearby = voyeur curiosity + positioning opportunity. 'Want to see their listing and what they're offering?' Frame as intelligence, not threat.",
    "review_theme_emerged": "Angle: recurring review theme = direct feedback from customers. Frame as free market research. Draft a response template + a GBP post that addresses the theme positively.",
}


def _find_digest_item(category: dict, trigger: dict) -> Optional[dict]:
    """Find the relevant digest item for research triggers."""
    payload = trigger.get("payload", {})
    top_item_id = payload.get("top_item_id")

    # Check if digest item is inline in trigger payload
    if "top_item" in payload and isinstance(payload["top_item"], dict):
        return payload["top_item"]

    # Look up by ID in category digest
    if top_item_id:
        for item in category.get("digest", []):
            if item.get("id") == top_item_id:
                return item

    # Fall back to first digest item
    digest = category.get("digest", [])
    return digest[0] if digest else None


def _compute_derived(category: dict, merchant: dict) -> dict:
    """Compute derived facts to anchor specificity."""
    derived = {}

    # CTR vs peer
    peer_ctr = category.get("peer_stats", {}).get("avg_ctr", 0)
    merchant_ctr = merchant.get("performance", {}).get("ctr", 0)
    if peer_ctr and merchant_ctr:
        delta = ((merchant_ctr - peer_ctr) / peer_ctr) * 100
        derived["ctr_vs_peer"] = (
            f"{merchant_ctr:.3f} vs peer median {peer_ctr:.3f} ({delta:+.0f}%)"
        )

    # Lapsed revenue opportunity
    agg = merchant.get("customer_aggregate", {})
    lapsed = agg.get("lapsed_180d_plus", 0) or agg.get("lapsed_count", 0)
    active_offers = [o for o in merchant.get("offers", []) if o.get("status") == "active"]
    if lapsed and active_offers:
        prices = []
        for o in active_offers:
            try:
                prices.append(float(str(o.get("value", "0")).replace(",", "").replace("₹", "")))
            except (ValueError, TypeError):
                pass
        if prices:
            min_p = min(prices)
            derived["lapsed_revenue"] = f"₹{int(lapsed * min_p):,}/qtr ({lapsed} lapsed × ₹{int(min_p)})"

    # Language preference
    langs = merchant.get("identity", {}).get("languages", ["en"])
    derived["use_hindi"] = "hi" in langs

    return derived


def _build_context_block(
    category: dict,
    merchant: dict,
    trigger: dict,
    customer: Optional[dict],
    derived: dict,
) -> str:
    identity = merchant.get("identity", {})
    perf = merchant.get("performance", {})
    sub = merchant.get("subscription", {})
    agg = merchant.get("customer_aggregate", {})
    active_offers = [o for o in merchant.get("offers", []) if o.get("status") == "active"]
    voice = category.get("voice", {})
    trigger_kind = trigger.get("kind", "unknown")

    block = f"""
=== CATEGORY: {category.get('slug', 'unknown')} ===
Voice tone: {voice.get('tone', 'peer')}
Allowed vocab examples: {voice.get('vocab_allowed', [])[:6]}
TABOO WORDS (never use): {voice.get('vocab_taboo', []) or voice.get('taboos', [])}
Offer catalog (use these, not generic discounts): {[o.get('title') for o in category.get('offer_catalog', [])[:5]]}
Peer stats: avg_ctr={category.get('peer_stats', {}).get('avg_ctr', '?')}, avg_rating={category.get('peer_stats', {}).get('avg_rating', '?')}, avg_reviews={category.get('peer_stats', {}).get('avg_review_count', '?')}
Seasonal beats: {category.get('seasonal_beats', [])}
Trend signals: {category.get('trend_signals', [])}

=== MERCHANT ===
Name: {identity.get('name', 'Merchant')}
Owner first name: {identity.get('owner_first_name', '')} (use this to open message)
City: {identity.get('city', '')}, Locality: {identity.get('locality', '')}
Languages: {identity.get('languages', ['en'])} | Use Hindi-English mix: {derived.get('use_hindi', False)}
Subscription: {sub.get('status', '?')}, plan={sub.get('plan', '?')}, days_remaining={sub.get('days_remaining', '?')}
Performance (30d): views={perf.get('views', '?')}, calls={perf.get('calls', '?')}, ctr={perf.get('ctr', '?')}, directions={perf.get('directions', '?')}
7d delta: {perf.get('delta_7d', {})}
CTR vs peer: {derived.get('ctr_vs_peer', 'unknown')}
Active offers: {[o.get('title') for o in active_offers]}
Customer aggregate: total_unique_ytd={agg.get('total_unique_ytd', '?')}, lapsed_180d={agg.get('lapsed_180d_plus', '?')}, retention_6mo={agg.get('retention_6mo_pct', '?')}
Lapsed revenue opportunity: {derived.get('lapsed_revenue', 'unknown')}
Signals (use these as anchors): {merchant.get('signals', [])}
Recent conversation: {merchant.get('conversation_history', [])[-2:]}

=== TRIGGER ===
Kind: {trigger_kind}
Scope: {trigger.get('scope', 'merchant')}
Urgency: {trigger.get('urgency', 2)}/5
Suppression key: {trigger.get('suppression_key', '')}
Payload: {json.dumps(trigger.get('payload', {}))}
"""

    # Add digest item if relevant
    if trigger_kind in ("research_digest", "category_research_digest_release", "regulation_change"):
        item = _find_digest_item(category, trigger)
        if item:
            block += f"""
=== RESEARCH/DIGEST ITEM (anchor message on this — cite source) ===
Title: {item.get('title', '')}
Source: {item.get('source', '')}
Trial N: {item.get('trial_n', '')}
Patient segment: {item.get('patient_segment', '')}
Summary: {item.get('summary', '')}
Actionable: {item.get('actionable', '')}
"""

    if customer:
        cust_id = customer.get("identity", {})
        rel = customer.get("relationship", {})
        block += f"""
=== CUSTOMER (send_as must be "merchant_on_behalf") ===
Name: {cust_id.get('name', '')}
Language preference: {cust_id.get('language_pref', 'en')}
State: {customer.get('state', 'active')}
Last visit: {rel.get('last_visit', '')}
Visits total: {rel.get('visits_total', 0)}
Services received: {rel.get('services_received', [])}
Preferences: {customer.get('preferences', {})}
Consent scope: {customer.get('consent', {}).get('scope', [])}
"""

    return block


_base_fallbacks = [
    "google/gemini-2.0-flash-001",
    "google/gemma-4-26b-a4b-it:free",
    "openai/gpt-oss-120b:free",
    "google/gemma-3-12b-it:free",
]
# Primary model first, then fallbacks (deduplicated)
FALLBACK_MODELS = [MODEL] + [m for m in _base_fallbacks if m != MODEL]


def _call_llm(messages: list, timeout: int = 22) -> str:
    import time as _time
    last_err = None
    for model in FALLBACK_MODELS:
        body = json.dumps({
            "model": model,
            "messages": messages,
            "temperature": 0,
            "max_tokens": 500,
        }).encode("utf-8")

        req = urlrequest.Request(
            "https://openrouter.ai/api/v1/chat/completions",
            data=body,
            headers={
                "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://magicpin.com",
                "X-Title": "Vera Bot",
            },
        )
        try:
            resp = urlrequest.urlopen(req, timeout=timeout, context=_SSL_CONTEXT)
            data = json.loads(resp.read().decode("utf-8"))
            return data["choices"][0]["message"]["content"]
        except urlerror.HTTPError as e:
            last_err = e
            if e.code == 429:
                _time.sleep(2)
                continue  # try next model
            raise
        except Exception as e:
            last_err = e
            continue
    raise last_err or RuntimeError("All models failed")


def _parse_llm_json(raw: str) -> dict:
    match = re.search(r"\{[\s\S]*\}", raw)
    if match:
        return json.loads(match.group())
    return json.loads(raw)


def _validate(result: dict, trigger: dict, customer: Optional[dict]) -> dict:
    """Remove URLs, fill defaults, enforce send_as."""
    body = result.get("body", "")
    # Strip URLs (hard penalty)
    body = re.sub(r"https?://\S+", "", body).strip()
    result["body"] = body

    # send_as
    if customer:
        result["send_as"] = "merchant_on_behalf"
    else:
        result.setdefault("send_as", "vera")

    # suppression_key fallback
    if not result.get("suppression_key"):
        result["suppression_key"] = trigger.get("suppression_key", f"trigger:{trigger.get('id', 'unknown')}")

    result.setdefault("cta", "open_ended")
    result.setdefault("rationale", "Composed from trigger + merchant context.")
    return result


class Composer:
    async def compose_tick(
        self,
        category: dict,
        merchant: dict,
        trigger: dict,
        customer: Optional[dict],
        conv_id: str,
        merchant_id: str,
        customer_id: Optional[str],
        trigger_id: str,
    ) -> Optional[dict]:
        trigger_kind = trigger.get("kind", "unknown")
        mode = TRIGGER_MODE.get(trigger_kind, "assistant")
        mode_instruction = OPERATOR_MODE_INSTRUCTION if mode == "operator" else ASSISTANT_MODE_INSTRUCTION

        derived = _compute_derived(category, merchant)
        context_block = _build_context_block(category, merchant, trigger, customer, derived)

        # Get trigger-specific angle
        angle = TRIGGER_ANGLE.get(trigger_kind, "")
        angle_block = f"\nTRIGGER ANGLE: {angle}" if angle else ""

        user_prompt = f"""{mode_instruction}
{context_block}{angle_block}

Compose the WhatsApp message now.
- Open with owner first name (or merchant name if no first name)
- Anchor on ONE specific verifiable fact from the context (number, date, source, peer stat)
- Apply category voice + taboo rules strictly
- LANGUAGE: If use_hindi=True, write NATURAL Hindi-English code-mix (Hinglish). NOT pure Hindi. NOT pure English. Weave both in same sentences like real Indian WhatsApp. Example: "Dr. Meera, JIDA ka Oct issue aa gaya. Aapke high-risk patients ke liye — 38% better caries control. Want me to draft a patient WhatsApp? — JIDA Oct 2026 p.14"
- CTA in the very last sentence only
- Keep body under 120 words
- No URLs anywhere
- No fabricated data — only use what's in context above

Return valid JSON only."""

        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ]

        try:
            raw = _call_llm(messages)
            result = _parse_llm_json(raw)
            result = _validate(result, trigger, customer)

            return {
                "conversation_id": conv_id,
                "merchant_id": merchant_id,
                "customer_id": customer_id,
                "send_as": result["send_as"],
                "trigger_id": trigger_id,
                "template_name": f"vera_{trigger_kind}_v1",
                "template_params": [
                    merchant.get("identity", {}).get("owner_first_name")
                    or merchant.get("identity", {}).get("name", ""),
                    result.get("body", "")[:100],
                    result.get("cta", ""),
                ],
                "body": result["body"],
                "cta": result["cta"],
                "suppression_key": result["suppression_key"],
                "rationale": result["rationale"],
            }
        except Exception as exc:
            print(f"compose_tick error [{trigger_id}]: {exc}")
            return None

    async def compose_commitment_reply(
        self,
        merchant: dict,
        category: dict,
        merchant_message: str,
    ) -> dict:
        """Merchant committed — switch to action mode immediately."""
        identity = merchant.get("identity", {})
        active_offers = [o for o in merchant.get("offers", []) if o.get("status") == "active"]
        agg = merchant.get("customer_aggregate", {})
        voice = category.get("voice", {})
        langs = identity.get("languages", ["en"])
        use_hindi = "hi" in langs

        prompt = f"""Merchant just said: "{merchant_message}"

This is a COMMITMENT. Do NOT ask any qualifying questions. Execute immediately.

Merchant: {identity.get('name')}, owner: {identity.get('owner_first_name', '')}
Category: {category.get('slug', '')} | Voice: {voice.get('tone', 'peer')}
Active offers: {[o.get('title') for o in active_offers]}
Customer aggregate: lapsed={agg.get('lapsed_180d_plus', 0)}, total={agg.get('total_unique_ytd', 0)}
Use Hindi-English mix: {use_hindi}

Respond with:
1. Confirm you're executing NOW (1 sentence)
2. State exact artifact being created (e.g., "Drafting patient WhatsApp for your 78 lapsed patients...")
3. Give concrete scope (numbers, time)
4. Binary CONFIRM/CANCEL CTA

Return JSON: {{"action": "send", "body": "...", "cta": "binary_confirm_cancel", "rationale": "..."}}"""

        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ]
        try:
            raw = _call_llm(messages)
            result = _parse_llm_json(raw)
            body = re.sub(r"https?://\S+", "", result.get("body", "")).strip()
            return {
                "action": result.get("action", "send"),
                "body": body,
                "cta": result.get("cta", "binary_confirm_cancel"),
                "rationale": result.get("rationale", "Merchant committed; switched to action mode."),
            }
        except Exception as exc:
            print(f"compose_commitment_reply error: {exc}")
            owner = merchant.get("identity", {}).get("owner_first_name", "")
            lapsed = merchant.get("customer_aggregate", {}).get("lapsed_180d_plus", 0)
            offer = ""
            for o in merchant.get("offers", []):
                if o.get("status") == "active":
                    offer = o.get("title", "")
                    break
            fb_body = f"{'Dr. ' + owner if owner else 'Ji'}, shurou kar rahi hoon abhi."
            if lapsed and offer:
                fb_body += f" {lapsed} lapsed patients ke liye {offer} recall draft kar rahi hoon. Reply CONFIRM to proceed."
            else:
                fb_body += " Draft ready hoga 2 minutes mein. Reply CONFIRM to proceed."
            return {
                "action": "send",
                "body": fb_body,
                "cta": "binary_confirm_cancel",
                "rationale": "Commitment detected; action mode. Fallback with merchant-specific anchor.",
            }

    async def compose_customer_reply(
        self,
        merchant: dict,
        category: dict,
        customer: Optional[dict],
        customer_message: str,
        history: list,
    ) -> dict:
        """Reply to a customer message — MUST open with customer name, send_as=merchant_on_behalf."""
        customer_name = ""
        customer_lang = "en"
        if customer:
            customer_name = customer.get("identity", {}).get("name", "")
            customer_lang = customer.get("identity", {}).get("language_pref", "en")

        merchant_name = merchant.get("identity", {}).get("name", "")
        voice = category.get("voice", {})
        active_offers = [o for o in merchant.get("offers", []) if o.get("status") == "active"]

        history_text = "\n".join(
            [f"[{h['role']}]: {h['message']}" for h in history[-4:]]
        ) if history else "No prior turns."

        use_hindi = "hi" in customer_lang or "hi" in customer_lang.split("-")

        prompt = f"""A customer has replied in a booking/recall conversation managed by {merchant_name}.

CUSTOMER NAME: {customer_name}  ← OPEN YOUR REPLY WITH THIS NAME, not the merchant name
Customer language preference: {customer_lang}
Customer message: "{customer_message}"

Merchant: {merchant_name}
Category: {category.get('slug', '')} | Voice: {voice.get('tone', 'warm_clinical')}
Taboos: {voice.get('vocab_taboo', [])}
Active offers: {[o.get('title') for o in active_offers]}
Use Hindi-English mix: {use_hindi}

Recent conversation:
{history_text}

CRITICAL RULES:
- First word(s) MUST be the customer's name: "{customer_name}" — never open with merchant name
- send_as = "merchant_on_behalf" always
- No medical claims, no "guaranteed"
- Script consistency: if body is Hindi, keep dates/times in numerals only (no mixing Devanagari digits with English month names mid-sentence). Prefer: "Wed 5 Nov, 6pm" (full English) OR pure Hindi date. Not mixed scripts in same date token.
- Confirm the action requested by customer concretely (date, time, price)
- Keep under 40 words
- Single CTA in last sentence

Return JSON: {{"action": "send", "body": "...", "cta": "...", "send_as": "merchant_on_behalf", "rationale": "..."}}"""

        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ]
        try:
            raw = _call_llm(messages)
            result = _parse_llm_json(raw)
            body = re.sub(r"https?://\S+", "", result.get("body", "")).strip()
            result["send_as"] = "merchant_on_behalf"
            return {
                "action": result.get("action", "send"),
                "body": body,
                "cta": result.get("cta", "none"),
                "send_as": "merchant_on_behalf",
                "rationale": result.get("rationale", "Customer reply; opened with customer name."),
            }
        except Exception as exc:
            print(f"compose_customer_reply error: {exc}")
            fallback_body = f"{customer_name}, booking confirmed." if customer_name else "Booking confirmed."
            return {
                "action": "send",
                "body": fallback_body,
                "cta": "none",
                "send_as": "merchant_on_behalf",
                "rationale": "Fallback customer reply.",
            }

    async def compose_reply(
        self,
        merchant: dict,
        category: dict,
        merchant_message: str,
        history: list,
    ) -> dict:
        """General reply to merchant message."""
        identity = merchant.get("identity", {})
        voice = category.get("voice", {})
        langs = identity.get("languages", ["en"])
        use_hindi = "hi" in langs

        history_text = "\n".join(
            [f"[{h['role']}]: {h['message']}" for h in history[-4:]]
        ) if history else "First reply."

        prompt = f"""Merchant replied in an ongoing Vera conversation.

Merchant: {identity.get('name')}, Category: {category.get('slug', '')}
Voice: {voice.get('tone', 'peer')} | Taboos: {voice.get('vocab_taboo', []) or voice.get('taboos', [])}
Use Hindi-English mix: {use_hindi}

Recent conversation:
{history_text}

Merchant says: "{merchant_message}"

Rules:
- If out-of-scope ask (GST, legal, etc.): one-sentence decline + redirect to original topic
- If asking for data/info: provide from merchant context above
- If asking Vera to execute something: confirm doing it + concrete output
- Keep reply SHORT (2-3 sentences max)
- Match merchant's language register
- End with CTA only if there's a clear next action, otherwise cta="none"
- No URLs

Return JSON: {{"action": "send"|"wait"|"end", "body": "...", "cta": "...", "rationale": "..."}}"""

        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ]
        try:
            raw = _call_llm(messages)
            result = _parse_llm_json(raw)
            body = re.sub(r"https?://\S+", "", result.get("body", "")).strip()
            return {
                "action": result.get("action", "send"),
                "body": body,
                "cta": result.get("cta", "none"),
                "rationale": result.get("rationale", ""),
            }
        except Exception as exc:
            print(f"compose_reply error: {exc}")
            return {
                "action": "send",
                "body": "Samajh gayi. Ek second — checking your data.",
                "cta": "none",
                "rationale": "Fallback reply.",
            }
