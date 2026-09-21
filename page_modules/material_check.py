"""
page_modules/material_check.py

EMIZA WMS — Material Check

Kaam:
- Warehouse staff kisi bhi SKU ko search kare
- Dekhe ki woh kis-kis location pe padi hai aur kitni hai
- Ek SKU multiple locations / multiple warehouses mein ho sakti hai
- Location se bhi dekh sakte hain ki wahan kaun-kaun si SKU padi hai

Stock logic (Gate Out ke jaisa hi):

    Current Stock (SKU + Location)
        = location_master.qty
        + inventory_transactions IN
        - inventory_transactions OUT

IMPORTANT:
- Yeh page READ ONLY hai, koi data change nahi karta
- Negative stock ko 0 dikhaya jata hai
"""

from __future__ import annotations

import html

import streamlit as st

from auth import get_client


PAGE_SIZE = 1000
TOP_DEFAULT = 5    # bina search ke: sabse zyada qty wale top 5
TOP_SEARCH = 20    # search karne par: matching mein se top 20


# =========================================================
# HELPERS
# =========================================================

def _s(value) -> str:
    return str(value or "").strip()


def _e(value) -> str:
    return html.escape(_s(value))


def _f(value) -> float:
    try:
        return float(value or 0)
    except Exception:
        return 0.0


def _fmt_qty(value) -> str:
    value = _f(value)

    if value.is_integer():
        return str(int(value))

    return f"{value:.2f}"


def _html(markup: str) -> None:
    """
    Har line ka indent hata ke aur blank lines nikaal ke
    single block bana dete hain, taaki Streamlit/Markdown
    ise code block na samjhe.
    """
    cleaned = " ".join(
        line.strip()
        for line in markup.splitlines()
        if line.strip()
    )

    st.markdown(
        cleaned,
        unsafe_allow_html=True,
    )


# =========================================================
# FETCH ALL ROWS (1000 se zyada rows ke liye)
# =========================================================

def _fetch_all(
    table: str,
    columns: str,
    order_col: str,
) -> list[dict]:

    client = get_client()

    rows: list[dict] = []
    start = 0

    while True:

        response = (
            client
            .table(table)
            .select(columns)
            .order(order_col)
            .range(
                start,
                start + PAGE_SIZE - 1,
            )
            .execute()
        )

        data = response.data or []

        rows.extend(data)

        if len(data) < PAGE_SIZE:
            break

        start += PAGE_SIZE

    return rows


# =========================================================
# LOAD STOCK (SKU + LOCATION WISE)
# =========================================================

@st.cache_data(
    ttl=30,
    show_spinner=False,
)
def _load_stock_rows() -> list[dict]:

    try:

        location_rows = _fetch_all(
            "location_master",
            "wh_location, tower, rack, bin, location, sku, qty",
            "location",
        )

        transaction_rows = _fetch_all(
            "inventory_transactions",
            "transaction_type, sku, location, qty",
            "id",
        )

    except Exception as e:

        st.error(
            f"Unable to load stock: {e}"
        )

        return []

    stock: dict[tuple[str, str], dict] = {}

    def _entry(sku: str, location: str) -> dict:

        key = (sku, location)

        if key not in stock:

            stock[key] = {
                "sku": sku,
                "location": location,
                "warehouse": "",
                "tower": "",
                "rack": "",
                "bin": "",
                "qty": 0.0,
            }

        return stock[key]

    # -----------------------------------------------------
    # OPENING STOCK (location_master)
    # -----------------------------------------------------

    for row in location_rows:

        sku = _s(row.get("sku"))
        location = _s(row.get("location"))

        if not sku or not location:
            continue

        entry = _entry(sku, location)

        entry["qty"] += _f(row.get("qty"))

        entry["warehouse"] = (
            entry["warehouse"]
            or _s(row.get("wh_location"))
        )
        entry["tower"] = (
            entry["tower"]
            or _s(row.get("tower"))
        )
        entry["rack"] = (
            entry["rack"]
            or _s(row.get("rack"))
        )
        entry["bin"] = (
            entry["bin"]
            or _s(row.get("bin"))
        )

    # -----------------------------------------------------
    # TRANSACTIONS (IN / OUT)
    # -----------------------------------------------------

    for tx in transaction_rows:

        sku = _s(tx.get("sku"))
        location = _s(tx.get("location"))

        if not sku or not location:
            continue

        transaction_type = _s(
            tx.get("transaction_type")
        ).upper()

        qty = _f(tx.get("qty"))

        entry = _entry(sku, location)

        if transaction_type == "IN":

            entry["qty"] += qty

        elif transaction_type == "OUT":

            entry["qty"] -= qty

    # -----------------------------------------------------
    # FINAL
    # -----------------------------------------------------

    rows = []

    for entry in stock.values():

        entry["qty"] = max(
            0.0,
            entry["qty"],
        )

        rows.append(entry)

    return rows


