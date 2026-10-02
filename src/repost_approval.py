"""A reviewed, owner-approved repost gets its own at-most-once journal entry."""
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

from editorial_packet import digest, publication_key, timestamp
from publication_journal import JournalError


def approved_key(packet, state, original, *, folder='automation/repost_approvals', now=None):
    key, packet_hash = publication_key(packet), digest(packet)
    path = Path(folder) / (packet_hash + '.json')
    if not path.is_file():
        return key
    approval = json.loads(path.read_text(encoding='utf-8'))
    current = now or datetime.now(timezone.utc)
    start = timestamp(approval.get('approved_at'), 'approved_at')
    end = timestamp(approval.get('expires_at'), 'expires_at')
    if (approval.get('schema_version') != 1 or approval.get('base_key') != key
            or approval.get('packet_sha256') != packet_hash
            or not original or original[0].get('status') != 'published'
            or not approval.get('original_media_id')
            or approval['original_media_id'] != original[0].get('media_id')
            or not start <= current <= end or not timedelta(0) < end - start <= timedelta(hours=24)
            or not approval.get('owner_request')
            or approval.get('reviewed_image_sha256') != state.get('image_sha256')
            or len(approval.get('reviewed_image_sha256') or []) != 7):
        raise JournalError('repost does not match the dated owner approval and reviewed seven images')
    return key + '-repost-' + packet_hash[:12]
