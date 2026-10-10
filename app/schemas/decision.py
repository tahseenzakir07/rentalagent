"""Schemas for agent qualification, quotes, counter-offers, and decisions."""

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from app.schemas.inquiry import ParsedInquiry


class DecisionEnum(str, Enum):
    """The three authoritative decision outcomes for contractor inquiries."""

    AUTO_QUOTE = "AUTO_QUOTE"
    REQUEST_INFO = "REQUEST_INFO"
    MANUAL_REVIEW = "MANUAL_REVIEW"


class ExecutionModeEnum(str, Enum):
    """Operation mode: full LLM orchestration or offline deterministic simulation."""

    LLM = "LLM"
    SIMULATED = "SIMULATED"


class CheckStatus(str, Enum):
    """Status of an individual qualification check."""

    PASS = "PASS"
    FAIL = "FAIL"
    MISSING = "MISSING"
    PENDING = "PENDING"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class CriticalityLevel(str, Enum):
    """Severity tier for qualification checks."""

    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class QualificationCheck(BaseModel):
    """Individual item evaluated on the qualification scorecard."""

    name: str = Field(..., description="Machine-readable check identifier.")
    status: CheckStatus = Field(..., description="Evaluation outcome.")
    explanation: str = Field(..., description="Human-readable justification for the check status.")
    criticality: CriticalityLevel = Field(
        default=CriticalityLevel.HIGH,
        description="Severity level. CRITICAL checks failing MUST force MANUAL_REVIEW.",
    )
    evidence_source: Optional[str] = Field(
        default=None,
        description="Source of verification (e.g. inventory_database, policy_rules, user_input).",
    )
    weight: float = Field(
        default=1.0,
        ge=0.0,
        description="Weight contribution to aggregate qualification score.",
    )


class EstimatedQuoteLineItem(BaseModel):
    """Individual pricing item within an estimated quote."""

    description: str = Field(..., description="Line item description.")
    unit_price: float = Field(..., ge=0.0, description="Base rate or price per unit.")
    quantity: float = Field(..., ge=0.0, description="Count or duration (e.g. days).")
    total_price: float = Field(..., ge=0.0, description="Total extended price for item.")


class ProviderComparisonOption(BaseModel):
    """Comparison item representing an equipment option across rental companies."""

    provider_id: str = Field(..., description="Provider unique ID.")
    company_name: str = Field(..., description="Rental company name.")
    equipment_id: str = Field(..., description="Equipment unit ID.")
    model_name: str = Field(..., description="Equipment model name.")
    daily_rate: float = Field(..., ge=0.0, description="Daily rate.")
    delivery_fee: float = Field(default=0.0, ge=0.0, description="Delivery fee.")
    total_estimated_amount: float = Field(..., ge=0.0, description="Total estimated quote for period.")
    is_cheapest: bool = Field(default=False, description="True if option is lowest cost.")
    is_eligible: bool = Field(default=True, description="True if option passes all safety & availability checks.")
    note: Optional[str] = Field(default=None, description="Notes on terms or slot availability.")


class EstimatedQuote(BaseModel):
    """Structured estimated quote breakdown.

    Explicit disclaimer: Does not create a booking or authoritative reservation.
    """

    equipment_id: str = Field(..., description="Verified equipment inventory ID.")
    equipment_name: str = Field(..., description="Equipment model and category name.")
    provider_id: Optional[str] = Field(default="PROV-001", description="Provider ID.")
    company_name: Optional[str] = Field(default="Apex Heavy Equipment Rentals", description="Rental company name.")
    duration_days: int = Field(..., gt=0, description="Rental period in days.")
    daily_rate: float = Field(..., ge=0.0, description="Daily rental rate.")
    base_amount: float = Field(..., ge=0.0, description="Base equipment rental charge.")
    operator_fee: float = Field(default=0.0, ge=0.0, description="Certified operator charge.")
    transport_fee: float = Field(default=0.0, ge=0.0, description="Delivery & pickup fee.")
    taxes_and_fees: float = Field(default=0.0, ge=0.0, description="Estimated taxes/surcharges.")
    total_estimated_amount: float = Field(..., ge=0.0, description="Total projected quote.")
    line_items: List[EstimatedQuoteLineItem] = Field(
        default_factory=list,
        description="Itemized quote components.",
    )
    provider_comparison: List[ProviderComparisonOption] = Field(
        default_factory=list,
        description="Multi-company budget comparison options evaluated by agent.",
    )
    currency: str = Field(default="USD", description="Currency code.")
    disclaimer: str = Field(
        default=(
            "Estimated quote only. Subject to provider review and formal rental agreement. "
            "Does not constitute an inventory hold or confirmed reservation."
        ),
        description="Legal and operational reservation disclaimer.",
    )