# =========================================================
# CSS
# =========================================================

def inject_material_check_css() -> None:

    st.markdown(
        """
        <style>

        /* TITLE */

        .mc-title {
            font-size: 1.35rem;
            font-weight: 700;
            color: #111827;
            margin-bottom: 1.2rem;
        }


        /* SUMMARY */

        .mc-summary {
            background: #eff6ff;
            border: 1px solid #bfdbfe;
            border-radius: 10px;
            padding: 0.85rem 1rem;
            margin: 0.5rem 0;
        }

        .mc-summary-label {
            color: #64748b;
            font-size: 0.75rem;
            margin-bottom: 0.2rem;
        }

        .mc-summary-value {
            color: #111827;
            font-size: 1.15rem;
            font-weight: 700;
        }


        /* CARD */

        .mc-card {
            background: #ffffff;
            border: 1px solid #e5e7eb;
            border-radius: 12px;
            padding: 0.9rem 1rem;
            margin: 0.8rem 0;
        }

        .mc-card-head {
            display: flex;
            justify-content: space-between;
            align-items: center;
            gap: 0.8rem;
            padding-bottom: 0.65rem;
            margin-bottom: 0.5rem;
            border-bottom: 1px solid #e5e7eb;
        }

        .mc-card-title {
            color: #111827;
            font-size: 0.95rem;
            font-weight: 700;
            word-break: break-word;
        }

        .mc-card-sub {
            color: #64748b;
            font-size: 0.75rem;
            margin-top: 0.15rem;
        }

        .mc-total {
            background: #f0fdf4;
            border: 1px solid #bbf7d0;
            color: #166534;
            border-radius: 10px;
            padding: 0.35rem 0.8rem;
            font-size: 0.9rem;
            font-weight: 700;
            white-space: nowrap;
        }

        .mc-total-zero {
            background: #fef2f2;
            border: 1px solid #fecaca;
            color: #991b1b;
        }


        /* LOCATION / SKU ROW */

        .mc-row {
            display: flex;
            justify-content: space-between;
            align-items: center;
            gap: 0.8rem;
            padding: 0.6rem 0.2rem;
            border-bottom: 1px dashed #e5e7eb;
        }

        .mc-row:last-child {
            border-bottom: none;
        }

        .mc-row-name {
            color: #111827;
            font-size: 0.86rem;
            font-weight: 700;
            word-break: break-word;
        }

        .mc-row-sub {
            color: #0284c7;
            font-size: 0.74rem;
            font-weight: 600;
            margin-top: 0.15rem;
        }

        .mc-row-extra {
            color: #64748b;
            font-weight: 500;
        }

        .mc-qty {
            background: #dcfce7;
            color: #166534;
            border-radius: 8px;
            padding: 0.25rem 0.7rem;
            font-size: 0.85rem;
            font-weight: 700;
            white-space: nowrap;
        }

        .mc-qty-zero {
            background: #fee2e2;
            color: #991b1b;
        }


        /* LABEL / TAB TEXT (dark theme mein halka dikhta tha) */

        [data-testid="stCheckbox"] label p,
        [data-testid="stCheckbox"] label span {
            color: #111827 !important;
            -webkit-text-fill-color: #111827 !important;
        }

        button[data-baseweb="tab"][aria-selected="false"] p {
            color: #374151 !important;
            -webkit-text-fill-color: #374151 !important;
        }

        </style>
        """,
        unsafe_allow_html=True,
    )


# =========================================================
# CARD BUILDERS
# =========================================================

def _location_extra(entry: dict) -> str:

    parts = []

    if entry.get("tower"):
        parts.append(f"Tower {_e(entry['tower'])}")

    if entry.get("rack"):
        parts.append(f"Rack {_e(entry['rack'])}")

    if entry.get("bin"):
        parts.append(f"Bin {_e(entry['bin'])}")

    if not parts:
        return ""

    return (
        '<span class="mc-row-extra"> · '
        + " · ".join(parts)
        + "</span>"
    )


