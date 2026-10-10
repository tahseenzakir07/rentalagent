"""Inquiry parser interface and implementations.

Extracts structured domain parameters from unstructured contractor inquiries.
Includes a deterministic MockInquiryParser and an optional LLM-backed adapter.
"""

import json
import logging
import re
from abc import ABC, abstractmethod
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional

from app.config import settings
from app.schemas.inquiry import ParsedInquiry

logger = logging.getLogger(__name__)


class InquiryParser(ABC):
    """Abstract interface for extracting inquiry fields."""

    @abstractmethod
    def parse(self, message: str, context: Optional[Dict[str, Any]] = None) -> ParsedInquiry:
        """Parse natural-language message into a structured ParsedInquiry object."""
        pass


class MockInquiryParser(InquiryParser):
    """Deterministic offline parser for testing, local development, and offline demo.

    Employs robust pattern matching, heuristics, and validation rules without
    calling any external API or paid service.
    """

    def parse(self, message: str, context: Optional[Dict[str, Any]] = None) -> ParsedInquiry:
        text = message.strip()
        lower_text = text.lower()
        context = context or {}

        # 1. Equipment Type & Capacity extraction
        equipment_type: Optional[str] = None
        equipment_capacity: Optional[str] = None

        if "mini excavator" in lower_text or "mini-excavator" in lower_text or "compact excavator" in lower_text:
            equipment_type = "Mini Excavator"
            equipment_capacity = "5-ton"
        elif "excavator" in lower_text or "trackhoe" in lower_text or "digger" in lower_text:
            equipment_type = "Excavator"
            # Look for capacity
            if "20-ton" in lower_text or "20 ton" in lower_text or "22-ton" in lower_text or "20t" in lower_text:
                equipment_capacity = "20-ton"
            elif "5-ton" in lower_text or "5 ton" in lower_text or "5t" in lower_text:
                equipment_type = "Mini Excavator"
                equipment_capacity = "5-ton"
            elif "30-ton" in lower_text or "30 ton" in lower_text:
                equipment_capacity = "30-ton"
        elif "boom lift" in lower_text or "cherry picker" in lower_text or "man lift" in lower_text:
            equipment_type = "Boom Lift"
            if "60-ft" in lower_text or "60 ft" in lower_text or "60ft" in lower_text or "60 foot" in lower_text:
                equipment_capacity = "60-ft"
            elif "45-ft" in lower_text or "45 ft" in lower_text:
                equipment_capacity = "45-ft"
            elif "80-ft" in lower_text or "80 ft" in lower_text:
                equipment_capacity = "80-ft"
        elif "bulldozer" in lower_text or "dozer" in lower_text:
            equipment_type = "Bulldozer"
            equipment_capacity = "20-ton"
        elif "wheel loader" in lower_text or "front loader" in lower_text:
            equipment_type = "Wheel Loader"
            equipment_capacity = "18-ton"
        elif "skid steer" in lower_text or "track loader" in lower_text or "bobcat" in lower_text:
            equipment_type = "Skid Steer"
            equipment_capacity = "4.8-ton"

        # 2. Date parsing (ISO YYYY-MM-DD or standard patterns)
        start_date: Optional[date] = None
        end_date: Optional[date] = None

        # Look for ISO date patterns: YYYY-MM-DD
        iso_dates = re.findall(r"\b(202[4-9]-\d{2}-\d{2})\b", text)
        if len(iso_dates) >= 2:
            try:
                start_date = datetime.strptime(iso_dates[0], "%Y-%m-%d").date()
                end_date = datetime.strptime(iso_dates[1], "%Y-%m-%d").date()
            except ValueError:
                pass
        elif len(iso_dates) == 1:
            try:
                start_date = datetime.strptime(iso_dates[0], "%Y-%m-%d").date()
            except ValueError:
                pass

        # 3. Duration parsing (e.g., "for 4 days", "4 days", "1 week", "for 2 weeks")
        duration_days: Optional[int] = None
        duration_match = re.search(r"\b(?:for\s+)?(\d+)\s*(?:days?|day)\b", lower_text)
        if duration_match:
            duration_days = int(duration_match.group(1))
        else:
            week_match = re.search(r"\b(?:for\s+)?(\d+)\s*(?:weeks?|week)\b", lower_text)
            if week_match:
                duration_days = int(week_match.group(1)) * 7

        # Cross calculate dates & duration if one is missing
        if start_date and duration_days and not end_date:
            end_date = start_date + timedelta(days=duration_days)
        elif start_date and end_date and not duration_days:
            diff = (end_date - start_date).days
            duration_days = max(1, diff)

        # 4. Location extraction
        location: Optional[str] = context.get("project_location")
        if not location:
            loc_match = re.search(
                r"\b(?:at|in|to)\s+([0-9A-Za-z\s,.-]+?(?:TX|Texas|Austin|Buda|Pflugerville|San Marcos|Kyle|Bastrop))\b",
                text,
                re.IGNORECASE,
            )
            if loc_match:
                location = loc_match.group(1).strip()
            elif "in " in lower_text:
                # Fallback location detection
                part = text.split("in ")[-1].split(".")[0].split(",")[0].strip()
                if len(part) > 2 and len(part) < 30:
                    location = part

        # 5. Budget extraction (e.g. "$8,000", "$1,800", "budget is 8000")
        budget: Optional[float] = None
        budget_match = re.search(r"\$\s*([0-9,]+(?:\.\d{2})?)", text)
        if budget_match:
            try:
                budget = float(budget_match.group(1).replace(",", ""))
            except ValueError:
                pass
        else:
            budget_kw = re.search(r"budget\s+(?:is|of|capped at)?\s*(?:strictly\s+capped\s+at)?\s*\$?([0-9,]+)", lower_text)
            if budget_kw:
                try:
                    budget = float(budget_kw.group(1).replace(",", ""))
                except ValueError:
                    pass

        # 6. Operator requirements
        operator_required: Optional[bool] = None
        if "dry hire" in lower_text or "self-operated" in lower_text or "our crew" in lower_text or "our own operator" in lower_text or "without operator" in lower_text:
            operator_required = False
        elif "with operator" in lower_text or "need operator" in lower_text or "operator required" in lower_text or "provide operator" in lower_text:
            operator_required = True

        # 7. Site access details & restrictions
        site_access_details: Optional[str] = None
        site_indicators = [
            "narrow alley",
            "clearance",
            "meters clearance",
            "steep slope",
            "overhead power lines",
            "tight access",
            "muddy",
            "weight-restricted",
        ]
        found_site_snippets = []
        for ind in site_indicators:
            if ind in lower_text:
                found_site_snippets.append(ind)
        if found_site_snippets:
            # Capture the context sentence
            sentences = [s.strip() for s in text.split(".") if any(ind in s.lower() for ind in found_site_snippets)]
            site_access_details = ". ".join(sentences) if sentences else ", ".join(found_site_snippets)

        # 8. Special requirements
        special_requirements: List[str] = []
        if "hydraulic breaker" in lower_text or "hammer" in lower_text:
            special_requirements.append("hydraulic_breaker")
        if "auger" in lower_text:
            special_requirements.append("auger")
        if "gps" in lower_text:
            special_requirements.append("gps_tracking")

        # 9. Missing fields identification
        missing_fields: List[str] = []
        if not equipment_type:
            missing_fields.append("equipment_type")
        if not equipment_capacity:
            missing_fields.append("equipment_capacity")
        if not start_date:
            missing_fields.append("start_date")
        if not duration_days:
            missing_fields.append("duration_days")
        if not location:
            missing_fields.append("location")

        # 10. Uncertain fields and assumptions
        uncertain_fields: List[str] = []
        assumptions: List[str] = []

        if operator_required is None:
            assumptions.append("Operator requirement not stated; defaulted to contractor self-operation if licensed.")

        if equipment_type and not equipment_capacity:
            uncertain_fields.append("equipment_capacity_unspecified")

        if start_date and end_date and duration_days:
            calc_days = (end_date - start_date).days
            if calc_days > 0 and calc_days != duration_days:
                uncertain_fields.append(f"duration_conflict_{duration_days}_vs_date_span_{calc_days}")

        return ParsedInquiry(
            equipment_type=equipment_type,
            equipment_capacity=equipment_capacity,
            start_date=start_date,
            end_date=end_date,
            duration_days=duration_days,
            location=location,
            budget=budget,
            operator_required=operator_required,
            site_access_details=site_access_details,
            special_requirements=special_requirements,
            missing_fields=missing_fields,
            uncertain_fields=uncertain_fields,
            assumptions=assumptions,
        )


