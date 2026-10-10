"""Confidence assessment module.

Calculates an auditable, transparent confidence score (0.0 to 1.0) based on
extraction completeness, parser certainty, tool execution success, and evidence consistency.
"""

from typing import List, Tuple
from app.schemas.decision import ToolExecutionSummary
from app.schemas.inquiry import ParsedInquiry


class ConfidenceAssessor:
    """Evaluates agent confidence in the integrity of the evaluation process."""

    @staticmethod
    def calculate(
        parsed: ParsedInquiry,
        tool_calls: List[ToolExecutionSummary],
        has_critical_failure: bool = False,
    ) -> Tuple[float, str]:
        """Compute transparent confidence score between 0.0 and 1.0."""
        breakdown = []
        score = 0.0

        # 1. Extraction Completeness (Max: 0.30)
        expected_fields = ["equipment_type", "equipment_capacity", "start_date", "duration_days", "location"]
        present_count = sum(1 for f in expected_fields if getattr(parsed, f, None) is not None)
        completeness_factor = (present_count / len(expected_fields)) * 0.30
        score += completeness_factor
        breakdown.append(f"Field completeness: {present_count}/{len(expected_fields)} ({completeness_factor:.2f}/0.30)")

        # 2. Parser Certainty (Max: 0.25)
        # Deduct for uncertain fields and unverifiable assumptions
        certainty_base = 0.25
        deductions = len(parsed.uncertain_fields) * 0.08 + len(parsed.assumptions) * 0.04
        certainty_factor = max(0.0, certainty_base - deductions)
        score += certainty_factor
        breakdown.append(f"Parser certainty: deductions={deductions:.2f} ({certainty_factor:.2f}/0.25)")

        # 3. Tool Execution Integrity (Max: 0.25)
        if not tool_calls:
            # If no tools were invoked (e.g. inquiry missing essential info), neutral baseline
            if parsed.missing_fields:
                tool_factor = 0.20  # High confidence that info is indeed missing!
                breakdown.append(f"Tool execution: info missing prior to execution ({tool_factor:.2f}/0.25)")
            else:
                tool_factor = 0.10
                breakdown.append(f"Tool execution: no tools invoked ({tool_factor:.2f}/0.25)")
        else:
            success_count = sum(1 for t in tool_calls if t.success)
            tool_factor = (success_count / len(tool_calls)) * 0.25
            breakdown.append(f"Tool execution: {success_count}/{len(tool_calls)} succeeded ({tool_factor:.2f}/0.25)")
        score += tool_factor

        # 4. Evidence Consistency & Resolution (Max: 0.20)
        consistency_factor = 0.20
        if has_critical_failure:
            consistency_factor = 0.15  # Solid confidence in identifying a real conflict/failure
        if any(t.error is not None for t in tool_calls):
            consistency_factor = 0.05
        score += consistency_factor
        breakdown.append(f"Evidence consistency: ({consistency_factor:.2f}/0.20)")

        final_score = round(min(1.0, max(0.0, score)), 2)
        explanation = "; ".join(breakdown) + f" => Final Confidence: {final_score:.2f}"
        return final_score, explanation
