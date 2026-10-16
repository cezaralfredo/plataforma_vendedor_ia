import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy.orm import Session

from app.models.chat_message import ChatMessage
from app.models.delivery import Delivery
from app.models.payment import Payment
from app.models.user import User
from app.services.whatsapp.gateway import WhatsAppGatewayService

logger = logging.getLogger(__name__)


class SalesRecoveryService:
    """
    Serviço inteligente de recuperação de vendas e follow-up no WhatsApp.
    Identifica clientes com carrinhos/pedidos pendentes ou conversas sem fechamento
    após um período de inatividade e dispara uma mensagem amigável de recuperação.
    """

    def __init__(self, db: Session):
        self.db = db
        self.gateway = WhatsAppGatewayService(db)

    def find_pending_leads(self, minutes_idle: int = 45, max_age_hours: int = 24) -> list[User]:
        now = datetime.now(UTC)
        idle_threshold = now - timedelta(minutes=minutes_idle)
        max_age_threshold = now - timedelta(hours=max_age_hours)

        # 1. Usuários com entregas ainda em preparação sem avanço
        pending_delivery_user_ids = [
            r[0]
            for r in self.db.query(Delivery.user_id)
            .filter(
                Delivery.delivery_status == "preparando",
                Delivery.created_at <= idle_threshold,
                Delivery.created_at >= max_age_threshold,
            )
            .distinct()
            .all()
        ]

        # 2. Usuários com cobranças pendentes
        pending_payment_user_ids = [
            r[0]
            for r in self.db.query(Payment.user_id)
            .filter(
                Payment.status == "pending",
                Payment.created_at <= idle_threshold,
                Payment.created_at >= max_age_threshold,
                Payment.user_id.isnot(None),
            )
            .distinct()
            .all()
        ]

        candidate_ids = set(pending_delivery_user_ids + pending_payment_user_ids)
        if not candidate_ids:
            return []

        users = self.db.query(User).filter(User.id.in_(candidate_ids), User.active.is_(True)).all()
        eligible_users = []

        for u in users:
            custom = u.custom_fields or {}
            # Não perturba quem já recebeu follow-up nas últimas 24 horas
            last_followup = custom.get("last_followup_at")
            if last_followup:
                try:
                    dt = datetime.fromisoformat(last_followup)
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=UTC)
                    if now - dt < timedelta(hours=20):
                        continue
                except Exception as exc:
                    logger.debug("Falha ao analisar last_followup_at para o lead %s: %s", u.id, exc)

            phone = u.whatsapp_number or u.phone
            if phone:
                eligible_users.append(u)

        return eligible_users

    def _get_company_name(self) -> str:
        """Obtém o nome da empresa configurado ou retorna padrão elegante."""
        try:
            from app.models.company_settings import CompanySettings
            settings = self.db.query(CompanySettings).first()
            if settings and settings.company_name and settings.company_name.strip():
                return settings.company_name.strip()
        except Exception as exc:
            logger.debug("Falha ao recuperar company_name em SalesRecoveryService: %s", exc)
        return "Anauê Design"

    async def send_followup_to_user(self, user: User, custom_text: str | None = None) -> dict[str, Any]:
        phone = user.whatsapp_number or user.phone
        if not phone:
            return {"success": False, "error": "Cliente sem número de telefone"}

        company_name = self._get_company_name()

        if custom_text and custom_text.strip():
            msg_text = custom_text.strip()
        else:
            # Identifica item ou pedido pendente recente para contextualizar
            recent_del = (
                self.db.query(Delivery)
                .filter(Delivery.user_id == user.id, Delivery.delivery_status == "preparando")
                .order_by(Delivery.created_at.desc())
                .first()
            )
            item_hint = f" (*{recent_del.items_description}*)" if (recent_del and recent_del.items_description) else ""

            msg_text = (
                f"Olá, *{user.name}*! Tudo bem? 😊\n\n"
                f"Passando para saber se ficou alguma dúvida sobre seu pedido{item_hint} na *{company_name}*!\n"
                "Se preferir, nós podemos agilizar a entrega para você **pagar somente no ato do recebimento** "
                "(em Dinheiro, PIX ou Cartão com o entregador)! 🚚\n\n"
                "Posso confirmar o envio para o seu endereço?"
            )

        send_success = False
        error_msg = None
        try:
            res = await self.gateway.send_text(phone, msg_text)
            send_success = getattr(res, "success", False)
            if not send_success:
                error_msg = getattr(res, "error", "Falha de envio")
        except Exception as e:
            logger.warning("Erro ao enviar follow-up para %s: %s", phone, e)
            error_msg = str(e)

        # Atualiza o timestamp de follow-up
        now_iso = datetime.now(UTC).isoformat()
        custom = dict(user.custom_fields or {})
        custom["last_followup_at"] = now_iso
        user.custom_fields = custom

        # Registra a mensagem no histórico do chat
        chat_msg = ChatMessage(
            phone=phone,
            role="assistant",
            content=msg_text,
            provider="recovery_service",
            created_at=datetime.now(UTC),
        )
        self.db.add(chat_msg)
        self.db.commit()

        return {
            "success": send_success,
            "error": error_msg,
            "user_id": user.id,
            "user_name": user.name,
            "phone": phone,
            "sent_at": now_iso,
        }

    async def run_batch_recovery(self, minutes_idle: int = 45) -> dict[str, Any]:
        leads = self.find_pending_leads(minutes_idle=minutes_idle)
        contacted = 0
        details = []

        for user in leads:
            res = await self.send_followup_to_user(user)
            if res.get("success"):
                contacted += 1
            details.append(res)

        return {
            "total_leads_found": len(leads),
            "total_contacted": contacted,
            "details": details,
        }
