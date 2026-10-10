"""Schemas for contractor inquiries and parsed domain entities."""

import uuid
from datetime import date
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, model_validator


class InquiryRequest(BaseModel):
    """Initial inquiry input received from a contractor or client channel."""

    inquiry_id: str = Field(
        default_factory=lambda: f"inq_{uuid.uuid4().hex[:10]}",
        description="Unique identifier for the inquiry. Auto-generated if omitted.",
    )
    contractor_message: str = Field(
        ...,
        min_length=3,
        description="Raw natural-language inquiry message from the contractor.",
    )
    contractor_id: Optional[str] = Field(
        default=None,
        description="Identifier of known contractor, if authenticated or recognized.",
    )
    provider_id: Optional[str] = Field(
        default="PROV-001",
        description="Identifier of equipment rental provider handling inquiry.",
    )
    project_location: Optional[str] = Field(
        default=None,
        description="Jobsite location or delivery address provided in context.",
    )
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Arbitrary client metadata (e.g. channel, urgent flag, source).",
    )


class ParsedInquiry(BaseModel):
    """Structured fields extracted from the contractor's natural-language message.

    Never silently invents missing values. Distinguishes unknown information from
    explicit negative answers. Inferred assumptions are recorded separately.
    """

    equipment_type: Optional[str] = Field(
        default=None,
        description="Identified category of equipment (e.g., Excavator, Boom Lift).",
    )
    equipment_capacity: Optional[str] = Field(
        default=None,
        description="Specific size or capacity specification (e.g., 20-ton, 60-ft).",
    )
    start_date: Optional[date] = Field(
        default=None,
        description="Requested rental start date in ISO format.",
    )
    end_date: Optional[date] = Field(
        default=None,
        description="Requested rental end date in ISO format.",
    )
    duration_days: Optional[int] = Field(
        default=None,
        gt=0,
        description="Total duration of rental in days (positive integer).",
    )
    location: Optional[str] = Field(
        default=None,
        description="Extracted or resolved delivery/jobsite location.",
    )
    budget: Optional[float] = Field(
        default=None,
        ge=0.0,
        description="Contractor's stated budget or price cap, if provided.",
    )
    operator_required: Optional[bool] = Field(
        default=None,
        description="True if operator requested, False if dry hire requested, None if unspecified.",
    )
    site_access_details: Optional[str] = Field(
        default=None,
        description="Site conditions, restrictions, clearances, or slope constraints.",
    )
    special_requirements: List[str] = Field(
        default_factory=list,
        description="Attachments, GPS, certification, or other specific equipment needs.",
    )
    missing_fields: List[str] = Field(
        default_factory=list,
        description="Essential domain fields that were not found in the contractor input.",
    )
    uncertain_fields: List[str] = Field(
        default_factory=list,
        description="Fields extracted with ambiguity or conflicting signals.",
    )
    assumptions: List[str] = Field(
        default_factory=list,
        description="Explicit assumptions made during interpretation without verified facts.",
    )

    @model_validator(mode="after")
    def validate_dates_and_duration(self) -> "ParsedInquiry":
        """Cross-validate dates and duration consistency."""
        if self.start_date and self.end_date:
            diff = (self.end_date - self.start_date).days
            if diff < 0:
                if "end_date_before_start_date" not in self.uncertain_fields:
                    self.uncertain_fields.append("end_date_before_start_date")
            elif diff == 0:
                # Same day rental is 1 day
                if self.duration_days is None:
                    self.duration_days = 1
            else:
                if self.duration_days is None:
                    self.duration_days = diff
                elif self.duration_days != diff:
                    mismatch = f"duration_mismatch: stated {self.duration_days} days vs date range {diff} days"
                    if mismatch not in self.uncertain_fields:
                        self.uncertain_fields.append(mismatch)
        elif self.start_date and self.duration_days and not self.end_date:
            # Note assumption if needed
            pass
        return self
