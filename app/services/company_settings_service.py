import logging
import os

from sqlalchemy.orm import Session

from app.models.company_settings import CompanySettings
from app.schemas.company_settings import CompanySettingsUpdate

logger = logging.getLogger(__name__)

LEGACY_SALON_KEYWORDS: list[str] = [
    "cabelo",
    "cabelos",
    "unha",
    "unhas",
    "estética",
    "estetica",
    "agendamento de serviços",
    "agendamento de servicos",
    "linha de produtos profissionais",
    "informações sobre horários e preços",
    "informacoes sobre horarios e precos",
    "barbearia",
    "barbeiro",
    "cabeleireiro",
    "cabeleireira",
    "manicure",
    "pedicure",
    "depilação",
    "depilacao",
    "agendar serviço",
    "agendar servico",
]


def is_legacy_salon_text(text: str | None) -> bool:
    """Verifica se uma string contém termos residuais de plataforma de salão/barbearia."""
    if not text:
        return False
    lower = text.lower()
    return any(keyword in lower for keyword in LEGACY_SALON_KEYWORDS)


def get_clean_product_welcome_message(company_name: str | None = None) -> str:
    """Gera a mensagem de boas-vindas padrão alinhada exclusivamente à plataforma de produtos."""
    name = (company_name or "Nossa Loja").strip()
    return (
        f"Olá! Seja muito bem-vindo(a) ao *{name}*! ✨\n\n"
        "Sou sua consultora virtual de vendas. Como posso te ajudar hoje?\n"
        "• Conhecer nossos Produtos e Catálogo\n"
        "• Fazer um Pedido e Consultar Preços\n"
        "• Informações sobre Entrega e Formas de Pagamento"
    )


class CompanySettingsService:
    def __init__(self, db: Session):
        self.db = db

    def sanitize_legacy_salon_data(self, settings: CompanySettings | None = None) -> bool:
        """
        Detecta e higieniza configurações com resíduos legados de salão/barbearia/agendamento,
        assegurando alinhamento estrito com a proposta de vendedor de produtos.
        """
        targets = [settings] if settings else self.db.query(CompanySettings).all()
        any_modified = False

        for target in targets:
            if not target:
                continue
            modified = False

            # 1. Higieniza welcome_message
            if target.welcome_message and is_legacy_salon_text(target.welcome_message):
                logger.warning(
                    "Expurgando mensagem de boas-vindas legada de salão nas configurações da empresa #%s.",
                    target.id,
                )
                target.welcome_message = get_clean_product_welcome_message(target.company_name)
                modified = True

            # 2. Higieniza ai_system_prompt
            if target.ai_system_prompt and is_legacy_salon_text(target.ai_system_prompt):
                logger.warning(
                    "Expurgando prompt de sistema legado de salão nas configurações da empresa #%s.",
                    target.id,
                )
                target.ai_system_prompt = (
                    "Atendimento consultivo e focado exclusivamente no catálogo de produtos, "
                    "pedidos de compras, entregas e opções de pagamento (PIX ou entrega). "
                    "Não oferecemos agendamento de serviços de salão ou barbearia."
                )
                modified = True

            # 3. Higieniza assistant_name se houver resíduo
            if target.assistant_name and any(k in target.assistant_name.lower() for k in ["barbeir", "cabeleireir"]):
                target.assistant_name = "Consultor de Vendas"
                modified = True

            if modified:
                any_modified = True

        if any_modified:
            try:
                self.db.commit()
                if settings:
                    self.db.refresh(settings)
                logger.info("Configurações da empresa expurgadas com sucesso de resíduos de salão.")
            except Exception as exc:
                self.db.rollback()
                logger.error("Falha ao salvar configurações expurgadas no banco: %s", exc)

        return any_modified

    def get_or_create_default(self) -> CompanySettings:
        """Retorna a configuração da empresa (singleton/primeiro registro) ou cria com padrões."""
        settings = self.db.query(CompanySettings).first()
        if not settings:
            settings = CompanySettings(
                company_name="Minha Empresa",
                payment_required=True,
                default_gateway="asaas",
                gateway_credentials={},
                accepted_payment_methods=["pix"],
                commission_model="percentage",
                default_commission_rate=0.0,
                split_enabled=False,
                whatsapp_provider=os.getenv("WHATSAPP_PROVIDER", "evolution"),
                assistant_name="Assistente",
                tone="casual",
                require_cpf=False,
                welcome_message=get_clean_product_welcome_message("Minha Empresa"),
                ai_system_prompt=(
                    "Atendimento consultivo e focado exclusivamente no catálogo de produtos, "
                    "pedidos de compras, entregas e opções de pagamento (PIX ou entrega)."
                ),
                human_support_phone=None,
                human_support_name="Equipe de Atendimento",
                human_support_message=None,
                custom_settings={},
            )
            self.db.add(settings)
            self.db.commit()
            self.db.refresh(settings)
        else:
            self.sanitize_legacy_salon_data(settings)
        return settings

    def update(self, update_data: CompanySettingsUpdate) -> CompanySettings:
        settings = self.get_or_create_default()
        fields_to_update = update_data.model_dump(exclude_unset=True)

        if "gateway_credentials" in fields_to_update:
            creds = dict(settings.gateway_credentials or {})
            creds.update(fields_to_update.pop("gateway_credentials") or {})
            settings.gateway_credentials = creds

        if "custom_settings" in fields_to_update:
            custom = dict(settings.custom_settings or {})
            custom.update(fields_to_update.pop("custom_settings") or {})
            settings.custom_settings = custom

        for field, value in fields_to_update.items():
            setattr(settings, field, value)

        self.db.commit()
        self.db.refresh(settings)
        return settings

    def is_payment_required(self) -> bool:
        settings = self.get_or_create_default()
        return bool(settings.payment_required)

    def get_active_gateway(self) -> str:
        settings = self.get_or_create_default()
        return settings.default_gateway or "asaas"
