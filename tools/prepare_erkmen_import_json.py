"""Create an Erkmen import snapshot without legacy sessions or tokens."""

import argparse
import json
import os
from pathlib import Path

FORMAT = 'erkmen-legacy-sqlite-v1'
BUSINESS_TABLES = ('users', 'services_service', 'services_process', 'services_sparepart')
USER_FIELDS = (
    'id', 'email', 'password', 'first_name', 'last_name',
    'is_staff', 'is_superuser', 'is_active',
)


def prepare(source, destination, skip_users=()):
    source = Path(source).expanduser().resolve()
    destination = Path(destination).expanduser().resolve()
    if not source.is_file() or source == destination or destination.exists():
        raise ValueError('Kaynak bulunamadi, cikti zaten var veya iki yol ayni.')
    with source.open('r', encoding='utf-8') as stream:
        payload = json.load(stream)
    if payload.get('format') != FORMAT or not isinstance(payload.get('tables'), dict):
        raise ValueError('Gecersiz Erkmen JSON dis aktarma bicimi.')
    if any(name not in payload['tables'] for name in BUSINESS_TABLES):
        raise ValueError('Gerekli is tablosu eksik.')

    tables = {name: payload['tables'][name] for name in BUSINESS_TABLES}
    users = tables['users']
    if any(field not in users['columns'] for field in USER_FIELDS):
        raise ValueError('Kullanici tablosunda alan eksik.')
    excluded = {email.strip().lower() for email in skip_users}
    user_rows = [
        {field: row.get(field) for field in USER_FIELDS}
        for row in users['rows']
        if str(row.get('email') or '').strip().lower() not in excluded
    ]
    tables['users'] = {'columns': list(USER_FIELDS), 'rows': user_rows}
    prepared = {
        'format': FORMAT,
        'prepared_from': source.name,
        'source_exported_at': payload.get('exported_at'),
        'excluded_users': sorted(excluded),
        'tables': tables,
    }
    descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, 'w', encoding='utf-8', newline='\n') as output:
        json.dump(prepared, output, ensure_ascii=False, indent=2)
        output.write('\n')
    return {name: len(table['rows']) for name, table in tables.items()}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', help='Tum tablolarin UTF-8 JSON yedegi')
    parser.add_argument('destination', help='Yalniz gerekli verileri iceren yeni JSON')
    parser.add_argument('--skip-user', action='append', default=[], metavar='EPOSTA')
    args = parser.parse_args()
    counts = prepare(args.source, args.destination, args.skip_user)
    for name, count in counts.items():
        print(f'{name}: {count}')
