"""Unit tests for the Decision Engine and Qualification Scorecard."""

from datetime import date
from app.agent.decision_engine import DecisionEngine
from app.schemas.decision import CheckStatus, CriticalityLevel, DecisionEnum
from app.schemas.inquiry import ParsedInquiry
from app.tools.interfaces import ToolResult


def test_decision_auto_quote():
    engine = DecisionEngine()
    inquiry = ParsedInquiry(
        equipment_type="Excavator",
        equipment_capacity="20-ton",
        start_date=date(2026, 11, 12),
        duration_days=4,
        location="Austin, TX",
        operator_required=False,
    )

    avail_res = ToolResult(
        success=True,
        data={"equipment_id": "EQ-CAT-320", "model_name": "Caterpillar 320 GC"},
        evidence="Equipment verified available.",
        source="inventory_db",
    )
    criteria_res = ToolResult(
        success=True,
        data={},
        evidence="All site criteria passed.",
        source="criteria_engine",
    )
    pricing_res = ToolResult(
        success=True,
        data={
            "equipment_id": "EQ-CAT-320",
            "equipment_name": "Caterpillar 320 GC",
            "duration_days": 4,
            "daily_rate": 1100.0,
            "base_amount": 4400.0,
            "transport_fee": 250.0,
            "taxes_and_fees": 383.62,
            "total_estimated_amount": 5033.62,
            "line_items": [],
            "is_over_budget": False,
        },
        evidence="Calculated valid quote.",
        source="rate_matrix",
    )

    decision, reason, score, checks, missing, quote, follow_up, req_approval = engine.evaluate(
        parsed_inquiry=inquiry,
        availability_result=avail_res,
        pricing_result=pricing_res,
        criteria_result=criteria_res,
    )

    assert decision == DecisionEnum.AUTO_QUOTE
    assert quote is not None
    assert quote.total_estimated_amount == 5033.62
    assert score >= 85.0
    assert not req_approval


def test_decision_request_info():
    engine = DecisionEngine()
    inquiry = ParsedInquiry(
        equipment_type="Excavator",
        missing_fields=["start_date", "duration_days", "equipment_capacity"],
    )

    decision, reason, score, checks, missing, quote, follow_up, req_approval = engine.evaluate(
        parsed_inquiry=inquiry,
    )

    assert decision == DecisionEnum.REQUEST_INFO
    assert quote is None
    assert "start_date" in missing
    assert not req_approval
    assert follow_up is not None
    assert "start date" in follow_up.lower()


def test_decision_manual_review_on_site_hazard():
    engine = DecisionEngine()
    inquiry = ParsedInquiry(
        equipment_type="Excavator",
        equipment_capacity="20-ton",
        start_date=date(2026, 11, 15),
        duration_days=3,
        location="Austin, TX",
        site_access_details="narrow alley with only 2.2 meters clearance next to power lines",
    )

    avail_res = ToolResult(success=True, data={}, evidence="Unit available", source="inventory")
    criteria_res = ToolResult(
        success=False,
        data={"violations": ["Site clearance is 2.2m, requires min 3.5m"]},
        evidence="Criteria validation FAILED: clearance width too narrow",
        source="criteria_engine",
    )

    decision, reason, score, checks, missing, quote, follow_up, req_approval = engine.evaluate(
        parsed_inquiry=inquiry,
        availability_result=avail_res,
        criteria_result=criteria_res,
    )

    assert decision == DecisionEnum.MANUAL_REVIEW
    assert req_approval is True
    assert quote is None
    assert "safety" in reason.lower() or "clearance" in reason.lower()


def test_critical_policy_precedence_high_score_cannot_override():
    engine = DecisionEngine()
    inquiry = ParsedInquiry(
        equipment_type="Excavator",
        equipment_capacity="20-ton",
        start_date=date(2026, 11, 15),
        duration_days=3,
        location="Austin, TX",
    )

    # Simulate availability collision
    avail_res = ToolResult(
        success=False,
        data={"conflict": "Booked"},
        evidence="Equipment is booked on another project.",
        source="inventory",
    )

    decision, reason, score, checks, missing, quote, follow_up, req_approval = engine.evaluate(
        parsed_inquiry=inquiry,
        availability_result=avail_res,
    )

    # Even if some checks passed, a critical check failing MUST yield MANUAL_REVIEW
    assert decision == DecisionEnum.MANUAL_REVIEW
    assert req_approval is True
    critical_failed = any(c.criticality == CriticalityLevel.CRITICAL and c.status == CheckStatus.FAIL for c in checks)
    assert critical_failed