def _qty_badge(qty: float) -> str:

    cls = "mc-qty"

    if qty <= 0:
        cls += " mc-qty-zero"

    return f'<div class="{cls}">{_fmt_qty(qty)}</div>'


def _sku_card_html(
    sku: str,
    entries: list[dict],
) -> str:

    total = sum(e["qty"] for e in entries)

    entries = sorted(
        entries,
        key=lambda e: (-e["qty"], e["location"]),
    )

    rows_html = ""

    for entry in entries:

        rows_html += f"""
            <div class="mc-row">
                <div>
                    <div class="mc-row-name">
                        📍 {_e(entry["location"])}
                    </div>
                    <div class="mc-row-sub">
                        🏭 {_e(entry["warehouse"]) or "-"}
                        {_location_extra(entry)}
                    </div>
                </div>
                {_qty_badge(entry["qty"])}
            </div>
        """

    total_cls = "mc-total"

    if total <= 0:
        total_cls += " mc-total-zero"

    location_count = len(entries)

    location_label = (
        "location"
        if location_count == 1
        else "locations"
    )

    return f"""
        <div class="mc-card">
            <div class="mc-card-head">
                <div>
                    <div class="mc-card-title">
                        📦 {_e(sku)}
                    </div>
                    <div class="mc-card-sub">
                        {location_count} {location_label}
                    </div>
                </div>
                <div class="{total_cls}">
                    Total: {_fmt_qty(total)}
                </div>
            </div>
            {rows_html}
        </div>
    """


def _location_card_html(
    location: str,
    entries: list[dict],
) -> str:

    total = sum(e["qty"] for e in entries)

    entries = sorted(
        entries,
        key=lambda e: (-e["qty"], e["sku"]),
    )

    warehouse = next(
        (
            e["warehouse"]
            for e in entries
            if e["warehouse"]
        ),
        "",
    )

    rows_html = ""

    for entry in entries:

        rows_html += f"""
            <div class="mc-row">
                <div class="mc-row-name">
                    📦 {_e(entry["sku"])}
                </div>
                {_qty_badge(entry["qty"])}
            </div>
        """

    total_cls = "mc-total"

    if total <= 0:
        total_cls += " mc-total-zero"

    sku_count = len(entries)

    sku_label = (
        "SKU"
        if sku_count == 1
        else "SKUs"
    )

    return f"""
        <div class="mc-card">
            <div class="mc-card-head">
                <div>
                    <div class="mc-card-title">
                        📍 {_e(location)}
                    </div>
                    <div class="mc-card-sub">
                        🏭 {_e(warehouse) or "-"}
                        · {sku_count} {sku_label}
                    </div>
                </div>
                <div class="{total_cls}">
                    Total: {_fmt_qty(total)}
                </div>
            </div>
            {rows_html}
        </div>
    """


# =========================================================
# MAIN PAGE
# =========================================================

def _limit_note(
    total: int,
    limit: int,
    label: str,
    searching: bool,
) -> None:

    if total <= limit:

        st.caption(
            f"Total {total} {label}"
        )

        return

    if searching:

        st.caption(
            f"Top {limit} {label} dikh rahe hain "
            f"(total {total} mile, zyada qty pehle). "
            f"Search aur specific karo."
        )

    else:

        st.caption(
            f"Sabse zyada qty wale top {limit} {label} "
            f"(total {total}). Kuch aur dekhna ho "
            f"to upar search karo."
        )


