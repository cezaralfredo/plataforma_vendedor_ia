from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.repositories.base import RelatedRecordsError
from app.schemas.professional import (
    ProfessionalCreate,
    ProfessionalRead,
    ProfessionalUpdate,
)
from app.schemas.professional_service import (
    ProfessionalServiceCreate,
    ProfessionalServiceRead,
    ProfessionalServiceUpdate,
)
from app.security import require_api_key
from app.services.professional_service import ProfessionalService
from app.services.professional_service_offering_service import ProfessionalOfferingService

router = APIRouter(
    prefix="/api/professionals",
    tags=["professionals"],
    dependencies=[Depends(require_api_key)],
)


@router.post("", response_model=ProfessionalRead, status_code=201)
def create_professional(data: ProfessionalCreate, db: Session = Depends(get_db)):
    service = ProfessionalService(db)
    return service.create(data)


@router.get("", response_model=list[ProfessionalRead])
def list_professionals(active_only: bool = False, skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    service = ProfessionalService(db)
    return service.list(skip=skip, limit=limit, active_only=active_only)


@router.get("/{professional_id}", response_model=ProfessionalRead)
def get_professional(professional_id: int, db: Session = Depends(get_db)):
    service = ProfessionalService(db)
    prof = service.get(professional_id)
    if not prof:
        raise HTTPException(status_code=404, detail="Profissional não encontrado")
    return prof


@router.put("/{professional_id}", response_model=ProfessionalRead)
def update_professional(professional_id: int, data: ProfessionalUpdate, db: Session = Depends(get_db)):
    service = ProfessionalService(db)
    prof = service.update(professional_id, data)
    if not prof:
        raise HTTPException(status_code=404, detail="Profissional não encontrado")
    return prof


@router.delete("/{professional_id}", status_code=204)
def delete_professional(professional_id: int, db: Session = Depends(get_db)):
    service = ProfessionalService(db)
    try:
        if not service.delete(professional_id):
            raise HTTPException(status_code=404, detail="Profissional não encontrado")
    except RelatedRecordsError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get(
    "/{professional_id}/services", response_model=list[ProfessionalServiceRead]
)
def list_professional_services(
    professional_id: int, db: Session = Depends(get_db)
):
    if not ProfessionalService(db).get(professional_id):
        raise HTTPException(status_code=404, detail="Profissional não encontrado")
    return ProfessionalOfferingService(db).list_for_professional(professional_id)


@router.post(
    "/{professional_id}/services",
    response_model=ProfessionalServiceRead,
    status_code=201,
)
def create_professional_service(
    professional_id: int,
    data: ProfessionalServiceCreate,
    db: Session = Depends(get_db),
):
    try:
        return ProfessionalOfferingService(db).create_or_update(
            professional_id=professional_id,
            service_id=data.service_id,
            commission_percent=data.commission_percent,
            active=data.active,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.put(
    "/{professional_id}/services/{service_id}",
    response_model=ProfessionalServiceRead,
)
def update_professional_service(
    professional_id: int,
    service_id: int,
    data: ProfessionalServiceUpdate,
    db: Session = Depends(get_db),
):
    try:
        offering = ProfessionalOfferingService(db).update(
            professional_id,
            service_id,
            **data.model_dump(exclude_unset=True),
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if not offering:
        raise HTTPException(status_code=404, detail="Vínculo não encontrado")
    return offering


@router.delete(
    "/{professional_id}/services/{service_id}", status_code=204
)
def delete_professional_service(
    professional_id: int, service_id: int, db: Session = Depends(get_db)
):
    outcome = ProfessionalOfferingService(db).archive_or_delete(
        professional_id, service_id
    )
    if not outcome:
        raise HTTPException(status_code=404, detail="Vínculo não encontrado")
