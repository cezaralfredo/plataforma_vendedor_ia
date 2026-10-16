import logging
import urllib.parse
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, or_
from sqlalchemy.orm import Session, joinedload

from app.models.delivery import Delivery
from app.models.user import User
from app.schemas.delivery import DeliveryCreate, DeliveryUpdate
from app.services.whatsapp.gateway import WhatsAppGatewayService

logger = logging.getLogger(__name__)


class DeliveryService:
    def __init__(self, db: Session):
        self.db = db

    def _generate_order_code(self) -> str:
        """Gera código único legível para o pedido de entrega, ex: ENT-1001."""
        count = self.db.query(func.count(Delivery.id)).scalar() or 0
        return f"ENT-{(count + 1):04d}"

    def list_deliveries(
        self,
        delivery_status: str | None = None,
        payment_timing: str | None = None,
        payment_status: str | None = None,
        branch_id: int | None = None,
        seller_id: int | None = None,
        search: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        query = (
            self.db.query(Delivery)
            .options(
                joinedload(Delivery.user),
                joinedload(Delivery.branch),
                joinedload(Delivery.seller),
            )
        )

        if delivery_status:
            query = query.filter(Delivery.delivery_status == delivery_status)
        if payment_timing:
            query = query.filter(Delivery.payment_timing == payment_timing)
        if payment_status:
            query = query.filter(Delivery.payment_status == payment_status)
        if branch_id:
            query = query.filter(Delivery.branch_id == branch_id)
        if seller_id:
            query = query.filter(Delivery.seller_id == seller_id)

        if search:
            term = f"%{search.strip()}%"
            query = query.join(Delivery.user).filter(
                or_(
                    Delivery.order_code.ilike(term),
                    Delivery.items_description.ilike(term),
                    Delivery.delivery_address.ilike(term),
                    Delivery.delivery_driver_name.ilike(term),
                    User.name.ilike(term),
                    User.phone.ilike(term),
                    User.whatsapp_number.ilike(term),
                )
            )

        deliveries = query.order_by(Delivery.created_at.desc()).offset(offset).limit(limit).all()
        return [self._format_delivery_dict(d) for d in deliveries]

    def get_delivery(self, delivery_id: int) -> dict[str, Any] | None:
        delivery = (
            self.db.query(Delivery)
            .options(
                joinedload(Delivery.user),
                joinedload(Delivery.branch),
                joinedload(Delivery.seller),
            )
            .filter(Delivery.id == delivery_id)
            .first()
        )
        if not delivery:
            return None
        return self._format_delivery_dict(delivery)

    def create_delivery(self, data: DeliveryCreate) -> dict[str, Any]:
        user = self.db.get(User, data.user_id)
        if not user:
            raise ValueError(f"Cliente ID {data.user_id} não encontrado.")

        order_code = self._generate_order_code()
        address = (data.delivery_address or user.full_address or "").strip()
        if not address:
            raise ValueError("O endereço de entrega completo é obrigatório.")

        delivery = Delivery(
            order_code=order_code,
            user_id=data.user_id,
            branch_id=data.branch_id,
            seller_id=data.seller_id,
            payment_id=data.payment_id,
            items_description=data.items_description.strip(),
            total_amount_cents=data.total_amount_cents,
            payment_method=data.payment_method,
            payment_timing=data.payment_timing,
            payment_status=data.payment_status,
            delivery_status=data.delivery_status,
            delivery_address=address,
            delivery_driver_name=data.delivery_driver_name.strip() if data.delivery_driver_name else None,
            notes=data.notes.strip() if data.notes else None,
        )

        if delivery.delivery_status == "a_caminho":
            delivery.dispatched_at = datetime.now(UTC)

        self.db.add(delivery)
        self.db.commit()
        self.db.refresh(delivery)
        return self._format_delivery_dict(delivery)

    def update_delivery(self, delivery_id: int, data: DeliveryUpdate) -> dict[str, Any] | None:
        delivery = self.db.get(Delivery, delivery_id)
        if not delivery:
            return None

        values = data.model_dump(exclude_unset=True)
        if "delivery_status" in values:
            new_status = values["delivery_status"]
            if new_status == "a_caminho" and not delivery.dispatched_at:
                delivery.dispatched_at = datetime.now(UTC)
            elif new_status == "entregue" and not delivery.delivered_at:
                delivery.delivered_at = datetime.now(UTC)
                if delivery.payment_timing == "na_entrega":
                    delivery.payment_status = "pago"

        for field, value in values.items():
            if isinstance(value, str):
                value = value.strip()
            setattr(delivery, field, value)

        self.db.commit()
        self.db.refresh(delivery)
        return self._format_delivery_dict(delivery)

    def update_status(
        self,
        delivery_id: int,
        delivery_status: str,
        payment_status: str | None = None,
        delivery_driver_name: str | None = None,
    ) -> dict[str, Any] | None:
        delivery = self.db.get(Delivery, delivery_id)
        if not delivery:
            return None

        delivery.delivery_status = delivery_status
        now = datetime.now(UTC)

        if delivery_status == "a_caminho" and not delivery.dispatched_at:
            delivery.dispatched_at = now
        elif delivery_status == "entregue":
            delivery.delivered_at = now
            if delivery.payment_timing == "na_entrega" and not payment_status:
                delivery.payment_status = "pago"

        if payment_status:
            delivery.payment_status = payment_status
        if delivery_driver_name is not None:
            delivery.delivery_driver_name = delivery_driver_name.strip() if delivery_driver_name else None

        self.db.commit()
        self.db.refresh(delivery)
        return self._format_delivery_dict(delivery)

    async def notify_dispatch_via_whatsapp(
        self, delivery_id: int, custom_message: str | None = None
    ) -> dict[str, Any]:
        """
        Dispara mensagem via WhatsApp para avisar o cliente que o produto está a caminho.
        Atualiza o status para 'a_caminho' e grava customer_notified_at.
        """
        delivery = (
            self.db.query(Delivery)
            .options(
                joinedload(Delivery.user),
                joinedload(Delivery.branch),
                joinedload(Delivery.seller),
            )
            .filter(Delivery.id == delivery_id)
            .first()
        )
        if not delivery:
            raise ValueError(f"Entrega ID {delivery_id} não encontrada.")

        client = delivery.user
        phone = client.whatsapp_number or client.phone
        if not phone:
            raise ValueError("O cliente não possui número de WhatsApp ou telefone cadastrado.")

        # Montagem da mensagem amigável e clara
        total_reais = f"R$ {delivery.total_amount_cents / 100:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        
        if delivery.payment_timing == "antecipado" or delivery.payment_status == "pago":
            payment_info = "✅ *Pagamento Antecipado (Já Liquidado)*"
        else:
            method_label = {
                "pix": "PIX",
                "dinheiro": "Dinheiro",
                "cartao_credito": "Cartão de Crédito",
                "cartao_debito": "Cartão de Débito",
            }.get(delivery.payment_method, "PIX / Dinheiro / Cartão")
            payment_info = f"💵 *Pagar na Entrega: {total_reais}* ({method_label})"

        driver_info = f"\n🛵 *Entregador:* {delivery.delivery_driver_name}" if delivery.delivery_driver_name else ""

        if custom_message and custom_message.strip():
            message_text = custom_message.strip()
        else:
            message_text = (
                f"🚚 *Seu pedido está a caminho!*\n\n"
                f"Olá, *{client.name}*! Temos uma ótima notícia da *Anauê Design*:\n"
                f"O seu pedido (*{delivery.order_code}*) já foi separado e o entregador está a caminho do seu endereço!\n\n"
                f"📦 *Itens do Pedido:*\n{delivery.items_description}\n\n"
                f"📍 *Endereço de Entrega:*\n{delivery.delivery_address}\n\n"
                f"💰 *Forma de Pagamento:*\n{payment_info}"
                f"{driver_info}\n\n"
                f"Por favor, certifique-se de que haverá alguém para receber. Qualquer dúvida, é só nos responder aqui! 🤝"
            )

        now = datetime.now(UTC)
        delivery.customer_notified_at = now
        if delivery.delivery_status == "preparando":
            delivery.delivery_status = "a_caminho"
            delivery.dispatched_at = now

        self.db.commit()
        self.db.refresh(delivery)

        # Envio ativo via gateway WhatsApp integrado
        send_success = False
        gateway_error = None
        try:
            gateway = WhatsAppGatewayService(self.db)
            res = await gateway.send_text(phone, message_text)
            send_success = getattr(res, "success", False)
            if not send_success:
                gateway_error = getattr(res, "error", "Falha de envio no gateway")
        except Exception as e:
            logger.warning(f"Aviso ao cliente via WhatsApp Gateway falhou: {e}")
            gateway_error = str(e)

        direct_url = self._build_wa_link(phone, message_text)

        return {
            "success": True,
            "dispatched": True,
            "gateway_sent": send_success,
            "gateway_error": gateway_error,
            "whatsapp_direct_url": direct_url,
            "message": message_text,
            "customer_notified_at": delivery.customer_notified_at.isoformat() if delivery.customer_notified_at else None,
            "delivery": self._format_delivery_dict(delivery),
        }

    def get_kpis(self) -> dict[str, Any]:
        """Retorna indicadores operacionais de logística."""
        total = self.db.query(func.count(Delivery.id)).scalar() or 0
        preparing = (
            self.db.query(func.count(Delivery.id))
            .filter(Delivery.delivery_status == "preparando")
            .scalar()
            or 0
        )
        in_transit = (
            self.db.query(func.count(Delivery.id))
            .filter(Delivery.delivery_status == "a_caminho")
            .scalar()
            or 0
        )

        # Entregues hoje
        today_start = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
        delivered_today = (
            self.db.query(func.count(Delivery.id))
            .filter(
                Delivery.delivery_status == "entregue",
                Delivery.delivered_at >= today_start,
            )
            .scalar()
            or 0
        )

        # Total a cobrar na entrega (onde pagamento ainda está pendente)
        to_collect_cents = (
            self.db.query(func.sum(Delivery.total_amount_cents))
            .filter(
                Delivery.payment_timing == "na_entrega",
                Delivery.payment_status == "pendente",
                Delivery.delivery_status != "cancelado",
            )
            .scalar()
            or 0
        )

        return {
            "total_deliveries": total,
            "preparing_count": preparing,
            "in_transit_count": in_transit,
            "delivered_today_count": delivered_today,
            "to_collect_cents": int(to_collect_cents),
        }

    def _build_wa_link(self, phone: str, text: str) -> str:
        clean_phone = "".join(filter(str.isdigit, phone or ""))
        if len(clean_phone) in (10, 11) and not clean_phone.startswith("55"):
            clean_phone = "55" + clean_phone
        encoded_text = urllib.parse.quote(text)
        return f"https://wa.me/{clean_phone}?text={encoded_text}"

    def _format_delivery_dict(self, d: Delivery) -> dict[str, Any]:
        user_name = d.user.name if d.user else "Cliente Desconhecido"
        user_phone = d.user.phone if d.user else ""
        user_whatsapp = d.user.whatsapp_number if d.user else ""
        branch_name = d.branch.name if d.branch else None
        seller_name = d.seller.name if d.seller else None

        phone_to_use = user_whatsapp or user_phone
        quick_msg = f"Olá, {user_name}! Seu pedido {d.order_code} da Anauê Design está a caminho!"
        wa_link = self._build_wa_link(phone_to_use, quick_msg) if phone_to_use else None

        return {
            "id": d.id,
            "order_code": d.order_code,
            "user_id": d.user_id,
            "user_name": user_name,
            "user_phone": user_phone,
            "user_whatsapp": user_whatsapp,
            "branch_id": d.branch_id,
            "branch_name": branch_name,
            "seller_id": d.seller_id,
            "seller_name": seller_name,
            "payment_id": d.payment_id,
            "items_description": d.items_description,
            "total_amount_cents": d.total_amount_cents,
            "payment_method": d.payment_method,
            "payment_timing": d.payment_timing,
            "payment_status": d.payment_status,
            "delivery_status": d.delivery_status,
            "delivery_address": d.delivery_address,
            "delivery_driver_name": d.delivery_driver_name,
            "dispatched_at": d.dispatched_at.isoformat() if d.dispatched_at else None,
            "delivered_at": d.delivered_at.isoformat() if d.delivered_at else None,
            "customer_notified_at": d.customer_notified_at.isoformat() if d.customer_notified_at else None,
            "notes": d.notes,
            "created_at": d.created_at.isoformat() if d.created_at else None,
            "updated_at": d.updated_at.isoformat() if d.updated_at else None,
            "whatsapp_direct_url": wa_link,
        }
