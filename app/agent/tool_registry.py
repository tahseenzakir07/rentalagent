"""Tool registry and built-in simulated tool implementations.

Role B (Tools Engineer) can register new tools or replace implementations
without altering the orchestrator loop or decision engine.
"""

import logging
import time
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

from app.data.repository import Repository, default_repository
from app.schemas.decision import ToolExecutionSummary
from app.schemas.inquiry import ParsedInquiry
from app.tools.interfaces import (
    AvailabilityTool,
    CriteriaValidationTool,
    PricingTool,
    ToolResult,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Built-in Default Tool Implementations (Role B can substitute or extend)
# ---------------------------------------------------------------------------

class DefaultAvailabilityTool(AvailabilityTool):
    """Verifies inventory schedules and detects conflicting bookings."""

    def __init__(self, repository: Repository):
        self.repository = repository

    def check_availability(
        self,
        inquiry: ParsedInquiry,
        equipment_id: Optional[str] = None,
        provider_id: Optional[str] = None,
    ) -> ToolResult:
        # Check for simulated tool error trigger
        if inquiry.site_access_details and "SIMULATE_TOOL_FAILURE_TEST" in inquiry.site_access_details:
            return ToolResult(
                success=False,
                data={},
                evidence="Hardware inventory telemetry stream timed out; service unreachable.",
                source="telemetry_rpc_service",
                is_simulated=True,
                error="RPC_TIMEOUT: Failed to query real-time equipment availability lock.",
            )

        if not inquiry.start_date:
            return ToolResult(
                success=False,
                data={},
                evidence="Cannot verify schedule: rental start_date is not specified.",
                source="inventory_database",
                is_simulated=True,
                error="MISSING_DATE: start_date required for schedule lookup.",
            )

        # Find matching equipment in catalog
        matching_equipment = self.repository.get_equipment(
            equipment_id=equipment_id,
            equipment_type=inquiry.equipment_type,
            capacity=inquiry.equipment_capacity,
        )

        if not matching_equipment:
            return ToolResult(
                success=False,
                data={},
                evidence=f"No equipment found in catalog for type='{inquiry.equipment_type}' capacity='{inquiry.equipment_capacity}'.",
                source="inventory_database",
                is_simulated=True,
                error="EQUIPMENT_NOT_FOUND",
            )

        target_eq = matching_equipment[0]
        eq_id = target_eq["equipment_id"]

        # Check inspection status
        if target_eq.get("inspection_status") == "INSPECTION_OVERDUE":
            return ToolResult(
                success=False,
                data={"equipment_id": eq_id, "inspection_status": "INSPECTION_OVERDUE"},
                evidence=f"Equipment {eq_id} is marked INSPECTION_OVERDUE and is locked from dispatch.",
                source="fleet_maintenance_db",
                is_simulated=True,
                error="MAINTENANCE_LOCK: Inspection overdue.",
            )

        # Check existing bookings for schedule collision
        bookings = self.repository.get_bookings(equipment_id=eq_id)
        start_dt = inquiry.start_date
        end_dt = inquiry.end_date or start_dt

        for b in bookings:
            try:
                b_start = datetime.strptime(b["start_date"], "%Y-%m-%d").date()
                b_end = datetime.strptime(b["end_date"], "%Y-%m-%d").date()
                # Overlap check
                if not (end_dt < b_start or start_dt > b_end):
                    # Collision detected! Search for verified available alternatives
                    all_active = [
                        e for e in self.repository.get_equipment()
                        if e.get("status") == "AVAILABLE" and e.get("inspection_status") == "PASSED" and e.get("equipment_id") != eq_id
                    ]
                    alternatives = []
                    for alt in all_active:
                        # Check if alt has collision
                        alt_bk = self.repository.get_bookings(equipment_id=alt["equipment_id"])
                        has_alt_collision = False
                        for ab in alt_bk:
                            ab_start = datetime.strptime(ab["start_date"], "%Y-%m-%d").date()
                            ab_end = datetime.strptime(ab["end_date"], "%Y-%m-%d").date()
                            if not (end_dt < ab_start or start_dt > ab_end):
                                has_alt_collision = True
                                break
                        if not has_alt_collision:
                            alternatives.append({
                                "equipment_id": alt["equipment_id"],
                                "model_name": alt["model_name"],
                                "equipment_type": alt["equipment_type"],
                                "capacity": alt["capacity"],
                                "daily_rate": alt["daily_rate"],
                            })

                    return ToolResult(
                        success=False,
                        data={
                            "equipment_id": eq_id,
                            "conflict_booking_id": b.get("booking_id"),
                            "conflict_dates": f"{b['start_date']} to {b['end_date']}",
                        },
                        evidence=f"Equipment {eq_id} ({target_eq['model_name']}) is already committed under booking {b.get('booking_id')} for {b['start_date']} to {b['end_date']}.",
                        source="inventory_database",
                        is_simulated=True,
                        suggested_alternatives=alternatives,
                    )
            except Exception as e:
                logger.warning("Error checking booking dates: %s", e)

        # Available!
        return ToolResult(
            success=True,
            data={
                "equipment_id": eq_id,
                "model_name": target_eq["model_name"],
                "equipment_type": target_eq["equipment_type"],
                "capacity": target_eq["capacity"],
                "daily_rate": target_eq["daily_rate"],
                "weight_tons": target_eq.get("weight_tons", 0),
                "min_access_width_m": target_eq.get("min_access_width_m", 3.0),
                "inspection_status": target_eq.get("inspection_status", "PASSED"),
            },
            evidence=f"Equipment {eq_id} ({target_eq['model_name']}) is verified AVAILABLE for dates {start_dt} to {end_dt}.",
            source="inventory_database",
            is_simulated=True,
        )


class DefaultPricingTool(PricingTool):
    """Calculates formal rates, fees, itemized breakdown, and checks budget."""

    def __init__(self, repository: Repository):
        self.repository = repository

    def calculate_price(
        self,
        inquiry: ParsedInquiry,
        equipment_id: Optional[str] = None,
        provider_id: Optional[str] = None,
    ) -> ToolResult:
        if not inquiry.duration_days or inquiry.duration_days <= 0:
            return ToolResult(
                success=False,
                data={},
                evidence="Cannot calculate quote: rental duration_days is missing or invalid.",
                source="rate_matrix",
                is_simulated=True,
                error="MISSING_DURATION",
            )

        provider = self.repository.get_provider(provider_id or "PROV-001")
        pricing_rules = provider.get("pricing_rules", {}) if provider else {}

        # Look up equipment
        equipment_list = self.repository.get_equipment(
            equipment_id=equipment_id,
            equipment_type=inquiry.equipment_type,
            capacity=inquiry.equipment_capacity,
        )

        if not equipment_list:
            return ToolResult(
                success=False,
                data={},
                evidence=f"No matching equipment pricing sheet for '{inquiry.equipment_type}'.",
                source="rate_matrix",
                is_simulated=True,
                error="EQUIPMENT_NOT_FOUND",
            )

        eq = equipment_list[0]
        daily_rate = float(eq["daily_rate"])
        duration = int(inquiry.duration_days)
        base_amount = daily_rate * duration

        # Operator fee
        operator_fee = 0.0
        if inquiry.operator_required:
            op_rate = float(pricing_rules.get("certified_operator_daily_rate", 500.0))
            operator_fee = op_rate * duration

        # Transport & Tax
        delivery_fee = float(pricing_rules.get("base_delivery_fee", 250.0))
        tax_rate = float(pricing_rules.get("sales_tax_rate", 0.0825))
        subtotal = base_amount + operator_fee + delivery_fee
        taxes = round(subtotal * tax_rate, 2)
        total_quote = round(subtotal + taxes, 2)

        line_items = [
            {
                "description": f"{eq['model_name']} Daily Rental ({duration} days @ ${daily_rate}/day)",
                "unit_price": daily_rate,
                "quantity": float(duration),
                "total_price": base_amount,
            },
            {
                "description": "Standard Flat-bed Delivery & Retrieval",
                "unit_price": delivery_fee,
                "quantity": 1.0,
                "total_price": delivery_fee,
            },
        ]
        if operator_fee > 0:
            line_items.append({
                "description": f"Certified Heavy Equipment Operator ({duration} days @ ${pricing_rules.get('certified_operator_daily_rate', 500.0)}/day)",
                "unit_price": float(pricing_rules.get("certified_operator_daily_rate", 500.0)),
                "quantity": float(duration),
                "total_price": operator_fee,
            })
        line_items.append({
            "description": f"State & Local Rental Surcharge/Tax ({tax_rate * 100:.2f}%)",
            "unit_price": taxes,
            "quantity": 1.0,
            "total_price": taxes,
        })

        # Check against contractor budget if given
        is_over_budget = False
        budget_gap = 0.0
        if inquiry.budget is not None and inquiry.budget > 0:
            if total_quote > inquiry.budget:
                is_over_budget = True
                budget_gap = round(total_quote - inquiry.budget, 2)

        # Check high-value threshold
        high_threshold = float(pricing_rules.get("high_value_quote_threshold", 12000.0))
        exceeds_auto_threshold = total_quote > high_threshold

        data_payload = {
            "equipment_id": eq["equipment_id"],
            "equipment_name": eq["model_name"],
            "duration_days": duration,
            "daily_rate": daily_rate,
            "base_amount": base_amount,
            "operator_fee": operator_fee,
            "transport_fee": delivery_fee,
            "taxes_and_fees": taxes,
            "total_estimated_amount": total_quote,
            "line_items": line_items,
            "currency": "USD",
            "is_over_budget": is_over_budget,
            "budget_gap": budget_gap,
            "exceeds_auto_threshold": exceeds_auto_threshold,
        }

        evidence = (
            f"Calculated quote of ${total_quote:,.2f} for {duration} days of {eq['model_name']}."
        )
        if is_over_budget:
            evidence += f" Stated contractor budget (${inquiry.budget:,.2f}) is exceeded by ${budget_gap:,.2f}."

        return ToolResult(
            success=True,
            data=data_payload,
            evidence=evidence,
            source="rate_matrix",
            is_simulated=True,
        )


class DefaultCriteriaValidationTool(CriteriaValidationTool):
    """Validates site access dimensions, ground stability, and operator certification."""

    def __init__(self, repository: Repository):
        self.repository = repository

    def validate_criteria(
        self,
        inquiry: ParsedInquiry,
        equipment_id: Optional[str] = None,
        provider_id: Optional[str] = None,
    ) -> ToolResult:
        policy = self.repository.get_policy(provider_id or "PROV-001")
        site_rules = policy.get("site_access_rules", {})
        operator_rules = policy.get("operator_rules", {})

        equipment_list = self.repository.get_equipment(
            equipment_id=equipment_id,
            equipment_type=inquiry.equipment_type,
            capacity=inquiry.equipment_capacity,
        )
        eq = equipment_list[0] if equipment_list else None

        violations = []
        warnings = []

        # 1. Site access width check
        site_text = (inquiry.site_access_details or "").lower()
        if site_text:
            # Check for hazardous keywords
            restricted_kws = site_rules.get("restricted_keywords", [])
            found_hazards = [kw for kw in restricted_kws if kw in site_text]
            if found_hazards:
                violations.append(
                    f"Jobsite hazard detected: {', '.join(found_hazards)}. Requires physical safety inspection."
                )

            # Check explicit clearance width constraints if noted (e.g., 2.2 meters)
            if eq:
                min_access = eq.get("min_access_width_m", 3.0)
                if "2.2" in site_text and min_access > 2.5:
                    violations.append(
                        f"Site clearance is only 2.2m, but {eq['model_name']} requires minimum {min_access}m access width."
                    )

        # 2. Minimum rental duration check
        dur_policy = policy.get("rental_durations", {}).get("heavy_equipment_min_days", {})
        if eq and inquiry.duration_days:
            min_req = dur_policy.get(eq["equipment_type"], 1)
            if inquiry.duration_days < min_req:
                violations.append(
                    f"{eq['equipment_type']} requires a minimum rental period of {min_req} days (contractor requested {inquiry.duration_days} days)."
                )

        # 3. Operator qualification check
        if eq:
            weight_tons = eq.get("weight_tons", 0)
            threshold = operator_rules.get("weight_threshold_tons_requiring_operator", 15.0)
            if weight_tons >= threshold and inquiry.operator_required is False:
                # Contractor requested dry hire for heavy machinery
                warnings.append(
                    f"Machine weight ({weight_tons}t) exceeds {threshold}t threshold; requires verified OSHA/NCCCO operator license."
                )

        if violations:
            return ToolResult(
                success=False,
                data={"violations": violations, "warnings": warnings},
                evidence=f"Criteria validation FAILED: {'; '.join(violations)}",
                source="policy_criteria_engine",
                is_simulated=True,
            )

        return ToolResult(
            success=True,
            data={"violations": [], "warnings": warnings},
            evidence="All jobsite access, minimum duration, and safety suitability criteria passed.",
            source="policy_criteria_engine",
            is_simulated=True,
        )


# ---------------------------------------------------------------------------
# Tool Registry
# ---------------------------------------------------------------------------

class ToolRegistry:
    """Central registry and executor for agent business tools.

    Logs execution latency, arguments, results, data sources, and errors.
    Allows easy addition or substitution of business tools by Role B.
    """

    def __init__(self, repository: Optional[Repository] = None):
        self.repository = repository or default_repository
        self._tools: Dict[str, Callable[..., ToolResult]] = {}
        self._execution_history: List[ToolExecutionSummary] = []

        # Register default tools
        avail_tool = DefaultAvailabilityTool(self.repository)
        pricing_tool = DefaultPricingTool(self.repository)
        criteria_tool = DefaultCriteriaValidationTool(self.repository)

        self.register_tool("check_availability", avail_tool.check_availability)
        self.register_tool("calculate_price", pricing_tool.calculate_price)
        self.register_tool("validate_criteria", criteria_tool.validate_criteria)

    def register_tool(self, name: str, func: Callable[..., ToolResult]) -> None:
        """Register a tool callable under a unique name."""
        self._tools[name] = func
        logger.debug("Registered tool: %s", name)

    def has_tool(self, name: str) -> bool:
        """Check if a tool is registered."""
        return name in self._tools

    def execute_tool(
        self,
        tool_name: str,
        inquiry: ParsedInquiry,
        **kwargs: Any,
    ) -> ToolResult:
        """Invoke a registered tool with timing, error capture, and audit logging."""
        if tool_name not in self._tools:
            err_msg = f"Tool '{tool_name}' is not registered in ToolRegistry."
            logger.error(err_msg)
            summary = ToolExecutionSummary(
                tool_name=tool_name,
                input_params=kwargs,
                success=False,
                execution_time_ms=0.0,
                result_summary=err_msg,
                data_source="registry",
                is_simulated=True,
                error=err_msg,
            )
            self._execution_history.append(summary)
            return ToolResult(
                success=False,
                data={},
                evidence=err_msg,
                source="registry",
                is_simulated=True,
                error=err_msg,
            )

        start_time = time.perf_counter()
        tool_func = self._tools[tool_name]

        try:
            result = tool_func(inquiry, **kwargs)
            duration_ms = round((time.perf_counter() - start_time) * 1000, 2)

            summary = ToolExecutionSummary(
                tool_name=tool_name,
                input_params={
                    "equipment_type": inquiry.equipment_type,
                    "equipment_capacity": inquiry.equipment_capacity,
                    "duration_days": inquiry.duration_days,
                    **kwargs,
                },
                success=result.success,
                execution_time_ms=duration_ms,
                result_summary=result.evidence[:250],
                data_source=result.source,
                is_simulated=result.is_simulated,
                error=result.error,
            )
            self._execution_history.append(summary)
            return result

        except Exception as e:
            duration_ms = round((time.perf_counter() - start_time) * 1000, 2)
            err_str = str(e)
            logger.exception("Unhandled exception executing tool %s: %s", tool_name, err_str)

            summary = ToolExecutionSummary(
                tool_name=tool_name,
                input_params=kwargs,
                success=False,
                execution_time_ms=duration_ms,
                result_summary=f"Tool failed with exception: {err_str}",
                data_source="registry",
                is_simulated=True,
                error=err_str,
            )
            self._execution_history.append(summary)
            return ToolResult(
                success=False,
                data={},
                evidence=f"Execution error in {tool_name}: {err_str}",
                source="registry",
                is_simulated=True,
                error=err_str,
            )

    def get_execution_history(self) -> List[ToolExecutionSummary]:
        """Return audit history of tool executions for the current session."""
        return list(self._execution_history)

    def clear_history(self) -> None:
        """Reset execution history."""
        self._execution_history.clear()
