from fastapi import APIRouter, Depends, status

from app.schemas.triage import TriageRequest, TriageResult
from app.security import require_api_key
from app.services.triage_service import TriageService

router = APIRouter(prefix="/api/triage", tags=["triage"])


@router.post(
    "",
    response_model=TriageResult,
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(require_api_key)],
    summary="Triagem rápida de mensagem de cliente",
    description=(
        "Classifica em milissegundos a intenção, probabilidade de pedido de atendente humano, "
        "afirmação de pagamento e nível de frustração do cliente utilizando o TypeSafe Jev via OpenRouter."
    ),
)
async def triage_message(request: TriageRequest) -> TriageResult:
    service = TriageService()
    return await service.evaluate(message=request.message, phone=request.phone)
