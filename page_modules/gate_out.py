"""
page_modules/gate_out.py

EMIZA WMS — Gate Out

Flow:

Gate Out
   ↓
Select Sales Order
   ↓
ALL SKUs of selected Sales Order shown together
   ↓
Ordered / Already Gate Out / Pending / Available Stock
   ↓
Allocate SKU
   ↓
Assigned Locations
   ↓
Warehouse + Location + Current Stock
   ↓
Gate Out Quantity
   ↓
Add
   ↓
Gate Out Review
   ↓
Save Gate Out
   ↓
inventory_transactions → OUT
   ↓
Accounts Email Automatically

IMPORTANT:
- Sales Order does NOT change stock
- Gate Out inserts OUT transaction only
- location_master.qty is never modified
- Location must already be assigned to SKU
- Gate Out Qty cannot exceed pending quantity
- Gate Out Qty cannot exceed location available stock
- Multiple locations can be used for same SKU
- Multiple warehouses are supported through location_master.wh_location
- No st.fragment
"""

from __future__ import annotations

import html

import streamlit as st

from auth import get_client
from page_modules.email_service import send_gate_out_email

PAGE_SIZE = 1000
TOP_LIST = 20


# =========================================================
# HELPERS
# =========================================================

def _s(value) -> str:
    return str(value or "").strip()


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
    Render HTML safely.
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
# SESSION STATE
# =========================================================

def _init_state() -> None:

    defaults = {
        "gate_out_active_order": None,
        "gate_out_items": [],
        "gate_out_success": False,
        "gate_out_error": "",
        "gate_out_email_sent": False,
        "gate_out_email_error": "",
    }

    for key, value in defaults.items():

        if key not in st.session_state:
            st.session_state[key] = value


# =========================================================
# RESET
# =========================================================

def _reset_form() -> None:

    keys = [
        "gate_out_active_order",
        "gate_out_items",
        "gate_out_success",
        "gate_out_error",
        "gate_out_email_sent",
        "gate_out_email_error",
    ]

    for key in keys:

        st.session_state.pop(
            key,
            None,
        )

    _init_state()


# =========================================================
# LOAD SALES ORDERS
# =========================================================

@st.cache_data(
    ttl=30,
    show_spinner=False,
)
def _load_sales_orders() -> list[dict]:

    client = get_client()

    try:

        response = (
            client
            .table("sales_orders")
            .select(
                """
                id,
                order_id,
                warehouse,
                existing_customer,
                customer_name,
                email,
                phone,
                alternate_phone,
                remark,
                order_type,

                billing_address_1,
                billing_address_2,
                billing_pincode,
                billing_state,
                billing_city,

                shipping_name,
                shipping_phone,
                shipping_address_1,
                shipping_address_2,
                shipping_pincode,
                shipping_state,
                shipping_city,

                same_as_billing,

                status,
                created_at
                """
            )
            .order(
                "created_at",
                desc=True,
            )
            .execute()
        )

        return response.data or []

    except Exception:

        return []


# =========================================================
# LOAD SALES ORDER ITEMS
# =========================================================

@st.cache_data(
    ttl=30,
    show_spinner=False,
)
def _load_sales_order_items(
    sales_order_id: int,
) -> list[dict]:

    client = get_client()

    try:

        response = (
            client
            .table("sales_order_items")
            .select(
                """
                id,
                sales_order_id,
                sku_code,
                quantity,
                shelf_life_type,
                mrp,
                selling_price,
                discount_amount,
                is_non_sellable,
                zone
                """
            )
            .eq(
                "sales_order_id",
                sales_order_id,
            )
            .execute()
        )

        return response.data or []

    except Exception as e:

        st.error(
            f"Unable to load Sales Order Items: {e}"
        )

        return []


# =========================================================
# LOAD LOCATIONS FOR SKU
# =========================================================

@st.cache_data(
    ttl=30,
    show_spinner=False,
)
def _load_sku_locations(
    sku_code: str,
) -> list[dict]:

    client = get_client()

    try:

        response = (
            client
            .table("location_master")
            .select(
                """
                wh_location,
                tower,
                rack,
                bin,
                location,
                sku,
                qty
                """
            )
            .eq(
                "sku",
                sku_code,
            )
            .execute()
        )

        return response.data or []

    except Exception as e:

        st.error(
            f"Unable to load locations for {sku_code}: {e}"
        )

        return []


# =========================================================
# LOAD TRANSACTIONS FOR SKU
# =========================================================

@st.cache_data(
    ttl=30,
    show_spinner=False,
)
def _load_sku_transactions(
    sku_code: str,
) -> list[dict]:

    client = get_client()

    try:

        response = (
            client
            .table("inventory_transactions")
            .select(
                """
                id,
                transaction_type,
                po_number,
                sku,
                location,
                qty,
                created_at
                """
            )
            .eq(
                "sku",
                sku_code,
            )
            .execute()
        )

        return response.data or []

    except Exception as e:

        st.error(
            f"Unable to load transactions for {sku_code}: {e}"
        )

        return []


# =========================================================
# ORDERED QTY
# =========================================================

def _get_ordered_qty(
    items: list[dict],
    sku_code: str,
) -> float:

    total = 0.0

    for item in items:

        if _s(item.get("sku_code")) == sku_code:

            total += _f(
                item.get("quantity")
            )

    return total


# =========================================================
# ALREADY GATE OUT
# =========================================================

def _get_already_gate_out_qty(
    transactions: list[dict],
    order_id: str,
    sku_code: str,
) -> float:

    total = 0.0

    for tx in transactions:

        transaction_type = _s(
            tx.get("transaction_type")
        ).upper()

        tx_order = _s(
            tx.get("po_number")
        )

        tx_sku = _s(
            tx.get("sku")
        )

        if (
            transaction_type == "OUT"
            and tx_order == order_id
            and tx_sku == sku_code
        ):

            total += _f(
                tx.get("qty")
            )

    return total


# =========================================================
# LOCATION CURRENT STOCK
# =========================================================

