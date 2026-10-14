"""
Audit module — Service layer.

Provides a simple interface for logging audit events from any module.
"""

from sqlalchemy.ext.asyncio import AsyncSession
from ulid import ULID

from app.modules.audit.models import AuditAction, AuditEvent, AuditOutcome


class AuditService:
    """Logs immutable audit events."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def log_event(
        self,
        action: str | AuditAction,
        actor_id: str | None = None,
        organization_id: str | None = None,
        resource_type: str | None = None,
        resource_id: str | None = None,
        outcome: str | AuditOutcome = "success",
        details: str | None = None,
        ip_address: str | None = None,
        user_agent: str | None = None,
        request_id: str | None = None,
    ) -> AuditEvent:
        """Create an audit event.

        Unknown action/outcome names are a programming error: recording them
        under some other action would silently corrupt the audit trail, so
        they raise ``ValueError`` instead.
        """
        audit_action = AuditAction(action)
        audit_outcome = AuditOutcome(outcome)

        event = AuditEvent(
            id=str(ULID()),
            organization_id=organization_id,
            actor_id=actor_id,
            action=audit_action,
            resource_type=resource_type,
            resource_id=resource_id,
            outcome=audit_outcome,
            details=details,
            ip_address=ip_address[:45] if ip_address else None,
            user_agent=user_agent[:500] if user_agent else None,
            request_id=request_id[:36] if request_id else None,
        )
        self.db.add(event)
        await self.db.flush()
        return event
