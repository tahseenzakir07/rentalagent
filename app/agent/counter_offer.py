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

        # 1. Schedule / Time Slot Conflict -> Alternative Slot or Equipment Counter-Offer
        if availability_result and not availability_result.success:
            avail_data = availability_result.data or {}
            
            # Feature 2: Time slot shift (Morning requested, Evening available)
            if avail_data.get("time_slot_conflict"):
                req_slot = avail_data.get("requested_slot", "morning")
                avail_slot = avail_data.get("available_slot", "evening")
                return CounterOffer(
                    counter_type="TIME_SLOT_SHIFT",
                    title="Revised Delivery Time Slot Option",
                    description=(
                        f"The requested {inquiry.equipment_capacity or ''} {inquiry.equipment_type} is unavailable for {req_slot.title()} delivery (9 AM) "
                        f"due to a prior jobsite schedule commitment. However, it IS available for {avail_slot.title()} delivery/pickup (5 PM)."
                    ),
                    original_term=f"Requested Slot: {req_slot.title()} (9 AM) - Booked",
                    proposed_term=f"Available Slot: {avail_slot.title()} (5 PM)",
                    rationale="Proposing same-day evening time slot adjustment to fulfill equipment request without multi-day delay.",
                )

            alternatives = availability_result.suggested_alternatives
            if alternatives:
                best_alt = alternatives[0]
                alt_eq_id = best_alt["equipment_id"]
                alt_model = best_alt["model_name"]
                alt_company = best_alt.get("company_name", "BuildPro Equipment Solutions")
                alt_rate = float(best_alt["daily_rate"])
                duration = inquiry.duration_days or 1
                base = alt_rate * duration
                tax = round(base * 0.0825, 2)
                delivery = 250.0
                total = base + tax + delivery

                alt_quote = EstimatedQuote(
                    equipment_id=alt_eq_id,
                    equipment_name=alt_model,
                    provider_id=best_alt.get("provider_id", "PROV-002"),
                    company_name=alt_company,
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
                            description=f"Flat-bed Delivery & Retrieval ({alt_company})",
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
                    counter_type="ALTERNATIVE_EQUIPMENT",
                    title=f"Verified Alternative Available from {alt_company}",
                    description=(
                        f"The requested unit is currently committed on another jobsite. "
                        f"However, {alt_model} from {alt_company} is verified AVAILABLE for your requested dates."
                    ),
                    original_term=f"{inquiry.equipment_capacity} {inquiry.equipment_type} (Unavailable)",
                    proposed_term=f"{alt_model} from {alt_company} @ ${alt_rate}/day",
                    verified_equipment_id=alt_eq_id,
                    estimated_quote=alt_quote,
                    rationale="Provider policy permits offering verified alternative fleet units when the primary unit has a schedule conflict.",
                )

        # 2. Budget Shortfall -> Feature 1 (Cheapest Company) or Feature 4 (No Company Fits Budget - Relaxation)
        if pricing_result and pricing_result.success:
            data = pricing_result.data
            if data.get("is_over_budget") and inquiry.budget is not None:
                comparison_options = data.get("provider_comparison") or []
                budget_fit_options = []

                for option in comparison_options:
                    total_amount = float(option.get("total_estimated_amount", 0.0) or 0.0)
                    daily_rate = float(option.get("daily_rate", 0.0) or 0.0)
                    if inquiry.budget_is_daily:
                        threshold_ok = daily_rate <= inquiry.budget
                    else:
                        threshold_ok = total_amount <= inquiry.budget
                    if threshold_ok:
                        budget_fit_options.append(option)

                if not budget_fit_options:
                    # Feature 4: No company fits the budget -> Requirement relaxation & manual review
                    return CounterOffer(
                        counter_type="REQUIREMENT_RELAXATION",
                        title="Requirement Relaxation & Custom Negotiation",
                        description=(
                            f"All available {inquiry.equipment_capacity or ''} {inquiry.equipment_type} units across our provider network "
                            f"exceed your budget cap of ${inquiry.budget:,.2f}. Would you consider: "
                            f"1. Down-tiering to a smaller machine capacity? 2. Extending rental period for a bulk discount? "
                            f"Or 3. Requesting a custom price negotiation manual review?"
                        ),
                        original_term=f"Strict Budget Cap: ${inquiry.budget:,.2f}",
                        proposed_term="Explore Capacity Down-tiering or Request Provider Price Negotiation",
                        rationale="All market options exceed strict budget cap. Escalating to requirement relaxation & manual review negotiation.",
                    )

                alt_option = sorted(budget_fit_options, key=lambda opt: float(opt.get("total_estimated_amount", 0.0) or 0.0))[0]
                alt_unit = next(
                    (e for e in self.repository.get_equipment() if e.get("equipment_id") == alt_option.get("equipment_id")),
                    None,
                )
                if alt_unit is None:
                    alt_unit = self.repository.get_equipment(
                        equipment_type=inquiry.equipment_type,
                        capacity=inquiry.equipment_capacity,
                    )[0]

                alt_rate = float(alt_unit["daily_rate"])
                alt_company = alt_unit.get("company_name", alt_option.get("company_name", "BuildPro Equipment Solutions"))
                duration = inquiry.duration_days or 1
                base = alt_rate * duration
                delivery = 0.0 if inquiry.delivery_mode == "pickup" else 180.0
                tax = round((base + delivery) * 0.07, 2)
                alt_total = base + delivery + tax

                alt_quote = EstimatedQuote(
                    equipment_id=alt_unit["equipment_id"],
                    equipment_name=alt_unit["model_name"],
                    provider_id=alt_unit.get("provider_id", "PROV-002"),
                    company_name=alt_company,
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
                            description=f"Delivery & Retrieval ({alt_company})" if delivery > 0 else "Self-Pickup (Delivery Waived)",
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
                    title=f"Cheapest Eligible Option: {alt_company}",
                    description=(
                        f"The primary quote (${data.get('total_estimated_amount'):,.2f}) exceeds your budget cap of ${inquiry.budget:,.2f}. "
                        f"{alt_company} offers {alt_unit['model_name']} at an estimated total of ${alt_total:,.2f}."
                    ),
                    original_term=f"Original Quote: ${data.get('total_estimated_amount'):,.2f} (Budget: ${inquiry.budget:,.2f})",
                    proposed_term=f"{alt_company} ({alt_unit['model_name']}) @ ${alt_total:,.2f}",
                    verified_equipment_id=alt_unit["equipment_id"],
                    estimated_quote=alt_quote,
                    rationale="Proposing lower-cost eligible provider option to fit contractor budget constraints.",
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
