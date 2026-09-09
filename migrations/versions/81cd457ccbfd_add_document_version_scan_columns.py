"""add_document_version_scan_columns

Revision ID: 81cd457ccbfd
Revises: 9426dede0922
Create Date: 2026-09-10 00:00:00.000000

Malware scanning (AC-FR-04-01) - see app/scanning/ and CLAUDE.md
"Malware scanning". No status-column change needed (DocumentVersion.status
is a plain string, not a DB-level enum constraint) - SCANNING/FAILED
are Python-side DocumentVersionStatus values only. malware_signature/
scan_error are dedicated, queryable columns rather than overloading
review_note, which means "why a HUMAN decided this" - these are
system-written, no reviewer involved.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '81cd457ccbfd'
down_revision: Union[str, Sequence[str], None] = '9426dede0922'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('document_versions', sa.Column('malware_signature', sa.String(length=255), nullable=True))
    op.add_column('document_versions', sa.Column('scan_error', sa.Text(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('document_versions', 'scan_error')
    op.drop_column('document_versions', 'malware_signature')