def render_material_check(
    on_back=None,
) -> None:

    inject_material_check_css()

    # =====================================================
    # TITLE
    # =====================================================

    _html(
        """
        <div class="mc-title">
            🔎 Material Check
        </div>
        """
    )

    # =====================================================
    # BACK BUTTON
    # =====================================================

    if on_back:

        if st.button(
            "⬅ Back To Home",
            key="mc_back",
        ):

            on_back()

            st.rerun()

    st.divider()

    # =====================================================
    # LOAD STOCK
    # =====================================================

    all_rows = _load_stock_rows()

    if not all_rows:

        st.info(
            "No stock data found."
        )

        return

    # =====================================================
    # SEARCH
    # =====================================================

    search = st.text_input(
        "Search SKU or Location",
        placeholder="Search SKU or Location...",
        label_visibility="collapsed",
        key="mc_search",
    )

    search = search.strip().lower()

    # =====================================================
    # FILTERS
    # =====================================================

    f1, f2, f3 = st.columns(
        [3, 2, 1.4]
    )

    warehouses = sorted(
        {
            r["warehouse"]
            for r in all_rows
            if r["warehouse"]
        }
    )

    with f1:

        selected_warehouse = st.selectbox(
            "Warehouse",
            ["All Warehouses"] + warehouses,
            label_visibility="collapsed",
            key="mc_warehouse",
        )

    with f2:

        hide_zero = st.checkbox(
            "Hide zero stock",
            value=True,
            key="mc_hide_zero",
        )

    with f3:

        if st.button(
            "🔄 Refresh",
            use_container_width=True,
            key="mc_refresh",
        ):

            _load_stock_rows.clear()

            st.rerun()

    # =====================================================
    # APPLY FILTERS
    # =====================================================

    rows = all_rows

    if selected_warehouse != "All Warehouses":

        rows = [
            r
            for r in rows
            if r["warehouse"] == selected_warehouse
        ]

    if hide_zero:

        rows = [
            r
            for r in rows
            if r["qty"] > 0
        ]

    if search:

        filtered = []

        for r in rows:

            sku_match = search in r["sku"].lower()
            location_match = search in r["location"].lower()

            if sku_match or location_match:
                filtered.append(r)

        rows = filtered

    if not rows:

        st.info(
            "Koi stock nahi mila. Search ya filter change karo."
        )

        return

    # =====================================================
    # SUMMARY
    # =====================================================

    unique_skus = {r["sku"] for r in rows}
    unique_locations = {r["location"] for r in rows}
    total_units = sum(r["qty"] for r in rows)

    s1, s2, s3 = st.columns(3)

    with s1:

        _html(
            f"""
            <div class="mc-summary">
                <div class="mc-summary-label">SKUs</div>
                <div class="mc-summary-value">
                    {len(unique_skus)}
                </div>
            </div>
            """
        )

    with s2:

        _html(
            f"""
            <div class="mc-summary">
                <div class="mc-summary-label">Locations</div>
                <div class="mc-summary-value">
                    {len(unique_locations)}
                </div>
            </div>
            """
        )

    with s3:

        _html(
            f"""
            <div class="mc-summary">
                <div class="mc-summary-label">Total Units</div>
                <div class="mc-summary-value">
                    {_fmt_qty(total_units)}
                </div>
            </div>
            """
        )

    # =====================================================
    # TABS
    # =====================================================

    tab_sku, tab_location = st.tabs(
        [
            "📦 By SKU",
            "📍 By Location",
        ]
    )

    # -----------------------------------------------------
    # BY SKU
    # -----------------------------------------------------

    with tab_sku:

        by_sku: dict[str, list[dict]] = {}

        for r in rows:
            by_sku.setdefault(r["sku"], []).append(r)

        # sabse zyada total qty wali SKU pehle
        sku_keys = sorted(
            by_sku.keys(),
            key=lambda k: (
                -sum(e["qty"] for e in by_sku[k]),
                k,
            ),
        )

        limit = TOP_SEARCH if search else TOP_DEFAULT

        _limit_note(
            len(sku_keys),
            limit,
            "SKUs",
            bool(search),
        )

        for sku in sku_keys[:limit]:

            _html(
                _sku_card_html(
                    sku,
                    by_sku[sku],
                )
            )

    # -----------------------------------------------------
    # BY LOCATION
    # -----------------------------------------------------

    with tab_location:

        by_location: dict[str, list[dict]] = {}

        for r in rows:
            by_location.setdefault(r["location"], []).append(r)

        # sabse zyada total qty wali location pehle
        location_keys = sorted(
            by_location.keys(),
            key=lambda k: (
                -sum(e["qty"] for e in by_location[k]),
                k,
            ),
        )

        limit = TOP_SEARCH if search else TOP_DEFAULT

        _limit_note(
            len(location_keys),
            limit,
            "locations",
            bool(search),
        )

        for location in location_keys[:limit]:

            _html(
                _location_card_html(
                    location,
                    by_location[location],
                )
            )
