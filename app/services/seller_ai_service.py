import logging
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.models.chat_message import ChatMessage
from app.models.company_settings import CompanySettings
from app.models.user import User
from app.schemas.user import UserCreate
from app.services.ai.orchestrator import SalesOrchestrator
from app.services.company_settings_service import CompanySettingsService
from app.services.payment_service import PaymentService
from app.services.product_service import ProductService
from app.services.user_service import UserService
from app.services.whatsapp.base import InboundMessage
from app.services.whatsapp.gateway import WhatsAppGatewayService

logger = logging.getLogger(__name__)


class SellerAIService:
    """
    Motor de Vendas Inteligente via WhatsApp.
    Recebe mensagens inbound dos canais (WAHA, Evolution ou Meta Cloud),
    identifica/cadastra o cliente, delega a conversação e tomada de decisão
    para o SalesOrchestrator (com os subagentes de catálogo, checkout PIX Asaas,
    pedidos e transbordo humano) e despacha a resposta de volta ao cliente.
    """

    def __init__(self, db: Session):
        self.db = db
        self.company_settings: CompanySettings = CompanySettingsService(db).get_or_create_default()
        self.gateway = WhatsAppGatewayService(db)
        self.user_service = UserService(db)
        self.payment_service = PaymentService(db)
        self.product_service = ProductService(db)

    def _get_or_create_user(self, phone: str, name: str | None = None) -> User:
        user = self.user_service.find_by_phone(phone)
        if not user:
            clean_name = (name or "Cliente").strip() or "Cliente"
            try:
                user = self.user_service.create(
                    UserCreate(
                        name=clean_name,
                        phone=phone,
                        whatsapp_number=phone,
                    )
                )
            except Exception as exc:
                logger.warning("Erro ao cadastrar novo cliente via WhatsApp: %s", exc)
                user = self.user_service.find_by_phone(phone)
        return user

    def _record_chat(self, phone: str, role: str, content: str, provider: str | None = None) -> None:
        msg = ChatMessage(
            phone=phone,
            role=role,
            content=content,
            provider=provider,
            created_at=datetime.now(UTC),
        )
        self.db.add(msg)
        self.db.commit()

    def _get_recent_history(self, phone: str, limit: int = 8) -> list[ChatMessage]:
        return (
            self.db.query(ChatMessage)
            .filter(ChatMessage.phone == phone)
            .order_by(ChatMessage.created_at.desc())
            .limit(limit)
            .all()
        )[::-1]

    def _extract_seller_code(self, text: str) -> str | None:
        import re
        from app.models.seller import Seller

        patterns = [
            r"vendedor[a]?\s+([A-Za-z0-9\-_]+)",
            r"c[oó]digo\s+([A-Za-z0-9\-_]+)",
            r"\b(VEND[A-Za-z0-9\-_]*)\b",
        ]
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                candidate = match.group(1).strip().upper()
                seller = self.db.query(Seller).filter(Seller.code == candidate).first()
                if seller:
                    return seller.code
        return None

    def _update_seller_attribution_if_present(self, user: User, text: str) -> None:
        from app.models.seller import Seller

        seller_code = self._extract_seller_code(text)
        if not seller_code:
            return

        seller = self.db.query(Seller).filter(Seller.code == seller_code).first()
        if not seller:
            return

        custom = dict(user.custom_fields or {})
        custom["seller_id"] = seller.id
        custom["branch_id"] = seller.branch_id
        custom["seller_code"] = seller.code
        custom["seller_name"] = seller.name
        if seller.branch:
            custom["branch_name"] = seller.branch.name
        user.custom_fields = custom
        self.db.commit()
        logger.info(
            "Cliente %s atribuído com sucesso ao vendedor '%s' (Filial: %s)",
            user.phone,
            seller.name,
            seller.branch.name if seller.branch else "N/A",
        )

    async def handle_inbound_message(self, inbound: InboundMessage) -> str:
        """Ponto de entrada único para qualquer mensagem recebida no WhatsApp."""
        phone = inbound.sender_phone
        text = inbound.text.strip()
        user = self._get_or_create_user(phone, inbound.sender_name)

        # Se for mensagem de áudio, tenta transcrever com Whisper
        if getattr(inbound, "media_type", None) == "audio" and inbound.media_url:
            try:
                from app.services.whatsapp.transcription_service import AudioTranscriptionService
                transcription = await AudioTranscriptionService(self.db).download_and_transcribe(inbound.media_url)
                if transcription:
                    text = transcription
                    logger.info("Áudio do WhatsApp (%s) transcrito com sucesso: '%s'", phone, text)
            except Exception as e:
                logger.warning("Falha ao tentar transcrever áudio recebido: %s", e)

        # Identifica se a mensagem contém indicação ou link de um vendedor específico
        self._update_seller_attribution_if_present(user, text)

        # Registra a mensagem do cliente no histórico
        self._record_chat(phone, "user", text, inbound.provider)


        # Verifica se o autoatendimento da IA está pausado para este cliente (transbordo humano ativo)
        custom_fields = dict(user.custom_fields or {})
        ai_paused_until_str = custom_fields.get("ai_paused_until")
        if ai_paused_until_str:
            # Permite ao cliente reativar a IA caso envie comandos de retomada
            lowered = text.lower()
            if any(w in lowered for w in ["voltar para o bot", "retomar ia", "falar com robô", "reiniciar ia", "menu"]):
                custom_fields.pop("ai_paused_until", None)
                user.custom_fields = custom_fields
                self.db.commit()
                logger.info("Atendimento por IA retomado para o cliente %s pelo comando do usuário.", phone)
            else:
                try:
                    paused_until = datetime.fromisoformat(ai_paused_until_str)
                    if paused_until.tzinfo is None:
                        paused_until = paused_until.replace(tzinfo=UTC)
                    if datetime.now(UTC) < paused_until:
                        logger.info("IA pausada para o telefone %s até %s (atendente humano em atendimento).", phone, paused_until)
                        return ""
                except Exception:
                    pass

        history = self._get_recent_history(phone)

        # Atualiza as configurações da empresa antes de orquestrar
        self.company_settings = CompanySettingsService(self.db).get_or_create_default()

        # Instancia o SalesOrchestrator com o provedor de IA escolhido pelo cliente
        orchestrator = SalesOrchestrator(
            db=self.db,
            user=user,
            company_settings=self.company_settings,
            payment_service=self.payment_service,
            product_service=self.product_service,
        )

        response_text = await orchestrator.process_message(text, history)

        # Registra a resposta do vendedor inteligente no histórico
        self._record_chat(phone, "assistant", response_text, inbound.provider)

        # Envia a mensagem de volta pelo canal WhatsApp do remetente
        try:
            await self.gateway.send_text(phone, response_text, provider_name=inbound.provider)
        except Exception as exc:
            logger.error("Erro ao despachar resposta via WhatsApp Gateway (%s): %s", inbound.provider, exc)

        return response_text

