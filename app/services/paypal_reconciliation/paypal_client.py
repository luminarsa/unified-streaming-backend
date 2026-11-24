
import os

import httpx


# ---------------------------------------------------------
# PAYPAL CONFIGURATION
# ---------------------------------------------------------

PAYPAL_CLIENT_ID = os.getenv("PAYPAL_CLIENT_ID")
PAYPAL_CLIENT_SECRET = os.getenv("PAYPAL_CLIENT_SECRET")

PAYPAL_ENVIRONMENT = os.getenv(
    "PAYPAL_ENVIRONMENT",
    "sandbox"
).lower()

PAYPAL_API_TIMEOUT_SECONDS = float(
    os.getenv("PAYPAL_API_TIMEOUT_SECONDS", "40")
)

if PAYPAL_ENVIRONMENT == "live":
    PAYPAL_BASE_URL = "https://api-m.paypal.com"
else:
    PAYPAL_BASE_URL = "https://api-m.sandbox.paypal.com"


# ---------------------------------------------------------
# GET PAYPAL ACCESS TOKEN
# ---------------------------------------------------------

async def get_paypal_access_token(
    client: httpx.AsyncClient
) -> str:
    """
    Requests an OAuth access token from PayPal.

    This function is independent of the checkout service.
    """

    if not PAYPAL_CLIENT_ID or not PAYPAL_CLIENT_SECRET:
        raise RuntimeError(
            "PayPal Client ID or Client Secret is missing."
        )

    response = await client.post(
        f"{PAYPAL_BASE_URL}/v1/oauth2/token",
        auth=(PAYPAL_CLIENT_ID, PAYPAL_CLIENT_SECRET),
        headers={
            "Accept": "application/json",
            "Accept-Language": "en_US",
        },
        data={
            "grant_type": "client_credentials"
        },
        timeout=PAYPAL_API_TIMEOUT_SECONDS,
    )

    response.raise_for_status()

    token_data = response.json()

    access_token = token_data.get("access_token")

    if not access_token:
        raise RuntimeError(
            "PayPal did not return an access token."
        )

    return access_token


# ---------------------------------------------------------
# SEARCH PAID PAYPAL INVOICES
# ---------------------------------------------------------

async def search_paid_invoices(
    client: httpx.AsyncClient,
    access_token: str,
    page: int = 1,
    page_size: int = 100,
) -> dict:
    """
    Searches PayPal for invoices with PAID status.

    Pagination is supported so the reconciliation process
    can retrieve additional pages when necessary.
    """

    response = await client.post(
        f"{PAYPAL_BASE_URL}/v2/invoicing/search-invoices",
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        json={
            "status": [
                "PAID"
            ],
            "page": page,
            "page_size": page_size,
            "total_required": True,
        },
        timeout=PAYPAL_API_TIMEOUT_SECONDS,
    )

    response.raise_for_status()

    return response.json()


# ---------------------------------------------------------
# GET INDIVIDUAL PAYPAL INVOICE
# ---------------------------------------------------------

async def get_invoice_details(
    client: httpx.AsyncClient,
    access_token: str,
    invoice_id: str,
) -> dict:
    """
    Retrieves the complete details of a PayPal invoice.

    The processor will use this information to verify
    payment status, amount, currency and invoice identity.
    """

    if not invoice_id:
        raise ValueError(
            "A PayPal invoice ID is required."
        )

    response = await client.get(
        f"{PAYPAL_BASE_URL}/v2/invoicing/invoices/{invoice_id}",
        headers={
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json",
        },
        timeout=PAYPAL_API_TIMEOUT_SECONDS,
    )

    response.raise_for_status()

    return response.json()