def _get_location_stock(
    location: str,
    location_data: list[dict],
    transactions: list[dict],
) -> float:

    location = _s(location)

    # =====================================================
    # OPENING STOCK
    # =====================================================

    opening_qty = 0.0

    for row in location_data:

        if _s(row.get("location")) == location:

            opening_qty += _f(
                row.get("qty")
            )

    # =====================================================
    # TRANSACTION STOCK
    # =====================================================

    transaction_qty = 0.0

    for tx in transactions:

        if _s(tx.get("location")) != location:
            continue

        transaction_type = _s(
            tx.get("transaction_type")
        ).upper()

        qty = _f(
            tx.get("qty")
        )

        if transaction_type == "IN":

            transaction_qty += qty

        elif transaction_type == "OUT":

            transaction_qty -= qty

    current_stock = (
        opening_qty
        + transaction_qty
    )

    return max(
        0.0,
        current_stock,
    )


# =========================================================
# TOTAL CURRENT STOCK
# =========================================================

def _get_total_stock(
    location_data: list[dict],
    transactions: list[dict],
) -> float:

    locations = set()

    for row in location_data:

        location = _s(
            row.get("location")
        )

        if location:

            locations.add(
                location
            )

    for tx in transactions:

        location = _s(
            tx.get("location")
        )

        if location:

            locations.add(
                location
            )

    total = 0.0

    for location in locations:

        total += _get_location_stock(
            location,
            location_data,
            transactions,
        )

    return total


# =========================================================
# CURRENT FORM OUT FOR SKU
# =========================================================

def _get_form_out_qty(
    order_id: str,
    sku_code: str,
) -> float:

    total = 0.0

    for item in st.session_state.gate_out_items:

        if (
            item["order_id"] == order_id
            and item["sku_code"] == sku_code
        ):

            total += _f(
                item["qty"]
            )

    return total


# =========================================================
# CURRENT FORM OUT FOR LOCATION
# =========================================================

def _get_form_location_qty(
    order_id: str,
    sku_code: str,
    location: str,
) -> float:

    total = 0.0

    for item in st.session_state.gate_out_items:

        if (
            item["order_id"] == order_id
            and item["sku_code"] == sku_code
            and item["location"] == location
        ):

            total += _f(
                item["qty"]
            )

    return total


# =========================================================
# ADD GATE OUT ITEM
# =========================================================

def _add_gate_out_item(
    order_id: str,
    sku_code: str,
    location: str,
    qty: float,
    available_location_stock: float,
    pending_qty: float,
    warehouse: str = "",
) -> bool:

    if not order_id:

        st.session_state.gate_out_error = (
            "Please select a Sales Order."
        )

        return False

    if not sku_code:

        st.session_state.gate_out_error = (
            "Please select a SKU."
        )

        return False

    if not location:

        st.session_state.gate_out_error = (
            "Please select a Location."
        )

        return False

    if qty <= 0:

        st.session_state.gate_out_error = (
            "Gate Out quantity must be greater than 0."
        )

        return False

    if qty > available_location_stock:

        st.session_state.gate_out_error = (
            f"Only {_fmt_qty(available_location_stock)} "
            f"units are available at {location}."
        )

        return False

    remaining_pending = pending_qty

    if qty > remaining_pending:

        st.session_state.gate_out_error = (
            f"Only {_fmt_qty(remaining_pending)} "
            f"units are pending for {sku_code}."
        )

        return False

    # =====================================================
    # ADD ITEM
    # =====================================================

    st.session_state.gate_out_items.append(
        {
            "order_id": order_id,
            "sku_code": sku_code,
            "location": location,
            "warehouse": warehouse,
            "qty": qty,
        }
    )

    st.session_state.gate_out_error = ""

    return True


# =========================================================
# SAVE GATE OUT
# =========================================================

