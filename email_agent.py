"""
email_agent.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Email Intelligence Agent — TrustAI instrumented demo

Pipeline:
  1. Intent Detection    → classify email intent
  2. Entity Extraction   → extract key entities
  3. Reply Automation    → generate a professional email reply

All 3 LLM calls are traced by TrustAI SDK and metrics appear
live in the dashboard at http://localhost:3000
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

import os
import sys
import json

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "trustai-sdk"))

import trustai
from openai import AzureOpenAI

# ── 1. Azure OpenAI Configuration (GPT-4o) ───────────────────────
def _require_env(name: str) -> str:
    """Returns a required environment variable or exits with a clear message (no secrets in code)."""
    value = os.getenv(name)
    if not value:
        sys.exit(f"Missing required environment variable {name}. Set it in your shell or .env file.")
    return value


AZURE_ENDPOINT   = _require_env("AZURE_OPENAI_ENDPOINT")
AZURE_API_KEY    = _require_env("AZURE_OPENAI_API_KEY")
AZURE_API_VERSION= "2025-01-01-preview"
DEPLOYMENT       = "gpt-4o"

# ── 2. TrustAI Configuration ─────────────────────────────────────
TRUSTAI_API_KEY    = os.getenv("TRUSTAI_API_KEY", "tai_live_demo_cooling_tower_12345")  # local demo key seeded by bootstrap_demo.py
TRUSTAI_PROJECT_ID = "6344c427-59fc-46eb-95ae-b1a3db9ea0b3"
TRUSTAI_INGEST_URL = "http://localhost:8001"

# ── 3. Hardcoded Input Email ──────────────────────────────────────
INPUT_EMAIL = """
Subject: Urgent — System Downtime Affecting Production

Hi Support Team,

