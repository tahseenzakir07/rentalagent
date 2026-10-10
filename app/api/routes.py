"""API route handlers for Rentaliq."""

import logging
from typing import Any, Dict, List
from fastapi import APIRouter, HTTPException, Query, status

from app.agent.orchestrator import AgentOrchestrator
from app.config import settings
from app.data.repository import default_repository
from app.schemas.decision import DecisionResponse
from app.schemas.inquiry import InquiryRequest

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/agent", tags=["Agent Evaluation"])
orchestrator = AgentOrchestrator(repository=default_repository)


@router.post(
    "/evaluate",
    response_model=DecisionResponse,
    status_code=status.HTTP_200_OK,
    summary="Evaluate a contractor equipment inquiry",
    description=(
        "Processes an unstructured contractor message, dynamically selects and executes "
        "business verification tools, scores criteria against hard safety policies, and produces "
        "an auditable decision (AUTO_QUOTE, REQUEST_INFO, or MANUAL_REVIEW)."
    ),
)
def evaluate_inquiry(request: InquiryRequest) -> DecisionResponse:
    """Evaluate an incoming inquiry using the Rentaliq orchestrator."""
    try:
        response = orchestrator.evaluate_inquiry(request)
        return response
    except Exception as e:
        logger.exception("Inquiry evaluation failed for %s: %s", request.inquiry_id, e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Inquiry evaluation error: {str(e)}",
        )


@router.get(
    "/demo-inquiries",
    response_model=List[Dict[str, Any]],
    summary="List curated demonstration scenarios",
    description="Returns preconfigured demo inquiries representing distinct business and edge cases.",
)
def get_demo_inquiries() -> List[Dict[str, Any]]:
    """Retrieve sample test cases for demonstration and testing."""
    return default_repository.get_sample_inquiries()


@router.get(
    "/inquiries",
    response_model=List[Dict[str, Any]],
    summary="List evaluation history",
    description="Returns historical evaluated inquiries stored in the persistent database.",
)
def list_inquiries(
    limit: int = Query(default=50, ge=1, le=100, description="Max records to return"),
) -> List[Dict[str, Any]]:
    """Retrieve inquiry evaluation audit history."""
    return default_repository.list_inquiry_evaluations(limit=limit)


@router.get(
    "/inquiries/{inquiry_id}",
    response_model=Dict[str, Any],
    summary="Retrieve saved inquiry evaluation details",
    description="Returns the full payload including request, response, scorecard, and reasoning trace.",
)
def get_inquiry_details(inquiry_id: str) -> Dict[str, Any]:
    """Retrieve a specific inquiry evaluation by ID."""
    record = default_repository.get_inquiry_evaluation(inquiry_id)
    if not record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Inquiry evaluation '{inquiry_id}' not found.",
        )
    return record


@router.get(
    "/equipment",
    response_model=List[Dict[str, Any]],
    summary="List available equipment catalog",
    description="Returns fleet units with real-time status, rates, and specifications.",
)
def list_equipment() -> List[Dict[str, Any]]:
    """Retrieve equipment inventory records."""
    return default_repository.get_equipment()


@router.get(
    "/bookings",
    response_model=List[Dict[str, Any]],
    summary="List currently dispersed / active bookings",
    description="Returns confirmed equipment reservations and schedule commitments.",
)
def list_bookings() -> List[Dict[str, Any]]:
    """Retrieve active bookings."""
    return default_repository.get_bookings()


@router.get(
    "/contractors",
    response_model=List[Dict[str, Any]],
    summary="List registered contractor profiles",
    description="Returns verified contractors, credit tiers, and safety ratings.",
)
def list_contractors() -> List[Dict[str, Any]]:
    """Retrieve contractor profiles."""
    return default_repository._contractors


@router.post(
    "/inquiries/{inquiry_id}/review",
    response_model=Dict[str, Any],
    summary="Provider manual review action",
    description="Approve, reject, or attach notes to a manual review inquiry.",
)
def review_inquiry(inquiry_id: str, action_data: Dict[str, Any]) -> Dict[str, Any]:
    """Update manual review state for human-in-the-loop escalation."""
    record = default_repository.get_inquiry_evaluation(inquiry_id)
    if not record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Inquiry '{inquiry_id}' not found.",
        )
    action = action_data.get("action", "APPROVED")  # APPROVED, REJECTED, MODIFIED
    notes = action_data.get("notes", "Reviewed by equipment dispatch manager.")
    record["manual_review_status"] = action
    record["manual_review_notes"] = notes
    return {"status": "success", "inquiry_id": inquiry_id, "action": action, "notes": notes}


@router.post(
    "/settings/api-key",
    response_model=Dict[str, Any],
    summary="Update agent LLM API credentials",
    description="Sets the runtime API key and switches agent execution mode to LLM.",
)
def update_api_key(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Dynamically set or clear LLM API credentials."""
    api_key = payload.get("api_key", "").strip()
    provider = payload.get("provider", "openai")
    model = payload.get("model", "gpt-4o-mini")

    settings.set_api_key(api_key=api_key, provider=provider, model=model)
    return {
        "status": "success",
        "execution_mode": settings.execution_mode,
        "llm_provider": settings.llm_provider,
        "llm_model": settings.llm_model,
        "has_key": bool(settings.llm_api_key),
    }


@router.get(
    "/settings/status",
    response_model=Dict[str, Any],
    summary="Get current agent runtime settings",
    description="Returns current execution mode and provider status.",
)
def get_settings_status() -> Dict[str, Any]:
    """Retrieve active runtime settings."""
    masked_key = ""
    if settings.llm_api_key:
        masked_key = settings.llm_api_key[:6] + "..." + settings.llm_api_key[-4:] if len(settings.llm_api_key) > 10 else "***"
    return {
        "execution_mode": settings.execution_mode,
        "llm_provider": settings.llm_provider,
        "llm_model": settings.llm_model,
        "has_key": bool(settings.llm_api_key),
        "masked_key": masked_key,
    }


