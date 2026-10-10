"""Tests for EquipmentAnalyzer in app/agent/analyse.py."""

import pytest
from app.agent.analyse import EquipmentAnalyzer
from app.agent.orchestrator import AgentOrchestrator
from app.data.repository import SQLiteRepository
from app.schemas.decision import DecisionEnum
from app.schemas.inquiry import InquiryRequest, ParsedInquiry


def test_equipment_analyzer_catalog_lookup(tmp_path):
    repo = SQLiteRepository(db_path=tmp_path / "test.db")
    analyzer = EquipmentAnalyzer(repo)

    # Known equipment types
    assert analyzer.is_catalog_equipment("Excavator") is True
    assert analyzer.is_catalog_equipment("Mini Excavator") is True
    assert analyzer.is_catalog_equipment("Boom Lift") is True
    assert analyzer.is_catalog_equipment("Bulldozer") is True

    # Unknown / unlisted equipment
    assert analyzer.is_catalog_equipment("Knife") is False
    assert analyzer.is_catalog_equipment("Generator") is False
    assert analyzer.is_catalog_equipment("Chainsaw") is False


def test_unlisted_equipment_knife_returns_not_found(tmp_path):
    repo = SQLiteRepository(db_path=tmp_path / "test.db")
    orchestrator = AgentOrchestrator(repository=repo)

    req = InquiryRequest(
        contractor_message="Do you have a knife available for rent?",
    )
    resp = orchestrator.evaluate_inquiry(req)

    assert resp.decision == DecisionEnum.REQUEST_INFO
    assert "Knife" in resp.decision_reason or "knife" in resp.decision_reason.lower() or "not available" in resp.decision_reason.lower()
    assert "not an equipment item we carry in our rental fleet" in resp.follow_up_message


def test_multi_turn_conversation_context_merging(tmp_path):
    repo = SQLiteRepository(db_path=tmp_path / "test.db")
    orchestrator = AgentOrchestrator(repository=repo)

    # Turn 1: Contractor specifies machine type
    turn1_msg = "I need a 20-ton excavator for rental."
    history = [{"role": "user", "content": turn1_msg}]

    # Turn 2: Contractor specifies location, dates, duration in follow-up
    turn2_req = InquiryRequest(
        contractor_message="In Austin, TX for 4 days starting 2026-11-12.",
        conversation_history=history,
    )

    resp = orchestrator.evaluate_inquiry(turn2_req)

    # Should retain "Excavator" and "20-ton" from Turn 1, matching all criteria -> AUTO_QUOTE
    assert resp.parsed_inquiry.equipment_type == "Excavator"
    assert resp.parsed_inquiry.equipment_capacity == "20-ton"
    assert resp.parsed_inquiry.location == "Austin, TX"
    assert resp.parsed_inquiry.duration_days == 4
    assert resp.decision == DecisionEnum.AUTO_QUOTE
