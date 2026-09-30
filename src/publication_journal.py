"""Durable at-most-once reservation using GitHub Contents compare-and-set.

A reserved/uncertain record is NEVER automatically retried. This deliberately
prefers a missed post over a duplicate after a timeout or runner crash.
"""
from __future__ import annotations
import base64
import json
import re
from datetime import datetime, timezone

class JournalError(RuntimeError):
    pass

class GitHubJournal:
    def __init__(self, repository, token, *, branch='main', session=None):
        if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', repository):
            raise JournalError('invalid repository')
        if not token:
            raise JournalError('GH_TOKEN is required for a durable pre-publication lock')
        if session is None:
            import requests
            session = requests.Session()
        self.session = session
        self.session.headers.update({'Authorization':'Bearer ' + token,
                                     'Accept':'application/vnd.github+json',
                                     'X-GitHub-Api-Version':'2022-11-28'})
        self.base = 'https://api.github.com/repos/' + repository + '/contents/automation/publication_log/'
        self.branch = branch

    def _url(self, key):
        if not re.fullmatch(r'us-stock-\d{4}-\d{2}-\d{2}', key):
            raise JournalError('invalid publication key')
        return self.base + key + '.json'

    def read(self, key):
        response = self.session.get(self._url(key), params={'ref':self.branch}, timeout=30)
        if response.status_code == 404:
            return None
        if response.status_code != 200:
            raise JournalError('cannot read journal: HTTP ' + str(response.status_code))
        value = response.json()
        try:
            record = json.loads(base64.b64decode(value['content']).decode('utf-8'))
            sha = value['sha']
        except (ValueError, KeyError, TypeError) as exc:
            raise JournalError('corrupt journal; manual reconciliation required') from exc
        if not isinstance(record, dict) or record.get('key') != key or not sha:
            raise JournalError('invalid journal identity')
        return record, sha

    def _write(self, key, record, sha=None):
        body = {'message':f'publication journal: {key} {record["status"]}', 'branch':self.branch,
                'content':base64.b64encode(json.dumps(record, sort_keys=True).encode()).decode()}
        if sha:
            body['sha'] = sha
        response = self.session.put(self._url(key), json=body, timeout=30)
        if response.status_code not in (200, 201):
            # Includes a race with another runner. Never retry the reservation.
            raise JournalError('journal CAS failed; no new post allowed: HTTP ' + str(response.status_code))
        try:
            ack = response.json()['content']['sha']
            if not isinstance(ack, str) or not ack:
                raise JournalError('journal acknowledgement missing; do not publish')
            return record, ack
        except (KeyError, TypeError) as exc:
            raise JournalError('journal acknowledgement missing; do not publish') from exc

    def reserve(self, key, packet_hash):
        existing = self.read(key)
        if existing:
            if existing[0].get('status') == 'published':
                return None
            raise JournalError('reserved/uncertain session; reconcile Instagram manually before any retry')
        record = {'version':1, 'key':key, 'packet_sha256':packet_hash, 'status':'reserved',
                  'reserved_at':datetime.now(timezone.utc).isoformat()}
        return self._write(key, record)

    def complete(self, reservation, media_id):
        record, sha = reservation
        updated = {**record, 'status':'published', 'media_id':str(media_id),
                   'published_at':datetime.now(timezone.utc).isoformat()}
        return self._write(record['key'], updated, sha)


def publish_once(journal, key, packet_hash, sender):
    reservation = journal.reserve(key, packet_hash)
    if reservation is None:
        return {'status':'skipped_duplicate', 'key':key}
    # A failure at ANY point leaves the durable reservation in place.
    # In particular, an HTTP timeout may mean Meta already published the post.
    media_id = sender()
    if not isinstance(media_id, str) or not media_id:
        raise JournalError('missing media ID; outcome uncertain, do not retry')
    journal.complete(reservation, media_id)
    return {'status':'published', 'key':key, 'media_id':media_id}
