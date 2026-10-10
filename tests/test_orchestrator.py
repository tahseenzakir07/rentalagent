"""Unit and scenario tests for the Agent Orchestrator."""

from app.agent.orchestrator import AgentOrchestrator
from app.data.repository import SQLiteRepository
from app.schemas.decision import DecisionEnum
from app.schemas.inquiry import InquiryRequest


def test_scenario_1_complete_inquiry(tmp_path):
    repo = SQLiteRepository(db_path=tmp_path / "test.db")
    orchestrator = AgentOrchestrator(repository=repo)

    req = InquiryRequest(
        inquiry_id="test_scen_1",
        contractor_message="Need a 20-ton excavator for 4 days starting 2026-11-12 at 1200 East 7th St, Austin TX. Standard open site access with certified operator on our crew. Our budget is $8,000.",
        contractor_id="CON-101",
    )

    response = orchestrator.evaluate_inquiry(req)

    assert response.decision == DecisionEnum.AUTO_QUOTE
    assert response.estimated_quote is not None
    assert response.estimated_quote.total_estimated_amount > 0
    assert response.confidence_score >= 0.70
    assert not response.requires_human_approval

    # Check tool sequence
    tool_names = [t.tool_name for t in response.tool_calls]
    assert "check_availability" in tool_names
    assert "validate_criteria" in tool_names
    assert "calculate_price" in tool_names


def test_scenario_2_missing_details(tmp_path):
    repo = SQLiteRepository(db_path=tmp_path / "test.db")
    orchestrator = AgentOrchestrator(repository=repo)

    req = InquiryRequest(
        inquiry_id="test_scen_2",
        contractor_message="Looking to rent an excavator for our upcoming trenching project in Buda, TX. Can you give us pricing and availability?",
        contractor_id="CON-102",
    )

    response = orchestrator.evaluate_inquiry(req)

    assert response.decision == DecisionEnum.REQUEST_INFO
    assert response.estimated_quote is None
    # Crucial: Should NOT invoke pricing or availability tools when essential info is missing
    assert len(response.tool_calls) == 0
    assert response.follow_up_message is not None
    assert len(response.missing_information) > 0


def test_scenario_3_unavailable_equipment_counter_offer(tmp_path):
    repo = SQLiteRepository(db_path=tmp_path / "test.db")
    orchestrator = AgentOrchestrator(repository=repo)

    # EQ-CAT-320 is booked 2026-10-16 to 2026-10-24 in synthetic bookings.json
    req = InquiryRequest(
        inquiry_id="test_scen_3",
        contractor_message="Need a 20-ton excavator for 4 days from 2026-10-18 to 2026-10-22 at our Pflugerville jobsite.",
        contractor_id="CON-101",
    )

    response = orchestrator.evaluate_inquiry(req)

    assert response.decision == DecisionEnum.MANUAL_REVIEW
    assert response.requires_human_approval is True
    # Should have evaluated a counter-offer
    assert response.counter_offer is not None
    assert response.counter_offer.counter_type == "ALTERNATIVE_EQUIPMENT"
    assert response.counter_offer.verified_equipment_id is not None


def test_scenario_4_site_risk(tmp_path):
    repo = SQLiteRepository(db_path=tmp_path / "test.db")
    orchestrator = AgentOrchestrator(repository=repo)

    req = InquiryRequest(
        inquiry_id="test_scen_4",
        contractor_message="Need a 20-ton excavator for 3 days starting 2026-11-15 in downtown Austin. The site access is through a very narrow alley with only 2.2 meters clearance next to active overhead power lines with a steep slope.",
        contractor_id="CON-102",
    )

    response = orchestrator.evaluate_inquiry(req)

    assert response.decision == DecisionEnum.MANUAL_REVIEW
    assert response.requires_human_approval is True
    assert response.estimated_quote is None

    # Check criteria tool was executed and failed
    tool_names = [t.tool_name for t in response.tool_calls]
    assert "validate_criteria" in tool_names
    # Pricing should have been skipped after criteria failure
    assert "calculate_price" not in tool_names


