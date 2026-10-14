from decimal import Decimal

from sqlalchemy.orm import Session, joinedload

from app.models.professional import Professional
from app.models.professional_service import ProfessionalService
from app.models.service import Service


class ProfessionalOfferingService:
    """Manages the commercial terms for a professional's catalog offering."""

    def __init__(self, db: Session):
        self.db = db

    def get(self, professional_id: int, service_id: int) -> ProfessionalService | None:
        return (
            self.db.query(ProfessionalService)
            .filter(
                ProfessionalService.professional_id == professional_id,
                ProfessionalService.service_id == service_id,
            )
            .first()
        )

    def get_active(
        self, professional_id: int, service_id: int
    ) -> ProfessionalService | None:
        return (
            self.db.query(ProfessionalService)
            .filter(
                ProfessionalService.professional_id == professional_id,
                ProfessionalService.service_id == service_id,
                ProfessionalService.active.is_(True),
            )
            .first()
        )

    def list_active(
        self,
        *,
        professional_id: int | None = None,
        category: str | None = None,
        skip: int = 0,
        limit: int = 100,
    ) -> list[ProfessionalService]:
        query = (
            self.db.query(ProfessionalService)
            .join(ProfessionalService.service)
            .join(ProfessionalService.professional)
            .options(
                joinedload(ProfessionalService.service),
                joinedload(ProfessionalService.professional),
            )
            .filter(
                ProfessionalService.active.is_(True),
                Service.active.is_(True),
                Professional.active.is_(True),
            )
        )
        if professional_id is not None:
            query = query.filter(ProfessionalService.professional_id == professional_id)
        if category is not None:
            query = query.filter(Service.category == category)
        return (
            query.order_by(Service.name, Professional.name)
            .offset(skip)
            .limit(limit)
            .all()
        )

    def list_for_professional(
        self, professional_id: int
    ) -> list[ProfessionalService]:
        return (
            self.db.query(ProfessionalService)
            .options(joinedload(ProfessionalService.service))
            .filter(ProfessionalService.professional_id == professional_id)
            .order_by(ProfessionalService.service_id)
            .all()
        )

    def create_or_update(
        self,
        *,
        professional_id: int,
        service_id: int,
        commission_percent: Decimal = Decimal("10.00"),
        active: bool = True,
    ) -> ProfessionalService:
        professional = self.db.get(Professional, professional_id)
        if not professional or not professional.active:
            raise ValueError("Profissional não encontrado ou inativo")
        service = self.db.get(Service, service_id)
        if not service or not service.active:
            raise ValueError("Serviço não encontrado ou inativo")
        commission_percent = Decimal(commission_percent)
        if not Decimal("0") <= commission_percent <= Decimal("100"):
            raise ValueError("A comissão deve estar entre 0% e 100%")

        offering = self.get(professional_id, service_id)
        if offering:
            offering.commission_percent = commission_percent
            offering.active = active
        else:
            offering = ProfessionalService(
                professional_id=professional_id,
                service_id=service_id,
                commission_percent=commission_percent,
                active=active,
            )
            self.db.add(offering)
        self.db.commit()
        self.db.refresh(offering)
        return offering

    def update(
        self,
        professional_id: int,
        service_id: int,
        *,
        commission_percent: Decimal | None = None,
        active: bool | None = None,
    ) -> ProfessionalService | None:
        offering = self.get(professional_id, service_id)
        if not offering:
            return None
        if commission_percent is not None:
            commission_percent = Decimal(commission_percent)
            if not Decimal("0") <= commission_percent <= Decimal("100"):
                raise ValueError("A comissão deve estar entre 0% e 100%")
            offering.commission_percent = commission_percent
        if active is not None:
            if active:
                professional = self.db.get(Professional, professional_id)
                service = self.db.get(Service, service_id)
                if not professional or not professional.active:
                    raise ValueError("Profissional não encontrado ou inativo")
                if not service or not service.active:
                    raise ValueError("Serviço não encontrado ou inativo")
            offering.active = active
        self.db.commit()
        self.db.refresh(offering)
        return offering

    def archive_or_delete(self, professional_id: int, service_id: int) -> str | None:
        offering = self.get(professional_id, service_id)
        if not offering:
            return None

        from app.models.appointment import Appointment

        has_history = (
            self.db.query(Appointment.id)
            .filter(
                Appointment.professional_id == professional_id,
                Appointment.service_id == service_id,
            )
            .first()
        )
        if has_history:
            offering.active = False
            self.db.commit()
            return "archived"
        self.db.delete(offering)
        self.db.commit()
        return "deleted"
