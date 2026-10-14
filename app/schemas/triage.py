from typing import Literal

from pydantic import BaseModel, Field


class TriageRequest(BaseModel):
    message: str = Field(..., min_length=1, description="Texto da mensagem enviada pelo cliente")
    phone: str | None = Field(None, description="Número de telefone/WhatsApp do cliente")
    client_name: str | None = Field(None, description="Nome do cliente caso já identificado")


TriageActionType = Literal[
    "fast_handoff_human",
    "fast_check_pix",
    "fast_greeting",
    "route_to_llm",
]


class TriageResult(BaseModel):
    intent: str = Field(..., description="Intenção detectada (ex: novo_agendamento, falar_humano, etc.)")
    intent_confidence: float = Field(..., description="Confiança na intenção (0.0 a 1.0)")
    is_human_handoff: float = Field(..., description="Probabilidade de ser pedido de atendimento humano (0.0 a 1.0)")
    is_payment_claim: float = Field(..., description="Probabilidade de ser afirmação de pagamento/PIX (0.0 a 1.0)")
    frustration_score: float = Field(..., description="Nota de insatisfação/irritação (0.0 a 2.0)")
    frustration_level: Literal["calmo", "impaciente", "irritado"] = Field(
        ..., description="Classificação do estado emocional do cliente"
    )
    recommended_action: TriageActionType = Field(
        ..., description="Ação sugerida para o sistema (fast_handoff_human, fast_check_pix, etc.)"
    )
    fast_response_text: str | None = Field(
        None, description="Mensagem de resposta rápida pronta para o WhatsApp quando cabível"
    )
    model_used: str = Field(..., description="Modelo de decisão utilizado")
    cost_usd: float | None = Field(None, description="Custo aproximado da inferência em dólares")
    is_fallback: bool = Field(False, description="Indica se o resultado foi gerado pelo fallback de contingência")
