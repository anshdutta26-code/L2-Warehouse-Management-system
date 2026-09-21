"""
db/supabase_client.py
----------------------
Central Supabase client for database operations.
"""
from __future__ import annotations
import os
import streamlit as st
from supabase import Client, create_client


def _get_secret(key: str) -> str | None:
    try:
        if key in st.secrets:
            return str(st.secrets[key])
    except Exception:
        pass
    return os.environ.get(key)


def get_client() -> Client:
    """
    Har call pe fresh client banata hai aur
    current user ka access_token attach karta hai.
    Cache nahi karta — warna token stale ho jaata hai.
    """
    url     = _get_secret("SUPABASE_URL")
    anon_key = _get_secret("SUPABASE_ANON_KEY")

    if not url or not anon_key:
        raise RuntimeError("SUPABASE_URL / SUPABASE_ANON_KEY missing.")

    supabase = create_client(url, anon_key)

    # Logged-in user ka JWT attach karo
    stored_session = st.session_state.get("session")
    if stored_session:
        access_token = getattr(stored_session, "access_token", None)
        if access_token:
            supabase.postgrest.auth(access_token)

    return supabase
