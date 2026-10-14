"""
Storage Service — MinIO S3-compatible object storage client.

Handles document upload, download, deletion, and presigned URL generation.
Ensures the bucket exists on initialization.
"""

import io
from urllib.parse import quote

import structlog
from minio import Minio
from minio.error import S3Error

from app.config import get_settings

logger = structlog.get_logger()


class StorageService:
    """MinIO S3-compatible storage client for document management."""

    def __init__(self) -> None:
        self.settings = get_settings()
        self.client = Minio(
            endpoint=self.settings.minio_endpoint,
            access_key=self.settings.minio_access_key,
            secret_key=self.settings.minio_secret_key,
            secure=self.settings.minio_use_ssl,
        )
        self.bucket = self.settings.minio_bucket

    def ensure_bucket(self) -> None:
        """Create the bucket if it doesn't exist."""
        try:
            if not self.client.bucket_exists(self.bucket):
                self.client.make_bucket(self.bucket)
                logger.info("Created MinIO bucket", bucket=self.bucket)
        except S3Error as e:
            logger.error("Failed to ensure bucket", error=str(e))
            raise

    def upload_file(
        self,
        object_key: str,
        data: bytes,
        content_type: str = "application/octet-stream",
    ) -> str:
        """Upload a file to MinIO. Returns the object key."""
        try:
            self.client.put_object(
                bucket_name=self.bucket,
                object_name=object_key,
                data=io.BytesIO(data),
                length=len(data),
                content_type=content_type,
            )
            logger.info(
                "File uploaded to MinIO",
                object_key=object_key,
                size_bytes=len(data),
            )
            return object_key
        except S3Error as e:
            logger.error("Failed to upload file", object_key=object_key, error=str(e))
            raise

    def download_file(self, object_key: str) -> bytes:
        """Download a file from MinIO. Returns bytes."""
        try:
            response = self.client.get_object(self.bucket, object_key)
            try:
                return response.read()
            finally:
                response.close()
                response.release_conn()
        except S3Error as e:
            logger.error("Failed to download file", object_key=object_key, error=str(e))
            raise

    def delete_file(self, object_key: str) -> None:
        """Delete a file from MinIO."""
        try:
            self.client.remove_object(self.bucket, object_key)
            logger.info("File deleted from MinIO", object_key=object_key)
        except S3Error as e:
            logger.error("Failed to delete file", object_key=object_key, error=str(e))
            raise

    def get_presigned_url(self, object_key: str, expires_hours: int = 1) -> str:
        """Generate a presigned URL for temporary direct access."""
        from datetime import timedelta

        try:
            url = self.client.presigned_get_object(
                self.bucket,
                object_key,
                expires=timedelta(hours=expires_hours),
            )
            return url
        except S3Error as e:
            logger.error(
                "Failed to generate presigned URL",
                object_key=object_key,
                error=str(e),
            )
            raise

    def file_exists(self, object_key: str) -> bool:
        """Check if a file exists in MinIO."""
        try:
            self.client.stat_object(self.bucket, object_key)
            return True
        except S3Error:
            return False

    @staticmethod
    def generate_object_key(
        org_id: str, document_id: str, version_number: int, filename: str
    ) -> str:
        """Generate a structured object key for a document version.

        Format: orgs/{org_id}/docs/{document_id}/v{version_number}/{filename}
        """
        safe_filename = quote(filename, safe="._-")
        return f"orgs/{org_id}/docs/{document_id}/v{version_number}/{safe_filename}"


# Singleton
_storage_service: StorageService | None = None


def get_storage_service() -> StorageService:
    """Factory for storage service (lazy singleton)."""
    global _storage_service
    if _storage_service is None:
        _storage_service = StorageService()
        _storage_service.ensure_bucket()
    return _storage_service