def _save_gate_out(
    items: list[dict],
) -> tuple[bool, str | None]:

    if not items:

        return (
            False,
            "Please add at least one Gate Out item.",
        )

    client = get_client()

    try:

        # =================================================
        # UNIQUE SKUS
        # =================================================

        unique_skus = list(
            dict.fromkeys(
                item["sku_code"]
                for item in items
            )
        )

        # =================================================
        # FRESH DATA
        # =================================================

        fresh_transactions = {}
        fresh_locations = {}

        for sku_code in unique_skus:

            tx_response = (
                client
                .table(
                    "inventory_transactions"
                )
                .select(
                    """
                    id,
                    transaction_type,
                    po_number,
                    sku,
                    location,
                    qty
                    """
                )
                .eq(
                    "sku",
                    sku_code,
                )
                .execute()
            )

            fresh_transactions[sku_code] = (
                tx_response.data or []
            )

            loc_response = (
                client
                .table(
                    "location_master"
                )
                .select(
                    """
                    wh_location,
                    location,
                    sku,
                    qty
                    """
                )
                .eq(
                    "sku",
                    sku_code,
                )
                .execute()
            )

            fresh_locations[sku_code] = (
                loc_response.data or []
            )

        # =================================================
        # UNIQUE ORDER + SKU PAIRS
        # =================================================

        order_sku_pairs = list(
            dict.fromkeys(
                (
                    item["order_id"],
                    item["sku_code"],
                )
                for item in items
            )
        )

        # =================================================
        # VALIDATE EVERY ORDER / SKU
        # =================================================

        for order_id, sku_code in order_sku_pairs:

            sku_items = [
                item
                for item in items
                if (
                    item["order_id"] == order_id
                    and item["sku_code"] == sku_code
                )
            ]

            # ---------------------------------------------
            # FIND SALES ORDER
            # ---------------------------------------------

            order_response = (
                client
                .table(
                    "sales_orders"
                )
                .select(
                    "id"
                )
                .eq(
                    "order_id",
                    order_id,
                )
                .single()
                .execute()
            )

            if not order_response.data:

                return (
                    False,
                    f"Sales Order {order_id} not found.",
                )

            sales_order_db_id = (
                order_response.data["id"]
            )

            # ---------------------------------------------
            # ORDERED QTY
            # ---------------------------------------------

            item_response = (
                client
                .table(
                    "sales_order_items"
                )
                .select(
                    "quantity"
                )
                .eq(
                    "sales_order_id",
                    sales_order_db_id,
                )
                .eq(
                    "sku_code",
                    sku_code,
                )
                .execute()
            )

            ordered_qty = sum(
                _f(
                    row.get("quantity")
                )
                for row in (
                    item_response.data or []
                )
            )

            # ---------------------------------------------
            # ALREADY OUT
            # ---------------------------------------------

            already_out = (
                _get_already_gate_out_qty(
                    fresh_transactions[
                        sku_code
                    ],
                    order_id,
                    sku_code,
                )
            )

            # ---------------------------------------------
            # REQUESTED NOW
            # ---------------------------------------------

            requested_qty = sum(
                _f(
                    item["qty"]
                )
                for item in sku_items
            )

            # ---------------------------------------------
            # PENDING
            # ---------------------------------------------

            pending_qty = (
                ordered_qty
                - already_out
            )

            # ---------------------------------------------
            # PENDING VALIDATION
            # ---------------------------------------------

            if requested_qty > pending_qty:

                return (
                    False,
                    (
                        f"{order_id} / {sku_code}: "
                        f"only "
                        f"{_fmt_qty(pending_qty)} "
                        f"units are pending, "
                        f"but "
                        f"{_fmt_qty(requested_qty)} "
                        f"were requested."
                    ),
                )

            # ---------------------------------------------
            # ASSIGNED LOCATIONS
            # ---------------------------------------------

            assigned_locations = {
                _s(
                    row.get("location")
                )
                for row in fresh_locations[
                    sku_code
                ]
                if _s(
                    row.get("location")
                )
            }

            # ---------------------------------------------
            # LOCATION ASSIGNMENT VALIDATION
            # ---------------------------------------------

            for item in sku_items:

                location = _s(
                    item["location"]
                )

                if location not in assigned_locations:

                    return (
                        False,
                        (
                            f"{location} is not assigned "
                            f"to SKU {sku_code}."
                        ),
                    )

            # ---------------------------------------------
            # LOCATION STOCK VALIDATION
            # ---------------------------------------------

            location_data = (
                fresh_locations[
                    sku_code
                ]
            )

            transaction_data = (
                fresh_transactions[
                    sku_code
                ]
            )

            unique_locations = list(
                dict.fromkeys(
                    item["location"]
                    for item in sku_items
                )
            )

            for location in unique_locations:

                requested_at_location = sum(
                    _f(
                        item["qty"]
                    )
                    for item in sku_items
                    if item["location"]
                    == location
                )

                available_stock = (
                    _get_location_stock(
                        location,
                        location_data,
                        transaction_data,
                    )
                )

                if (
                    requested_at_location
                    > available_stock
                ):

                    return (
                        False,
                        (
                            f"{sku_code} at "
                            f"{location}: only "
                            f"{_fmt_qty(available_stock)} "
                            f"units available, "
                            f"but "
                            f"{_fmt_qty(requested_at_location)} "
                            f"requested."
                        ),
                    )

        # =================================================
        # PREPARE OUT TRANSACTIONS
        # =================================================

        rows = []

        for item in items:

            rows.append(
                {
                    "transaction_type": "OUT",
                    "po_number": item["order_id"],
                    "sku": item["sku_code"],
                    "location": item["location"],
                    "qty": item["qty"],
                }
            )

        # =================================================
        # BULK INSERT
        # =================================================

        client.table(
            "inventory_transactions"
        ).insert(
            rows
        ).execute()

        # =================================================
        # CLEAR CACHE
        # =================================================

        _load_sales_orders.clear()
        _load_sales_order_items.clear()
        _load_sku_locations.clear()
        _load_sku_transactions.clear()
        _load_all_order_items.clear()
        _load_out_totals.clear()

        return (
            True,
            None,
        )

    except Exception as e:

        return (
            False,
            str(e),
        )


# =========================================================
# CSS
# =========================================================

