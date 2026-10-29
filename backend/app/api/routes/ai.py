import logging

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import get_current_user
from app.models.models import User
from app.schemas.ai import AIAnswerResponse, AIAskRequest
from app.services.ai_evidence import get_answer_generator


router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("/ask", response_model=AIAnswerResponse)
def ask_ai(
    request: AIAskRequest,
    current_user: User = Depends(get_current_user),
) -> AIAnswerResponse:
    try:
        result = get_answer_generator().generate_answer(request.question)
        return AIAnswerResponse.model_validate(result)
    except Exception:
        logger.exception("AI evidence retrieval request failed")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="AI evidence retrieval is temporarily unavailable.",
        ) from None
