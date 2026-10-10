"""Unit tests for the Repository and SQLite Persistence layer."""

from datetime import date
from app.data.repository import SQLiteRepository
from app.schemas.decision import CheckStatus, DecisionEnum, DecisionResponse, QualificationCheck
from app.schemas.inquiry import InquiryRequest, ParsedInquiry


def test_repository_initialization_and_master_data(tmp_path):
    repo = SQLiteRepository(db_path=tmp_path / "test.db")

    equipment = repo.get_equipment()
    assert len(equipment) > 0

    excavators = repo.get_equipment(equipment_type="Excavator")
    assert any("320" in e["model_name"] for e in excavators)

    provider = repo.get_provider("PROV-001")
    assert provider is not None
    assert provider["company_name"] == "Apex Heavy Equipment Rentals"

    bookings = repo.get_bookings()
    assert len(bookings) > 0


def test_save_and_retrieve_evaluation(tmp_path):
    repo = SQLiteRepository(db_path=tmp_path / "test.db")

    req = InquiryRequest(
        inquiry_id="inq_persist_001",
        contractor_message="Need 20-ton excavator for 4 days.",
        contractor_id="CON-101",
    )
    parsed = ParsedInquiry(equipment_type="Excavator", duration_days=4)
    resp = DecisionResponse(
        inquiry_id="inq_persist_001",
        decision=DecisionEnum.AUTO_QUOTE,
        decision_reason="All checks passed.",
        parsed_inquiry=parsed,
        qualification_score=92.5,
        qualification_checks=[
            QualificationCheck(name="TEST_CHECK", status=CheckStatus.PASS, explanation="Passed test.")
        ],
        missing_information=[],
        confidence_score=0.88,
        requires_human_approval=False,
    )

    repo.save_inquiry_evaluation(resp, req)

    retrieved = repo.get_inquiry_evaluation("inq_persist_001")
    assert retrieved is not None
    assert retrieved["inquiry_id"] == "inq_persist_001"
    assert retrieved["response"]["decision"] == "AUTO_QUOTE"
    assert retrieved["response"]["qualification_score"] == 92.5


def test_duplicate_inquiry_id_handling(tmp_path):
    repo = SQLiteRepository(db_path=tmp_path / "test.db")

    req = InquiryRequest(
        inquiry_id="inq_dup_001",
        contractor_message="First inquiry version",
    )
    parsed = ParsedInquiry(equipment_type="Excavator")
    resp_v1 = DecisionResponse(
        inquiry_id="inq_dup_001",
        decision=DecisionEnum.REQUEST_INFO,
        decision_reason="Missing dates.",
        parsed_inquiry=parsed,
        qualification_score=50.0,
        missing_information=["start_date"],
        confidence_score=0.6,
        requires_human_approval=False,
    )
    repo.save_inquiry_evaluation(resp_v1, req)

    # Re-submit with updated decision
    resp_v2 = DecisionResponse(
        inquiry_id="inq_dup_001",
        decision=DecisionEnum.AUTO_QUOTE,
        decision_reason="Dates now provided.",
        parsed_inquiry=parsed,
        qualification_score=95.0,
        missing_information=[],
        confidence_score=0.9,
        requires_human_approval=False,
    )
    repo.save_inquiry_evaluation(resp_v2, req)

    # Verify record was updated in-place, NOT duplicated
    history = repo.list_inquiry_evaluations()
    matching = [h for h in history if h["inquiry_id"] == "inq_dup_001"]
    assert len(matching) == 1
    assert matching[0]["decision"] == "AUTO_QUOTE"


def test_quotes_do_not_alter_inventory_or_bookings(tmp_path):
    repo = SQLiteRepository(db_path=tmp_path / "test.db")

    initial_bookings_count = len(repo.get_bookings())
    initial_equipment = repo.get_equipment()

    # Simulate quote saving
    req = InquiryRequest(
        inquiry_id="inq_no_booking_mod",
        contractor_message="Testing quote generation does not book unit.",
    )
    resp = DecisionResponse(
        inquiry_id="inq_no_booking_mod",
        decision=DecisionEnum.AUTO_QUOTE,
        decision_reason="Auto quote simulated.",
        parsed_inquiry=ParsedInquiry(equipment_type="Excavator"),
        qualification_score=90.0,
        confidence_score=0.85,
        requires_human_approval=False,
    )
    repo.save_inquiry_evaluation(resp, req)

    # Bookings and equipment counts MUST remain unchanged
    after_bookings_count = len(repo.get_bookings())
    after_equipment = repo.get_equipment()

    assert initial_bookings_count == after_bookings_count
    assert len(initial_equipment) == len(after_equipment)


def test_delete_inquiry_evaluation(tmp_path):
    repo = SQLiteRepository(db_path=tmp_path / "test.db")
    req = InquiryRequest(inquiry_id="inq_to_delete", contractor_message="Delete me")
    resp = DecisionResponse(
        inquiry_id="inq_to_delete",
        decision=DecisionEnum.MANUAL_REVIEW,
        decision_reason="Needs review",
        parsed_inquiry=ParsedInquiry(equipment_type="Excavator"),
        qualification_score=75.0,
        confidence_score=0.8,
        requires_human_approval=True,
    )
    repo.save_inquiry_evaluation(resp, req)
    assert repo.get_inquiry_evaluation("inq_to_delete") is not None

    deleted = repo.delete_inquiry_evaluation("inq_to_delete")
    assert deleted is True
    assert repo.get_inquiry_evaluation("inq_to_delete") is None
    # Subsequent delete should return False
    assert repo.delete_inquiry_evaluation("inq_to_delete") is False


def test_update_inquiry_review_persists_changes(tmp_path):
    repo = SQLiteRepository(db_path=tmp_path / "test.db")
    req = InquiryRequest(inquiry_id="inq_review_persist", contractor_message="Review me")
    resp = DecisionResponse(
        inquiry_id="inq_review_persist",
        decision=DecisionEnum.MANUAL_REVIEW,
        decision_reason="Safety flag",
        parsed_inquiry=ParsedInquiry(equipment_type="Dozer"),
        qualification_score=70.0,
        confidence_score=0.75,
        requires_human_approval=True,
    )
    repo.save_inquiry_evaluation(resp, req)

    updated = repo.update_inquiry_review("inq_review_persist", action="APPROVED", notes="Approved by supervisor")
    assert updated is not None
    assert updated["manual_review_status"] == "APPROVED"
    assert updated["manual_review_notes"] == "Approved by supervisor"

    # Verify directly from database that it updated decision and requires_human_approval
    history = repo.list_inquiry_evaluations()
    target = next((h for h in history if h["inquiry_id"] == "inq_review_persist"), None)
    assert target is not None
    assert target["decision"] == "AUTO_QUOTE"
    assert target["requires_human_approval"] == 0

