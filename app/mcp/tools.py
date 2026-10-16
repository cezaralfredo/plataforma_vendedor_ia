import logging
from datetime import datetime as dt_cls
from datetime import timedelta

import httpx
from sqlalchemy.orm import Session, joinedload

from app.config import settings
from app.models.appointment import Appointment
from app.schemas.appointment import AppointmentCreate
from app.schemas.user import UserCreate, UserUpdate
from app.services.appointment_service import AppointmentService
from app.services.asaas_client import AsaasIntegrationError
from app.services.payment_service import PaymentService
from app.services.product_service import ProductService
from app.services.user_service import UserService

logger = logging.getLogger(__name__)

TOOL_DEFINITIONS = [
    {
        "name": "buscar_cliente_por_telefone",
        "description": "Busca um cliente cadastrado pelo número de telefone/WhatsApp, nome completo ou CPF/CNPJ",
        "inputSchema": {
            "type": "object",
            "properties": {
                "phone": {"type": "string", "description": "Número de telefone ou WhatsApp (opcional)"},
                "name": {"type": "string", "description": "Nome completo ou parcial do cliente (opcional)"},
                "cpf_cnpj": {"type": "string", "description": "CPF ou CNPJ do cliente (opcional)"},
            },
        },
    },
    {
        "name": "cadastrar_cliente",
        "description": "Cadastra um novo cliente",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Nome completo do cliente"},
                "phone": {"type": "string", "description": "Número de telefone no formato 55XXXXXXXXXXX"},
                "email": {"type": "string", "description": "Email do cliente (opcional)"},
                "whatsapp_number": {"type": "string", "description": "Número do WhatsApp no formato 55XXXXXXXXXXX (opcional)"},
                "cpf_cnpj": {"type": "string", "description": "CPF ou CNPJ do cliente (opcional, apenas números ou formatado)"},
            },
            "required": ["name", "phone"],
        },
    },
    {
        "name": "atualizar_cliente",
        "description": "Atualiza dados de um cliente existente",
        "inputSchema": {
            "type": "object",
            "properties": {
                "user_id": {"type": "integer", "description": "ID do cliente"},
                "name": {"type": "string", "description": "Nome completo (opcional)"},
                "phone": {"type": "string", "description": "Telefone (opcional)"},
                "email": {"type": "string", "description": "Email (opcional)"},
                "whatsapp_number": {"type": "string", "description": "WhatsApp (opcional)"},
                "cpf_cnpj": {"type": "string", "description": "CPF ou CNPJ (opcional)"},
            },
            "required": ["user_id"],
        },
    },
    {
        "name": "vincular_whatsapp",
        "description": "Vincula um número de WhatsApp a um cliente existente",
        "inputSchema": {
            "type": "object",
            "properties": {
                "user_id": {"type": "integer", "description": "ID do cliente"},
                "whatsapp_number": {"type": "string", "description": "Número do WhatsApp no formato 55XXXXXXXXXXX"},
            },
            "required": ["user_id", "whatsapp_number"],
        },
    },
    {
        "name": "listar_produtos",
        "description": "Lista produtos disponíveis para venda por categoria ou termo de busca, com preço, peso (kg) e estoque",
        "inputSchema": {
            "type": "object",
            "properties": {
                "category": {"type": "string", "description": "Categoria do produto (opcional)"},
                "search": {"type": "string", "description": "Termo de busca pelo nome ou descrição (opcional)"},
                "in_stock_only": {"type": "boolean", "description": "Se verdadeiro, lista apenas itens com estoque > 0 (padrão: true)"},
            },
        },
    },
    {
        "name": "consultar_produto",
        "description": "Consulta detalhes, preço, peso (kg) e estoque de um produto específico por ID ou nome",
        "inputSchema": {
            "type": "object",
            "properties": {
                "product_id": {"type": "integer", "description": "ID do produto (opcional)"},
                "name": {"type": "string", "description": "Nome ou parte do nome do produto (opcional)"},
            },
        },
    },
    {
        "name": "criar_reserva",
        "description": "Cria uma nova reserva (agendamento) para um cliente",
        "inputSchema": {
            "type": "object",
            "properties": {
                "user_id": {"type": "integer", "description": "ID do cliente"},
                "professional_id": {"type": "integer", "description": "ID do profissional"},
                "service_id": {"type": "integer", "description": "ID do serviço"},
                "start_time": {"type": "string", "description": "Horário início (ISO 8601)"},
                "end_time": {"type": "string", "description": "Horário fim (ISO 8601)"},
                "notes": {"type": "string", "description": "Observações (opcional)"},
            },
            "required": ["user_id", "professional_id", "service_id", "start_time", "end_time"],
        },
    },
    {
        "name": "cancelar_reserva",
        "description": "Cancela uma reserva existente",
        "inputSchema": {
            "type": "object",
            "properties": {
                "appointment_id": {"type": "integer", "description": "ID do agendamento"},
            },
            "required": ["appointment_id"],
        },
    },
    {
        "name": "criar_cobranca_asaas",
        "description": "Cria uma cobrança no Asaas para uma venda de produto ou agendamento e retorna o link de pagamento",
        "inputSchema": {
            "type": "object",
            "properties": {
                "appointment_id": {"type": "integer", "description": "ID do agendamento (opcional se fornecido user_id)"},
                "user_id": {"type": "integer", "description": "ID do cliente (opcional se appointment_id informado)"},
                "product_id": {"type": "integer", "description": "ID do produto vendido (opcional)"},
                "amount_cents": {"type": "integer", "description": "Valor em centavos (opcional, calculado automaticamente se product_id informado)"},
                "description": {"type": "string", "description": "Descrição da venda (opcional)"},
                "billing_type": {
                    "type": "string",
                    "description": "Tipo: PIX, BOLETO, CREDIT_CARD ou UNDEFINED",
                    "default": "UNDEFINED",
                },
            },
        },
    },
    {
        "name": "verificar_pagamentos_recentes",
        "description": "Verifica pagamentos pendentes no Asaas e atualiza status dos que foram confirmados",
        "inputSchema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "listar_pendentes_notificacao",
        "description": "Lista agendamentos com pagamento confirmado que ainda não foram notificados ao cliente",
        "inputSchema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "marcar_notificado",
        "description": "Legado: a confirmação de pagamento é registrada automaticamente após entrega pelo WhatsApp.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "appointment_id": {"type": "integer", "description": "ID do agendamento"},
            },
            "required": ["appointment_id"],
        },
    },
    {
        "name": "meus_agendamentos",
        "description": "Lista os agendamentos de um cliente por ID, número de telefone/WhatsApp, nome ou CPF/CNPJ (oculta automaticamente reservas canceladas sem pagamento)",
        "inputSchema": {
            "type": "object",
            "properties": {
                "user_id": {"type": "integer", "description": "ID do cliente (opcional se phone, name ou cpf_cnpj informado)"},
                "phone": {"type": "string", "description": "Número do telefone/WhatsApp do cliente (opcional)"},
                "name": {"type": "string", "description": "Nome completo ou parcial do cliente (opcional)"},
                "cpf_cnpj": {"type": "string", "description": "CPF ou CNPJ do cliente (opcional)"},
                "include_unpaid_cancelled": {"type": "boolean", "description": "Se verdadeiro, inclui reservas canceladas sem pagamento (padrão: false)"},
            },
        },
    },
    {
        "name": "verificar_status_pagamento",
        "description": "Verifica em tempo real o status de pagamento de um agendamento junto ao Asaas, confirma a reserva se pago e retorna mensagem com detalhes completos",
        "inputSchema": {
            "type": "object",
            "properties": {
                "appointment_id": {"type": "integer", "description": "ID do agendamento"},
            },
            "required": ["appointment_id"],
        },
    },
    {
        "name": "solicitar_agendamento_orquestrador_n8n",
        "description": "Aciona o Orquestrador central do n8n para criar o agendamento completo (busca/cadastra cliente, valida disponibilidade, cria reserva e gera cobrança PIX no Asaas) e retorna o link de pagamento e código PIX.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "client_name": {"type": "string", "description": "Nome completo do cliente"},
                "phone": {"type": "string", "description": "Número do WhatsApp no formato 55XXXXXXXXXXX"},
                "cpf_cnpj": {"type": "string", "description": "CPF ou CNPJ do cliente (apenas números ou formatado) para emissão de cobrança no Asaas (opcional/recomendado)"},
                "professional_id": {"description": "ID do profissional (número) ou nome do profissional"},
                "service_id": {"description": "ID do serviço (número) ou nome do serviço"},
                "start_time": {"type": "string", "description": "Horário início (ISO 8601, ex: 2026-09-25T14:00:00-03:00)"},
                "end_time": {"type": "string", "description": "Horário fim (ISO 8601). OPCIONAL: calculado automaticamente a partir da duração do serviço."},
                "notes": {"type": "string", "description": "Observações (opcional)"},
            },
            "required": ["client_name", "phone", "professional_id", "service_id", "start_time"],
        },
    },
    {
        "name": "solicitar_cancelamento_n8n",
        "description": "Aciona o Subagente de Cancelamento do n8n para cancelar a reserva, liberar o horário na agenda e disparar a notificação de cancelamento.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "appointment_id": {"type": "integer", "description": "ID do agendamento"},
                "phone": {"type": "string", "description": "Número de WhatsApp do cliente (opcional)"},
            },
            "required": ["appointment_id"],
        },
    },
    {
        "name": "triar_mensagem",
        "description": "Realiza triagem ultrarrápida de uma mensagem de cliente usando o TypeSafe Jev. Detecta intenção, pedido de atendimento humano, afirmação de pagamento PIX e nível de frustração.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "message": {"type": "string", "description": "Texto da mensagem enviada pelo cliente"},
                "phone": {"type": "string", "description": "Telefone/WhatsApp do cliente (opcional)"},
            },
            "required": ["message"],
        },
    },
]


