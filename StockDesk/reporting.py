"""Read-only warehouse views; all balances remain owned by the ledger."""
from datetime import datetime
from zoneinfo import ZoneInfo


def filter_stock(rows, query='', reorder_only=False):
    query = query.strip().casefold()
    return [row for row in rows
            if query in ' '.join(str(row.get(k, '')) for k in ('Article ID', 'Article', 'HSN')).casefold()
            and (not reorder_only or row.get('Status') == 'REORDER')]


def filter_movements(moves, start, end, location=None, article=None):
    result = []
    for move in moves:
        stamp = datetime.fromisoformat(move['at'].replace('Z', '+00:00'))
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=ZoneInfo('Asia/Kolkata'))
        day = stamp.astimezone(ZoneInfo('Asia/Kolkata')).date()
        if start <= day <= end and (location is None or move['location'] == location) and (article is None or move['article'] == article):
            result.append(dict(move))
    return result
