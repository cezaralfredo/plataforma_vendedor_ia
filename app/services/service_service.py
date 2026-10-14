from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.models.appointment import Appointment
from app.models.notification_log import NotificationLog
from app.models.payment import Payment
from app.models.professional_service import ProfessionalService
from app.models.service import Service
from app.repositories import ServiceRepository
from app.repositories.base import RelatedRecordsError
from app.schemas.service import ServiceCreate, ServiceUpdate
from app.services.payment_state_service import _is_expired


class ServiceService:
    def __init__(self, db: Session):
        self.repo = ServiceRepository(db)

    def create(self, data: ServiceCreate):
        return self.repo.create(**data.model_dump())

    def get(self, service_id: int):
        return self.repo.get(service_id)

    def list(
        self,
        category: str | None = None,
        skip: int = 0,
        limit: int = 100,
        active_only: bool = False,
    ):
        if category is not None:
            return self.repo.list_by_category(
                category, skip=skip, limit=limit, active_only=active_only
            )
        return self.repo.list_catalog(
            skip=skip, limit=limit, active_only=active_only
        )

    def update(self, service_id: int, data: ServiceUpdate):
        return self.repo.update(service_id, **data.model_dump(exclude_unset=True))

    def delete(self, service_id: int):
        catalog = ServiceCatalogService(self.repo.db)
        if catalog.deletion_requires_archival(service_id):
            raise RelatedRecordsError(
                "Serviço possui histórico protegido; desative-o em vez de excluir"
            )
        return catalog.archive_or_delete(service_id)


class ServiceCatalogService:
    """Applies safe archival rules to the shared service catalog."""

    def __init__(self, db: Session):
        self.db = db

    def create(
        self,
        *,
        name: str,
        description: str | None,
        category: str | None,
        duration_minutes: int,
        price_cents: int,
    ) -> Service:
        service = Service(
            name=name,
            description=description,
            category=category,
            duration_minutes=duration_minutes,
            price_cents=price_cents,
        )
        self.db.add(service)
        self.db.commit()
        self.db.refresh(service)
        return service

    def update(
        self,
        service_id: int,
        *,
        name: str | None = None,
        description: str | None = None,
        category: str | None = None,
        duration_minutes: int | None = None,
        price_cents: int | None = None,
    ) -> Service | None:
        service = self.db.get(Service, service_id)
        if not service:
            return None
        if name is not None:
            service.name = name
        if description is not None:
            service.description = description
        if category is not None:
            service.category = category
        if duration_minutes is not None:
            service.duration_minutes = duration_minutes
        if price_cents is not None:
            service.price_cents = price_cents
        self.db.commit()
        self.db.refresh(service)
        return service

    def reactivate(self, service_id: int) -> Service | None:
        service = self.db.get(Service, service_id)
        if not service:
            return None
        service.active = True
        self.db.commit()
        self.db.refresh(service)
        return service

    def archive_or_delete(self, service_id: int) -> str | None:
        service = self.db.get(Service, service_id)
        if not service:
            return None

        appointments = self.db.query(Appointment).filter(
            Appointment.service_id == service_id
        ).all()
        protected_statuses = {"confirmed", "completed"}
        financial_statuses = {"received", "confirmed", "refunded"}
        has_protected_history = any(
            appointment.status in protected_statuses
            or any(payment.status in financial_statuses for payment in appointment.payments)
            for appointment in appointments
        )

        if has_protected_history:
            service.active = False
            for offering in service.professional_offerings:
                offering.active = False
            self.db.commit()
            return "archived"

        now = datetime.now(UTC)
        removable_appointments = all(
            appointment.status == "cancelled"
            or (
                appointment.status in {"pending", "awaiting_payment"}
                and appointment.expires_at is not None
                and _is_expired(appointment.expires_at, now)
            )
            for appointment in appointments
        )
        if appointments and not removable_appointments:
            service.active = False
            for offering in service.professional_offerings:
                offering.active = False
            self.db.commit()
            return "archived"

        appointment_ids = [appointment.id for appointment in appointments]
        if appointment_ids:
            self.db.query(NotificationLog).filter(
                NotificationLog.appointment_id.in_(appointment_ids)
            ).delete(synchronize_session=False)
            self.db.query(Payment).filter(
                Payment.appointment_id.in_(appointment_ids)
            ).delete(synchronize_session=False)
            self.db.query(Appointment).filter(
                Appointment.id.in_(appointment_ids)
            ).delete(synchronize_session=False)

        self.db.query(ProfessionalService).filter(
            ProfessionalService.service_id == service_id
        ).delete(synchronize_session=False)

        self.db.delete(service)
        self.db.commit()
        return "deleted"

    def deletion_requires_archival(self, service_id: int) -> bool:
        appointments = (
            self.db.query(Appointment)
            .filter(Appointment.service_id == service_id)
            .all()
        )
        protected_statuses = {"confirmed", "completed"}
        financial_statuses = {"received", "confirmed", "refunded"}
        if any(
            appointment.status in protected_statuses
            or any(
                payment.status in financial_statuses
                for payment in appointment.payments
            )
            for appointment in appointments
        ):
            return True
        now = datetime.now(UTC)
        return any(
            appointment.status != "cancelled"
            and not (
                appointment.status in {"pending", "awaiting_payment"}
                and appointment.expires_at is not None
                and _is_expired(appointment.expires_at, now)
            )
            for appointment in appointments
        )
