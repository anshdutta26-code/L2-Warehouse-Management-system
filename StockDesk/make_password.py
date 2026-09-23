"""Run locally. Password is read privately; output contains only salt and hash."""
import getpass
import hashlib
import secrets

if __name__ == '__main__':
    password = getpass.getpass('Choose a strong password (12+ characters): ')
    if len(password) < 12:
        raise SystemExit('Use at least 12 characters.')
    if password != getpass.getpass('Repeat password: '):
        raise SystemExit('Passwords do not match.')
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac('sha256', password.encode(), salt, 600000).hex()
    print(salt.hex() + '$' + digest)
