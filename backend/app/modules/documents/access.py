"""Current access checks for persisted evidence, including historical versions."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.documents.models import Document, DocumentStatus, DocumentVersion
from app.modules.documents.service import _membership, visible_documents_filter


async def visible_versions(
    db: AsyncSession, user_id: str, org_id: str
) -> dict[str, tuple[str, str]]:
    membership = await _membership(db, user_id, org_id)
    rows = await db.execute(
        select(DocumentVersion.id, Document.id, Document.title)
        .join(Document, Document.id == DocumentVersion.document_id)
        .where(
            Document.organization_id == org_id,
            Document.status != DocumentStatus.ARCHIVED,
            visible_documents_filter(user_id, membership),
        )
    )
    return {version_id: (doc_id, title) for version_id, doc_id, title in rows}
