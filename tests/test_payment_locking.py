from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Session

from app.services.payment_service import PaymentService


def test_charge_lookup_locks_only_appointment_with_eager_loads(db_session: Session):
    query = PaymentService(db_session)._locked_appointment_query(123)

    sql = str(
        query.statement.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )

    assert "LEFT OUTER JOIN" in sql
    assert "FOR UPDATE OF appointments" in sql
