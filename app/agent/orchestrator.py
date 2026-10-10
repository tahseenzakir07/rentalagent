"""Agent orchestrator for Rentaliq.

Orchestrates the multi-step reasoning loop:
Understand -> Assess -> Plan -> Execute Tools -> Reassess -> Decide -> Persist.
Demonstrates context-dependent tool execution paths, strict safety policy enforcement,
and auditable reasoning traces. Supports both SIMULATED (offline) and LLM modes.
"""

import logging
from typing import Optional

from app.agent.analyse import EquipmentAnalyzer
from app.agent.confidence import ConfidenceAssessor
from app.agent.counter_offer import CounterOfferGenerator
from app.agent.decision_engine import DecisionEngine
from app.agent.parser import InquiryParser, LLMInquiryParser, MockInquiryParser
from app.agent.reasoning import ReasoningTracer
from app.agent.tool_registry import ToolRegistry
from app.config import settings
from app.data.repository import Repository, default_repository
from app.schemas.decision import (
    DecisionResponse,
    ExecutionModeEnum,
)
from app.schemas.inquiry import InquiryRequest, ParsedInquiry
from app.tools.interfaces import ToolResult

logger = logging.getLogger(__name__)


class AgentOrchestrator:
    """Central agent orchestrator coordinating parsing, dynamic tool execution,

    policy enforcement, and audit persistence.
    """

    def __init__(
        self,
        repository: Optional[Repository] = None,
        parser: Optional[InquiryParser] = None,
        tool_registry: Optional[ToolRegistry] = None,
        decision_engine: Optional[DecisionEngine] = None,
    ):
        self.repository = repository or default_repository
        self._custom_parser = parser
        self.tool_registry = tool_registry or ToolRegistry(self.repository)
        self.decision_engine = decision_engine or DecisionEngine()
        self.counter_offer_gen = CounterOfferGenerator(self.repository)
        self.equipment_analyzer = EquipmentAnalyzer(self.repository)

    @property
    def parser(self) -> InquiryParser:
        """Dynamic parser based on current runtime settings."""
        if self._custom_parser:
            return self._custom_parser
        if settings.execution_mode.upper() == "LLM" and settings.llm_api_key:
            return LLMInquiryParser()
        return MockInquiryParser()

    def evaluate_inquiry(self, request: InquiryRequest) -> DecisionResponse:
        """Run the end-to-end agent evaluation loop on an incoming inquiry."""
        inquiry_id = request.inquiry_id
        tracer = ReasoningTracer(inquiry_id)
        self.tool_registry.clear_history()

        # Determine execution mode label
        is_llm = bool(settings.execution_mode.upper() == "LLM" and settings.llm_api_key)
        execution_mode = ExecutionModeEnum.LLM if is_llm else ExecutionModeEnum.SIMULATED

        # -------------------------------------------------------------
        # STEP 1: UNDERSTAND & PARSE
        # -------------------------------------------------------------
        tracer.log_event(
            event_type="INQUIRY_RECEIVED",
            explanation=f"Received inquiry '{inquiry_id}' from contractor '{request.contractor_id or 'UNKNOWN'}'.",
            metadata={"channel": request.metadata.get("channel", "direct"), "mode": execution_mode.value},
        )

        parse_context = {
            "project_location": request.project_location,
            "contractor_id": request.contractor_id,
            "provider_id": request.provider_id,
        }

        # Handle simulation triggers from metadata
        if request.metadata.get("simulate_tool_error"):
            parse_context["simulate_tool_error"] = True

        parsed: ParsedInquiry = self.parser.parse(request.contractor_message, parse_context)

        # Merge multi-turn conversation history if provided
        if request.conversation_history:
            prev_parsed_acc = None
            for item in request.conversation_history:
                msg_content = item.get("content") or item.get("message") or ""
                role = item.get("role") or ""
                if role == "user" and msg_content and msg_content != request.contractor_message:
                    prev_p = self.parser.parse(msg_content, parse_context)
                    if prev_parsed_acc is None:
                        prev_parsed_acc = prev_p
                    else:
                        prev_parsed_acc = self.equipment_analyzer.merge_conversation_context(prev_p, previous_parsed=prev_parsed_acc)
            if prev_parsed_acc:
                parsed = self.equipment_analyzer.merge_conversation_context(parsed, previous_parsed=prev_parsed_acc)

        # Propagate simulated tool error token if requested in metadata
        if request.metadata.get("simulate_tool_error"):
            parsed.site_access_details = (parsed.site_access_details or "") + " SIMULATE_TOOL_FAILURE_TEST"

        tracer.log_event(
            event_type="PARSING_COMPLETED",
            explanation=(
                f"Extracted equipment='{parsed.equipment_type}' ({parsed.equipment_capacity}), "
                f"dates={parsed.start_date} to {parsed.end_date} ({parsed.duration_days} days), "
                f"location='{parsed.location}'."
            ),
            metadata={
                "missing_fields": parsed.missing_fields,
                "uncertain_fields": parsed.uncertain_fields,
                "assumptions": parsed.assumptions,
            },
        )

        # Check if equipment_type exists in fleet catalog database using EquipmentAnalyzer
        is_known_catalog_type = self.equipment_analyzer.is_catalog_equipment(parsed.equipment_type)

        has_essential_missing = bool(
            not parsed.start_date
            or not parsed.duration_days
            or not parsed.equipment_type
            or (not parsed.equipment_capacity and is_known_catalog_type)
        )

        if parsed.equipment_type and not is_known_catalog_type:
            # If equipment_type is unlisted/unknown (e.g. "knife"), execute availability check to confirm DB absence
            has_essential_missing = False

        has_site_risk = bool(
            parsed.site_access_details
            and any(w in parsed.site_access_details.lower() for w in ["narrow", "power lines", "steep", "clearance"])
        )

        tracer.log_event(
            event_type="ASSESSMENT_COMPLETED",
            explanation=(
                f"Assessment status: essential_missing={has_essential_missing}, "
                f"is_known_catalog_type={is_known_catalog_type}, site_risk={has_site_risk}, "
                f"budget_specified={parsed.budget is not None}."
            ),
            metadata={"has_essential_missing": has_essential_missing, "has_site_risk": has_site_risk},
        )

        # -------------------------------------------------------------
        # STEP 3 & 4: DYNAMIC PLANNING & TOOL EXECUTION LOOP
        # -------------------------------------------------------------
        availability_result: Optional[ToolResult] = None
        criteria_result: Optional[ToolResult] = None
        pricing_result: Optional[ToolResult] = None

        iterations = 0
        max_iter = settings.max_iterations

        while iterations < max_iter:
            iterations += 1

            # Strategy Branch 1: Missing Essential Info -> Skip tools, request clarification
            if has_essential_missing:
                tracer.log_event(
                    event_type="PLAN_DECISION",
                    explanation=(
                        "Essential parameters (dates, duration, or machine capacity) are missing. "
                        "Skipping availability, criteria, and pricing tool calls to avoid speculative quotes."
                    ),
                    metadata={"action": "REQUEST_CLARIFICATION"},
                )
                break

            # Strategy Branch 2: Check Availability first
            if availability_result is None:
                tracer.log_event(
                    event_type="TOOL_SELECTION",
                    explanation="Selecting 'check_availability' tool to confirm physical fleet inventory status.",
                    metadata={"tool": "check_availability"},
                )
                availability_result = self.tool_registry.execute_tool(
                    "check_availability",
                    parsed,
                    provider_id=request.provider_id,
                )
                tracer.log_event(
                    event_type="TOOL_EXECUTED",
                    explanation=f"Availability tool returned: success={availability_result.success}. {availability_result.evidence}",
                    metadata={"success": availability_result.success, "error": availability_result.error},
                )

                # If tool failed or encountered system error / item missing -> STOP execution
                if availability_result.error:
                    if availability_result.error == "EQUIPMENT_NOT_FOUND":
                        tracer.log_event(
                            event_type="EQUIPMENT_NOT_FOUND_IN_CATALOG",
                            explanation=f"Equipment '{parsed.equipment_type}' was not found in fleet catalog database. Halting tool pipeline.",
                            metadata={"action": "NOTIFY_CATALOG_UNAVAILABLE"},
                        )
                    else:
                        tracer.log_event(
                            event_type="SYSTEM_ERROR_ENCOUNTERED",
                            explanation=f"Availability verification failed with error: {availability_result.error}. Halting tool pipeline.",
                            metadata={"action": "ESCALATE_MANUAL_REVIEW"},
                        )
                    break

                # If requested machine is unavailable -> do NOT calculate normal quote; proceed to evaluate alternatives
                if not availability_result.success:
                    tracer.log_event(
                        event_type="AVAILABILITY_CONFLICT",
                        explanation="Equipment schedule conflict detected. Skipping quote calculation for original unavailable machine.",
                        metadata={"suggested_alternatives_count": len(availability_result.suggested_alternatives)},
                    )
                    break

            # Strategy Branch 3: Validate Criteria & Site Safety
            if criteria_result is None:
                tracer.log_event(
                    event_type="TOOL_SELECTION",
                    explanation="Selecting 'validate_criteria' tool to check jobsite access clearance and safety policies.",
                    metadata={"tool": "validate_criteria"},
                )
                criteria_result = self.tool_registry.execute_tool(
                    "validate_criteria",
                    parsed,
                    provider_id=request.provider_id,
                )
                tracer.log_event(
                    event_type="TOOL_EXECUTED",
                    explanation=f"Criteria tool returned: success={criteria_result.success}. {criteria_result.evidence}",
                    metadata={"success": criteria_result.success},
                )

                # If criteria validation failed -> STOP; do not issue quote for unsafe or violating request
                if not criteria_result.success:
                    tracer.log_event(
                        event_type="SAFETY_POLICY_VIOLATION",
                        explanation="Mandatory site safety or clearance check failed. Skipping quote generation.",
                        metadata={"action": "ESCALATE_MANUAL_REVIEW"},
                    )
                    break

            # Strategy Branch 4: Calculate Pricing & Rate Matrix
            if pricing_result is None:
                tracer.log_event(
                    event_type="TOOL_SELECTION",
                    explanation="All prior checks passed. Selecting 'calculate_price' tool to compute formal rate breakdown.",
                    metadata={"tool": "calculate_price"},
                )
                pricing_result = self.tool_registry.execute_tool(
                    "calculate_price",
                    parsed,
                    provider_id=request.provider_id,
                )
                tracer.log_event(
                    event_type="TOOL_EXECUTED",
                    explanation=f"Pricing tool returned: success={pricing_result.success}. {pricing_result.evidence}",
                    metadata={"success": pricing_result.success},
                )
                break  # Completed full pipeline

        # -------------------------------------------------------------
        # STEP 5: EVALUATE COUNTER-OFFER (IF APPLICABLE)
        # -------------------------------------------------------------
        counter_offer = self.counter_offer_gen.evaluate_counter_offer(
            inquiry=parsed,
            availability_result=availability_result,
            pricing_result=pricing_result,
            criteria_result=criteria_result,
        )

        if counter_offer:
            tracer.log_event(
                event_type="COUNTER_OFFER_FORMULATED",
                explanation=f"Formulated verified counter-offer: {counter_offer.title} ({counter_offer.proposed_term}).",
                metadata={"counter_type": counter_offer.counter_type},
            )

        # -------------------------------------------------------------
        # STEP 6: DECIDE (ENFORCE DETERMINISTIC POLICY ENGINE)
        # -------------------------------------------------------------
        (
            decision,
            reason,
            qual_score,
            qual_checks,
            missing_info,
            est_quote,
            follow_up,
            req_human_approval,
        ) = self.decision_engine.evaluate(
            parsed_inquiry=parsed,
            availability_result=availability_result,
            pricing_result=pricing_result,
            criteria_result=criteria_result,
            counter_offer=counter_offer,
        )

        tracer.log_event(
            event_type="DECISION_FINALIZED",
            explanation=f"Decision finalized as '{decision.value}': {reason}",
            metadata={
                "decision": decision.value,
                "qualification_score": qual_score,
                "requires_human_approval": req_human_approval,
            },
        )

        # -------------------------------------------------------------
        # STEP 7: ASSESS CONFIDENCE & AUDIT TRACE
        # -------------------------------------------------------------
        tool_summaries = self.tool_registry.get_execution_history()
        has_critical_failure = any(c.status.value == "FAIL" and c.criticality.value == "CRITICAL" for c in qual_checks)
        conf_score, conf_expl = ConfidenceAssessor.calculate(
            parsed=parsed,
            tool_calls=tool_summaries,
            has_critical_failure=has_critical_failure,
        )

        response = DecisionResponse(
            inquiry_id=inquiry_id,
            decision=decision,
            decision_reason=reason,
            parsed_inquiry=parsed,
            qualification_score=qual_score,
            qualification_checks=qual_checks,
            missing_information=missing_info,
            estimated_quote=est_quote,
            counter_offer=counter_offer,
            follow_up_message=follow_up,
            confidence_score=conf_score,
            confidence_explanation=conf_expl,
            reasoning_trace=tracer.get_events(),
            tool_calls=tool_summaries,
            requires_human_approval=req_human_approval,
            execution_mode=execution_mode,
        )

        # -------------------------------------------------------------
        # STEP 8: PERSIST TO REPOSITORY
        # -------------------------------------------------------------
        try:
            self.repository.save_inquiry_evaluation(response, request)
            tracer.log_event(
                event_type="DATASET_UPDATE_COMPLETED",
                explanation=f"Inquiry evaluation persisted to repository for {inquiry_id}.",
                metadata={"status": "SAVED"},
            )
        except Exception as e:
            logger.error("Failed to persist inquiry evaluation: %s", e)

        return response
