"""Trusted reconciliation of uncertain object transfers; never infers terminality from age."""
import argparse
import hashlib
import json
import os
import uuid

import psycopg
from psycopg.rows import dict_row

from admaker.cloud_objects import configured_cloud_storage


def reconcile_cloud_object(database_url, account_id, local_key, resolution_id, operator, decision, evidence, *, store=None):
    account_id, resolution_id = uuid.UUID(str(account_id)), uuid.UUID(str(resolution_id))
    operator, evidence = operator.strip(), evidence.strip()
    if not 1 <= len(operator) <= 100 or not 1 <= len(evidence) <= 500:
        raise ValueError("A bounded operator and terminal-operation evidence reference are required")
    if decision not in {'verified_present', 'verified_absent'}:
        raise ValueError("A verified terminal outcome is required")
    with psycopg.connect(database_url) as c:
        c.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", (f'account-media:{account_id}',))
        prior = c.execute('SELECT account_id,local_key,operator,decision,evidence FROM app.cloud_object_reviews WHERE id=%s', (resolution_id,)).fetchone()
        if prior:
            if prior != (account_id, local_key, operator, decision, evidence):
                raise ValueError("Resolution identifier already has a different outcome")
            return True
        row = c.execute('SELECT object_key,origin,bucket,checksum,size_bytes,state FROM app.cloud_objects WHERE account_id=%s AND local_key=%s FOR UPDATE', (account_id, local_key)).fetchone()
        if row is None:
            return False
        if row[5] != 'pending':
            raise ValueError("Only a pending transfer can be reconciled")
        store = store or configured_cloud_storage()
        if (row[1], row[2]) != (store.origin, store.bucket):
            raise ValueError("Storage destination differs from the recorded transfer")
        remote = store.download(row[0], row[4])
        if decision == 'verified_present':
            if remote is None or len(remote) != row[4] or hashlib.sha256(remote).hexdigest() != row[3]:
                raise ValueError("Remote content does not match the registered object")
            state = 'ready'
        else:
            if remote is not None:
                raise ValueError("The object still exists")
            state = 'verified_absent'
        c.execute('INSERT INTO app.cloud_object_reviews(id,account_id,local_key,object_key,checksum,operator,decision,evidence) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)',
            (resolution_id, account_id, local_key, row[0], row[3], operator, decision, evidence))
        c.execute('UPDATE app.cloud_objects SET state=%s WHERE account_id=%s AND local_key=%s', (state, account_id, local_key))
    return True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    pending = commands.add_parser('list')
    pending.add_argument('--limit', type=int, choices=range(1, 101), default=20)
    resolve = commands.add_parser('resolve')
    resolve.add_argument('account_id', type=uuid.UUID)
    resolve.add_argument('local_key')
    resolve.add_argument('--resolution-id', type=uuid.UUID, required=True)
    resolve.add_argument('--operator', required=True)
    resolve.add_argument('--decision', choices=['verified_present', 'verified_absent'], required=True)
    resolve.add_argument('--evidence', required=True, help='Restricted evidence that the original upload has terminated; no private payloads')
    args = parser.parse_args()
    try:
        url = os.environ['DATABASE_URL']
        if args.command == 'list':
            with psycopg.connect(url, row_factory=dict_row) as c:
                rows = c.execute("SELECT account_id,local_key,object_key,origin,bucket,created_at FROM app.cloud_objects WHERE state='pending' ORDER BY created_at LIMIT %s", (args.limit,)).fetchall()
            print(json.dumps(rows, default=str))
        elif reconcile_cloud_object(url, args.account_id, args.local_key, args.resolution_id, args.operator, args.decision, args.evidence):
            print('Cloud transfer outcome recorded; no upload or credit change performed.')
        else:
            parser.exit(1, 'No transfer found.\n')
    except ValueError as error:
        parser.exit(1, str(error) + '\n')
    except (psycopg.Error, OSError, KeyError):
        parser.exit(1, 'Cloud reconciliation is unavailable.\n')


if __name__ == '__main__':
    main()
