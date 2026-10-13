"""
Central ORM model registry.

Importing this module registers every mapped class on ``Base.metadata``.
SQLAlchemy resolves foreign keys across *all* tables when it configures
mappers, so any entrypoint that touches the database outside the web app —
most importantly the Celery worker — must import this first or it will fail
with ``NoReferencedTableError`` (e.g. ``documents.organization_id`` cannot
find the ``organizations`` table).

The web app already imports every model transitively via its routers; the
registry makes the worker and standalone scripts do the same explicitly.
"""

from app.modules.actions.models import ActionRun, Task  # noqa: F401
from app.modules.audit.models import AuditEvent  # noqa: F401
from app.modules.conversations.models import (  # noqa: F401
    Conversation,
    Message,
    MessageCitation,
)
from app.modules.documents.models import (  # noqa: F401
    Document,
    DocumentPermission,
    DocumentVersion,
    ProcessingJob,
)
from app.modules.identity.models import RefreshToken, User  # noqa: F401
from app.modules.ingestion.models import VectorIndex  # noqa: F401
from app.modules.knowledge_quality.models import KnowledgeFinding  # noqa: F401
from app.modules.organizations.models import (  # noqa: F401
    Group,
    GroupMembership,
    Membership,
    Organization,
    OrgInvitation,
)