def inject_gate_out_css() -> None:

    st.markdown(
        """
        <style>

        .go-title {
            font-size: 1.35rem;
            font-weight: 700;
            color: #111827;
            margin-bottom: 1.2rem;
        }

        .go-section {
            font-size: 0.82rem;
            font-weight: 700;
            color: #64748b;
            letter-spacing: 0.08em;
            text-transform: uppercase;
            padding-bottom: 0.55rem;
            border-bottom: 1px solid #e5e7eb;
            margin-bottom: 1rem;
        }

        .go-info {
            background: #eff6ff;
            border: 1px solid #bfdbfe;
            border-radius: 10px;
            padding: 0.85rem 1rem;
            margin: 0.5rem 0;
        }

        .go-info-label {
            color: #64748b;
            font-size: 0.75rem;
            margin-bottom: 0.2rem;
        }

        .go-info-value {
            color: #111827;
            font-size: 1rem;
            font-weight: 700;
        }

        .go-stock {
            background: #f0fdf4;
            border: 1px solid #bbf7d0;
            border-radius: 10px;
            padding: 0.85rem 1rem;
            color: #166534;
            font-weight: 600;
            margin: 0.5rem 0;
        }

        .go-pending {
            background: #fff7ed;
            border: 1px solid #fed7aa;
            border-radius: 10px;
            padding: 0.85rem 1rem;
            color: #9a3412;
            font-weight: 600;
            margin: 0.5rem 0;
        }

        .go-sku-card {
            background: #ffffff;
            border: 1px solid #e5e7eb;
            border-radius: 10px;
            padding: 0.9rem 1rem;
            margin-top: 1rem;
            margin-bottom: 0.7rem;
        }

        .go-sku-code {
            color: #111827;
            font-size: 0.95rem;
            font-weight: 700;
        }

        .go-location-card {
            background: #ffffff;
            border: 1px solid #e5e7eb;
            border-radius: 10px;
            padding: 0.9rem 1rem;
            margin: 0.5rem 0;
        }

        .go-location-name {
            color: #111827;
            font-size: 0.88rem;
            font-weight: 700;
        }

        .go-location-warehouse {
            color: #0284c7;
            font-size: 0.75rem;
            font-weight: 600;
            margin-top: 0.2rem;
        }

        .go-location-stock {
            color: #166534;
            font-size: 0.85rem;
            font-weight: 700;
        }

        .go-review {
            background: #ffffff;
            border: 1px solid #e5e7eb;
            border-radius: 8px;
            padding: 0.75rem 1rem;
            margin-bottom: 0.5rem;
        }

        .go-review-label {
            color: #64748b;
            font-size: 0.72rem;
            text-transform: uppercase;
            letter-spacing: 0.04em;
        }

        .go-review-value {
            color: #111827;
            font-size: 0.9rem;
            font-weight: 700;
        }

        .go-dispatched {
            background: #ecfdf5;
            border: 1px solid #bbf7d0;
            border-radius: 10px;
            padding: 0.8rem 1rem;
            color: #166534;
            font-weight: 600;
            margin: 0.6rem 0;
        }

        .go-divider {
            height: 1px;
            background: #e5e7eb;
            margin: 1.2rem 0;
        }

        .gl-head {
            font-size: 0.76rem;
            font-weight: 700;
            color: #374151;
        }

        .gl-order {
            color: #0284c7;
            font-size: 0.86rem;
            font-weight: 700;
            word-break: break-word;
        }

        .gl-cell {
            color: #374151;
            font-size: 0.82rem;
            line-height: 1.4;
            word-break: break-word;
        }

        .gl-num {
            color: #111827;
            font-size: 0.88rem;
            font-weight: 700;
        }

        .gl-badge {
            display: inline-block;
            padding: 4px 9px;
            border-radius: 15px;
            font-size: 0.7rem;
            font-weight: 600;
            white-space: nowrap;
        }

        .gl-badge-pending {
            background: #ffedd5;
            color: #9a3412;
        }

        .gl-badge-partial {
            background: #dbeafe;
            color: #1e40af;
        }

        .gl-badge-dispatched {
            background: #dcfce7;
            color: #166534;
        }

        .gl-sep {
            border-bottom: 1px solid #e5e7eb;
            margin: 0.2rem 0 0.4rem 0;
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
# LOAD ALL ORDER ITEMS
# =========================================================

@st.cache_data(
    ttl=30,
    show_spinner=False,
)
def _load_all_order_items() -> dict:

    client = get_client()

    grouped: dict = {}

    start = 0

    while True:

        response = (
            client
            .table("sales_order_items")
            .select(
                "id,sales_order_id,sku_code,quantity"
            )
            .order("id")
            .range(
                start,
                start + PAGE_SIZE - 1,
            )
            .execute()
        )

        data = response.data or []

        for row in data:

            grouped.setdefault(
                row["sales_order_id"],
                [],
            ).append(row)

        if len(data) < PAGE_SIZE:
            break

        start += PAGE_SIZE

    return grouped


# =========================================================
# LOAD ALL GATE OUT TOTALS
# =========================================================

@st.cache_data(
    ttl=30,
    show_spinner=False,
)
def _load_out_totals() -> dict:

    client = get_client()

    totals: dict = {}

    start = 0

    while True:

        response = (
            client
            .table("inventory_transactions")
            .select(
                "po_number,sku,qty"
            )
            .eq(
                "transaction_type",
                "OUT",
            )
            .order("id")
            .range(
                start,
                start + PAGE_SIZE - 1,
            )
            .execute()
        )

        data = response.data or []

        for row in data:

            key = (
                _s(row.get("po_number")),
                _s(row.get("sku")),
            )

            totals[key] = (
                totals.get(key, 0.0)
                + _f(row.get("qty"))
            )

        if len(data) < PAGE_SIZE:
            break

        start += PAGE_SIZE

    return totals


# =========================================================
# ORDER SUMMARY
# =========================================================

def _order_summary(
    order: dict,
    items: list[dict],
    out_totals: dict,
) -> dict:

    order_id = _s(
        order.get("order_id")
    )

    ordered_by_sku: dict[str, float] = {}

    for item in items:

        sku = _s(
            item.get("sku_code")
        )

        if not sku:
            continue

        ordered_by_sku[sku] = (
            ordered_by_sku.get(
                sku,
                0.0,
            )
            + _f(
                item.get("quantity")
            )
        )

    ordered = 0.0
    dispatched = 0.0
    pending = 0.0

    for sku, ordered_qty in ordered_by_sku.items():

        out_qty = out_totals.get(
            (
                order_id,
                sku,
            ),
            0.0,
        )

        ordered += ordered_qty

        dispatched += min(
            out_qty,
            ordered_qty,
        )

        pending += max(
            ordered_qty - out_qty,
            0.0,
        )

    if ordered > 0 and pending <= 0:

        status = "DISPATCHED"

    elif dispatched > 0:

        status = "PARTIAL"

    else:

        status = "PENDING"

    return {
        "order_id": order_id,
        "customer": _s(
            order.get("customer_name")
        ),
        "phone": _s(
            order.get("phone")
        ),
        "warehouse": _s(
            order.get("warehouse")
        ),
        "sku_count": len(
            ordered_by_sku
        ),
        "ordered": ordered,
        "dispatched": dispatched,
        "pending": pending,
        "status": status,
    }


# =========================================================
# ORDER LIST VIEW
# =========================================================

_LIST_COLS = [
    1.4,
    2.0,
    1.2,
    0.9,
    0.9,
    0.9,
    1.3,
    1.0,
]


def _render_order_rows(
    rows: list[dict],
    tab_key: str,
) -> None:

    if not rows:

        st.info(
            "Koi Sales Order nahi mila."
        )

        return

    shown = rows[:TOP_LIST]

    header = st.columns(
        _LIST_COLS
    )

    for col, label in zip(
        header,
        [
            "Order ID",
            "Customer",
            "Warehouse",
            "SKUs",
            "Ordered",
            "Pending",
            "Status",
            "Action",
        ],
    ):

        col.markdown(
            f'<div class="gl-head">{label}</div>',
            unsafe_allow_html=True,
        )

    for r in shown:

        c = st.columns(
            _LIST_COLS
        )

        c[0].markdown(
            f'<div class="gl-order">'
            f'{html.escape(r["order_id"])}'
            f'</div>',
            unsafe_allow_html=True,
        )

        c[1].markdown(
            f'<div class="gl-cell">'
            f'{html.escape(r["customer"]) or "-"}'
            f'<br>'
            f'<span style="color:#64748b;'
            f'font-size:0.75rem;">'
            f'{html.escape(r["phone"])}'
            f'</span>'
            f'</div>',
            unsafe_allow_html=True,
        )

        c[2].markdown(
            f'<div class="gl-cell">'
            f'{html.escape(r["warehouse"]) or "-"}'
            f'</div>',
            unsafe_allow_html=True,
        )

        c[3].markdown(
            f'<div class="gl-num">'
            f'{r["sku_count"]}'
            f'</div>',
            unsafe_allow_html=True,
        )

        c[4].markdown(
            f'<div class="gl-num">'
            f'{_fmt_qty(r["ordered"])}'
            f'</div>',
            unsafe_allow_html=True,
        )

        c[5].markdown(
            f'<div class="gl-num">'
            f'{_fmt_qty(r["pending"])}'
            f'</div>',
            unsafe_allow_html=True,
        )

        c[6].markdown(
            f'<span class="gl-badge '
            f'gl-badge-{r["status"].lower()}">'
            f'{r["status"]}'
            f'</span>',
            unsafe_allow_html=True,
        )

        with c[7]:

            label = (
                "View"
                if r["status"] == "DISPATCHED"
                else "Open ▶"
            )

            if st.button(
                label,
                key=(
                    f"go_open_"
                    f"{tab_key}_"
                    f"{r['order_id']}"
                ),
                use_container_width=True,
            ):

                st.session_state.gate_out_active_order = (
                    r["order_id"]
                )

                st.rerun()

        st.markdown(
            '<div class="gl-sep"></div>',
            unsafe_allow_html=True,
        )

    if len(rows) > TOP_LIST:

        st.caption(
            f"Pehle {TOP_LIST} orders dikh rahe hain "
            f"(total {len(rows)}). "
            f"Baaki dekhne ke liye upar search karo."
        )


def _render_order_list(
    orders: list[dict],
) -> None:

    _html(
        """
        <div class="go-section">
            📋 SALES ORDERS
        </div>
        """
    )

    try:

        items_by_order = (
            _load_all_order_items()
        )

        out_totals = (
            _load_out_totals()
        )

    except Exception as e:

        st.error(
            f"❌ Order data load nahi hua: {e}"
        )

        items_by_order = {}
        out_totals = {}

    search = st.text_input(
        "Search Sales Order",
        placeholder=(
            "Search Order ID, Customer, Phone or Warehouse..."
        ),
        label_visibility="collapsed",
        key="gate_out_search",
    ).strip().lower()

    summaries = []

    for order in orders:

        if not _s(
                order.get("order_id")
        ):
            continue

            # CANCELLED Sales Orders should not appear in Gate Out
        if _s(
                order.get("status")
        ).upper() == "CANCELLED":
            continue

        summary = _order_summary(
            order,
            items_by_order.get(
                order["id"],
                [],
            ),
            out_totals,
        )

        if search:

            searchable = " ".join(
                [
                    summary["order_id"],
                    summary["customer"],
                    summary["phone"],
                    summary["warehouse"],
                ]
            ).lower()

            if search not in searchable:
                continue

        summaries.append(
            summary
        )

    pending_rows = [
        s
        for s in summaries
        if s["status"] != "DISPATCHED"
    ]

    done_rows = [
        s
        for s in summaries
        if s["status"] == "DISPATCHED"
    ]

    tab_pending, tab_done = st.tabs(
        [
            f"⏳ Pending ({len(pending_rows)})",
            f"✅ Dispatched ({len(done_rows)})",
        ]
    )

    with tab_pending:

        _render_order_rows(
            pending_rows,
            "pending",
        )

    with tab_done:

        _render_order_rows(
            done_rows,
            "done",
        )


# =========================================================
# ORDER DETAIL VIEW
# =========================================================

def _render_order_detail(
    selected_order: dict,
    selected_order_id: str,
) -> None:

    # =====================================================
    # BACK TO ORDER LIST
    # =====================================================

    if st.button(
        "⬅ Back To Order List",
        key="go_back_list",
    ):

        st.session_state.gate_out_active_order = None

        st.rerun()

    # =====================================================
    # ORDER HEADER
    # =====================================================

    c1, c2, c3 = st.columns(3)

    with c1:

        _html(
            f"""
            <div class="go-info">
                <div class="go-info-label">
                    Order ID
                </div>

                <div class="go-info-value">
                    {_s(selected_order.get("order_id"))}
                </div>
            </div>
            """
        )

    with c2:

        _html(
            f"""
            <div class="go-info">
                <div class="go-info-label">
                    Customer
                </div>

                <div class="go-info-value">
                    {_s(selected_order.get("customer_name"))}
                </div>
            </div>
            """
        )

    with c3:

        _html(
            f"""
            <div class="go-info">
                <div class="go-info-label">
                    Warehouse
                </div>

                <div class="go-info-value">
                    {_s(selected_order.get("warehouse"))}
                </div>
            </div>
            """
        )

    # =====================================================
    # LOAD ALL ORDER ITEMS
    # =====================================================

    sales_order_db_id = selected_order["id"]

    order_items = _load_sales_order_items(
        sales_order_db_id
    )

    if not order_items:

        st.warning(
            "No SKU items found in this Sales Order."
        )

        return

    # =====================================================
    # UNIQUE SKU LIST
    # =====================================================

    sku_list = list(
        dict.fromkeys(
            _s(
                item.get("sku_code")
            )
            for item in order_items
            if _s(
                item.get("sku_code")
            )
        )
    )

    # =====================================================
    # ORDER SKUS
    # =====================================================

    _html(
        """
        <div class="go-section"
             style="margin-top:1.5rem;">
            📦 ORDER SKUs
        </div>
        """
    )

    # =====================================================
    # PROCESS ALL SKUS
    # =====================================================

    for sku_index, sku_code in enumerate(
        sku_list
    ):

        location_data = _load_sku_locations(
            sku_code
        )

        transaction_data = _load_sku_transactions(
            sku_code
        )

        ordered_qty = _get_ordered_qty(
            order_items,
            sku_code,
        )

        already_out = (
            _get_already_gate_out_qty(
                transaction_data,
                selected_order_id,
                sku_code,
            )
        )

        current_form_out = (
            _get_form_out_qty(
                selected_order_id,
                sku_code,
            )
        )

        pending_qty = max(
            0.0,
            ordered_qty
            - already_out
            - current_form_out,
        )

        total_stock = _get_total_stock(
            location_data,
            transaction_data,
        )

        _html(
            f"""
            <div class="go-sku-card">
                <div class="go-sku-code">
                    📦 {html.escape(sku_code)}
                </div>
            </div>
            """
        )

        # =================================================
        # SUMMARY CARDS
        # =================================================

        c1, c2, c3, c4 = st.columns(4)

        with c1:

            _html(
                f"""
                <div class="go-info">
                    <div class="go-info-label">
                        Ordered
                    </div>

                    <div class="go-info-value">
                        {_fmt_qty(ordered_qty)}
                    </div>
                </div>
                """
            )

        with c2:

            _html(
                f"""
                <div class="go-info">
                    <div class="go-info-label">
                        Already Gate Out
                    </div>

                    <div class="go-info-value">
                        {_fmt_qty(already_out)}
                    </div>
                </div>
                """
            )

        with c3:

            _html(
                f"""
                <div class="go-pending">
                    <div style="font-size:0.72rem;">
                        PENDING
                    </div>

                    <div style="
                        font-size:1rem;
                        margin-top:0.15rem;
                    ">
                        {_fmt_qty(pending_qty)}
                    </div>
                </div>
                """
            )

        with c4:

            _html(
                f"""
                <div class="go-stock">
                    <div style="font-size:0.72rem;">
                        AVAILABLE STOCK
                    </div>

                    <div style="
                        font-size:1rem;
                        margin-top:0.15rem;
                    ">
                        {_fmt_qty(total_stock)}
                    </div>
                </div>
                """
            )

        # =================================================
        # FULLY DISPATCHED
        # =================================================

        if pending_qty <= 0:

            _html(
                f"""
                <div class="go-dispatched">
                    ✅ {html.escape(sku_code)}
                    is fully dispatched.
                </div>
                """
            )

            continue

        # =================================================
        # NO STOCK
        # =================================================

        if total_stock <= 0:

            st.warning(
                f"⚠️ No available stock for {sku_code}."
            )

            continue

        # =================================================
        # ASSIGNED LOCATIONS
        # =================================================

        assigned_location_rows = []

        seen_locations = set()

        for row in location_data:

            location = _s(
                row.get("location")
            )

            if not location:
                continue

            if location in seen_locations:
                continue

            seen_locations.add(
                location
            )

            assigned_location_rows.append(
                row
            )

        if not assigned_location_rows:

            st.warning(
                f"No location is assigned to {sku_code}."
            )

            continue

        # =================================================
        # ALLOCATION
        # =================================================

        with st.expander(
            f"📍 Allocate {sku_code}",
            expanded=True,
        ):

            _html(
                """
                <div style="
                    font-size:0.9rem;
                    font-weight:700;
                    color:#374151;
                    margin-bottom:0.7rem;
                ">
                    Assigned Locations
                </div>
                """
            )

            # =============================================
            # FULLY ALLOCATE
            # =============================================

            if st.button(
                f"⚡ Fully Allocate ({_fmt_qty(pending_qty)})",
                type="primary",
                key=(
                    f"go_full_"
                    f"{selected_order_id}_"
                    f"{sku_code}"
                ),
            ):

                remaining = max(
                    0.0,
                    ordered_qty
                    - already_out
                    - _get_form_out_qty(
                        selected_order_id,
                        sku_code,
                    ),
                )

                allocated_any = False

                for alloc_row in assigned_location_rows:

                    if remaining <= 0:
                        break

                    alloc_location = _s(
                        alloc_row.get("location")
                    )

                    alloc_warehouse = _s(
                        alloc_row.get("wh_location")
                    )

                    if not alloc_warehouse:

                        alloc_warehouse = _s(
                            selected_order.get(
                                "warehouse"
                            )
                        )

                    alloc_stock = _get_location_stock(
                        alloc_location,
                        location_data,
                        transaction_data,
                    )

                    alloc_available = max(
                        0.0,
                        alloc_stock
                        - _get_form_location_qty(
                            selected_order_id,
                            sku_code,
                            alloc_location,
                        ),
                    )

                    take = min(
                        remaining,
                        alloc_available,
                    )

                    if take <= 0:
                        continue

                    if _add_gate_out_item(
                        selected_order_id,
                        sku_code,
                        alloc_location,
                        take,
                        alloc_available,
                        remaining,
                        warehouse=alloc_warehouse,
                    ):

                        remaining -= take
                        allocated_any = True

                if allocated_any:

                    if remaining > 0:

                        st.session_state.gate_out_error = (
                            f"{sku_code}: stock kam tha, "
                            f"{_fmt_qty(remaining)} units "
                            f"abhi bhi pending hain."
                        )

                    st.session_state.gate_out_clear_prefixes = [
                        f"go_qty_{selected_order_id}_{sku_code}_"
                    ]

                    st.rerun()

            # =============================================
            # LOCATION ROWS
            # =============================================

            for location_index, location_row in enumerate(
                assigned_location_rows
            ):

                location = _s(
                    location_row.get("location")
                )

                warehouse = _s(
                    location_row.get(
                        "wh_location"
                    )
                )

                if not warehouse:

                    warehouse = _s(
                        selected_order.get(
                            "warehouse"
                        )
                    )

                actual_stock = _get_location_stock(
                    location,
                    location_data,
                    transaction_data,
                )

                already_in_form_at_location = (
                    _get_form_location_qty(
                        selected_order_id,
                        sku_code,
                        location,
                    )
                )

                available_for_this_form = max(
                    0.0,
                    actual_stock
                    - already_in_form_at_location,
                )

                c1, c2, c3 = st.columns(
                    [3.2, 2.0, 2.0]
                )

                with c1:

                    _html(
                        f"""
                        <div class="go-location-card">
                            <div class="go-location-name">
                                📍 {html.escape(location)}
                            </div>

                            <div class="go-location-warehouse">
                                🏭 Warehouse:
                                {html.escape(warehouse or "-")}
                            </div>
                        </div>
                        """
                    )

                with c2:

                    _html(
                        f"""
                        <div class="go-location-card">

                            <div class="go-location-stock">
                                Stock:
                                {_fmt_qty(actual_stock)}
                            </div>

                            <div style="
                                color:#64748b;
                                font-size:0.72rem;
                                margin-top:0.25rem;
                            ">
                                Available now:
                                {_fmt_qty(
                                    available_for_this_form
                                )}
                            </div>

                        </div>
                        """
                    )

                with c3:

                    max_qty = min(
                        pending_qty,
                        available_for_this_form,
                    )

                    max_qty = max(
                        0.0,
                        max_qty,
                    )

                    if max_qty > 0:

                        location_qty = st.number_input(
                            "Gate Out Qty",
                            min_value=0.0,
                            max_value=float(
                                max_qty
                            ),
                            value=0.0,
                            step=1.0,
                            key=(
                                f"go_qty_"
                                f"{selected_order_id}_"
                                f"{sku_code}_"
                                f"{location_index}"
                            ),
                        )

                    else:

                        location_qty = 0.0

                        st.caption(
                            "No stock available"
                        )

                # =========================================
                # ADD BUTTON
                # =========================================

                if location_qty > 0:

                    if st.button(
                        "➕ Add",
                        type="primary",
                        use_container_width=True,
                        key=(
                            f"go_add_"
                            f"{selected_order_id}_"
                            f"{sku_code}_"
                            f"{location_index}"
                        ),
                    ):

                        latest_form_out = (
                            _get_form_out_qty(
                                selected_order_id,
                                sku_code,
                            )
                        )

                        latest_pending = max(
                            0.0,
                            ordered_qty
                            - already_out
                            - latest_form_out,
                        )

                        latest_stock = (
                            _get_location_stock(
                                location,
                                location_data,
                                transaction_data,
                            )
                        )

                        latest_location_form = (
                            _get_form_location_qty(
                                selected_order_id,
                                sku_code,
                                location,
                            )
                        )

                        latest_available = max(
                            0.0,
                            latest_stock
                            - latest_location_form,
                        )

                        if location_qty > latest_pending:

                            st.error(
                                f"Only "
                                f"{_fmt_qty(latest_pending)} "
                                f"units are pending for "
                                f"{sku_code}."
                            )

                        elif (
                            location_qty
                            > latest_available
                        ):

                            st.error(
                                f"Only "
                                f"{_fmt_qty(latest_available)} "
                                f"units are available "
                                f"at {location}."
                            )

                        else:

                            added = (
                                _add_gate_out_item(
                                    selected_order_id,
                                    sku_code,
                                    location,
                                    location_qty,
                                    latest_available,
                                    latest_pending,
                                    warehouse=warehouse,
                                )
                            )

                            if added:

                                st.session_state.gate_out_clear_prefixes = [
                                    f"go_qty_{selected_order_id}_{sku_code}_"
                                ]

                                st.rerun()

        # =================================================
        # SEPARATOR
        # =================================================

        if sku_index < len(sku_list) - 1:

            _html(
                """
                <div class="go-divider"></div>
                """
            )

    # =====================================================
    # GATE OUT REVIEW
    # =====================================================

    selected_review_items = [
        item
        for item in st.session_state.gate_out_items
        if item["order_id"]
        == selected_order_id
    ]

    if selected_review_items:

        _html(
            """
            <div class="go-section"
                 style="margin-top:1.5rem;">
                📋 GATE OUT REVIEW
            </div>
            """
        )

        # =================================================
        # REVIEW HEADER
        # =================================================

        c1, c2, c3, c4 = st.columns(
            [3, 3, 1.5, 0.8]
        )

        with c1:
            st.markdown("**SKU**")

        with c2:
            st.markdown("**WAREHOUSE / LOCATION**")

        with c3:
            st.markdown("**QTY**")

        with c4:
            st.markdown("**REMOVE**")

        # =================================================
        # REVIEW ITEMS
        # =================================================

        for item in selected_review_items:

            actual_index = (
                st.session_state.gate_out_items.index(
                    item
                )
            )

            # ---------------------------------------------
            # FIND WAREHOUSE
            # ---------------------------------------------

            warehouse_name = _s(
                item.get("warehouse")
            )

            if not warehouse_name:

                try:

                    review_location_data = (
                        _load_sku_locations(
                            item["sku_code"]
                        )
                    )

                    for row in review_location_data:

                        if (
                            _s(row.get("location"))
                            == item["location"]
                        ):

                            warehouse_name = _s(
                                row.get(
                                    "wh_location"
                                )
                            )

                            break

                except Exception:

                    warehouse_name = ""

            if not warehouse_name:

                warehouse_name = _s(
                    selected_order.get(
                        "warehouse"
                    )
                )

            # ---------------------------------------------
            # REVIEW ROW
            # ---------------------------------------------

            c1, c2, c3, c4 = st.columns(
                [3, 3, 1.5, 0.8]
            )

            with c1:

                _html(
                    f"""
                    <div class="go-review">

                        <div class="go-review-label">
                            SKU
                        </div>

                        <div class="go-review-value">
                            {html.escape(
                                _s(item["sku_code"])
                            )}
                        </div>

                    </div>
                    """
                )

            with c2:

                _html(
                    f"""
                    <div class="go-review">

                        <div class="go-review-label">
                            Warehouse / Location
                        </div>

                        <div class="go-review-value">
                            🏭 {html.escape(
                                _s(warehouse_name)
                            )}
                        </div>

                        <div style="
                            color:#0284c7;
                            font-size:0.8rem;
                            font-weight:600;
                            margin-top:0.25rem;
                        ">
                            📍 {html.escape(
                                _s(item["location"])
                            )}
                        </div>

                    </div>
                    """
                )

            with c3:

                _html(
                    f"""
                    <div class="go-review">

                        <div class="go-review-label">
                            QTY
                        </div>

                        <div class="go-review-value">
                            {_fmt_qty(item["qty"])}
                        </div>

                    </div>
                    """
                )

            with c4:

                if st.button(
                    "🗑",
                    key=f"go_remove_{actual_index}",
                ):

                    st.session_state.gate_out_items.pop(
                        actual_index
                    )

                    st.rerun()

        # =================================================
        # TOTAL QTY
        # =================================================

        total_review_qty = sum(
            _f(
                item["qty"]
            )
            for item in selected_review_items
        )

        _html(
            f"""
            <div style="
                background:#eff6ff;
                border:1px solid #bfdbfe;
                border-radius:10px;
                padding:0.9rem 1rem;
                margin-top:0.8rem;
                margin-bottom:0.8rem;
                color:#1e3a8a;
                font-weight:600;
            ">
                Total Gate Out Quantity:
                {_fmt_qty(total_review_qty)}
            </div>
            """
        )

        # =================================================
        # ERROR
        # =================================================

        if st.session_state.gate_out_error:

            st.error(
                st.session_state.gate_out_error
            )

        # =================================================
        # SAVE GATE OUT
        # =================================================

        if st.button(
            "✅ Save Gate Out",
            type="primary",
            use_container_width=True,
            key="save_gate_out",
        ):

            with st.spinner(
                "Saving Gate Out..."
            ):

                success, error = (
                    _save_gate_out(
                        selected_review_items
                    )
                )

            # =================================================
            # SUCCESS
            # =================================================

            if success:

                # =================================================
                # PREPARE EMAIL ITEMS
                # =================================================

                email_items = []

                for item in selected_review_items:

                    email_item = dict(
                        item
                    )

                    warehouse_name = _s(
                        item.get("warehouse")
                    )

                    if not warehouse_name:

                        try:

                            review_location_data = (
                                _load_sku_locations(
                                    item["sku_code"]
                                )
                            )

                            for row in review_location_data:

                                if (
                                    _s(
                                        row.get(
                                            "location"
                                        )
                                    )
                                    == item["location"]
                                ):

                                    warehouse_name = _s(
                                        row.get(
                                            "wh_location"
                                        )
                                    )

                                    break

                        except Exception:

                            warehouse_name = ""

                    if not warehouse_name:

                        warehouse_name = _s(
                            selected_order.get(
                                "warehouse"
                            )
                        )

                    email_item["warehouse"] = (
                        warehouse_name
                    )

                    email_items.append(
                        email_item
                    )

                # =================================================
                # SEND EMAIL
                # =================================================

                email_success, email_error = (
                    send_gate_out_email(
                        order_data=selected_order,
                        gate_out_items=email_items,
                        processed_by=st.session_state.get(
                            "username",
                            "",
                        ),
                    )
                )

                # =================================================
                # REMOVE CURRENT ORDER ITEMS
                # =================================================

                st.session_state.gate_out_items = [
                    i
                    for i in st.session_state.gate_out_items
                    if i["order_id"]
                    != selected_order_id
                ]

                # =================================================
                # SUCCESS STATE
                # =================================================

                st.session_state.gate_out_success = True

                st.session_state.gate_out_error = ""

                # =================================================
                # EMAIL STATUS
                # =================================================

                st.session_state.gate_out_email_sent = (
                    email_success
                )

                st.session_state.gate_out_email_error = (
                    ""
                    if email_success
                    else (
                        email_error
                        or "Unknown email error"
                    )
                )

                # =================================================
                # BACK TO ORDER LIST
                # =================================================

                st.session_state.gate_out_active_order = None

                st.session_state.gate_out_clear_prefixes = [
                    "go_qty_",
                ]

                st.rerun()

            # =================================================
            # FAILURE
            # =================================================

            else:

                st.session_state.gate_out_error = (
                    error
                    or "Unknown error"
                )

                st.error(
                    f"❌ Gate Out failed: {error}"
                )


# =========================================================
# MAIN PAGE
# =========================================================

def render_gate_out(
    on_back=None,
) -> None:

    _init_state()

    inject_gate_out_css()

    # =====================================================
    # CLEAR PREVIOUS WIDGET VALUES
    # =====================================================

    prefixes = st.session_state.pop(
        "gate_out_clear_prefixes",
        None,
    )

    if prefixes:

        for key in list(
            st.session_state.keys()
        ):

            if (
                isinstance(key, str)
                and key.startswith(
                    tuple(prefixes)
                )
            ):

                st.session_state.pop(
                    key,
                    None,
                )

    # =====================================================
    # TITLE
    # =====================================================

    _html(
        """
        <div class="go-title">
            🚪 Gate Out
        </div>
        """
    )

    # =====================================================
    # BACK BUTTON
    # =====================================================

    if on_back:

        if st.button(
            "⬅ Back To Home",
            key="go_back",
        ):

            _reset_form()

            on_back()

            st.rerun()

    st.divider()

    # =====================================================
    # SUCCESS BANNER
    # =====================================================

    if st.session_state.gate_out_success:

        st.balloons()

        st.success(
            "🎉 Gate Out Saved Successfully!"
        )

        # =================================================
        # EMAIL SUCCESS
        # =================================================

        if st.session_state.get(
            "gate_out_email_sent",
            False,
        ):

            st.success(
                "📧 Accounts notification sent successfully."
            )

        # =================================================
        # EMAIL FAILURE
        # =================================================

        else:

            st.warning(
                "⚠️ Gate Out save ho gaya, "
                "lekin Accounts email send nahi ho payi."
            )

            email_error = st.session_state.get(
                "gate_out_email_error",
                "",
            )

            if email_error:

                st.caption(
                    f"Email Error: {email_error}"
                )

        st.session_state.gate_out_success = False

    # =====================================================
    # LOAD ORDERS
    # =====================================================

    orders = _load_sales_orders()

    if not orders:

        st.info(
            "No Sales Orders found."
        )

        return

    # =====================================================
    # LIST / DETAIL
    # =====================================================

    active_id = (
        st.session_state.gate_out_active_order
    )

    active_order = None

    if active_id:

        active_order = next(
            (
                o
                for o in orders
                if _s(
                    o.get("order_id")
                )
                == _s(active_id)
            ),
            None,
        )

    if active_order:

        _render_order_detail(
            active_order,
            _s(
                active_order.get(
                    "order_id"
                )
            ),
        )

    else:

        st.session_state.gate_out_active_order = None

        _render_order_list(
            orders
        )