class LLMInquiryParser(InquiryParser):
    """LLM parser adapter with native HTTP (httpx) and litellm support."""

    def __init__(self, fallback_parser: Optional[InquiryParser] = None):
        self.fallback = fallback_parser or MockInquiryParser()

    def parse(self, message: str, context: Optional[Dict[str, Any]] = None) -> ParsedInquiry:
        if not settings.llm_api_key or settings.execution_mode.upper() != "LLM":
            logger.debug("No LLM credentials or simulated mode active; using deterministic parser.")
            return self.fallback.parse(message, context)

        system_prompt = (
            "You are an equipment rental parsing agent. Extract domain parameters into a strict JSON object with keys: "
            "equipment_type (str or null), equipment_capacity (str or null), start_date (YYYY-MM-DD or null), "
            "end_date (YYYY-MM-DD or null), duration_days (int or null), location (str or null), budget (float or null), "
            "operator_required (bool or null), site_access_details (str or null), special_requirements (list of strings), "
            "missing_fields (list of strings), uncertain_fields (list of strings), assumptions (list of strings). "
            "Do NOT invent dates, availability, or pricing facts. Return ONLY valid JSON."
        )

        # 1. Attempt using litellm if installed
        try:
            import litellm
            model_name = settings.llm_model
            if (settings.llm_provider == "gemini" or settings.llm_api_key.startswith("AIza")) and not model_name.startswith("gemini/"):
                model_name = f"gemini/{model_name}"

            completion = litellm.completion(
                model=model_name,
                api_key=settings.llm_api_key,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": message},
                ],
                response_format={"type": "json_object"},
                temperature=0.0,
                num_retries=0,
                request_timeout=6.0,
            )
            raw_content = completion.choices[0].message.content or "{}"
            parsed_dict = self._clean_and_parse_json(raw_content)
            if parsed_dict:
                return ParsedInquiry(**parsed_dict)
        except ImportError:
            pass  # litellm not installed, proceed to native httpx
        except Exception as e:
            logger.warning("litellm parsing encountered error (%s); trying direct provider HTTP endpoint.", e)

        # 2. Direct HTTP calling via httpx
        try:
            import httpx

            provider = settings.llm_provider.lower()
            key = settings.llm_api_key
            model = settings.llm_model

            # Remove prefixes if present
            if model.startswith("gemini/"):
                model = model.replace("gemini/", "")

            if provider == "gemini" or key.startswith("AIza"):
                # Google Gemini REST API
                url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}"
                payload = {
                    "contents": [
                        {
                            "role": "user",
                            "parts": [
                                {"text": f"{system_prompt}\n\nContractor Message to parse:\n\"{message}\""}
                            ]
                        }
                    ],
                    "generationConfig": {
                        "responseMimeType": "application/json",
                        "temperature": 0.0,
                    }
                }
                with httpx.Client(timeout=15.0) as client:
                    resp = client.post(url, json=payload)
                    if resp.status_code == 200:
                        data = resp.json()
                        text_val = data["candidates"][0]["content"]["parts"][0]["text"]
                        parsed_dict = self._clean_and_parse_json(text_val)
                        if parsed_dict:
                            return ParsedInquiry(**parsed_dict)
                    else:
                        logger.warning("Gemini direct API returned status %s: %s", resp.status_code, resp.text)

            elif provider == "openai" or key.startswith("sk-"):
                # OpenAI REST API
                url = "https://api.openai.com/v1/chat/completions"
                headers = {
                    "Authorization": f"Bearer {key}",
                    "Content-Type": "application/json",
                }
                payload = {
                    "model": model or "gpt-4o-mini",
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": message},
                    ],
                    "response_format": {"type": "json_object"},
                    "temperature": 0.0,
                }
                with httpx.Client(timeout=15.0) as client:
                    resp = client.post(url, headers=headers, json=payload)
                    if resp.status_code == 200:
                        data = resp.json()
                        raw_text = data["choices"][0]["message"]["content"]
                        parsed_dict = self._clean_and_parse_json(raw_text)
                        if parsed_dict:
                            return ParsedInquiry(**parsed_dict)
                    else:
                        logger.warning("OpenAI direct API returned status %s: %s", resp.status_code, resp.text)

        except Exception as e:
            logger.warning("Direct HTTP LLM parser failed (%s); falling back to deterministic parser.", e)

        return self.fallback.parse(message, context)

    @staticmethod
    def _clean_and_parse_json(raw_str: str) -> Optional[Dict[str, Any]]:
        """Clean markdown backticks or text wrapping from JSON output."""
        cleaned = raw_str.strip()
        if cleaned.startswith("```json"):
            cleaned = cleaned[7:]
        elif cleaned.startswith("```"):
            cleaned = cleaned[3:]
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3]
        cleaned = cleaned.strip()

        try:
            return json.loads(cleaned)
        except Exception:
            # Try finding first { and last }
            start = cleaned.find("{")
            end = cleaned.rfind("}")
            if start != -1 and end != -1:
                try:
                    return json.loads(cleaned[start:end+1])
                except Exception:
                    pass
        return None
