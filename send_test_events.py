"""
send_test_events.py
Sends synthetic LLM telemetry directly to the App Insights REST endpoint.
No SDK required — only uses 'requests' (pip install requests).

Run: python send_test_events.py
"""
import json
import os
import random
import time
import uuid
from datetime import datetime, timezone

import requests

# ── Config ───────────────────────────────────────────────────────────────────
INSTRUMENTATION_KEY = os.environ["APPLICATIONINSIGHTS_INSTRUMENTATION_KEY"]  # from the App Insights resource
INGESTION_URL       = "https://eastus-8.in.applicationinsights.azure.com/v2/track"

# ── Synthetic data ────────────────────────────────────────────────────────────
MODELS = [
    ("gpt-4o",      2.50, 10.00),
    ("gpt-4o-mini", 0.15,  0.60),
    ("gpt-4",      30.00, 60.00),
]

def make_event(model: str, in_tok: int, out_tok: int, duration: float, cost: float, success: bool) -> dict:
    """Build an App Insights custom event in the v2/track wire format."""
    return {
        "name": f"Microsoft.ApplicationInsights.{INSTRUMENTATION_KEY}.Event",
        "time": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z",
        "iKey": INSTRUMENTATION_KEY,
        "tags": {
            "ai.cloud.roleInstance": "trustai-test",
            "ai.operation.id": str(uuid.uuid4()).replace("-", ""),
        },
        "data": {
            "baseType": "EventData",
            "baseData": {
                "ver": 2,
                "name": "llm_call",          # TrustAI KQL: where name in ("llm_call", "trustai_span")
                "properties": {
                    "model_name":    model,
                    "input_tokens":  str(in_tok),
                    "output_tokens": str(out_tok),
                    "duration_ms":   str(round(duration, 2)),
                    "cost_usd":      str(round(cost, 8)),
                    "success":       "true" if success else "false",
                    "provider":      "azure_openai",
                },
                "measurements": {
                    "input_tokens":  in_tok,
                    "output_tokens": out_tok,
                    "duration_ms":   duration,
                    "cost_usd":      cost,
                },
            },
        },
    }

# ── Send events ───────────────────────────────────────────────────────────────
print(f"Sending 10 synthetic LLM events to App Insights...\n")

batch = []
for i in range(10):
    model, in_price, out_price = random.choice(MODELS)
    in_tok   = random.randint(200, 2000)
    out_tok  = random.randint(50,  600)
    duration = random.uniform(600, 5000)
    success  = random.random() > 0.1
    cost     = (in_tok * in_price + out_tok * out_price) / 1_000_000

    batch.append(make_event(model, in_tok, out_tok, duration, cost, success))

    status = "OK  " if success else "FAIL"
    print(f"  [{status}] Event {i+1:02d} | {model:<14} | "
          f"in={in_tok:>4} out={out_tok:>3} tok | "
          f"{round(duration):>4}ms | ${cost:.6f}")

# Send all 10 in one batch request
resp = requests.post(
    INGESTION_URL,
    headers={"Content-Type": "application/json"},
    data=json.dumps(batch),
    timeout=15,
)

print(f"\nHTTP {resp.status_code} — {resp.text[:200] or 'OK'}")

if resp.status_code in (200, 206):
    print("""
============================================================
  10 events sent successfully!
============================================================

Next steps:
1. Wait 2-5 min for Azure to ingest them.

2. Verify in Azure Portal -> App Insights -> Logs:
     customEvents
     | where name == "llm_call"
     | project timestamp, name, customDimensions
     | order by timestamp desc
     | take 20

3. Trigger immediate TrustAI sync (PowerShell):
     $connId = "c744075b-2b4b-4f1b-a556-3b6d77b03c78"
     Invoke-RestMethod -Method POST `
       -Uri "http://localhost:8003/api/v1/connectors/$connId/sync" `
       -ContentType "application/json" | ConvertTo-Json

4. Open dashboard: http://localhost:3000
============================================================
""")
else:
    print(f"\nWarning: Unexpected status {resp.status_code}")
    print(resp.text)