async def handle_tool_call(name: str, arguments: dict, db: Session) -> dict:
    try:
        if name == "buscar_cliente_por_telefone":
            user_service = UserService(db)
            phone = arguments.get("phone")
            name_arg = arguments.get("name")
            cpf_cnpj = arguments.get("cpf_cnpj")
            query = arguments.get("query")
            if not any([phone, name_arg, cpf_cnpj, query]):
                return {"content": [{"type": "text", "text": "Informe o telefone, nome ou CPF do cliente para a busca."}]}
            user = user_service.find_by_identifier(
                query=query, phone=phone, name=name_arg, cpf_cnpj=cpf_cnpj
            )
            if not user or not getattr(user, "active", True):
                return {"content": [{"type": "text", "text": "Cliente não encontrado."}]}
            return {"content": [{"type": "text", "text": _format_cliente(user)}]}

        elif name == "cadastrar_cliente":
            user_service = UserService(db)
            try:
                user_create = UserCreate(
                    name=arguments["name"],
                    phone=arguments["phone"],
                    email=arguments.get("email"),
                    whatsapp_number=arguments.get("whatsapp_number"),
                    cpf_cnpj=arguments.get("cpf_cnpj"),
                )
                user = user_service.create(user_create)
                return {
                    "content": [
                        {
                            "type": "text",
                            "text": f"Cliente cadastrado com sucesso!\n{_format_cliente(user)}",
                        }
                    ]
                }
            except ValueError as e:
                # Se já existe por telefone ou CPF, retornar o cadastro existente amigavelmente
                existing = user_service.find_by_identifier(
                    phone=arguments.get("phone"),
                    cpf_cnpj=arguments.get("cpf_cnpj"),
                    name=arguments.get("name"),
                )
                if existing:
                    return {
                        "isError": True,
                        "content": [
                            {
                                "type": "text",
                                "text": (
                                    f"Aviso: {e!s}.\n"
                                    f"O cliente já possui cadastro ativo no sistema:\n{_format_cliente(existing)}"
                                ),
                            }
                        ],
                    }
                raise e

        elif name == "atualizar_cliente":
            user_service = UserService(db)
            fields = {"name", "phone", "email", "whatsapp_number", "cpf_cnpj"}
            user_update = UserUpdate(
                **{key: arguments[key] for key in fields if key in arguments}
            )
            user = user_service.update(arguments["user_id"], user_update)
            if not user:
                return {"content": [{"type": "text", "text": "Cliente não encontrado."}]}
            return {"content": [{"type": "text", "text": f"Cliente atualizado!\n{_format_cliente(user)}"}]}

        elif name == "vincular_whatsapp":
            user_service = UserService(db)
            user = user_service.link_whatsapp(arguments["user_id"], arguments["whatsapp_number"])
            if not user:
                return {"content": [{"type": "text", "text": "Cliente não encontrado."}]}
            return {"content": [{"type": "text", "text": f"WhatsApp vinculado com sucesso!\n{_format_cliente(user)}"}]}

        elif name == "listar_produtos":
            product_service = ProductService(db)
            category = arguments.get("category")
            search = arguments.get("search")
            in_stock_only = arguments.get("in_stock_only", True)

            products = product_service.list_products(
                category=category,
                search=search,
                in_stock_only=in_stock_only,
            )

            if not products:
                return {
                    "content": [
                        {
                            "type": "text",
                            "text": "Nenhum produto encontrado com os filtros informados.",
                        }
                    ]
                }

            lines = ["Produtos disponíveis para venda:"]
            for prod in products:
                price = f"R$ {prod.price_cents / 100:.2f}".replace(".", ",")
                cat_tag = f" [{prod.category}]" if prod.category else ""
                weight_tag = f" - Peso: {prod.weight_kg} kg" if prod.weight_kg is not None else ""
                lines.append(
                    f"  #{prod.id} {prod.name} - {price}{weight_tag} (Estoque: {prod.stock_quantity}){cat_tag}"
                )
            return {"content": [{"type": "text", "text": "\n".join(lines)}]}

        elif name == "consultar_produto":
            product_service = ProductService(db)
            product_id = arguments.get("product_id")
            name_arg = arguments.get("name")

            product = None
            if product_id:
                product = product_service.get_by_id(int(product_id))
            elif name_arg:
                matches = product_service.find_by_name(name_arg)
                if matches:
                    product = matches[0]

            if not product:
                return {
                    "content": [
                        {"type": "text", "text": "Produto não encontrado no catálogo."}
                    ]
                }

            price = f"R$ {product.price_cents / 100:.2f}".replace(".", ",")
            desc = f"\n  Descrição: {product.description}" if product.description else ""
            cat = f"\n  Categoria: {product.category}" if product.category else ""
            weight = f"\n  Peso: {product.weight_kg} kg" if product.weight_kg is not None else ""
            status_est = (
                f"{product.stock_quantity} unidades disponíveis"
                if product.stock_quantity > 0
                else "Esgotado no momento"
            )

            text = (
                f"Produto #{product.id}: {product.name}\n"
                f"  Preço: {price}\n"
                f"  Estoque: {status_est}"
                f"{weight}"
                f"{cat}"
                f"{desc}"
            )
            return {"content": [{"type": "text", "text": text}]}

        elif name == "criar_reserva":
            appointment_service = AppointmentService(db)
            appointment_create = AppointmentCreate(
                user_id=arguments["user_id"],
                professional_id=arguments["professional_id"],
                service_id=arguments["service_id"],
                start_time=arguments["start_time"],
                end_time=arguments["end_time"],
                notes=arguments.get("notes"),
            )
            appointment = appointment_service.create(appointment_create)
            return {
                "content": [
                    {
                        "type": "text",
                        "text": (
                            f"Reserva criada! ID: {appointment.id}\n"
                            f"Status: {appointment.status}\n"
                            f"Expira em: {appointment.expires_at}"
                        ),
                    }
                ]
            }

        elif name == "cancelar_reserva":
            appointment_service = AppointmentService(db)
            appointment = appointment_service.cancel(arguments["appointment_id"])
            if not appointment:
                return {"content": [{"type": "text", "text": "Reserva não encontrada."}]}
            return {"content": [{"type": "text", "text": f"Reserva {appointment.id} cancelada com sucesso."}]}

        elif name == "criar_cobranca_asaas":
            payment_service = PaymentService(db)
            if arguments.get("appointment_id"):
                payment = await payment_service.create_charge(
                    appointment_id=arguments["appointment_id"],
                    billing_type=arguments.get("billing_type", "UNDEFINED"),
                )
            else:
                payment = await payment_service.create_direct_charge(
                    user_id=arguments.get("user_id"),
                    product_id=arguments.get("product_id"),
                    amount_cents=arguments.get("amount_cents"),
                    description=arguments.get("description"),
                    billing_type=arguments.get("billing_type", "UNDEFINED"),
                )
            return {
                "content": [
                    {
                        "type": "text",
                        "text": (
                            f"Cobrança criada!\n"
                            f"ID Asaas: {payment.asaas_payment_id}\n"
                            f"Valor: R$ {payment.amount_cents / 100:.2f}\n"
                            f"Link: {payment.invoice_url}"
                        ),
                    }
                ]
            }

        elif name == "verificar_pagamentos_recentes":
            payment_service = PaymentService(db)
            updated = await payment_service.verify_recent_payments()
            unnotified = payment_service.list_unnotified_confirmed()

            lines = []
            if updated:
                lines.append("Pagamentos recém-atualizados no gateway:")
                lines.extend(f"  • Pagamento {p.id}: reserva {p.appointment_id} - {p.status}" for p in updated)
            if unnotified:
                lines.append(f"Reservas confirmadas aguardando aviso ao cliente ({len(unnotified)}):")
                for a in unnotified:
                    cli_nome = a.user.name if a.user else "Cliente"
                    cli_tel = getattr(a.user, "whatsapp_number", None) or getattr(a.user, "phone", "")
                    lines.append(f"  • Agendamento #{a.id} ({cli_nome} - {cli_tel}): {a.start_time}")

            if not lines:
                return {"content": [{"type": "text", "text": "Nenhum pagamento novo confirmado e nenhuma notificação pendente."}]}
            return {"content": [{"type": "text", "text": "\n".join(lines)}]}

        elif name == "listar_pendentes_notificacao":
            payment_service = PaymentService(db)
            unnotified = payment_service.list_unnotified_confirmed()
            if not unnotified:
                return {"content": [{"type": "text", "text": "Nenhum agendamento pendente de notificação."}]}
            lines = []
            for a in unnotified:
                cliente_nome = a.user.name if a.user else "Desconhecido"
                cliente_tel = getattr(a.user, "whatsapp_number", None) or getattr(a.user, "phone", "Sem telefone")
                lines.append(
                    f"• Agendamento #{a.id}: Cliente {cliente_nome} ({cliente_tel}) | Data/Hora: {a.start_time}"
                )
            return {
                "content": [
                    {
                        "type": "text",
                        "text": f"Encontrado(s) {len(unnotified)} agendamento(s) confirmado(s) aguardando notificação:\n" + "\n".join(lines),
                    }
                ]
            }

        elif name == "marcar_notificado":
            return {
                "content": [
                    {
                        "type": "text",
                        "text": "A confirmação é registrada automaticamente somente após o WhatsApp aceitar a mensagem.",
                    }
                ]
            }

        elif name == "meus_agendamentos":
            user_id = arguments.get("user_id")
            if not user_id:
                user_service = UserService(db)
                user = user_service.find_by_identifier(
                    query=arguments.get("query"),
                    phone=arguments.get("phone"),
                    name=arguments.get("name"),
                    cpf_cnpj=arguments.get("cpf_cnpj"),
                )
                if user:
                    user_id = user.id
            if not user_id:
                return {
                    "content": [
                        {
                            "type": "text",
                            "text": "Não foi possível localizar o cliente. Por favor, forneça o número de telefone, nome ou CPF do cliente.",
                        }
                    ]
                }

            include_unpaid_cancelled = bool(arguments.get("include_unpaid_cancelled", False))
            appointments = (
                db.query(Appointment)
                .options(
                    joinedload(Appointment.payments),
                )
                .filter(Appointment.user_id == user_id)
                .order_by(Appointment.start_time.desc())
                .all()
            )

            # Ocultar do histórico reservas canceladas sem pagamento recebido/confirmado
            visible_appointments = []
            for a in appointments:
                has_paid_payment = any(
                    p.status in {"received", "confirmed", "refunded"}
                    for p in (a.payments or [])
                )
                if a.status == "cancelled" and not has_paid_payment and not include_unpaid_cancelled:
                    continue
                visible_appointments.append(a)

            if not visible_appointments:
                return {"content": [{"type": "text", "text": "Nenhum agendamento encontrado."}]}

            lines = ["Seus agendamentos:"]
            for a in visible_appointments:
                data_hora = a.start_time.strftime("%d/%m/%Y às %H:%M")

                latest_payment = a.payments[-1] if a.payments else None
                pay_info = ""
                if latest_payment:
                    if latest_payment.status in {"received", "confirmed"}:
                        pay_info = " | Pagamento: Confirmado"
                    elif latest_payment.status in {"pending", "awaiting_payment"}:
                        link = latest_payment.invoice_url or "Link pendente"
                        pay_info = f" | Aguardando Pagamento (Link: {link})"
                    else:
                        pay_info = f" | Pagamento: {latest_payment.status}"

                status_label = "Confirmado" if a.status == "confirmed" else ("Cancelado" if a.status == "cancelled" else a.status)
                lines.append(f"• #{a.id}: Agendamento em {data_hora} | Status: {status_label}{pay_info}")

            return {"content": [{"type": "text", "text": "\n".join(lines)}]}

        elif name == "verificar_status_pagamento":
            appointment_id = arguments["appointment_id"]
            payment_service = PaymentService(db)
            payment = payment_service.get_payment_by_appointment(appointment_id)
            if not payment:
                return {
                    "content": [
                        {
                            "type": "text",
                            "text": f"Nenhuma cobrança encontrada para o agendamento #{appointment_id}.",
                        }
                    ]
                }

            if payment.status in {"pending", "awaiting_payment"} and payment.asaas_payment_id:
                try:
                    await payment_service.check_payment_status(payment)
                except Exception as e:
                    logger.warning("Erro ao consultar status no Asaas para pagamento %s: %s", payment.id, e)

            appointment = (
                db.query(Appointment)
                .options(
                    joinedload(Appointment.user),
                )
                .filter(Appointment.id == appointment_id)
                .first()
            )

            if payment.status in {"received", "confirmed"}:
                if appointment:
                    from app.services.notification_service import NotificationService

                    notification_service = NotificationService(db)
                    delivery = notification_service.queue_payment_confirmed(appointment.id, payment.id)
                    db.commit()
                    await notification_service.dispatch_payment_confirmed(delivery.id)

                cli_name = appointment.user.name if appointment and appointment.user else "Cliente"
                data_hora = appointment.start_time.strftime("%d/%m/%Y às %H:%M") if appointment else ""
                val = f"R$ {payment.amount_cents / 100:.2f}"
                forma = (payment.billing_type or "PIX").upper()

                return {
                    "content": [
                        {
                            "type": "text",
                            "text": (
                                f"✅ Pagamento CONFIRMADO com sucesso!\n\n"
                                f"• Cliente: {cli_name}\n"
                                f"• Referência: #{appointment_id}\n"
                                f"• Data e Horário: {data_hora}\n"
                                f"• Valor Pago: {val} ({forma})\n\n"
                                f"A venda/reserva está 100% confirmada!"
                            ),
                        }
                    ]
                }
            elif payment.status in {"pending", "awaiting_payment"}:
                val = f"R$ {payment.amount_cents / 100:.2f}"
                invoice = payment.invoice_url or "Link não disponível"
                return {
                    "content": [
                        {
                            "type": "text",
                            "text": (
                                f"⏳ Pagamento PENDENTE para o agendamento #{appointment_id}.\n"
                                f"• Valor: {val}\n"
                                f"• Link de pagamento: {invoice}\n\n"
                                f"Assim que o pagamento for concluído no banco, a confirmação será processada."
                            ),
                        }
                    ]
                }
            else:
                return {
                    "content": [
                        {
                            "type": "text",
                            "text": f"Status do pagamento para o agendamento #{appointment_id}: {payment.status.upper()}.",
                        }
                    ]
                }

        elif name == "solicitar_agendamento_orquestrador_n8n":
            prof_arg = arguments.get("professional_id", 1)
            prof_id = int(prof_arg) if str(prof_arg).isdigit() else 1

            serv_arg = arguments.get("service_id", 1)
            serv_id = int(serv_arg) if str(serv_arg).isdigit() else 1

            computed_end_time = arguments.get("end_time")
            if not computed_end_time:
                duration = 30
                start_dt = dt_cls.fromisoformat(arguments["start_time"])
                computed_end_dt = start_dt + timedelta(minutes=duration)
                computed_end_time = computed_end_dt.isoformat()

            from urllib.parse import urlparse
            n8n_base = "http://n8n:5678"
            webhook_url = getattr(settings, "n8n_webhook_url", None)
            if webhook_url:
                parsed_url = urlparse(webhook_url)
                if parsed_url.scheme and parsed_url.netloc:
                    n8n_base = f"{parsed_url.scheme}://{parsed_url.netloc}"
            n8n_url = f"{n8n_base}/webhook/agendamento/criar"

            payload = {
                "client_name": arguments["client_name"],
                "phone": arguments["phone"],
                "cpf_cnpj": arguments.get("cpf_cnpj"),
                "professional_id": prof_id,
                "service_id": serv_id,
                "start_time": arguments["start_time"],
                "end_time": computed_end_time,
                "notes": arguments.get("notes", "Agendado via Hermes WhatsApp"),
            }

            try:
                async with httpx.AsyncClient(timeout=15.0) as client:
                    resp = await client.post(n8n_url, json=payload)
                    if resp.status_code == 200:
                        data = resp.json()
                        appt_id = data.get("appointment_id", "")
                        amount = data.get("amount", "")
                        payment_url = data.get("payment_url", "")
                        pix_code = data.get("pix_code", "")
                        msg = (
                            f"Agendamento #{appt_id} orquestrado com sucesso pelo n8n!\n"
                            f"Valor: {amount}\n"
                            f"Link de Pagamento: {payment_url}\n"
                            f"PIX Copia e Cola: {pix_code}"
                        )
                        return {"content": [{"type": "text", "text": msg}]}
            except Exception as e:
                logger.warning("Falha ao acionar orquestrador do n8n, executando fallback local: %s", e)

            # Fallback local resiliente
            user_service = UserService(db)
            user = user_service.find_by_phone(arguments["phone"])
            if not user and arguments.get("client_name"):
                user = user_service.find_by_phone(arguments["client_name"])
            if not user:
                user = user_service.create(
                    UserCreate(
                        name=arguments["client_name"],
                        phone=arguments["phone"],
                        whatsapp_number=arguments["phone"],
                        cpf_cnpj=arguments.get("cpf_cnpj"),
                    )
                )
            elif arguments.get("cpf_cnpj") and not user.cpf_cnpj:
                try:
                    user_service.update(user.id, UserUpdate(cpf_cnpj=arguments.get("cpf_cnpj")))
                except Exception as e:
                    logger.warning("Não foi possível atualizar CPF no fallback: %s", e)
            appointment_service = AppointmentService(db)
            appointment = appointment_service.create(
                AppointmentCreate(
                    user_id=user.id,
                    professional_id=prof_id,
                    service_id=serv_id,
                    start_time=arguments["start_time"],
                    end_time=computed_end_time,
                    notes=arguments.get("notes", "Agendado via Hermes WhatsApp"),
                )
            )

            payment_service = PaymentService(db)
            payment = await payment_service.create_charge(appointment.id, billing_type="PIX")

            pix_code = ""
            if payment.asaas_payment_id:
                try:
                    pix_res = await payment_service.asaas.get_pix_qr_code(payment.asaas_payment_id)
                    pix_code = pix_res.get("payload", "")
                except Exception as ex:
                    logger.warning("Não foi possível buscar QR Code PIX: %s", ex)

            invoice = payment.invoice_url or "Link não disponível"
            lines = [
                f"Reserva #{appointment.id} criada com sucesso!",
                f"Status: {appointment.status}",
                f"Valor: R$ {payment.amount_cents / 100:.2f}",
                f"Link de Pagamento: {invoice}",
            ]
            if pix_code:
                lines.append(f"PIX Copia e Cola: {pix_code}")

            return {"content": [{"type": "text", "text": "\n".join(lines)}]}

        elif name == "solicitar_cancelamento_n8n":
            from urllib.parse import urlparse
            n8n_base = "http://n8n:5678"
            webhook_url = getattr(settings, "n8n_webhook_url", None)
            if webhook_url:
                parsed_url = urlparse(webhook_url)
                if parsed_url.scheme and parsed_url.netloc:
                    n8n_base = f"{parsed_url.scheme}://{parsed_url.netloc}"
            n8n_url = f"{n8n_base}/webhook/agendamento/cancelar"

            appointment_id = arguments["appointment_id"]
            payload = {
                "appointment_id": appointment_id,
                "phone": arguments.get("phone", ""),
            }

            try:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    resp = await client.post(n8n_url, json=payload)
                    if resp.status_code == 200:
                        return {
                            "content": [
                                {
                                    "type": "text",
                                    "text": f"Reserva #{appointment_id} cancelada com sucesso via Subagente de Cancelamento do n8n.",
                                }
                            ]
                        }
            except Exception as e:
                logger.warning("Falha ao acionar cancelamento via n8n, executando fallback local: %s", e)

            appointment_service = AppointmentService(db)
            appointment = appointment_service.cancel(appointment_id)
            if not appointment:
                return {"content": [{"type": "text", "text": "Reserva não encontrada."}]}
            return {"content": [{"type": "text", "text": f"Reserva #{appointment.id} cancelada com sucesso."}]}

        elif name == "triar_mensagem":
            from app.services.triage_service import TriageService
            message_text = arguments.get("message", "")
            phone = arguments.get("phone")
            triage_service = TriageService()
            result = await triage_service.evaluate(message=message_text, phone=phone)
            human_str = "Sim" if result.is_human_handoff >= 0.8 else "Não"
            pix_str = "Sim" if result.is_payment_claim >= 0.75 else "Não"
            resp_str = f"- Resposta Rápida Sugerida: {result.fast_response_text}\n" if result.fast_response_text else ""
            return {
                "content": [
                    {
                        "type": "text",
                        "text": (
                            f"Triagem Concluída:\n"
                            f"- Intenção: {result.intent} (confiança: {result.intent_confidence})\n"
                            f"- Pedido de Atendente Humano: {human_str} ({result.is_human_handoff})\n"
                            f"- Afirmação de Pagamento PIX: {pix_str} ({result.is_payment_claim})\n"
                            f"- Nível de Frustração: {result.frustration_level} (nota {result.frustration_score}/2.0)\n"
                            f"- Ação Recomendada: {result.recommended_action}\n"
                            + resp_str
                        ),
                    }
                ]
            }

        else:
            return {
                "isError": True,
                "content": [{"type": "text", "text": f"Ferramenta desconhecida: {name}"}],
            }

    except (ValueError, AsaasIntegrationError) as e:
        return {
            "isError": True,
            "content": [{"type": "text", "text": str(e)}],
        }
    except Exception:
        logger.exception("MCP tool failed", extra={"tool_name": name})
        return {
            "isError": True,
            "content": [
                {
                    "type": "text",
                    "text": "Erro interno ao processar a solicitação.",
                }
            ],
        }



def _format_cliente(user) -> str:
    whatsapp = getattr(user, "whatsapp_number", None) or "-"
    cpf = getattr(user, "cpf_cnpj", None) or "-"
    return (
        f"  ID: {user.id}\n"
        f"  Nome: {user.name}\n"
        f"  Telefone: {user.phone}\n"
        f"  CPF/CNPJ: {cpf}\n"
        f"  Email: {user.email or '-'}\n"
        f"  WhatsApp: {whatsapp}"
    )
