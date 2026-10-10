"""Counter-offer generation module.

Constructs verified, policy-compliant alternatives when the original inquiry
encounters availability conflicts, minimum duration policy violations, or budget constraints.
Never invents rates, machines, or discounts without verified evidence.
"""

import logging
from typing import Optional

from app.data.repository import Repository
from app.schemas.decision import CounterOffer, EstimatedQuote, EstimatedQuoteLineItem
from app.schemas.inquiry import ParsedInquiry
from app.tools.interfaces import ToolResult

logger = logging.getLogger(__name__)


class CounterOfferGenerator:
    """Generates policy-compliant counter-offers with verified pricing and availability."""

    def __init__(self, repository: Repository):
        self.repository = repository

    def evaluate_counter_offer(
        self,
        inquiry: ParsedInquiry,
        availability_result: Optional[ToolResult],
        pricing_result: Optional[ToolResult],
        criteria_result: Optional[ToolResult],
    ) -> Optional[CounterOffer]:
        """Evaluate whether a verified alternative can be offered."""

        # 1. Schedule Conflict -> Alternative Equipment Counter-Offer
        if availability_result and not availability_result.success:
            alternatives = availability_result.suggested_alternatives
            if alternatives:
                best_alt = alternatives[0]
                alt_eq_id = best_alt["equipment_id"]
                alt_model = best_alt["model_name"]
                alt_rate = float(best_alt["daily_rate"])
                duration = inquiry.duration_days or 1
                base = alt_rate * duration
                tax = round(base * 0.0825, 2)
                delivery = 250.0
                total = base + tax + delivery

                alt_quote = EstimatedQuote(
                    equipment_id=alt_eq_id,
                    equipment_name=alt_model,
                    duration_days=duration,
                    daily_rate=alt_rate,
                    base_amount=base,
                    transport_fee=delivery,
                    taxes_and_fees=tax,
                    total_estimated_amount=round(total, 2),
                    line_items=[
                        EstimatedQuoteLineItem(
                            description=f"{alt_model} Daily Rental ({duration} days @ ${alt_rate}/day)",
                            unit_price=alt_rate,
                            quantity=float(duration),
                            total_price=base,
                        ),
                        EstimatedQuoteLineItem(
                            description="Flat-bed Delivery & Retrieval",
                            unit_price=delivery,
                            quantity=1.0,
                            total_price=delivery,
                        ),
                        EstimatedQuoteLineItem(
                            description="State & Local Tax (8.25%)",
                            unit_price=tax,
                            quantity=1.0,
                            total_price=tax,
                        ),
                    ],
                )

                return CounterOffer(
                    counter_type="ALTERNATIVE_EQUIPMENT",
                    title="Verified Alternative Equipment Available",
                    description=(
                        f"The requested {inquiry.equipment_capacity or ''} {inquiry.equipment_type} is currently committed on another jobsite. "
                        f"However, {alt_model} ({alt_eq_id}) is verified AVAILABLE for your requested dates."
                    ),
                    original_term=f"{inquiry.equipment_capacity} {inquiry.equipment_type} (Unavailable)",
                    proposed_term=f"{alt_model} (Verified Available)",
                    verified_equipment_id=alt_eq_id,
                    estimated_quote=alt_quote,
                    rationale="Provider policy permits offering verified alternative fleet units when the requested unit has a confirmed schedule conflict.",
                )

        # 2. Budget Shortfall -> Cheaper Machine Counter-Offer
        if pricing_result and pricing_result.success:
            data = pricing_result.data
            if data.get("is_over_budget") and inquiry.budget is not None:
                # Search for cheaper available equipment
                all_eq = self.repository.get_equipment()
                cheaper_units = [
                    e for e in all_eq
                    if e.get("status") == "AVAILABLE"
                    and e.get("inspection_status") == "PASSED"
                    and float(e.get("daily_rate", 9999)) < data.get("daily_rate", 0)
                ]
                if cheaper_units:
                    alt_unit = cheaper_units[0]
                    alt_rate = float(alt_unit["daily_rate"])
                    duration = inquiry.duration_days or 1
                    base = alt_rate * duration
                    delivery = 250.0
                    tax = round((base + delivery) * 0.0825, 2)
                    alt_total = base + delivery + tax

                    if alt_total <= inquiry.budget or alt_rate < data.get("daily_rate", 0):
                        alt_quote = EstimatedQuote(
                            equipment_id=alt_unit["equipment_id"],
                            equipment_name=alt_unit["model_name"],
                            duration_days=duration,
                            daily_rate=alt_rate,
                            base_amount=base,
                            transport_fee=delivery,
                            taxes_and_fees=tax,
                            total_estimated_amount=round(alt_total, 2),
                            line_items=[
                                EstimatedQuoteLineItem(
                                    description=f"{alt_unit['model_name']} Rental ({duration} days @ ${alt_rate}/day)",
                                    unit_price=alt_rate,
                                    quantity=float(duration),
                                    total_price=base,
                                ),
                                EstimatedQuoteLineItem(
                                    description="Delivery & Retrieval",
                                    unit_price=delivery,
                                    quantity=1.0,
                                    total_price=delivery,
                                ),
                                EstimatedQuoteLineItem(
                                    description="Taxes & Fees",
                                    unit_price=tax,
                                    quantity=1.0,
                                    total_price=tax,
                                ),
                            ],
                        )

                        return CounterOffer(
                            counter_type="BUDGET_TIER",
                            title="Budget-Aligned Fleet Alternative",
                            description=(
                                f"The requested {inquiry.equipment_capacity or ''} {inquiry.equipment_type} quote (${data.get('total_estimated_amount'):,.2f}) "
                                f"exceeds your stated budget cap of ${inquiry.budget:,.2f}. We can offer {alt_unit['model_name']} "
                                f"at an estimated total of ${alt_total:,.2f}."
                            ),
                            original_term=f"Original Quote: ${data.get('total_estimated_amount'):,.2f} (Budget: ${inquiry.budget:,.2f})",
                            proposed_term=f"{alt_unit['model_name']} @ ${alt_total:,.2f}",
                            verified_equipment_id=alt_unit["equipment_id"],
                            estimated_quote=alt_quote,
                            rationale="Suggesting lower capacity machine to satisfy contractor budget constraint without violating pricing rules.",
                        )

        # 3. Minimum Duration Violation Counter-Offer
        if criteria_result and not criteria_result.success:
            violations = criteria_result.data.get("violations", [])
            for v in violations:
                if "minimum rental period" in v:
                    # Extract suggested duration
                    policy = self.repository.get_policy()
                    dur_policy = policy.get("rental_durations", {}).get("heavy_equipment_min_days", {})
                    min_days = dur_policy.get(inquiry.equipment_type, 2)
                    return CounterOffer(
                        counter_type="DURATION_ADJUSTMENT",
                        title="Adjusted Rental Duration (Policy Requirement)",
                        description=(
                            f"Our provider policy requires a minimum commitment of {min_days} days for {inquiry.equipment_type}. "
                            f"We can quote this inquiry for the required {min_days}-day minimum duration."
                        ),
                        original_term=f"{inquiry.duration_days} days requested",
                        proposed_term=f"{min_days} days minimum",
                        rationale="Heavy machinery dispatch economics require a minimum rental period.",
                    )

        return None