class CounterOffer(BaseModel):
    """Policy-compliant alternative suggested when original request cannot be fulfilled."""

    counter_type: str = Field(
        ...,
        description="Category: ALTERNATIVE_EQUIPMENT, DURATION_ADJUSTMENT, or BUDGET_TIER.",
    )
    title: str = Field(..., description="Concise headline for the counter-offer.")
    description: str = Field(..., description="Detailed explanation presented to contractor.")
    original_term: str = Field(..., description="Original requested parameter that hit conflict.")
    proposed_term: str = Field(..., description="Verified compliant alternative proposed.")
    verified_equipment_id: Optional[str] = Field(
        default=None,
        description="Verified alternate inventory unit ID if applicable.",
    )
    estimated_quote: Optional[EstimatedQuote] = Field(
        default=None,
        description="Complete pricing breakdown for proposed counter-offer.",
    )
    rationale: str = Field(
        ...,
        description="Operational and business rationale for proposing this option.",
    )


class ReasoningTraceEvent(BaseModel):
    """Auditable milestone event recorded during agent reasoning loop."""

    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="UTC timestamp when the event occurred.",
    )
    event_type: str = Field(
        ...,
        description="Step type: PARSING, TOOL_SELECTION, TOOL_RESULT, POLICY_CHECK, DECISION.",
    )
    explanation: str = Field(
        ...,
        description="Concise description of the reasoning or action taken.",
    )
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Observable action parameters, verified evidence, or outcomes.",
    )


class ToolExecutionSummary(BaseModel):
    """Structured record of a single tool execution."""

    tool_name: str = Field(..., description="Name of invoked business tool.")
    input_params: Dict[str, Any] = Field(
        default_factory=dict,
        description="Input parameters passed to the tool.",
    )
    success: bool = Field(..., description="Whether tool execution completed successfully.")
    execution_time_ms: float = Field(
        default=0.0,
        ge=0.0,
        description="Execution duration in milliseconds.",
    )
    result_summary: str = Field(
        ...,
        description="Human-readable summary of the verification result.",
    )
    data_source: str = Field(
        ...,
        description="Authoritative source or dataset queried (e.g. SQLite, JSON, mock).",
    )
    is_simulated: bool = Field(
        default=True,
        description="True if result originates from simulated/mock dataset.",
    )
    error: Optional[str] = Field(
        default=None,
        description="Error detail if execution encountered a failure.",
    )


class DecisionResponse(BaseModel):
    """Complete, auditable output contract for an evaluated contractor inquiry."""

    inquiry_id: str = Field(..., description="Inquiry identifier.")
    decision: DecisionEnum = Field(..., description="AUTO_QUOTE, REQUEST_INFO, or MANUAL_REVIEW.")
    decision_reason: str = Field(..., description="Clear explanation of why this decision was reached.")
    parsed_inquiry: ParsedInquiry = Field(..., description="Extracted parameters and missing/uncertain fields.")
    qualification_score: float = Field(
        ...,
        ge=0.0,
        le=100.0,
        description="Weighted qualification score from 0 to 100.",
    )
    qualification_checks: List[QualificationCheck] = Field(
        default_factory=list,
        description="Full scorecard of structured criteria checks.",
    )
    missing_information: List[str] = Field(
        default_factory=list,
        description="Critical fields that must be provided by the contractor.",
    )
    estimated_quote: Optional[EstimatedQuote] = Field(
        default=None,
        description="Estimated quote if AUTO_QUOTE was approved.",
    )
    counter_offer: Optional[CounterOffer] = Field(
        default=None,
        description="Verified policy-compliant alternative if available.",
    )
    follow_up_message: Optional[str] = Field(
        default=None,
        description="Rendered contractor message draft (follow-up question or quote summary).",
    )
    confidence_score: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Agent confidence in evaluation accuracy from 0.0 to 1.0.",
    )
    confidence_explanation: Optional[str] = Field(
        default=None,
        description="Transparent breakdown of confidence calculation.",
    )
    reasoning_trace: List[ReasoningTraceEvent] = Field(
        default_factory=list,
        description="Chronological audit trace of agent reasoning steps.",
    )
    tool_calls: List[ToolExecutionSummary] = Field(
        default_factory=list,
        description="All tools invoked during the evaluation loop.",
    )
    requires_human_approval: bool = Field(
        ...,
        description="Flag indicating whether human authority/review is strictly required.",
    )
    execution_mode: ExecutionModeEnum = Field(
        default=ExecutionModeEnum.SIMULATED,
        description="Mode used for evaluation: LLM or SIMULATED.",
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Timestamp when evaluation response was finalized.",
    )
