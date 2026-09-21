"""
page_modules/gate_in.py
----------------
Gate In page — Supabase optimized version.

Flow:
  Gate In khulte hi PO ki list dikhti hai (Pending / Completed tabs)
      ↓
  PO pe "Open" dabao
      ↓
  Us PO ke andar SKU + Location + Qty se Gate In karo
      ↓
  Items Added → Save All Gate In
      ↓
  PO ki saari qty aa jaye to woh Completed tab mein chala jata hai
"""

import json
import pandas as pd
import streamlit as st
from db.supabase_client import get_client


PAGE_SIZE = 1000
TOP_LIST = 20      # ek tab mein max itne PO dikhenge (search se filter karo)


# =========================================================
# HELPERS
# =========================================================

def _s(val) -> str:
    """str + strip shorthand"""
    return str(val or "").strip()


def _f(val) -> float:
    """safe float"""
    try:
        return float(val or 0)
    except Exception:
        return 0.0


# =========================================================
# SESSION STATE
# =========================================================

def _init_state() -> None:
    defaults = {
        "gate_in_items": [],
        "gate_in_success": False,
        "gate_in_success_message": "",
        "gate_in_active_po": None,
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


# =========================================================
# LOAD PO LIST — only on Gate In open
# =========================================================

@st.cache_data(ttl=60, show_spinner=False)
def _load_pos() -> list[dict]:
    try:
        response = (
            get_client()
            .table("po_master")
            .select("po_no,warehouse,vendor,po_type,sku_data")
            .order("created_at", desc=True)
            .execute()
        )
        return response.data or []
    except Exception as e:
        raise Exception(f"PO Master load error: {e}")


# =========================================================
# RECEIVED QTY (IN transactions only)
#   _sum_in_transactions(None)   → saare POs  {(po_no, sku): qty}
#   _sum_in_transactions("PO-1") → sirf ek PO {(po_no, sku): qty}
# =========================================================

def _sum_in_transactions(po_no: str | None = None) -> dict:
    try:
        client = get_client()
        totals: dict = {}
        start = 0

        while True:
            query = (
                client
                .table("inventory_transactions")
                .select("po_number,sku,qty")
                .eq("transaction_type", "IN")
            )
            if po_no is not None:
                query = query.eq("po_number", po_no)

            response = (
                query
                .order("id")
                .range(start, start + PAGE_SIZE - 1)
                .execute()
            )
            data = response.data or []

            for row in data:
                key = (_s(row.get("po_number")), _s(row.get("sku")))
                totals[key] = totals.get(key, 0.0) + _f(row.get("qty"))

            if len(data) < PAGE_SIZE:
                break

            start += PAGE_SIZE

        return totals

    except Exception as e:
        raise Exception(f"Received qty load error: {e}")


# PO list ke liye — saare POs ka received qty (list view)
@st.cache_data(ttl=30, show_spinner=False)
def _load_received_by_po_sku() -> dict:
    return _sum_in_transactions()


# PO detail ke liye — sirf is PO ka received qty (chhoti query)
@st.cache_data(ttl=30, show_spinner=False)
def _load_received_for_po(po_no: str) -> dict:
    return _sum_in_transactions(_s(po_no))


# =========================================================
# LOAD LOCATIONS FOR SKU — only on SKU select
# =========================================================

@st.cache_data(ttl=30, show_spinner=False)
def _load_sku_locations(sku_code: str) -> list[dict]:
    sku_code = _s(sku_code)
    if not sku_code:
        return []
    try:
        response = (
            get_client()
            .table("location_master")
            .select("wh_location,tower,rack,bin,location,sku,qty")
            .eq("sku", sku_code)
            .order("location")
            .execute()
        )
        return response.data or []
    except Exception as e:
        raise Exception(f"Location Master load error: {e}")


# =========================================================
# LOAD TRANSACTIONS FOR SKU — only on SKU select
# =========================================================

@st.cache_data(ttl=10, show_spinner=False)
def _load_sku_transactions(sku_code: str) -> list[dict]:
    sku_code = _s(sku_code)
    if not sku_code:
        return []
    try:
        # created_at is page mein use nahi hota, isliye nahi mangwaya
        response = (
            get_client()
            .table("inventory_transactions")
            .select("id,transaction_type,po_number,sku,location,qty")
            .eq("sku", sku_code)
            .execute()
        )
        return response.data or []
    except Exception as e:
        raise Exception(f"Inventory Transactions load error: {e}")


def _clear_gate_in_caches() -> None:
    """Save ke baad sab related cache saaf."""
    _load_sku_transactions.clear()
    _load_sku_locations.clear()
    _load_received_by_po_sku.clear()
    _load_received_for_po.clear()
    _load_pos.clear()


# =========================================================
# GET SKU DATA FROM PO
# =========================================================

def _get_po_skus(po_record: dict) -> list[dict]:
    raw = po_record.get("sku_data")
    if not raw:
        return []
    try:
        data = json.loads(raw) if isinstance(raw, str) else raw
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _unique_skus(po_skus: list[dict]) -> dict[str, dict]:
    """
    {sku_code: sku_record}  — same SKU dobara ho to last record jeetta hai.
    (List view aur detail view dono yahi rule use karte hain)
    """
    return {
        _s(s.get("sku_code")): s
        for s in po_skus
        if _s(s.get("sku_code"))
    }


# =========================================================
# GET RECEIVED QTY — only IN transactions
# =========================================================

def _get_received_qty(
    transaction_data: list[dict],
    po_no: str,
    sku_code: str,
) -> float:
    if not transaction_data:
        return 0.0
    target_po  = _s(po_no)
    target_sku = _s(sku_code)
    return sum(
        _f(row.get("qty"))
        for row in transaction_data
        if _s(row.get("transaction_type")).upper() == "IN"
        and _s(row.get("po_number")) == target_po
        and _s(row.get("sku"))       == target_sku
    )


# =========================================================
# PO SUMMARY (ordered / received / pending / status)
# =========================================================

def _po_summary(po: dict, received_map: dict) -> dict:
    po_no = _s(po.get("po_no"))

    unique_skus = _unique_skus(_get_po_skus(po))

    ordered = 0.0
    received = 0.0
    pending = 0.0

    for sku_code, sku in unique_skus.items():
        o = _f(sku.get("qty"))
        r = received_map.get((po_no, sku_code), 0.0)

        ordered += o
        received += min(r, o)
        pending += max(o - r, 0.0)

    if ordered > 0 and pending <= 0:
        status = "COMPLETED"
    elif received > 0:
        status = "PARTIAL"
    else:
        status = "PENDING"

    return {
        "po": po,
        "po_no": po_no,
        "vendor": _s(po.get("vendor")),
        "warehouse": _s(po.get("warehouse")),
        "sku_count": len(unique_skus),
        "ordered": ordered,
        "received": received,
        "pending": pending,
        "status": status,
    }


def _get_opening_stock(location_data: list[dict]) -> pd.DataFrame:
    rows = [
        {"location": _s(r.get("location")),
         "sku":      _s(r.get("sku")),
         "qty":      _f(r.get("qty"))}
        for r in location_data
        if _s(r.get("location")) and _s(r.get("sku"))
    ]
    if not rows:
        return pd.DataFrame(columns=["location", "sku", "qty"])
    return (
        pd.DataFrame(rows)
        .groupby(["location", "sku"], as_index=False)["qty"]
        .sum()
    )


def _get_transaction_stock(transaction_data: list[dict]) -> pd.DataFrame:
    rows = []
    for r in transaction_data:
        loc = _s(r.get("location"))
        sku = _s(r.get("sku"))
        if not loc or not sku:
            continue
        qty  = _f(r.get("qty"))
        ttype = _s(r.get("transaction_type")).upper()
        if ttype == "IN":
            rows.append({"location": loc, "sku": sku, "qty":  qty})
        elif ttype == "OUT":
            rows.append({"location": loc, "sku": sku, "qty": -qty})
    if not rows:
        return pd.DataFrame(columns=["location", "sku", "qty"])
    return (
        pd.DataFrame(rows)
        .groupby(["location", "sku"], as_index=False)["qty"]
        .sum()
    )


def _get_current_stock(
    location_data: list[dict],
    transaction_data: list[dict],
) -> pd.DataFrame:
    combined = pd.concat(
        [_get_opening_stock(location_data),
         _get_transaction_stock(transaction_data)],
        ignore_index=True,
    )
    if combined.empty:
        return pd.DataFrame(columns=["location", "sku", "current_qty"])
    result = (
        combined
        .groupby(["location", "sku"], as_index=False)["qty"]
        .sum()
        .rename(columns={"qty": "current_qty"})
    )
    result.loc[result["current_qty"].abs() < 1e-6, "current_qty"] = 0
    return result[result["current_qty"] > 0].reset_index(drop=True)


def _get_location_stock(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=["location", "current_qty"])
    return (
        df[["location", "current_qty"]]
        .groupby("location", as_index=False)["current_qty"]
        .sum()
        .sort_values("current_qty", ascending=False)
        .reset_index(drop=True)
    )


def _get_location_qty(df: pd.DataFrame, location: str) -> float:
    if df.empty:
        return 0.0
    mask = df["location"].astype(str).str.strip() == _s(location)
    return float(df.loc[mask, "current_qty"].sum())


def _get_location_names(location_data: list[dict]) -> list[str]:
    return sorted({
        _s(r.get("location"))
        for r in location_data
        if _s(r.get("location"))
    })


_CSS = """
<style>
.gate-title {
    font-size: 1.35rem; font-weight: 700; color: #111827;
    margin-bottom: 1rem; padding-bottom: 0.7rem;
    border-bottom: 1px solid #e5e7eb;
}
.section-title {
    font-size: 0.78rem; font-weight: 700; color: #6b7280;
    letter-spacing: 0.08em; text-transform: uppercase;
    margin-top: 1.1rem; margin-bottom: 0.7rem;
    padding-bottom: 0.45rem; border-bottom: 1px solid #e5e7eb;
}
.po-info {
    background: #eff6ff; border: 1px solid #bfdbfe;
    border-radius: 10px; padding: 0.75rem 1rem;
    color: #1d4ed8; margin-bottom: 1rem;
}
.stock-empty {
    background: #eff6ff; border: 1px solid #bfdbfe;
    border-radius: 10px; padding: 0.75rem 1rem; color: #1d4ed8;
}

/* PO LIST */
.gi-head {
    font-size: 0.76rem; font-weight: 700; color: #374151;
}
.gi-po {
    color: #0284c7; font-size: 0.86rem; font-weight: 700;
    word-break: break-word;
}
.gi-cell {
    color: #374151; font-size: 0.82rem; line-height: 1.4;
    word-break: break-word;
}
.gi-num {
    color: #111827; font-size: 0.88rem; font-weight: 700;
}
.gi-badge {
    display: inline-block; padding: 4px 9px; border-radius: 15px;
    font-size: 0.7rem; font-weight: 600; white-space: nowrap;
}
.gi-badge-pending   { background: #ffedd5; color: #9a3412; }
.gi-badge-partial   { background: #dbeafe; color: #1e40af; }
.gi-badge-completed { background: #dcfce7; color: #166534; }
.gi-sep {
    border-bottom: 1px solid #e5e7eb; margin: 0.2rem 0 0.4rem 0;
}

button[data-baseweb="tab"][aria-selected="false"] p {
    color: #374151 !important;
    -webkit-text-fill-color: #374151 !important;
}
</style>
"""


_COLS = [1.5, 2.0, 1.2, 0.9, 0.9, 0.9, 1.2, 1.0]


# =========================================================
# PO LIST VIEW
# =========================================================

def _cell(col, css_class: str, text) -> None:
    col.markdown(
        f'<div class="{css_class}">{text}</div>',
        unsafe_allow_html=True,
    )


def _render_po_rows(rows: list[dict], tab_key: str) -> None:

    if not rows:
        st.info("Koi PO nahi mila.")
        return

    shown = rows[:TOP_LIST]

    h = st.columns(_COLS)
    for col, label in zip(
        h,
        ["PO No", "Vendor", "Warehouse", "SKUs",
         "Ordered", "Pending", "Status", "Action"],
    ):
        _cell(col, "gi-head", label)

    for r in shown:

        c = st.columns(_COLS)

        _cell(c[0], "gi-po",   r["po_no"])
        _cell(c[1], "gi-cell", r["vendor"] or "-")
        _cell(c[2], "gi-cell", r["warehouse"] or "-")
        _cell(c[3], "gi-num",  r["sku_count"])
        _cell(c[4], "gi-num",  f'{r["ordered"]:g}')
        _cell(c[5], "gi-num",  f'{r["pending"]:g}')
        c[6].markdown(
            f'<span class="gi-badge gi-badge-{r["status"].lower()}">'
            f'{r["status"]}</span>',
            unsafe_allow_html=True,
        )

        with c[7]:
            label = "Open ▶" if r["status"] != "COMPLETED" else "View"
            if st.button(
                label,
                key=f"gate_in_open_{tab_key}_{r['po_no']}",
                use_container_width=True,
            ):
                st.session_state.gate_in_active_po = r["po_no"]
                st.rerun()

        st.markdown('<div class="gi-sep"></div>', unsafe_allow_html=True)

    if len(rows) > TOP_LIST:
        st.caption(
            f"Pehle {TOP_LIST} PO dikh rahe hain (total {len(rows)}). "
            f"Baaki dekhne ke liye upar search karo."
        )


def _render_po_list(po_data: list[dict]) -> None:

    st.markdown(
        '<div class="section-title">📄 Purchase Orders</div>',
        unsafe_allow_html=True,
    )

    try:
        received_map = _load_received_by_po_sku()
    except Exception as e:
        st.error(f"❌ Received Qty Load Error: {e}")
        received_map = {}

    search = st.text_input(
        "Search PO",
        placeholder="Search PO No, Vendor or Warehouse...",
        label_visibility="collapsed",
        key="gate_in_search",
    ).strip().lower()

    summaries = []

    for po in po_data:

        if not _s(po.get("po_no")):
            continue

        summary = _po_summary(po, received_map)

        if search:
            searchable = " ".join(
                [summary["po_no"], summary["vendor"], summary["warehouse"]]
            ).lower()
            if search not in searchable:
                continue

        summaries.append(summary)

    pending_rows = [s for s in summaries if s["status"] != "COMPLETED"]
    done_rows = [s for s in summaries if s["status"] == "COMPLETED"]

    tab_pending, tab_done = st.tabs(
        [
            f"⏳ Pending ({len(pending_rows)})",
            f"✅ Completed ({len(done_rows)})",
        ]
    )

    with tab_pending:
        _render_po_rows(pending_rows, "pending")

    with tab_done:
        _render_po_rows(done_rows, "done")


# =========================================================
# PO DETAIL VIEW (Gate In inside a PO)
# =========================================================

def _render_po_detail(selected_po: dict) -> None:

    selected_po_no = _s(selected_po.get("po_no"))

    # ── Back to PO list ──
    if st.button("⬅ Back To PO List", key="gate_in_back_list"):
        st.session_state.gate_in_active_po = None
        st.rerun()

    st.markdown(
        f'<div class="po-info">'
        f'<b>PO:</b> {selected_po_no} &nbsp;|&nbsp; '
        f'<b>Vendor:</b> {_s(selected_po.get("vendor"))} &nbsp;|&nbsp; '
        f'<b>Warehouse:</b> {_s(selected_po.get("warehouse"))}'
        f'</div>',
        unsafe_allow_html=True,
    )

    po_skus = _get_po_skus(selected_po)

    if not po_skus:
        st.warning("⚠️ Is PO ke andar koi SKU nahi mila.")
        return

    sku_records = list(_unique_skus(po_skus).values())

    # ── SKU summary (ordered / received / pending) ──
    # Sirf isi PO ka received qty (saare POs ka nahi) — chhoti query
    try:
        received_map = _load_received_for_po(selected_po_no)
    except Exception as e:
        st.error(f"❌ Received Qty Load Error: {e}")
        received_map = {}

    summary_rows = []
    sku_pending: dict[str, float] = {}

    for s in sku_records:
        code = _s(s.get("sku_code"))
        o = _f(s.get("qty"))
        r = received_map.get((selected_po_no, code), 0.0)
        p = max(o - r, 0.0)
        sku_pending[code] = p
        summary_rows.append(
            {
                "SKU": _s(s.get("sku_name")) or code,
                "Ordered": o,
                "Received": r,
                "Pending": p,
            }
        )

    st.markdown(
        '<div class="section-title">📦 PO Items</div>',
        unsafe_allow_html=True,
    )
    st.dataframe(
        pd.DataFrame(summary_rows),
        use_container_width=True,
        hide_index=True,
    )

    if all(p <= 0 for p in sku_pending.values()):
        st.success("✅ Is PO ki saari quantity receive ho chuki hai.")

    # ── SKU select (pehla pending SKU default) ──
    sku_options = [
        f"{_s(s.get('sku_name')) or _s(s.get('sku_code'))}"
        f" — Pending: {sku_pending[_s(s.get('sku_code'))]:g}"
        for s in sku_records
    ]

    default_index = next(
        (
            i
            for i, s in enumerate(sku_records)
            if sku_pending[_s(s.get("sku_code"))] > 0
        ),
        0,
    )

    selected_sku_display = st.selectbox(
        "Select SKU", sku_options,
        index=default_index,
        label_visibility="collapsed",
        key=f"gate_in_sku_{selected_po_no}",
    )

    idx = sku_options.index(selected_sku_display)

    _render_sku_gate_in(selected_po_no, sku_records[idx])


def _render_sku_gate_in(selected_po_no: str, selected_sku: dict) -> None:
    """Ek SKU ka stock, location, qty aur Add Item."""

    sku_code = _s(selected_sku.get("sku_code"))
    sku_name = _s(selected_sku.get("sku_name"))

    # Load SKU data (cached)
    try:
        with st.spinner("Loading SKU stock..."):
            loc_data = _load_sku_locations(sku_code)
            txn_data = _load_sku_transactions(sku_code)
    except Exception as e:
        st.error(f"❌ SKU Data Load Error: {e}")
        loc_data, txn_data = [], []

    current_stock_df = _get_current_stock(loc_data, txn_data)
    ordered_qty      = _f(selected_sku.get("qty"))
    received_qty     = _get_received_qty(txn_data, selected_po_no, sku_code)
    pending_qty      = max(ordered_qty - received_qty, 0)

    # Metrics
    c1, c2, c3 = st.columns(3)
    c1.metric("Ordered Qty",      f"{ordered_qty:g}")
    c2.metric("Already Received", f"{received_qty:g}")
    c3.metric("Pending Qty",      f"{pending_qty:g}")

    # Existing stock
    st.markdown('<div class="section-title">📍 Existing Location Stock</div>',
                unsafe_allow_html=True)
    loc_stock_df = _get_location_stock(current_stock_df)
    if loc_stock_df.empty:
        st.markdown(
            '<div class="stock-empty">'
            'ℹ️ Is SKU ka abhi kisi location par stock nahi hai.'
            '</div>',
            unsafe_allow_html=True,
        )
    else:
        display_df = loc_stock_df.copy()
        display_df.columns = ["Location", "Current Qty"]
        st.dataframe(display_df, use_container_width=True, hide_index=True)

    if pending_qty <= 0:
        st.success("✅ Is SKU ki PO quantity completely received hai.")
        return

    st.markdown('<div class="section-title">📍 Gate In Location</div>',
                unsafe_allow_html=True)
    sku_locations = _get_location_names(loc_data)

    if not sku_locations:
        st.error(
            f"❌ {sku_name} ke liye Location Master mein "
            "koi location assigned nahi hai."
        )
        return

    # Already added in current session
    already_added = sum(
        _f(item["qty"])
        for item in st.session_state.gate_in_items
        if _s(item["po_no"])   == selected_po_no
        and _s(item["sku_code"]) == sku_code
    )
    remaining = max(pending_qty - already_added, 0)

    if remaining <= 0:
        st.info(
            "ℹ️ Is SKU ki pending quantity "
            "current Gate In mein already add ho chuki hai."
        )
        return

    # Location dropdown
    loc_display_map = {}
    loc_options     = ["— Select Location —"]
    for loc in sku_locations:
        cur_qty = _get_location_qty(current_stock_df, loc)
        disp    = f"{loc} — Current: {cur_qty:g}"
        loc_display_map[disp] = loc
        loc_options.append(disp)

    sel_loc_disp = st.selectbox(
        "Select Location", loc_options,
        label_visibility="collapsed",
        key=f"gate_in_location_{sku_code}",
    )

    if sel_loc_disp == "— Select Location —":
        return

    selected_location = loc_display_map[sel_loc_disp]

    st.markdown(
        '<div class="section-title">📦 Received Quantity</div>',
        unsafe_allow_html=True,
    )
    gate_qty = st.number_input(
        "How many items received?",
        min_value=0.0,
        max_value=float(remaining),
        value=0.0,
        step=1.0,
        key=f"gate_in_qty_{sku_code}",
        help=f"Maximum {remaining:g} items add kar sakte ho.",
    )

    if st.button("➕ Add Item", type="primary",
                 key=f"gate_in_add_{sku_code}"):
        if gate_qty <= 0:
            st.error("❌ Received quantity 0 se greater honi chahiye.")
        elif gate_qty > remaining:
            st.error(f"❌ Sirf {remaining:g} quantity add kar sakte ho.")
        else:
            st.session_state.gate_in_items.append({
                "po_no":    selected_po_no,
                "sku_code": sku_code,
                "sku_name": sku_name,
                "qty":      float(gate_qty),
                "location": selected_location,
            })
            st.session_state.gate_in_flash = "✅ Item added successfully."
            st.session_state.gate_in_clear_prefixes = [
                f"gate_in_qty_{sku_code}",
                f"gate_in_location_{sku_code}",
            ]
            st.rerun()


# =========================================================
# SAVE ALL GATE IN
#   Koi bhi validation fail ho to Exception (user-facing message)
# =========================================================

def _save_gate_in(items_to_save: list[dict], po_data: list[dict]) -> None:
    supabase = get_client()

    # Group qty by PO + SKU for validation
    items_by_sku: dict[tuple, float] = {}
    for item in items_to_save:
        key = (_s(item["po_no"]), _s(item["sku_code"]))
        items_by_sku[key] = items_by_sku.get(key, 0.0) + _f(item["qty"])

    # Clear txn cache once before validation loop
    _load_sku_transactions.clear()

    # PO lookup ek baar (pehla match jeetta hai, jaise pehle `next(...)` mein tha)
    po_by_no: dict[str, dict] = {}
    for p in po_data:
        po_by_no.setdefault(_s(p.get("po_no")), p)

    # Validate each PO + SKU
    for (po_no, sku_code), total_qty in items_by_sku.items():
        if total_qty <= 0:
            raise Exception(f"{po_no} / {sku_code}: Quantity invalid hai.")

        po_record = po_by_no.get(po_no)
        if not po_record:
            raise Exception(f"PO {po_no} nahi mila.")

        sku_record = next(
            (s for s in _get_po_skus(po_record)
             if _s(s.get("sku_code")) == sku_code),
            None,
        )
        if not sku_record:
            raise Exception(f"SKU {sku_code} PO {po_no} mein nahi mila.")

        ordered_qty      = _f(sku_record.get("qty"))
        fresh_txns       = _load_sku_transactions(sku_code)
        already_received = _get_received_qty(fresh_txns, po_no, sku_code)
        pending_qty      = max(ordered_qty - already_received, 0)

        if total_qty > pending_qty:
            raise Exception(
                f"{po_no} / {sku_code}: "
                f"Sirf {pending_qty:g} quantity pending hai."
            )

    # Validate locations (har SKU ke allowed locations ek baar nikaalo)
    allowed_by_sku: dict[str, list[str]] = {}
    for item in items_to_save:
        item_sku = _s(item["sku_code"])
        item_loc = _s(item["location"])
        if item_sku not in allowed_by_sku:
            allowed_by_sku[item_sku] = _get_location_names(
                _load_sku_locations(item_sku)
            )
        if item_loc not in allowed_by_sku[item_sku]:
            raise Exception(
                f"{item_sku} ke liye {item_loc} "
                "valid assigned location nahi hai."
            )

    # Insert
    rows = [
        {
            "transaction_type": "IN",
            "po_number":        _s(i["po_no"]),
            "sku":              _s(i["sku_code"]),
            "location":         _s(i["location"]),
            "qty":              _f(i["qty"]),
        }
        for i in items_to_save
    ]
    response = supabase.table("inventory_transactions").insert(rows).execute()
    if response is None:
        raise Exception("Supabase se response nahi mila.")

    # Clear all caches after successful insert
    _clear_gate_in_caches()


# =========================================================
# ITEMS ADDED — outside PO/SKU block so always visible
# =========================================================

def _render_items_added(po_data: list[dict]) -> None:
    st.divider()
    st.markdown('<div class="section-title">📋 Items Added</div>',
                unsafe_allow_html=True)

    review_df = pd.DataFrame(st.session_state.gate_in_items)[
        ["po_no", "sku_code", "sku_name", "qty", "location"]
    ]
    review_df.columns = ["PO No", "SKU Code", "SKU Name", "Qty", "Location"]
    st.dataframe(review_df, use_container_width=True, hide_index=True)

    total = sum(_f(i["qty"]) for i in st.session_state.gate_in_items)
    st.info(f"📦 Total This Gate In: {total:g}")

    if not st.button("✅ Save All Gate In", type="primary",
                     use_container_width=True, key="gate_in_save_all"):
        return

    items_to_save = list(st.session_state.gate_in_items)
    if not items_to_save:
        st.warning("⚠️ Pehle kam se kam ek item Add Item se add karo.")
        return

    try:
        _save_gate_in(items_to_save, po_data)
    except Exception as e:
        st.error(f"❌ Gate In Save Nahi Hua: {e}")
        return

    # Save ho gaya → items khali, PO list pe wapas.
    # Balloons + success message top banner dikhayega.
    st.session_state.gate_in_items     = []
    st.session_state.gate_in_success   = True
    st.session_state.gate_in_active_po = None
    st.session_state.gate_in_clear_prefixes = [
        "gate_in_qty_",
        "gate_in_location_",
        "gate_in_sku_",
    ]
    st.rerun()


# =========================================================
# MAIN PAGE
# =========================================================

def render_gate_in(on_back=None) -> None:
    _init_state()
    st.markdown(_CSS, unsafe_allow_html=True)

    # ── Pichhle run ne jo widget values clear karne ko kaha ──
    # (Add/Save ke baad purani qty/location value nayi max limit se
    #  zyada reh jati thi aur error deti thi)
    prefixes = st.session_state.pop("gate_in_clear_prefixes", None)
    if prefixes:
        for k in list(st.session_state.keys()):
            if isinstance(k, str) and k.startswith(tuple(prefixes)):
                st.session_state.pop(k, None)

    # ── Title ──
    st.markdown('<div class="gate-title">📥 Gate In</div>',
                unsafe_allow_html=True)

    # ── Back ──
    if st.button("⬅ Back To Home", key="gate_in_back"):
        for k in ("gate_in_items", "gate_in_success",
                  "gate_in_success_message",
                  "gate_in_active_po"):
            st.session_state.pop(k, None)
        if on_back:
            on_back()
        st.rerun()

    st.divider()

    # ── Success banner (after save) ──
    if st.session_state.gate_in_success:
        st.balloons()
        st.success("🎉 Gate In Saved Successfully!")
        st.session_state.gate_in_success = False

    flash = st.session_state.pop("gate_in_flash", "")
    if flash:
        st.success(flash)

    # ── Load POs ──
    try:
        po_data = _load_pos()
    except Exception as e:
        st.error(f"❌ PO Data Load Error: {e}")
        return

    # ── List view  /  PO detail view ──
    active_po_no = st.session_state.gate_in_active_po

    active_po = next(
        (p for p in po_data if _s(p.get("po_no")) == _s(active_po_no)),
        None,
    ) if active_po_no else None

    if active_po:
        _render_po_detail(active_po)
    else:
        st.session_state.gate_in_active_po = None
        _render_po_list(po_data)

    if st.session_state.gate_in_items:
        _render_items_added(po_data)