I am writing on behalf of Nexcore Technologies (Account #NT-8821).
Our production system has been experiencing intermittent failures since
yesterday at 3:00 PM IST. The API gateway is returning 503 errors and
our data pipeline has completely stopped processing records.

This is a critical issue and is impacting our end customers directly.
We need an urgent response and a resolution timeline by end of today.

Best regards,
Rahul Mehta
CTO, Nexcore Technologies
rahul.mehta@nexcore.io
+91-98765-43210
"""

# ── 4. Initialize TrustAI SDK ─────────────────────────────────────
print("\n" + "="*60)
print("  TrustAI Email Intelligence Agent")
print("="*60)
print(f"[TrustAI] Project : {TRUSTAI_PROJECT_ID}")
print(f"[TrustAI] Ingest  : {TRUSTAI_INGEST_URL}")
print(f"[LLM]     Model   : {DEPLOYMENT} | {AZURE_ENDPOINT}")
print("="*60 + "\n")

trustai.init(
    api_key=TRUSTAI_API_KEY,
    project_id=TRUSTAI_PROJECT_ID,
    environment="production",
    ingest_url=TRUSTAI_INGEST_URL,
    content_capture_mode="full",
)

# ── 5. Build Azure OpenAI Client (API Key auth) ───────────────────
client = AzureOpenAI(
    azure_endpoint=AZURE_ENDPOINT,
    api_key=AZURE_API_KEY,
    api_version=AZURE_API_VERSION,
)


# ── 6. Instrumented Pipeline Steps ───────────────────────────────

@trustai.llm_call(model=DEPLOYMENT, provider="azure_openai", operation="intent_detection")
def detect_intent_llm(email: str):
    """Step 1: Classify the email intent."""
    print("[Step 1/3] Detecting email intent via GPT-4o...")
    response = client.chat.completions.create(
        model=DEPLOYMENT,
        messages=[
            {
                "role": "system",
                "content": (
                    "You are an email classification assistant. Analyze the email and "
                    "return a JSON object with these fields:\n"
                    "  intent: one of [complaint, inquiry, request, escalation, feedback, other]\n"
                    "  confidence: float 0-1\n"
                    "  priority: one of [low, medium, high, critical]\n"
                    "  summary: one-sentence summary of the email\n"
                    "Return ONLY valid JSON, no markdown formatting."
                ),
            },
            {"role": "user", "content": f"Email:\n{email}"},
        ],
        temperature=0.2,
    )
    return response


@trustai.llm_call(model=DEPLOYMENT, provider="azure_openai", operation="entity_extraction")
def extract_entities_llm(email: str):
    """Step 2: Extract key entities from the email."""
    print("[Step 2/3] Extracting entities via GPT-4o...")
    response = client.chat.completions.create(
        model=DEPLOYMENT,
        messages=[
            {
                "role": "system",
                "content": (
                    "You are an entity extraction assistant. Extract information from the email "
                    "and return a JSON object with these fields:\n"
                    "  sender_name: string or null\n"
                    "  sender_email: string or null\n"
                    "  sender_phone: string or null\n"
                    "  company: string or null\n"
                    "  account_id: string or null\n"
                    "  products_mentioned: list of strings\n"
                    "  issue_description: string\n"
                    "  dates_mentioned: list of strings\n"
                    "  urgency_keywords: list of strings\n"
                    "Return ONLY valid JSON, no markdown formatting."
                ),
            },
            {"role": "user", "content": f"Email:\n{email}"},
        ],
        temperature=0.2,
    )
    return response


@trustai.llm_call(model=DEPLOYMENT, provider="azure_openai", operation="reply_automation")
def generate_reply_llm(context_prompt: str):
    """Step 3: Generate a professional email reply."""
    print("[Step 3/3] Generating automated reply via GPT-4o...")
    response = client.chat.completions.create(
        model=DEPLOYMENT,
        messages=[
            {
                "role": "system",
                "content": (
                    "You are a professional customer support engineer. Write a clear, empathetic, "
                    "and action-oriented email reply. Acknowledge the issue, provide timeline, "
                    "and sign off professionally. Keep it concise (under 200 words)."
                ),
            },
            {"role": "user", "content": context_prompt},
        ],
        temperature=0.4,
    )
    return response


# ── 7. Orchestrator (parent agent span) ──────────────────────────

@trustai.agent("email_intelligence_agent")
def run_email_pipeline(email: str) -> dict:
    """Full email processing pipeline: intent -> entities -> reply."""

    with trustai.span("email_preprocessing", kind="tool") as sp:
        sp.tags["email_length"] = len(email)
        sp.tags["has_subject"] = "Subject:" in email
        sp.tags["word_count"] = len(email.split())
        print("  - Preprocessed email metadata.")

    # Step 1: Intent Detection
    intent_resp = detect_intent_llm(email)
    raw_intent = intent_resp.choices[0].message.content.strip().strip("```json").strip("```")
    try:
        intent = json.loads(raw_intent)
    except Exception:
        intent = {"intent": "escalation", "priority": "critical", "confidence": 0.9, "summary": raw_intent}
    print(f"  - Intent: {intent.get('intent', '').upper()} (Tokens: {intent_resp.usage.total_tokens})")

    # Step 2: Entity Extraction
    entity_resp = extract_entities_llm(email)
    raw_entity = entity_resp.choices[0].message.content.strip().strip("```json").strip("```")
    try:
        entities = json.loads(raw_entity)
    except Exception:
        entities = {"issue_description": raw_entity}
    print(f"  - Entities Extracted (Tokens: {entity_resp.usage.total_tokens})")

    # Step 3: Reply Generation
    context_prompt = (
        f"Context:\n"
        f"Intent: {intent.get('intent', 'unknown')} (Priority: {intent.get('priority', 'medium')})\n"
        f"Summary: {intent.get('summary', '')}\n"
        f"Sender: {entities.get('sender_name', 'Customer')} from {entities.get('company', 'Organization')}\n"
        f"Issue: {entities.get('issue_description', 'Incident')}\n\n"
        f"Original Email:\n{email}\n\n"
        f"Write the reply:"
    )
    reply_resp = generate_reply_llm(context_prompt)
    reply = reply_resp.choices[0].message.content.strip()
    print(f"  - Reply Generated (Tokens: {reply_resp.usage.total_tokens})")

    return {
        "intent":   intent,
        "entities": entities,
        "reply":    reply,
        "total_tokens": (intent_resp.usage.total_tokens + entity_resp.usage.total_tokens + reply_resp.usage.total_tokens),
    }


# ── 9. Run & Display Results ──────────────────────────────────────
if __name__ == "__main__":
    print("INPUT EMAIL:")
    print("-" * 60)
    print(INPUT_EMAIL.strip())
    print("-" * 60 + "\n")

    result = run_email_pipeline(INPUT_EMAIL)

    intent   = result["intent"]
    entities = result["entities"]
    reply    = result["reply"]

    print("\n" + "="*60)
    print("RESULTS")
    print("="*60)

    print("\n[INTENT DETECTION]")
    print(f"  Intent    : {intent.get('intent', 'unknown').upper()}")
    print(f"  Priority  : {intent.get('priority', 'medium').upper()}")
    print(f"  Confidence: {intent.get('confidence', 0):.0%}")
    print(f"  Summary   : {intent.get('summary', '')}")

    print("\n[ENTITY EXTRACTION]")
    for key, val in entities.items():
        if val:
            label = key.replace("_", " ").title()
            print(f"  {label:<24}: {val}")

    print("\n[AUTOMATED REPLY]")
    print("-" * 60)
    print(reply)
    print("-" * 60)

    print("\n[TrustAI] Flushing telemetry...")
    trustai.flush()
    print("[TrustAI] Done! 3 LLM spans sent to http://localhost:8001")
    print(f"[TrustAI] View metrics at: http://localhost:3000")
    print("="*60 + "\n")
