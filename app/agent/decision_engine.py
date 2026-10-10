"""Deterministic decision engine and qualification scorecard.

Enforces strict business rules, safety criteria, and policy constraints.
Independent of LLM and UI. Evaluates qualification checks, calculates scorecards,
and determines AUTO_QUOTE, REQUEST_INFO, or MANUAL_REVIEW.
"""

import logging
from typing import Dict, List, Optional, Tuple

from app.schemas.decision import (
    CheckStatus,
    CounterOffer,
    CriticalityLevel,
    DecisionEnum,
    EstimatedQuote,
    EstimatedQuoteLineItem,
    ProviderComparisonOption,
    QualificationCheck,
)
from app.schemas.inquiry import ParsedInquiry
from app.tools.interfaces import ToolResult

logger = logging.getLogger(__name__)


class DecisionEngine:
    """Deterministic policy engine for evaluating equipment rental inquiries."""

    def evaluate(
        self,
        parsed_inquiry: ParsedInquiry,
        availability_result: Optional[ToolResult] = None,
        pricing_result: Optional[ToolResult] = None,
        criteria_result: Optional[ToolResult] = None,
        counter_offer: Optional[CounterOffer] = None,
    ) -> Tuple[DecisionEnum, str, float, List[QualificationCheck], List[str], Optional[EstimatedQuote], Optional[str], bool]:
        """Run policy checks and return:

        (decision, reason, qualification_score, checks, missing_info, quote, follow_up_draft, requires_human_approval)
        """
        checks: List[QualificationCheck] = []
        missing_info: List[str] = list(parsed_inquiry.missing_fields)
        estimated_quote: Optional[EstimatedQuote] = None
        requires_human_approval = False

        # ---------------------------------------------------------
        # 1. Build Qualification Scorecard
        # ---------------------------------------------------------

        # Check 1: Equipment Identification
        if parsed_inquiry.equipment_type and parsed_inquiry.equipment_capacity:
            checks.append(
                QualificationCheck(
                    name="EQUIPMENT_IDENTIFICATION",
                    status=CheckStatus.PASS,
                    explanation=f"Equipment identified: {parsed_inquiry.equipment_capacity} {parsed_inquiry.equipment_type}.",
                    criticality=CriticalityLevel.CRITICAL,
                    evidence_source="inquiry_parser",
                    weight=1.5,
                )
            )
        elif parsed_inquiry.equipment_type:
            checks.append(
                QualificationCheck(
                    name="EQUIPMENT_IDENTIFICATION",
                    status=CheckStatus.MISSING,
                    explanation=f"Equipment category identified ({parsed_inquiry.equipment_type}), but capacity/size is unspecified.",
                    criticality=CriticalityLevel.CRITICAL,
                    evidence_source="inquiry_parser",
                    weight=1.5,
                )
            )
        else:
            checks.append(
                QualificationCheck(
                    name="EQUIPMENT_IDENTIFICATION",
                    status=CheckStatus.MISSING,
                    explanation="Equipment type and capacity are missing from contractor request.",
                    criticality=CriticalityLevel.CRITICAL,
                    evidence_source="inquiry_parser",
                    weight=1.5,
                )
            )

        # Check 2: Dates and Duration
        if parsed_inquiry.start_date and parsed_inquiry.duration_days and parsed_inquiry.duration_days > 0:
            if "end_date_before_start_date" in parsed_inquiry.uncertain_fields:
                checks.append(
                    QualificationCheck(
                        name="DATES_AND_DURATION",
                        status=CheckStatus.FAIL,
                        explanation="Rental end_date precedes start_date.",
                        criticality=CriticalityLevel.CRITICAL,
                        evidence_source="inquiry_parser",
                        weight=1.5,
                    )
                )
            else:
                checks.append(
                    QualificationCheck(
                        name="DATES_AND_DURATION",
                        status=CheckStatus.PASS,
                        explanation=f"Valid rental period: {parsed_inquiry.start_date} for {parsed_inquiry.duration_days} day(s).",
                        criticality=CriticalityLevel.CRITICAL,
                        evidence_source="inquiry_parser",
                        weight=1.5,
                    )
                )
        else:
            checks.append(
                QualificationCheck(
                    name="DATES_AND_DURATION",
                    status=CheckStatus.MISSING,
                    explanation="Rental start date or duration is missing or unverified.",
                    criticality=CriticalityLevel.CRITICAL,
                    evidence_source="inquiry_parser",
                    weight=1.5,
                )
            )

        # Check 3: Availability Verification
        if availability_result is not None:
            if availability_result.error:
                checks.append(
                    QualificationCheck(
                        name="AVAILABILITY_VERIFICATION",
                        status=CheckStatus.FAIL,
                        explanation=f"Availability check error: {availability_result.error}",
                        criticality=CriticalityLevel.CRITICAL,
                        evidence_source=availability_result.source,
                        weight=2.0,
                    )
                )
            elif availability_result.success:
                checks.append(
                    QualificationCheck(
                        name="AVAILABILITY_VERIFICATION",
                        status=CheckStatus.PASS,
                        explanation=availability_result.evidence,
                        criticality=CriticalityLevel.CRITICAL,
                        evidence_source=availability_result.source,
                        weight=2.0,
                    )
                )
            else:
                checks.append(
                    QualificationCheck(
                        name="AVAILABILITY_VERIFICATION",
                        status=CheckStatus.FAIL,
                        explanation=availability_result.evidence,
                        criticality=CriticalityLevel.CRITICAL,
                        evidence_source=availability_result.source,
                        weight=2.0,
                    )
                )
        else:
            status = CheckStatus.PENDING if not missing_info else CheckStatus.NOT_APPLICABLE
            checks.append(
                QualificationCheck(
                    name="AVAILABILITY_VERIFICATION",
                    status=status,
                    explanation="Availability check has not been performed.",
                    criticality=CriticalityLevel.CRITICAL,
                    evidence_source="inventory_database",
                    weight=2.0,
                )
            )

        # Check 4: Site Access & Safety Suitability
        if criteria_result is not None:
            if criteria_result.success:
                checks.append(
                    QualificationCheck(
                        name="SITE_AND_SAFETY_SUITABILITY",
                        status=CheckStatus.PASS,
                        explanation=criteria_result.evidence,
                        criticality=CriticalityLevel.CRITICAL,
                        evidence_source=criteria_result.source,
                        weight=1.5,
                    )
                )
            else:
                checks.append(
                    QualificationCheck(
                        name="SITE_AND_SAFETY_SUITABILITY",
                        status=CheckStatus.FAIL,
                        explanation=criteria_result.evidence,
                        criticality=CriticalityLevel.CRITICAL,
                        evidence_source=criteria_result.source,
                        weight=1.5,
                    )
                )
        else:
            # Check if site text has immediate safety flags
            if parsed_inquiry.site_access_details and any(
                w in parsed_inquiry.site_access_details.lower() for w in ["narrow", "power lines", "steep"]
            ):
                checks.append(
                    QualificationCheck(
                        name="SITE_AND_SAFETY_SUITABILITY",
                        status=CheckStatus.FAIL,
                        explanation="Potential site access or power line hazard noted without tool verification.",
                        criticality=CriticalityLevel.CRITICAL,
                        evidence_source="contractor_message",
                        weight=1.5,
                    )
                )
            else:
                status = CheckStatus.PENDING if not missing_info else CheckStatus.NOT_APPLICABLE
                checks.append(
                    QualificationCheck(
                        name="SITE_AND_SAFETY_SUITABILITY",
                        status=status,
                        explanation="Site access criteria check pending or skipped.",
                        criticality=CriticalityLevel.HIGH,
                        evidence_source="policy_criteria_engine",
                        weight=1.5,
                    )
                )

        # Check 5: Operator and Licensing
        if parsed_inquiry.operator_required is True:
            checks.append(
                QualificationCheck(
                    name="OPERATOR_AND_LICENSING",
                    status=CheckStatus.PASS,
                    explanation="Certified provider operator requested and provisioned in rate structure.",
                    criticality=CriticalityLevel.MEDIUM,
                    evidence_source="rate_matrix",
                    weight=1.0,
                )
            )
        elif parsed_inquiry.operator_required is False:
            checks.append(
                QualificationCheck(
                    name="OPERATOR_AND_LICENSING",
                    status=CheckStatus.PASS,
                    explanation="Contractor confirmed self-operation with qualified on-site operator.",
                    criticality=CriticalityLevel.MEDIUM,
                    evidence_source="contractor_input",
                    weight=1.0,
                )
            )
        else:
            checks.append(
                QualificationCheck(
                    name="OPERATOR_AND_LICENSING",
                    status=CheckStatus.PASS,
                    explanation="Dry hire assumed; standard operator terms apply.",
                    criticality=CriticalityLevel.LOW,
                    evidence_source="policy_defaults",
                    weight=1.0,
                )
            )

        # Check 6: Pricing and Budget Calculation
        if pricing_result is not None:
            if pricing_result.success:
                pdata = pricing_result.data
                if pdata.get("is_over_budget"):
                    checks.append(
                        QualificationCheck(
                            name="PRICING_AND_BUDGET",
                            status=CheckStatus.FAIL,
                            explanation=f"Calculated quote (${pdata.get('total_estimated_amount'):,.2f}) exceeds contractor budget (${parsed_inquiry.budget:,.2f}).",
                            criticality=CriticalityLevel.HIGH,
                            evidence_source=pricing_result.source,
                            weight=1.5,
                        )
                    )
                elif pdata.get("exceeds_auto_threshold"):
                    checks.append(
                        QualificationCheck(
                            name="PRICING_AND_BUDGET",
                            status=CheckStatus.FAIL,
                            explanation=f"Calculated quote (${pdata.get('total_estimated_amount'):,.2f}) exceeds auto-quote limit ($12,000); requires manager sign-off.",
                            criticality=CriticalityLevel.HIGH,
                            evidence_source=pricing_result.source,
                            weight=1.5,
                        )
                    )
                else:
                    checks.append(
                        QualificationCheck(
                            name="PRICING_AND_BUDGET",
                            status=CheckStatus.PASS,
                            explanation=f"Quote successfully calculated: ${pdata.get('total_estimated_amount'):,.2f}.",
                            criticality=CriticalityLevel.HIGH,
                            evidence_source=pricing_result.source,
                            weight=1.5,
                        )
                    )
                    # Construct quote model
                    line_items = [
                        EstimatedQuoteLineItem(**item) for item in pdata.get("line_items", [])
                    ]
                    provider_comparison = [
                        ProviderComparisonOption(**option)
                        for option in pdata.get("provider_comparison", [])
                    ]
                    estimated_quote = EstimatedQuote(
                        equipment_id=pdata["equipment_id"],
                        equipment_name=pdata["equipment_name"],
                        provider_id=pdata.get("provider_id", "PROV-001"),
                        company_name=pdata.get("company_name", "Apex Heavy Equipment Rentals"),
                        duration_days=pdata["duration_days"],
                        daily_rate=pdata["daily_rate"],
                        base_amount=pdata["base_amount"],
                        operator_fee=pdata.get("operator_fee", 0.0),
                        transport_fee=pdata.get("transport_fee", 0.0),
                        taxes_and_fees=pdata.get("taxes_and_fees", 0.0),
                        total_estimated_amount=pdata["total_estimated_amount"],
                        line_items=line_items,
                        provider_comparison=provider_comparison,
                        currency=pdata.get("currency", "USD"),
                    )
            else:
                checks.append(
                    QualificationCheck(
                        name="PRICING_AND_BUDGET",
                        status=CheckStatus.FAIL,
                        explanation=pricing_result.evidence,
                        criticality=CriticalityLevel.HIGH,
                        evidence_source=pricing_result.source,
                        weight=1.5,
                    )
                )
        else:
            status = CheckStatus.PENDING if not missing_info else CheckStatus.NOT_APPLICABLE
            checks.append(
                QualificationCheck(
                    name="PRICING_AND_BUDGET",
                    status=status,
                    explanation="Pricing calculation pending or skipped due to incomplete requirements.",
                    criticality=CriticalityLevel.HIGH,
                    evidence_source="rate_matrix",
                    weight=1.5,
                )
            )

        # Check 7: Mandatory Policy Compliance
        has_failed_critical = any(
            c.criticality == CriticalityLevel.CRITICAL and c.status == CheckStatus.FAIL for c in checks
        )
        if has_failed_critical:
            checks.append(
                QualificationCheck(
                    name="POLICY_COMPLIANCE",
                    status=CheckStatus.FAIL,
                    explanation="One or more critical safety, availability, or eligibility checks failed.",
                    criticality=CriticalityLevel.CRITICAL,
                    evidence_source="decision_policy",
                    weight=1.0,
                )
            )
        else:
            checks.append(
                QualificationCheck(
                    name="POLICY_COMPLIANCE",
                    status=CheckStatus.PASS,
                    explanation="No policy violations detected.",
                    criticality=CriticalityLevel.HIGH,
                    evidence_source="decision_policy",
                    weight=1.0,
                )
            )

        # ---------------------------------------------------------
        # 2. Calculate Weighted Qualification Score (0.0 to 100.0)
        # ---------------------------------------------------------
        total_weight = sum(c.weight for c in checks)
        passed_weight = sum(c.weight for c in checks if c.status == CheckStatus.PASS)
        qualification_score = round((passed_weight / total_weight) * 100.0, 1) if total_weight > 0 else 0.0

        # ---------------------------------------------------------
        # 3. Deterministic Decision Policy Rules
        # ---------------------------------------------------------

        # Rule 0: Equipment Not Found in Catalog -> REQUEST_INFO with catalog notification
        if availability_result and availability_result.error == "EQUIPMENT_NOT_FOUND":
            decision = DecisionEnum.REQUEST_INFO
            item_name = parsed_inquiry.equipment_type or "requested equipment"
            reason = f"Requested equipment '{item_name}' is not available in fleet catalog inventory."
            requires_human_approval = False
            follow_up = (
                f"Thank you for contacting Apex Equipment Rentals. Unfortunately, '{item_name}' is not an equipment item "
                "we carry in our rental fleet. Our available equipment categories include Excavators, Mini Excavators, "
                "Boom Lifts, Bulldozers, Wheel Loaders, and Skid Steers. Please let us know if one of these machines "
                "would work for your project!"
            )
            return decision, reason, qualification_score, checks, missing_info, None, follow_up, requires_human_approval

        # Rule 1: Tool execution failure or hard system exception -> MANUAL_REVIEW
        if availability_result and availability_result.error:
            decision = DecisionEnum.MANUAL_REVIEW
            reason = f"System verification failure encountered: {availability_result.error}. Fails closed for human escalation."
            requires_human_approval = True
            follow_up = (
                "Thank you for contacting Apex Equipment Rentals. Our automated reservation system encountered an "
                "internal inventory synchronization error while verifying real-time machine availability. "
                "Our dispatch team has been notified and will verify the unit manually within 1 business hour."
            )
            return decision, reason, qualification_score, checks, missing_info, None, follow_up, requires_human_approval

        # Rule 2: Critical safety or site access violation -> MANUAL_REVIEW
        site_check = next((c for c in checks if c.name == "SITE_AND_SAFETY_SUITABILITY"), None)
        if site_check and site_check.status == CheckStatus.FAIL:
            decision = DecisionEnum.MANUAL_REVIEW
            reason = f"Critical safety or site clearance violation: {site_check.explanation}"
            requires_human_approval = True
            follow_up = (
                "Thank you for contacting Apex Equipment Rentals. Your requested jobsite presents access or safety constraints "
                f"({site_check.explanation}). To ensure safe delivery and OSHA compliance, an equipment logistics manager will "
                "contact you to discuss access clearances or arrange an on-site route assessment."
            )
            return decision, reason, qualification_score, checks, missing_info, None, follow_up, requires_human_approval

        # Rule 3: Equipment unavailable / Booking conflict -> MANUAL_REVIEW (with Counter-Offer if available)
        avail_check = next((c for c in checks if c.name == "AVAILABILITY_VERIFICATION"), None)
        if avail_check and avail_check.status == CheckStatus.FAIL:
            decision = DecisionEnum.MANUAL_REVIEW
            requires_human_approval = True
            if counter_offer and counter_offer.counter_type == "TIME_SLOT_SHIFT":
                reason = f"Morning time slot (9 AM) is booked. Proposed same-day Evening slot (5 PM) adjustment."
                follow_up = (
                    f"Thank you for your inquiry. The requested {parsed_inquiry.equipment_capacity or ''} {parsed_inquiry.equipment_type} is currently "
                    f"booked during your requested Morning slot (9 AM). However, it IS available for Evening delivery/pickup (5 PM). "
                    f"Would an Evening slot work for your schedule? If not, we can search other providers for morning availability."
                )
            elif counter_offer:
                reason = f"Requested machine is booked for these dates. Verified counter-offer proposed: {counter_offer.proposed_term}."
                follow_up = (
                    f"Thank you for your inquiry. The requested {parsed_inquiry.equipment_capacity or ''} {parsed_inquiry.equipment_type} is "
                    f"currently committed on another jobsite during your dates. However, we have a verified alternative: {counter_offer.title} "
                    f"({counter_offer.proposed_term}). A rental specialist will contact you to confirm if this option meets your project needs."
                )
            else:
                reason = f"Equipment schedule conflict: {avail_check.explanation}."
                follow_up = (
                    f"Thank you for your inquiry. The requested {parsed_inquiry.equipment_type} is fully booked during your specified dates. "
                    "A fleet coordinator will review alternative dispatch schedules and follow up promptly."
                )
            return decision, reason, qualification_score, checks, missing_info, None, follow_up, requires_human_approval

        # Rule 4A: Budget is optional; if it was not specified, ask the user for it instead of escalating.
        price_check = next((c for c in checks if c.name == "PRICING_AND_BUDGET"), None)
        if parsed_inquiry.budget is None and (
            price_check is None or price_check.status in {CheckStatus.PASS, CheckStatus.NOT_APPLICABLE, CheckStatus.PENDING}
        ):
            decision = DecisionEnum.REQUEST_INFO
            reason = "Budget not specified. Available equipment options can be shown, but a maximum budget is required to filter and compare them properly."
            requires_human_approval = False
            follow_up = (
                "Thank you for the inquiry. We have verified the equipment options that are available. "
                "To compare the best matches against your spending limit and keep the process efficient, "
                "could you please share your maximum total budget or your daily budget cap?"
            )
            return decision, reason, qualification_score, checks, missing_info, None, follow_up, requires_human_approval

        # Rule 4B: Budget exceeded -> MANUAL_REVIEW (with Budget Counter-Offer or Requirement Relaxation if available)
        if price_check and price_check.status == CheckStatus.FAIL:
            decision = DecisionEnum.MANUAL_REVIEW
            requires_human_approval = True
            if counter_offer and counter_offer.counter_type == "BUDGET_TIER":
                reason = f"Requested configuration exceeds contractor budget. Verified budget-aligned alternative proposed."
                follow_up = (
                    f"Thank you for your inquiry. Our standard rate for the requested {parsed_inquiry.equipment_type} exceeds your "
                    f"stated budget cap of ${parsed_inquiry.budget:,.2f}. We have prepared a budget-aligned alternative option ({counter_offer.title}: "
                    f"{counter_offer.proposed_term}). An account representative is reviewing your file to finalize terms."
                )
            elif counter_offer and counter_offer.counter_type == "REQUIREMENT_RELAXATION":
                reason = f"All provider companies exceed contractor budget cap. Requirement relaxation prompt generated."
                follow_up = (
                    f"Thank you for reaching out! All 20-ton equipment options across our rental provider network exceed your "
                    f"stated budget cap of ${parsed_inquiry.budget:,.2f}. Before escalating to our commercial team for a custom manual review negotiation, "
                    f"would you consider: 1. Down-tiering to a smaller machine capacity? 2. Extending rental period for a bulk discount? "
                    f"Or 3. Requesting a custom price negotiation manual review?"
                )
            else:
                reason = f"Pricing or budget constraint: {price_check.explanation}"
                follow_up = (
                    f"Thank you for your inquiry. Our calculated quote exceeds your specified budget cap or standard limits "
                    f"({price_check.explanation}). A commercial manager has been assigned to explore flexible terms."
                )
            return decision, reason, qualification_score, checks, missing_info, None, follow_up, requires_human_approval

        # Rule 5: Essential information missing or ambiguous -> REQUEST_INFO
        essential_missing = [f for f in ["equipment_type", "equipment_capacity", "start_date", "duration_days"] if f in missing_info]
        if essential_missing or len(parsed_inquiry.missing_fields) >= 2 or not parsed_inquiry.start_date:
            decision = DecisionEnum.REQUEST_INFO
            reason = f"Essential rental parameters missing: {', '.join(essential_missing or parsed_inquiry.missing_fields)}."
            requires_human_approval = False
            # Draft targeted questions
            questions = []
            if "start_date" in missing_info or not parsed_inquiry.start_date:
                questions.append("What is your expected rental start date?")
            if "duration_days" in missing_info or not parsed_inquiry.duration_days:
                questions.append("How many days or weeks do you plan to use the machine?")
            if "equipment_capacity" in missing_info or not parsed_inquiry.equipment_capacity:
                questions.append("What machine size/tonnage or reach capacity does your job require?")
            if "location" in missing_info or not parsed_inquiry.location:
                questions.append("What is the jobsite delivery city or address?")

            q_text = " ".join(f"{i+1}. {q}" for i, q in enumerate(questions))
            follow_up = (
                f"Thank you for reaching out to Apex Equipment Rentals! We would love to provide you with an accurate quote. "
                f"Could you please confirm the following details? {q_text}"
            )
            return decision, reason, qualification_score, checks, missing_info, None, follow_up, requires_human_approval

        # Rule 6: Availability confirmed, mandatory criteria pass, pricing valid -> AUTO_QUOTE
        all_passed = (
            avail_check is not None and avail_check.status == CheckStatus.PASS
            and site_check is not None and site_check.status == CheckStatus.PASS
            and price_check is not None and price_check.status == CheckStatus.PASS
            and estimated_quote is not None
        )

        if all_passed:
            decision = DecisionEnum.AUTO_QUOTE
            reason = (
                f"All qualification criteria passed. Verified available {estimated_quote.equipment_name} ({estimated_quote.company_name}) for "
                f"{estimated_quote.duration_days} days. Total estimated quote: ${estimated_quote.total_estimated_amount:,.2f}."
            )
            requires_human_approval = False

            delivery_note = ""
            if parsed_inquiry.delivery_mode == "pickup":
                if parsed_inquiry.has_licensed_operator is False:
                    delivery_note = " Mode: Self-Pickup (Delivery charge waived: $0). Certified operator added at $65/hr since no licensed operator is on site."
                else:
                    delivery_note = " Mode: Self-Pickup (Delivery charge waived: $0). Customer confirmed licensed operator for pickup."
            else:
                delivery_note = f" Delivery Fee: ${estimated_quote.transport_fee:,.2f}."

            comp_note = ""
            if estimated_quote.provider_comparison and len(estimated_quote.provider_comparison) > 1:
                cheapest_opt = estimated_quote.provider_comparison[0]
                comp_note = f" Evaluated {len(estimated_quote.provider_comparison)} rental companies; selected cheapest eligible option: {cheapest_opt['company_name']} (${cheapest_opt['total_estimated_amount']:,.2f})."

            follow_up = (
                f"Hello Marcus! We have verified that the {estimated_quote.equipment_name} from {estimated_quote.company_name} is available for your project "
                f"starting {parsed_inquiry.start_date} for {estimated_quote.duration_days} days. "
                f"Your estimated quote total is ${estimated_quote.total_estimated_amount:,.2f} "
                f"(Base: ${estimated_quote.base_amount:,.2f},{delivery_note} "
                f"Taxes/Fees: ${estimated_quote.taxes_and_fees:,.2f}).{comp_note} "
                f"Disclaimer: {estimated_quote.disclaimer}"
            )
            return decision, reason, qualification_score, checks, missing_info, estimated_quote, follow_up, requires_human_approval

        # Fallback closed -> MANUAL_REVIEW
        decision = DecisionEnum.MANUAL_REVIEW
        reason = "Inquiry conditions could not be resolved automatically. Escalating to dispatch specialist."
        requires_human_approval = True
        follow_up = (
            "Thank you for your inquiry. A rental coordinator will review your request details and follow up within 2 hours."
        )
        return decision, reason, qualification_score, checks, missing_info, None, follow_up, requires_human_approval