def test_scenario_5_budget_constraint(tmp_path):
    repo = SQLiteRepository(db_path=tmp_path / "test.db")
    orchestrator = AgentOrchestrator(repository=repo)

    req = InquiryRequest(
        inquiry_id="test_scen_5",
        contractor_message="Looking to rent a 20-ton excavator for 5 days starting 2026-11-20 in San Marcos. Our maximum total budget is strictly capped at $1,800.",
        contractor_id="CON-102",
    )

    response = orchestrator.evaluate_inquiry(req)

    assert response.decision == DecisionEnum.MANUAL_REVIEW
    assert response.counter_offer is not None
    assert response.counter_offer.counter_type == "REQUIREMENT_RELAXATION"


def test_scenario_6_tool_failure_fails_closed(tmp_path):
    repo = SQLiteRepository(db_path=tmp_path / "test.db")
    orchestrator = AgentOrchestrator(repository=repo)

    req = InquiryRequest(
        inquiry_id="test_scen_6",
        contractor_message="Need a 60-ft boom lift for 2 days starting 2026-11-10 in Kyle, TX.",
        metadata={"simulate_tool_error": True},
    )

    response = orchestrator.evaluate_inquiry(req)

    assert response.decision == DecisionEnum.MANUAL_REVIEW
    assert response.requires_human_approval is True
    assert response.estimated_quote is None
    # Tool failure was captured in tool calls
    assert any(not t.success for t in response.tool_calls)


def test_confidence_score_bounds(tmp_path):
    repo = SQLiteRepository(db_path=tmp_path / "test.db")
    orchestrator = AgentOrchestrator(repository=repo)

    req = InquiryRequest(
        contractor_message="Need a 20-ton excavator for 4 days starting 2026-11-12 in Austin TX.",
    )
    response = orchestrator.evaluate_inquiry(req)

    assert 0.0 <= response.confidence_score <= 1.0
    assert response.confidence_explanation is not None


def test_offline_operation_without_credentials(tmp_path):
    repo = SQLiteRepository(db_path=tmp_path / "test.db")
    orchestrator = AgentOrchestrator(repository=repo)

    req = InquiryRequest(
        contractor_message="Need a 20-ton excavator for 4 days starting 2026-11-12 in Austin TX.",
    )
    response = orchestrator.evaluate_inquiry(req)

    # Must operate in SIMULATED mode without external credentials
    assert response.execution_mode.value == "SIMULATED"
    assert response.decision in [DecisionEnum.AUTO_QUOTE, DecisionEnum.MANUAL_REVIEW, DecisionEnum.REQUEST_INFO]


def test_tool_call_sequences_are_context_dependent(tmp_path):
    repo = SQLiteRepository(db_path=tmp_path / "test.db")
    orchestrator = AgentOrchestrator(repository=repo)

    # 1. Complete inquiry -> executes availability, criteria, pricing
    req_complete = InquiryRequest(
        inquiry_id="seq_1",
        contractor_message="Need a 20-ton excavator for 4 days starting 2026-11-12 at 1200 East 7th St, Austin TX. Budget $8,000.",
    )
    resp_complete = orchestrator.evaluate_inquiry(req_complete)
    seq_complete = [t.tool_name for t in resp_complete.tool_calls]

    # 2. Incomplete inquiry -> executes NO tools (skips immediately to clarification)
    req_missing = InquiryRequest(
        inquiry_id="seq_2",
        contractor_message="Looking to rent an excavator in Buda, TX.",
    )
    resp_missing = orchestrator.evaluate_inquiry(req_missing)
    seq_missing = [t.tool_name for t in resp_missing.tool_calls]

    # 3. Schedule conflict inquiry -> executes availability only (stops before pricing)
    req_conflict = InquiryRequest(
        inquiry_id="seq_3",
        contractor_message="Need a 20-ton excavator for 4 days from 2026-10-18 to 2026-10-22 at our Pflugerville jobsite.",
    )
    resp_conflict = orchestrator.evaluate_inquiry(req_conflict)
    seq_conflict = [t.tool_name for t in resp_conflict.tool_calls]

    # Tool sequences MUST be distinct
    assert seq_complete == ["check_availability", "validate_criteria", "calculate_price"]
    assert seq_missing == []
    assert seq_conflict == ["check_availability"]
    assert seq_complete != seq_missing
    assert seq_complete != seq_conflict


