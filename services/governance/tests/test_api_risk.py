"""Integration + unit tests: risk templates, tiering, workflow and human decisions."""
from __future__ import annotations

import httpx

from app.services.risk import answers_from_facts, classify
from tests.conftest import FACTORY

API = "/api/v1"
FACTORY_FACTS = {
    "system_type": "agentic workflow", "industry": "Manufacturing - accounts payable / finance",
    "autonomy_level": "conditional", "write_actions": ["schedule_payment", "delete_vendor"],
    "approval_required_actions": ["schedule_payment"], "denied_actions": ["delete_vendor"],
    "handles_pii": True, "regulatory_scope": ["GDPR", "SOX"], "integrations": ["SAP", "Outlook"],
    "built_by": "RandomTrees AI Factory",
}


def test_facts_map_to_answers_with_provenance() -> None:
    answers, prov = answers_from_facts(FACTORY_FACTS)
    assert answers["purpose.domain"] == "finance" and answers["actions.financial"] is True
    assert answers["actions.approval_gates"] is True  # schedule_payment gated, delete_vendor denied (can never run)
    ungated, _ = answers_from_facts({**FACTORY_FACTS, "write_actions": ["schedule_payment", "send_email"]})
    assert ungated["actions.approval_gates"] is False  # send_email is a real ungated write
    thresholds, _ = answers_from_facts({**FACTORY_FACTS, "approval_required_actions": [],
                                        "threshold_gated_actions": ["schedule_payment"]})
    assert thresholds["actions.approval_gates"] is True
    assert answers["data.regulatory_scope"] == ["gdpr", "sox"] and answers["oversight.audit_logging"] is True
    assert "write_actions" in prov["actions.write_actions"]


def test_tiering_is_explainable_and_has_floors() -> None:
    low = classify({"purpose.domain": "general", "purpose.decision_impact": "informational", "autonomy.level": "assistive",
                    "actions.write_actions": False, "actions.irreversible": False, "data.personal_data": False,
                    "users.audience": "internal_employees", "users.scale": "lt_100", "integration.external_systems": 0,
                    "oversight.human_in_loop": True, "oversight.audit_logging": True})
    assert low["tier"] == 1 and "PII Strict" not in " ".join(low["required_controls"])
    prohibited = classify({"purpose.prohibited_practice": True})
    assert prohibited["tier"] == 4 and prohibited["floors"]
    annex = classify({"purpose.domain": "hr_employment", "purpose.decision_impact": "decides_with_review",
                      "autonomy.level": "assistive", "actions.write_actions": False, "data.personal_data": False,
                      "users.audience": "internal_employees", "oversight.human_in_loop": True})
    assert annex["tier"] >= 3 and any("Annex III" in f for f in annex["floors"])


async def test_template_and_one_shot_assessment(client: httpx.AsyncClient, agent: dict) -> None:
    tpl = (await client.get(f"{API}/risk/templates/trustai_build_v1")).json()
    assert tpl["frameworks"][0] == "EU AI Act" and len(tpl["tiers"]) == 4
    assert (await client.get(f"{API}/risk/templates/other")).status_code == 404
    res = await client.post(f"{API}/risk/assess", headers=FACTORY,
                            json={"external_id": agent["external_id"], "facts": FACTORY_FACTS})
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["status"] == "classified" and body["risk_tier"] >= 3 and body["decision"] is None
    assert body["evidence"]["assumptions"] and body["required_controls"]
    refreshed = (await client.get(f"{API}/agents/{agent['id']}", headers=FACTORY)).json()
    assert refreshed["risk_tier"] == body["risk_tier"] and refreshed["lifecycle_status"] == "assessed"


async def test_draft_workflow_and_human_decision(client: httpx.AsyncClient, agent: dict) -> None:
    draft = (await client.post(f"{API}/assessments", headers=FACTORY,
                               json={"agent_id": agent["id"], "answers": {"purpose.domain": "finance"}})).json()
    assert draft["status"] == "draft" and draft["validation"]["missing"]
    aid = draft["id"]
    incomplete = await client.post(f"{API}/assessments/{aid}/submit", headers=FACTORY)
    assert incomplete.status_code == 422 and incomplete.json()["detail"]["missing"]
    bad = await client.put(f"{API}/assessments/{aid}/answers", headers=FACTORY, json={"answers": {"autonomy.level": "rogue"}})
    assert bad.json()["validation"]["errors"]
    await client.put(f"{API}/assessments/{aid}/answers", headers=FACTORY, json={"answers": {"autonomy.level": "supervised"}})
    validation = (await client.post(f"{API}/assessments/{aid}/validate", headers=FACTORY)).json()
    assert validation["valid"] is False
    submitted = (await client.post(f"{API}/assessments/{aid}/submit", params={"fill_defaults": True}, headers=FACTORY)).json()
    assert submitted["status"] == "classified"
    reclassified = await client.post(f"{API}/assessments/{aid}/classify", headers=FACTORY)
    assert reclassified.json()["risk_tier"] == submitted["risk_tier"]

    machine = await client.post(f"{API}/assessments/{aid}/decision", headers=FACTORY, json={"decision": "approved"})
    assert machine.status_code == 403
    no_conditions = await client.post(f"{API}/assessments/{aid}/decision", json={"decision": "approved_with_conditions"})
    assert no_conditions.status_code == 422
    decided = (await client.post(f"{API}/assessments/{aid}/decision",
                                 json={"decision": "approved_with_conditions", "conditions": ["weekly review"]})).json()
    assert decided["status"] == "decided" and decided["decided_by"] == "dev-admin@trustai.local"
    frozen = await client.put(f"{API}/assessments/{aid}/answers", json={"answers": {"autonomy.level": "assistive"}})
    assert frozen.status_code == 409
    listed = (await client.get(f"{API}/assessments", params={"agent_id": agent["id"]}, headers=FACTORY)).json()
    assert [a["id"] for a in listed] == [aid]
    assert (await client.get(f"{API}/assessments/{aid}", headers=FACTORY)).json()["conditions"] == ["weekly review"]
