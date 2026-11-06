# TrustAI Python SDK

Zero-friction GenAI observability, distributed tracing, and cost monitoring for Python AI applications.

---

## 🚀 Quickstart

### 1. Installation

```bash
pip install ./trustai-sdk
```

### 2. Basic Usage

```python
from openai import AzureOpenAI
import trustai

# Initialize once at application startup
trustai.init(
    api_key="tai_live_your_project_key",
    project_id="your-project-uuid",
    environment="production",
    ingest_url="http://localhost:8001",
    content_capture_mode="masked", # "full" | "masked" | "disabled"
)

client = AzureOpenAI(
    azure_endpoint="https://your-resource.openai.azure.com/",
    api_key="your-key",
    api_version="2024-08-01-preview"
)

# Automatically extracts tokens, cost, latency, and masked messages
@trustai.llm_call(model="gpt-4o", provider="azure_openai")
def call_llm(prompt: str):
    return client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": prompt}]
    )

# Automatically creates a root agent trace span
@trustai.agent("customer_support_agent")
def run_agent(query: str):
    response = call_llm(query)
    return response.choices[0].message.content

# Run
answer = run_agent("How can I track LLM costs?")
print(answer)
```

---

## 📚 Complete Documentation

For the full developer guide including:
- **Decorators (`@trustai.agent`, `@trustai.llm_call`, `@trustai.trace`)**
- **Context Manager (`with trustai.span(...)`)**
- **Explicit Lifecycle API for Custom & Multi-Turn Agents**
- **RAG & Tool Instrumentation Examples**
- **Privacy & PII Masking Modes**
- **Production Best Practices & Checklist**

👉 Please refer to the [TrustAI SDK Developer Guide](../docs/TRUSTAI_SDK_DEVELOPER_GUIDE.md).