def test_same_equipment_cheapest_eligible_option_with_budget(tmp_path):
    repo = SQLiteRepository(db_path=tmp_path / "test.db")
    orchestrator = AgentOrchestrator(repository=repo)

    req = InquiryRequest(
        inquiry_id="budget_daily_1",
        contractor_message="Need a 20-ton excavator for 2 days starting 2026-11-12 in Austin, TX. Budget is ₹5,000 per day. Self-pickup with a licensed operator.",
        contractor_id="CON-101",
    )

    response = orchestrator.evaluate_inquiry(req)

    assert response.decision == DecisionEnum.AUTO_QUOTE
    assert response.estimated_quote is not None
    assert response.estimated_quote.company_name == "BuildPro Equipment Solutions"
    assert response.estimated_quote.daily_rate <= 5000


def test_morning_slot_conflict_offers_evening_alternative(tmp_path):
    repo = SQLiteRepository(db_path=tmp_path / "test.db")
    orchestrator = AgentOrchestrator(repository=repo)

    req = InquiryRequest(
        inquiry_id="slot_conflict_1",
        contractor_message="Need a 20-ton excavator for 4 days starting 2026-10-18 at 9 AM in Pflugerville, TX.",
        contractor_id="CON-101",
    )

    response = orchestrator.evaluate_inquiry(req)

    assert response.decision == DecisionEnum.MANUAL_REVIEW
    assert response.counter_offer is not None
    assert response.counter_offer.counter_type == "TIME_SLOT_SHIFT"
    assert "5 PM" in response.follow_up_message or "Evening" in response.follow_up_message


def test_pickup_without_license_adds_hourly_operator_fee(tmp_path):
    repo = SQLiteRepository(db_path=tmp_path / "test.db")
    orchestrator = AgentOrchestrator(repository=repo)

    req = InquiryRequest(
        inquiry_id="pickup_no_license_1",
        contractor_message="Need a 20-ton excavator for 2 days starting 2026-11-12 in San Marcos, TX. Self-pickup. No licensed operator on our crew.",
        contractor_id="CON-101",
    )

    response = orchestrator.evaluate_inquiry(req)

    assert response.decision == DecisionEnum.AUTO_QUOTE
    assert response.estimated_quote is not None
    assert response.estimated_quote.transport_fee == 0.0
    assert response.estimated_quote.operator_fee > 0


def test_no_budget_prompts_for_budget_instead_of_manual_review(tmp_path):
    repo = SQLiteRepository(db_path=tmp_path / "test.db")
    orchestrator = AgentOrchestrator(repository=repo)

    req = InquiryRequest(
        inquiry_id="budget_missing_1",
        contractor_message="Need a 20-ton excavator for 2 days starting 2026-11-12 in Austin, TX. Self-pickup with a licensed operator.",
        contractor_id="CON-103",
    )

    response = orchestrator.evaluate_inquiry(req)

    assert response.decision == DecisionEnum.REQUEST_INFO
    assert "budget" in response.follow_up_message.lower()
    assert "manual review" not in response.follow_up_message.lower()


def test_budget_exceedance_prompts_requirement_relaxation_when_no_company_fits(tmp_path):
    repo = SQLiteRepository(db_path=tmp_path / "test.db")
    orchestrator = AgentOrchestrator(repository=repo)

    req = InquiryRequest(
        inquiry_id="budget_relax_1",
        contractor_message="Need a 20-ton excavator for 2 days starting 2026-11-12 in Austin, TX. Budget is $250.",
        contractor_id="CON-102",
    )

    response = orchestrator.evaluate_inquiry(req)

    assert response.decision == DecisionEnum.MANUAL_REVIEW
    assert response.counter_offer is not None
    assert response.counter_offer.counter_type == "REQUIREMENT_RELAXATION"
    assert "budget" in response.follow_up_message.lower()

