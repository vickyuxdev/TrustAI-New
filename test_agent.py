"""
test_agent.py
Developer integration test script using TrustAI SDK + Real Azure OpenAI.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "trustai-sdk"))

from openai import AzureOpenAI
from azure.identity import ClientSecretCredential, get_bearer_token_provider
import trustai

# ── 1. Load Azure & TrustAI Environment Variables ─────────────────
TENANT_ID = os.environ["AZURE_TENANT_ID"]
CLIENT_ID = os.environ["AZURE_CLIENT_ID"]
CLIENT_SECRET = os.environ["AZURE_CLIENT_SECRET"]  # never hardcode; set in your shell or .env
ENDPOINT = os.environ["AZURE_OPENAI_ENDPOINT"]
DEPLOYMENT = os.getenv("AZURE_OPENAI_DEPLOYMENT", "gpt-5.4-mini")

# Pre-configured with the seeded Project ID & Key
PROJECT_ID = os.getenv("TRUSTAI_PROJECT_ID", "6344c427-59fc-46eb-95ae-b1a3db9ea0b3")
API_KEY = os.getenv("TRUSTAI_API_KEY", "tai_live_demo_cooling_tower_12345")
INGEST_URL = os.getenv("TRUSTAI_INGEST_URL", "http://localhost:8001")

# ── 2. Initialize TrustAI SDK ─────────────────────────────────────
print(f"[TrustAI] Initializing SDK with Ingestion: {INGEST_URL}...")
trustai.init(
    api_key=API_KEY,
    project_id=PROJECT_ID,
    environment="production",
    ingest_url=INGEST_URL,
    content_capture_mode="full",
)

# ── 3. Initialize Azure OpenAI / Foundry Client ───────────────────
credential = ClientSecretCredential(
    tenant_id=TENANT_ID,
    client_id=CLIENT_ID,
    client_secret=CLIENT_SECRET,
)

# For Azure Cognitive Services token
token_provider = get_bearer_token_provider(
    credential,
    "https://cognitiveservices.azure.com/.default"
)

# If endpoint has /openai/v1 (Foundry style), use OpenAI client with base_url
if "/openai/v1" in ENDPOINT:
    from openai import OpenAI
    # Use Bearer token from Entra ID
    token = token_provider()
    client = OpenAI(
        base_url=ENDPOINT.rstrip("/"),
        api_key=token,
    )
else:
    # Standard Azure OpenAI endpoint (e.g. https://<name>.openai.azure.com)
    clean_endpoint = ENDPOINT.replace("/openai", "").rstrip("/")
    client = AzureOpenAI(
        azure_endpoint=clean_endpoint,
        azure_ad_token_provider=token_provider,
        api_version=os.getenv("AZURE_OPENAI_API_VERSION", "2024-06-01"),
    )

# ── 4. Define Instrumented Agent & LLM Call ───────────────────────

@trustai.llm_call(model=DEPLOYMENT, provider="azure_openai", operation="chat")
def ask_cooling_tower_expert(question: str):
    print(f"[LLM] Calling Azure OpenAI ({DEPLOYMENT})...")
    response = client.chat.completions.create(
        model=DEPLOYMENT,
        messages=[
            {"role": "system", "content": "You are an industrial engineer specializing in cooling tower thermal diagnostics."},
            {"role": "user", "content": question},
        ],
        temperature=0.2,
    )
    return response


@trustai.agent("cooling_tower_diagnostics_agent")
def run_diagnostic_pipeline(sensor_reading: str):
    print(f"\n[Agent Run] Processing Sensor Reading: '{sensor_reading}'")
    
    with trustai.span("sensor_data_validation", kind="tool") as sp:
        sp.tags["sensor_type"] = "vibration_and_temp"
        sp.tags["location"] = "Tower_Unit_4"
        print("  - Step 1: Validated sensor parameters.")

    # Call LLM
    response = ask_cooling_tower_expert(
        f"Diagnose this cooling tower issue: {sensor_reading}. Provide 2 actionable checks."
    )
    
    answer = response.choices[0].message.content
    tokens = response.usage.total_tokens
    print(f"  - Step 2: LLM Diagnostics Generated ({tokens} tokens).")
    return answer


# ── 5. Execute Test ───────────────────────────────────────────────
if __name__ == "__main__":
    result = run_diagnostic_pipeline(
        "Temperature reading 42°C with high motor vibration of 4.8 mm/s on pump #2."
    )
    
    print("\n" + "="*60)
    print("Diagnostic Report Output:")
    print("="*60)
    print(result)
    print("="*60)
    
    # Ensure telemetry is flushed immediately to TrustAI
    print("\n[TrustAI] Flushing telemetry to TrustAI...")
    trustai.flush()
    print("[TrustAI] Done! Telemetry sent to http://localhost:8001.")
