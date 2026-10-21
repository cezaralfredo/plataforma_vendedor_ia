import logging
import threading
import time

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.processed_inbound_message import ProcessedInboundMessage

logger = logging.getLogger(__name__)


class InboundDeduplicator:
    _instance = None
    _lock = threading.Lock()

    def __init__(self, memory_ttl_seconds: int = 300):
        self._memory_cache: dict[str, float] = {}
        self._cache_lock = threading.Lock()
        self._ttl = memory_ttl_seconds

    @classmethod
    def get_instance(cls) -> "InboundDeduplicator":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    def try_acquire(
        self,
        db: Session,
        message_id: str | None,
        provider: str | None = None,
        phone: str | None = None,
    ) -> bool:
        """Retorna True se for a PRIMEIRA vez que esta mensagem é processada.

        Retorna False se for uma mensagem duplicada (já vista no cache ou no banco).
        """
        if not message_id or not str(message_id).strip():
            return True

        clean_id = str(message_id).strip()[:190]
        now = time.time()

        # 1. Checagem em memória no mesmo processo (fast path)
        with self._cache_lock:
            if len(self._memory_cache) > 500:
                expired = [k for k, t in self._memory_cache.items() if now - t > self._ttl]
                for k in expired:
                    del self._memory_cache[k]

            if clean_id in self._memory_cache:
                logger.info(
                    "Deduplicator (memória): mensagem duplicada ignorada (id=%s, phone=%s)",
                    clean_id,
                    phone,
                )
                return False

        # 2. Checagem atômica no banco de dados (cross-process / multi-worker)
        try:
            entry = ProcessedInboundMessage(
                message_id=clean_id,
                provider=str(provider)[:30] if provider else None,
                phone=str(phone)[:50] if phone else None,
            )
            db.add(entry)
            db.commit()

            with self._cache_lock:
                self._memory_cache[clean_id] = now

            return True
        except IntegrityError:
            db.rollback()
            with self._cache_lock:
                self._memory_cache[clean_id] = now

            logger.info(
                "Deduplicator (banco): mensagem duplicada detectada e ignorada (id=%s, phone=%s)",
                clean_id,
                phone,
            )
            return False
        except Exception as exc:
            logger.warning("Deduplicator: erro ao checar deduplicação no banco: %s", exc)
            db.rollback()
            with self._cache_lock:
                if clean_id in self._memory_cache:
                    return False
                self._memory_cache[clean_id] = now
            return True
