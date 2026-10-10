"""Equipment & Inquiry Analysis module for Rentaliq.

Analyzes equipment requirements against catalog database inventory,
validates equipment availability, and merges multi-turn chat context.
"""

import logging
from typing import Any, Dict, List, Optional
from app.data.repository import Repository, default_repository
from app.schemas.inquiry import ParsedInquiry

logger = logging.getLogger(__name__)


class EquipmentAnalyzer:
    """Analyzer for equipment catalog validation and multi-turn chat context fusion."""

    def __init__(self, repository: Optional[Repository] = None):
        self.repository = repository or default_repository

    def get_catalog_categories(self) -> List[str]:
        """Return unique equipment categories available in the fleet repository."""
        equipment_list = self.repository.get_equipment()
        categories = sorted(list(set(e["equipment_type"] for e in equipment_list if "equipment_type" in e)))
        return categories

    def is_catalog_equipment(self, equipment_type: Optional[str]) -> bool:
        """Check if equipment_type matches any category or item in the fleet catalog."""
        if not equipment_type:
            return False
        matches = self.repository.get_equipment(equipment_type=equipment_type)
        if matches:
            return True
        
        # Check partial/case-insensitive match against known categories
        eq_lower = equipment_type.strip().lower()
        for cat in self.get_catalog_categories():
            if eq_lower in cat.lower() or cat.lower() in eq_lower:
                return True
        return False

    def analyze_equipment_inquiry(self, parsed: ParsedInquiry) -> Dict[str, Any]:
        """Analyze equipment inquiry against fleet catalog.

        Returns status dict with catalog availability and details.
        """
        if not parsed.equipment_type:
            return {
                "has_equipment": False,
                "in_catalog": False,
                "equipment_type": None,
                "message": "No equipment specified in inquiry."
            }

        in_catalog = self.is_catalog_equipment(parsed.equipment_type)
        categories = self.get_catalog_categories()

        if not in_catalog:
            return {
                "has_equipment": True,
                "in_catalog": False,
                "equipment_type": parsed.equipment_type,
                "available_categories": categories,
                "message": (
                    f"Equipment '{parsed.equipment_type}' is not available in our equipment rental fleet. "
                    f"Available categories: {', '.join(categories)}."
                )
            }

        return {
            "has_equipment": True,
            "in_catalog": True,
            "equipment_type": parsed.equipment_type,
            "message": f"Equipment '{parsed.equipment_type}' is supported by inventory catalog."
        }

    def merge_conversation_context(
        self,
        current_parsed: ParsedInquiry,
        conversation_history: Optional[List[Dict[str, str]]] = None,
        previous_parsed: Optional[ParsedInquiry] = None,
    ) -> ParsedInquiry:
        """Merge context from previous chat history or previous parsed inquiry into current_parsed.

        Ensures multi-turn chats retain equipment type, capacity, dates, and location
        when follow-up messages only specify updated or remaining parameters.
        """
        if not conversation_history and not previous_parsed:
            return current_parsed

        # Copy current fields
        data = current_parsed.model_dump()

        # If previous_parsed is provided, inherit missing fields from it
        if previous_parsed:
            for field in [
                "equipment_type",
                "equipment_capacity",
                "location",
                "start_date",
                "end_date",
                "duration_days",
                "budget",
                "operator_required",
            ]:
                if data.get(field) is None:
                    prev_val = getattr(previous_parsed, field, None)
                    if prev_val is not None:
                        data[field] = prev_val

        # Recompute end_date or duration_days if one of them is missing after merge
        if data.get("start_date") and data.get("duration_days") and not data.get("end_date"):
            from datetime import timedelta
            data["end_date"] = data["start_date"] + timedelta(days=data["duration_days"])
        elif data.get("start_date") and data.get("end_date") and not data.get("duration_days"):
            diff = (data["end_date"] - data["start_date"]).days
            data["duration_days"] = max(1, diff)

        # Update missing_fields list based on merged values
        new_missing = []
        if not data.get("equipment_type"):
            new_missing.append("equipment_type")
        if not data.get("equipment_capacity") and self.is_catalog_equipment(data.get("equipment_type")):
            new_missing.append("equipment_capacity")
        if not data.get("start_date"):
            new_missing.append("start_date")
        if not data.get("duration_days"):
            new_missing.append("duration_days")
        if not data.get("location"):
            new_missing.append("location")
        data["missing_fields"] = new_missing

        return ParsedInquiry(**data)

