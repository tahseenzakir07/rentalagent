"""Tool interfaces and execution contracts for business domain tools."""

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from app.schemas.inquiry import ParsedInquiry


class ToolResult(BaseModel):
    """Structured response returned by all business tools."""

    success: bool = Field(..., description="Whether the tool execution and verification succeeded.")
    data: Dict[str, Any] = Field(
        default_factory=dict,
        description="Verified domain payload (e.g., equipment specs, line items, conflict details).",
    )
    evidence: str = Field(..., description="Detailed explanation or audit trail of the finding.")
    source: str = Field(..., description="Data source (e.g., inventory_db, rate_matrix, policy_rules).")
    is_simulated: bool = Field(
        default=True,
        description="True if result originates from simulated/synthetic datasets.",
    )
    suggested_alternatives: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="Verified alternatives (e.g. available substitute machines, duration options).",
    )
    error: Optional[str] = Field(
        default=None,
        description="Error message if tool execution failed or threw an exception.",
    )


class AvailabilityTool(ABC):
    """Contract for verifying equipment schedule and reservation conflicts."""

    @abstractmethod
    def check_availability(
        self,
        inquiry: ParsedInquiry,
        equipment_id: Optional[str] = None,
        provider_id: Optional[str] = None,
    ) -> ToolResult:
        """Verify if matching equipment is available for the requested date window."""
        pass


class PricingTool(ABC):
    """Contract for computing formal daily rates, fees, and estimated total quotes."""

    @abstractmethod
    def calculate_price(
        self,
        inquiry: ParsedInquiry,
        equipment_id: Optional[str] = None,
        provider_id: Optional[str] = None,
    ) -> ToolResult:
        """Calculate itemized pricing based on rates, duration, operator, and fees."""
        pass


class CriteriaValidationTool(ABC):
    """Contract for validating jobsite suitability, operator qualifications, and safety."""

    @abstractmethod
    def validate_criteria(
        self,
        inquiry: ParsedInquiry,
        equipment_id: Optional[str] = None,
        provider_id: Optional[str] = None,
    ) -> ToolResult:
        """Validate site access clearances, ground slope, and safety criteria."""
        pass
