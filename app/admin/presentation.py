from app.models.service import Service


def service_option_label(service: Service) -> str:
    """Explain a catalog choice without changing its identity or stored name."""
    name = (service.name or '').strip() or 'Serviço sem nome'
    description = (service.description or '').strip()
    if description and description.casefold() != name.casefold():
        name += f' — {description}'
    cents = service.price_cents
    price = f'{cents // 100:,}'.replace(',', '.') + f',{cents % 100:02d}'
    return f'{name} · R$ {price} · {service.duration_minutes} min'
