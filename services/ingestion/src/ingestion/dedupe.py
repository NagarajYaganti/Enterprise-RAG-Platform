from dataclasses import dataclass

from connectors.postgres.repository import DocumentRepository


@dataclass(frozen=True)
class VersionDecision:
    version: int
    is_exact_duplicate: bool


def determine_version(
    document_repo: DocumentRepository, tenant_id: str, source_uri: str, checksum: str
) -> VersionDecision:
    """Re-uploading the same source_uri bumps its version unless the content
    (checksum) is identical to what's already stored, in which case it's a
    no-op duplicate.

    An existing row with an empty checksum is the API's placeholder row
    (created at upload time, before the worker has parsed anything and
    computed a real checksum) — it must not be mistaken for a genuine prior
    version, or every first-time upload would be misclassified as a
    re-upload the moment the worker runs.
    """
    existing = document_repo.find_by_source_uri(tenant_id, source_uri)
    if existing is None or existing.checksum == "":
        return VersionDecision(version=1, is_exact_duplicate=False)
    if existing.checksum == checksum:
        return VersionDecision(version=existing.version, is_exact_duplicate=True)
    return VersionDecision(version=existing.version + 1, is_exact_duplicate=False)
