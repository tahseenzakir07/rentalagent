"""Unit tests for the Inquiry Parser."""

from datetime import date
from app.agent.parser import MockInquiryParser, LLMInquiryParser
from app.schemas.inquiry import ParsedInquiry


def test_mock_parser_complete_inquiry():
    parser = MockInquiryParser()
    message = "Need a 20-ton excavator for 4 days starting 2026-11-12 at 1200 East 7th St, Austin TX. Standard open site access with certified operator on our crew. Our budget is $8,000."
    parsed = parser.parse(message)

    assert parsed.equipment_type == "Excavator"
    assert parsed.equipment_capacity == "20-ton"
    assert parsed.start_date == date(2026, 11, 12)
    assert parsed.duration_days == 4
    assert parsed.budget == 8000.0
    assert parsed.operator_required is False
    assert len(parsed.missing_fields) == 0


def test_mock_parser_missing_fields():
    parser = MockInquiryParser()
    message = "Looking to rent an excavator for our upcoming trenching project. Can you give us pricing and availability?"
    parsed = parser.parse(message)

    assert parsed.equipment_type == "Excavator"
    assert parsed.equipment_capacity is None
    assert parsed.start_date is None
    assert parsed.duration_days is None
    assert "start_date" in parsed.missing_fields
    assert "duration_days" in parsed.missing_fields
    assert "equipment_capacity" in parsed.missing_fields


def test_mock_parser_operator_required_true():
    parser = MockInquiryParser()
    message = "Need a 60-ft boom lift for 2 days starting 2026-11-10 in Austin TX. We need operator provided."
    parsed = parser.parse(message)

    assert parsed.equipment_type == "Boom Lift"
    assert parsed.equipment_capacity == "60-ft"
    assert parsed.operator_required is True


def test_mock_parser_site_risk_extraction():
    parser = MockInquiryParser()
    message = "Need a 20-ton excavator for 3 days starting 2026-11-15 in Austin TX. Narrow alley with 2.2 meters clearance next to power lines."
    parsed = parser.parse(message)

    assert parsed.site_access_details is not None
    assert "clearance" in parsed.site_access_details.lower() or "narrow" in parsed.site_access_details.lower()


def test_llm_parser_graceful_fallback():
    # LLM parser should fallback cleanly to Mock parser when no credentials are configured
    llm_parser = LLMInquiryParser()
    parsed = llm_parser.parse("Need a 5-ton mini excavator for 2 days starting 2026-11-01 in Austin TX.")

    assert parsed.equipment_type == "Mini Excavator"
    assert parsed.equipment_capacity == "5-ton"
    assert parsed.duration_days == 2


def test_parsed_inquiry_date_consistency_validator():
    # Test validator when end date is before start date
    inquiry = ParsedInquiry(
        start_date=date(2026, 11, 10),
        end_date=date(2026, 11, 5),
    )
    assert "end_date_before_start_date" in inquiry.uncertain_fields
