"""Export every table in a legacy SQLite database to a UTF-8 JSON snapshot."""

import argparse
import base64
import json
import os
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path


FORMAT = 'erkmen-legacy-sqlite-v1'


def json_value(value):
    if isinstance(value, bytes):
        return {'base64': base64.b64encode(value).decode('ascii')}
    return value


def export(source, destination):
    source = Path(source).expanduser().resolve()
    destination = Path(destination).expanduser().resolve()
    if not source.is_file():
        raise ValueError(f'SQLite dosyasi bulunamadi: {source}')
    if source == destination:
        raise ValueError('Kaynak ve JSON cikti dosyasi ayni olamaz.')
    if destination.exists():
        raise ValueError(f'JSON dosyasi zaten var: {destination}')
    if not destination.parent.is_dir():
        raise ValueError(f'Cikti dizini bulunamadi: {destination.parent}')

    with closing(sqlite3.connect(f'{source.as_uri()}?mode=ro', uri=True)) as connection:
        connection.row_factory = sqlite3.Row
        if connection.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
            raise ValueError('SQLite butunluk kontrolu basarisiz.')
        table_names = [row[0] for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name"
        )]
        tables = {}
        for table in table_names:
            escaped = table.replace('"', '""')
            columns = [row[1] for row in connection.execute(f'PRAGMA table_info("{escaped}")')]
            rows = [
                {key: json_value(row[key]) for key in row.keys()}
                for row in connection.execute(f'SELECT * FROM "{escaped}"')
            ]
            tables[table] = {'columns': columns, 'rows': rows}

    payload = {
        'format': FORMAT,
        'exported_at': datetime.now(timezone.utc).isoformat(),
        'tables': tables,
    }
    descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, 'w', encoding='utf-8', newline='\n') as output:
        json.dump(payload, output, ensure_ascii=False, indent=2)
        output.write('\n')
    return {name: len(table['rows']) for name, table in tables.items()}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', help='Eski db.sqlite3 dosyasi')
    parser.add_argument('destination', help='Yeni UTF-8 JSON dosyasi')
    args = parser.parse_args()
    counts = export(args.source, args.destination)
    for name, count in counts.items():
        print(f'{name}: {count}')
