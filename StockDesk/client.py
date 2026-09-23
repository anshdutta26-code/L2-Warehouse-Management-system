"""Signed server-to-server requests. Credentials never go into Google Sheet cells."""
import hashlib
import hmac
import json
import time
import requests


class Backend:
    def __init__(self, url, secret):
        if not url.startswith('https://script.google.com/macros/s/') or not url.endswith('/exec'):
            raise ValueError('Use the deployed Google Apps Script /exec URL.')
        self.url, self.secret = url, secret

    def call(self, action, data=None, revision=0, request_id=None, actor='operator'):
        body = {'action': action, 'data': data or {}, 'revision': revision,
                'id': request_id, 'actor': actor, 'timestamp': int(time.time())}
        payload = json.dumps(body, separators=(',', ':'), ensure_ascii=True)
        signature = hmac.new(self.secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
        response = requests.post(self.url, json={'payload': payload, 'signature': signature}, timeout=90)
        response.raise_for_status()
        try:
            result = response.json()
        except ValueError as exc:
            raise RuntimeError('Backend did not return JSON. Check deployment access and /exec URL.') from exc
        if not result.get('ok'):
            raise ValueError(result.get('error', 'Backend rejected the request'))
        return result


def pin_lookup(pin):
    if len(pin) != 6 or not pin.isdigit() or pin[0] == '0':
        raise ValueError('Enter a valid six-digit PIN.')
    r = requests.get(f'https://api.postalpincode.in/pincode/{pin}', timeout=12)
    r.raise_for_status()
    data = r.json()
    if not data or data[0].get('Status') != 'Success':
        raise ValueError('PIN not found. Enter city and state manually.')
    return data[0].get('PostOffice', [])
