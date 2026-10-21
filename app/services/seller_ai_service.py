import asyncio
import logging
import re
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from app.models.chat_message import ChatMessage
from app.models.company_settings import CompanySettings
from app.models.payment import Payment
from app.models.user import User
from app.schemas.user import UserCreate
from app.services.ai.orchestrator import SalesOrchestrator
from app.services.ai.subagents.support_subagent import SupportSubagent
from app.services.company_settings_service import CompanySettingsService
from app.services.delivery_service import DeliveryService
from app.services.payment_service import PaymentService
from app.services.product_service import ProductService
from app.services.triage_service import TriageService
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

    def __init__(self, db: Session, triage_service: TriageService | None = None):
        self.db = db
        self.company_settings: CompanySettings = CompanySettingsService(db).get_or_create_default()
        self.gateway = WhatsAppGatewayService(db)
        self.user_service = UserService(db)
        self.payment_service = PaymentService(db)
        self.product_service = ProductService(db)
        self.delivery_service = DeliveryService(db)
        self.triage_service = triage_service or TriageService()

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
        elif (
            user
            and user.name.strip().lower() in ("cliente", "seja muito bem-vindo(a)")
            and name
            and name.strip()
            and name.strip().lower() != "cliente"
        ):
            user.name = name.strip()
            self.db.commit()
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

    def _update_customer_name_if_present(self, user: User, text: str) -> None:
        """Detecta se o cliente informou o próprio nome na mensagem e atualiza o cadastro."""
        import re

        patterns = [
            r"(?:^|\n)\s*(?:1[\.\-\)]\s*)?(?:meu\s+nome\s+[ée]|me\s+chamo|pode\s+me\s+chamar\s+de|sou\s+o|sou\s+a)\s+([A-Za-zÀ-ÖØ-öø-ÿ\s]{2,50})",
            r"(?:^|\n)\s*(?:1[\.\-\)]\s*)?nome(?:\s+completo)?\s*:\s*([A-Za-zÀ-ÖØ-öø-ÿ\s]{2,50})",
            r"(?:^|\n)\s*1[\.\-\)]\s*([A-Za-zÀ-ÖØ-öø-ÿ\s]{2,40})(?:\r?\n|$)",
        ]
        invalid_words = {
            "cliente", "obrigado", "obrigada", "valeu", "sim", "não", "nao", "ok",
            "bom dia", "boa tarde", "boa noite", "olá", "ola", "oi", "entrega",
            "retirada", "pix", "dinheiro", "cartao", "cartão", "camarão", "peixe",
            "produto", "endereço", "endereco", "rua", "av", "avenida",
        }
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                raw_name = match.group(1).strip()
                raw_name = re.sub(r"[\.,!?;].*$", "", raw_name).strip()
                words = [w for w in raw_name.split() if w]
                if (
                    raw_name
                    and 1 <= len(words) <= 5
                    and len(raw_name) >= 2
                    and not any(w.lower() in invalid_words for w in words)
                    and raw_name.lower() not in invalid_words
                ):
                    clean_name = " ".join(part.capitalize() for part in words)
                    user.name = clean_name
                    self.db.commit()
                    logger.info("Nome do cliente atualizado para '%s' (mensagem: '%s')", clean_name, text)
                    return

    def is_bot_message(self, message_id: str, phone: str, text: str) -> bool:
        """Verifica se a mensagem com fromMe: true foi disparada pela própria API ou por humano no WhatsApp Business."""
        from app.services.whatsapp.tracker import SentMessageTracker
        if SentMessageTracker.get_instance().is_bot_message(message_id):
            return True

        recent = (
            self.db.query(ChatMessage)
            .filter(ChatMessage.phone == phone, ChatMessage.role == "assistant")
            .order_by(ChatMessage.created_at.desc())
            .first()
        )
        if recent and recent.content and text:
            if recent.content.strip() == text.strip():
                return True
        return False

    @staticmethod
    def split_whatsapp_message(text: str, max_chunk_chars: int = 500, max_chunks: int = 4) -> list[str]:
        """
        Fraciona uma mensagem de IA em blocos menores e naturais para envio no WhatsApp.
        Suporta o separador explícito '---' e quebras duplas de parágrafo.
        """
        raw = (text or "").strip()
        if not raw:
            return []

        # Divide por delimitador explícito '---' ou '___' isolado em linhas
        raw_blocks = re.split(r"(?:\n\s*[-*_]{3,}\s*\n|\n{3,})", raw)

        chunks: list[str] = []
        for block in raw_blocks:
            block = block.strip()
            if not block:
                continue

            # Se o bloco for curto ou razoável, mantém íntegro
            if len(block) <= max_chunk_chars:
                chunks.append(block)
                continue

            # Se for longo, divide por quebras de parágrafo (\n\n)
            paragraphs = block.split("\n\n")
            current: list[str] = []
            curr_len = 0
            for p in paragraphs:
                p = p.strip()
                if not p:
                    continue
                if current and (curr_len + len(p) + 2 > max_chunk_chars):
                    chunks.append("\n\n".join(current).strip())
                    current = [p]
                    curr_len = len(p)
                else:
                    current.append(p)
                    curr_len += len(p) + 2
            if current:
                chunks.append("\n\n".join(current).strip())

        # Limita o número máximo de mensagens para não sobrecarregar com notificações
        if len(chunks) > max_chunks:
            head = chunks[:max_chunks - 1]
            tail = "\n\n".join(chunks[max_chunks - 1:])
            chunks = [*head, tail]

        return [c for c in chunks if c.strip()] or [raw]

    async def _send_fractioned_messages(self, phone: str, text: str, provider_name: str | None = None) -> None:
        """Envia os blocos fracionados via WhatsApp com pequeno intervalo para simular digitação natural."""
        chunks = self.split_whatsapp_message(text)
        if not chunks:
            return

        for i, chunk in enumerate(chunks):
            if i > 0:
                await asyncio.sleep(1.0)
            try:
                await self.gateway.send_text(phone, chunk, provider_name=provider_name)
            except Exception as exc:
                logger.error("Erro ao despachar bloco %d de mensagem via WhatsApp (%s): %s", i + 1, provider_name, exc)

    async def handle_inbound_message(self, inbound: InboundMessage) -> str:
        """Ponto de entrada único para qualquer mensagem recebida no WhatsApp."""
        phone = inbound.sender_phone
        text = inbound.text.strip()
        user = self._get_or_create_user(phone, inbound.sender_name)

        # Se for mensagem enviada do próprio número (fromMe: true / WhatsApp Business App)
        if inbound.is_from_me:
            # 1. Se for eco da mensagem que o próprio bot enviou via API, ignora
            if self.is_bot_message(inbound.message_id, phone, text):
                logger.debug("Mensagem %s ignorada: eco do envio do próprio bot para %s.", inbound.message_id, phone)
                return ""

            # 2. Intervenção de atendente humano pelo app WhatsApp Business
            self.company_settings = CompanySettingsService(self.db).get_or_create_default()
            if not self.company_settings.coexistence_enabled:
                logger.info("Coexistence desabilitada. Mensagem do atendente humano para %s ignorada.", phone)
                return ""

            lowered = text.lower()
            custom_fields = dict(user.custom_fields or {})

            # Comando do atendente para reativar IA: #ia, #bot, #ativar, #robo, #auto
            if any(cmd in lowered for cmd in ["#ia", "#bot", "#ativar", "#robo", "#auto"]):
                custom_fields.pop("ai_paused_until", None)
                user.custom_fields = custom_fields
                self.db.commit()
                self._record_chat(phone, "human_agent", text, inbound.provider)
                logger.info("Coexistence: Atendente reativou o bot via comando (%s) para o cliente %s.", text, phone)
                return ""

            # Comando do atendente para pausar por tempo longo: #pausa, #pause, #humano, #manual
            if any(cmd in lowered for cmd in ["#pausa", "#pause", "#humano", "#manual"]):
                paused_until = (datetime.now(UTC) + timedelta(hours=4)).isoformat()
                custom_fields["ai_paused_until"] = paused_until
                user.custom_fields = custom_fields
                self.db.commit()
                self._record_chat(phone, "human_agent", text, inbound.provider)
                logger.info("Coexistence: Atendente pausou a IA por 4 horas via comando (%s) para o cliente %s.", text, phone)
                return ""

            # Mensagem normal do atendente humano ao cliente
            pause_minutes = int(self.company_settings.coexistence_pause_minutes or 45)
            paused_until = (datetime.now(UTC) + timedelta(minutes=pause_minutes)).isoformat()
            custom_fields["ai_paused_until"] = paused_until
            user.custom_fields = custom_fields
            self.db.commit()

            # Registra no histórico como human_agent para que a IA tenha contexto quando reassumir
            self._record_chat(phone, "human_agent", text, inbound.provider)
            logger.info(
                "Coexistence: Atendente humano atendeu %s pelo WhatsApp Business. IA silenciada por %d minutos (até %s).",
                phone,
                pause_minutes,
                paused_until,
            )
            return ""

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

        # Identifica se o cliente informou o próprio nome
        self._update_customer_name_if_present(user, text)

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
                    logger.debug("Falha ao analisar data de pausa de IA para %s", phone)

        # 1. Triagem Ultrarrápida de Nível 1 com TypeSafe Jev (OpenRouter Decisions API)
        triage_result = None
        try:
            triage_result = await self.triage_service.evaluate(text, phone=phone)
        except Exception as exc:
            logger.warning("Erro na avaliação de triagem com Jev: %s. Prosseguindo para o orquestrador.", exc)

        if triage_result and not triage_result.is_fallback:
            logger.info(
                "Triagem Jev executada para %s: ação=%s, intent=%s (conf=%.2f), frustração=%s",
                phone,
                triage_result.recommended_action,
                triage_result.intent,
                triage_result.intent_confidence,
                triage_result.frustration_level,
            )

            # Ação 1: Transbordo Humano Imediato (0 tokens de LLM)
            if triage_result.recommended_action == "fast_handoff_human":
                support_subagent = SupportSubagent(self.company_settings, db=self.db, user=user, gateway=self.gateway)
                res_tool = await support_subagent.execute_tool(
                    "acionar_atendente_humano",
                    {"motivo": f"Solicitado pelo cliente via Triagem Jev (intenção: {triage_result.intent})"},
                )
                import json
                support_data = json.loads(res_tool)
                response_text = (
                    f"Com certeza, {user.name or 'Cliente'}! Já notifiquei nossa equipe de atendimento humano.\n\n"
                    f"Se preferir falar diretamente agora, basta clicar no link:\n"
                    f"👉 {support_data.get('link_suporte')}\n\n"
                    "Em instantes você será atendido! 🤝"
                )
                self._record_chat(phone, "assistant", response_text, inbound.provider)
                try:
                    await self._send_fractioned_messages(phone, response_text, provider_name=inbound.provider)
                except Exception as exc:
                    logger.error("Erro ao despachar fast_handoff_human via WhatsApp (%s): %s", inbound.provider, exc)
                return response_text

            # Ação 2: Confirmação Rápida de Pagamento PIX (0 tokens de LLM)
            if triage_result.recommended_action == "fast_check_pix":
                recent_payment = (
                    self.db.query(Payment)
                    .filter(Payment.user_id == user.id)
                    .order_by(Payment.created_at.desc())
                    .first()
                )
                if recent_payment:
                    if recent_payment.status in ("received", "confirmed"):
                        valor_str = f"R$ {recent_payment.amount_cents / 100:.2f}"
                        response_text = (
                            f"🎉 Excelente notícia, {user.name or 'Cliente'}! Localizamos o seu pagamento de *{valor_str}* confirmado com sucesso!\n\n"
                            f"📦 *Pedido #{recent_payment.id}* está confirmado e em preparação. Muito obrigado pela confiança! 🚀"
                        )
                    else:
                        valor_str = f"R$ {recent_payment.amount_cents / 100:.2f}"
                        link_pix = f"\n👉 Link do pagamento: {recent_payment.invoice_url}" if recent_payment.invoice_url else ""
                        response_text = (
                            f"Olá, {user.name or 'Cliente'}! Estou acompanhando seu pagamento de *{valor_str}* no sistema.\n\n"
                            f"⏳ Assim que a confirmação bancária for liquidada (normalmente leva poucos segundos), "
                            f"seu pedido será atualizado automaticamente aqui!{link_pix}"
                        )
                    self._record_chat(phone, "assistant", response_text, inbound.provider)
                    try:
                        await self._send_fractioned_messages(phone, response_text, provider_name=inbound.provider)
                    except Exception as exc:
                        logger.error("Erro ao despachar fast_check_pix via WhatsApp (%s): %s", inbound.provider, exc)
                    return response_text

            # Ação 3: Saudação Rápida Inicial (0 tokens de LLM)
            if triage_result.recommended_action == "fast_greeting":
                history = self._get_recent_history(phone)
                # Dispara resposta rápida apenas se for mensagem inicial sem histórico de compras ativo
                if len(history) <= 1:
                    company_name = self.company_settings.company_name or "Nossa Loja"
                    welcome = self.company_settings.welcome_message
                    if welcome and welcome.strip():
                        response_text = welcome.strip()
                    else:
                        response_text = (
                            f"Olá, {user.name or 'seja muito bem-vindo(a)'}! Tudo bem?\n\n"
                            f"Sou o consultor virtual da *{company_name}*. Como posso te ajudar hoje?"
                        )
                    self._record_chat(phone, "assistant", response_text, inbound.provider)
                    try:
                        await self._send_fractioned_messages(phone, response_text, provider_name=inbound.provider)
                    except Exception as exc:
                        logger.error("Erro ao despachar fast_greeting via WhatsApp (%s): %s", inbound.provider, exc)
                    return response_text

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
            delivery_service=self.delivery_service,
            gateway=self.gateway,
        )

        response_text = await orchestrator.process_message(text, history)

        # Registra a resposta do vendedor inteligente no histórico
        self._record_chat(phone, "assistant", response_text, inbound.provider)

        # Envia a mensagem de volta pelo canal WhatsApp do remetente de forma fracionada
        try:
            await self._send_fractioned_messages(phone, response_text, provider_name=inbound.provider)
        except Exception as exc:
            logger.error("Erro ao despachar resposta via WhatsApp Gateway (%s): %s", inbound.provider, exc)

        return response_text

