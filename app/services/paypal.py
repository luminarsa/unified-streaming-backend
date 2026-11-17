
import os
import base64
import httpx

from decimal import Decimal, InvalidOperation


# =========================================================
# PAYPAL CONFIGURATION
# =========================================================

PAYPAL_CLIENT_ID = os.getenv("PAYPAL_CLIENT_ID")
PAYPAL_CLIENT_SECRET = os.getenv("PAYPAL_CLIENT_SECRET")

PAYPAL_ENVIRONMENT = os.getenv(
    "PAYPAL_ENVIRONMENT",
    "sandbox"
).lower()

if PAYPAL_ENVIRONMENT == "live":
    PAYPAL_BASE_URL = "https://api-m.paypal.com"
else:
    PAYPAL_BASE_URL = "https://api-m.sandbox.paypal.com"

PAYPAL_TIMEOUT = float(
    os.getenv("PAYPAL_API_TIMEOUT_SECONDS", "30")
)


# =========================================================
# 1. AUTHENTICATE WITH PAYPAL
# =========================================================

async def get_paypal_access_token(client: httpx.AsyncClient) -> str:

    if not PAYPAL_CLIENT_ID or not PAYPAL_CLIENT_SECRET:
        raise ValueError(
            "PayPal credentials are missing from environment variables."
        )

    credentials = (
        f"{PAYPAL_CLIENT_ID}:{PAYPAL_CLIENT_SECRET}"
    )

    encoded_credentials = base64.b64encode(
        credentials.encode("utf-8")
    ).decode("utf-8")

    response = await client.post(
        f"{PAYPAL_BASE_URL}/v1/oauth2/token",
        headers={
            "Authorization": f"Basic {encoded_credentials}",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        data={
            "grant_type": "client_credentials"
        },
    )

    response.raise_for_status()

    token_data = response.json()

    access_token = token_data.get("access_token")

    if not access_token:
        raise RuntimeError(
            "PayPal authentication did not return an access token."
        )

    return access_token


# =========================================================
# 2. CREATE AND SEND PAYPAL INVOICE
# =========================================================


# =========================================================
# LUMINA INVOICE BRANDING
# =========================================================

LUMINA_BUSINESS_NAME = "Lumina"
LUMINA_WEBSITE = "https://luminatv.com"

LUMINA_LOGO_URL = (
    "https://ik.imagekit.io/sobl5vhb4/"
    "Lumina%20TV%20Logos/Lumina%20Logo.webp"
)


# =========================================================
# CREATE AND SEND PAYPAL INVOICE
# =========================================================

async def create_paypal_checkout(
    customer_name: str,
    customer_email: str,
    plan_name: str,
    subscription_id: str,
    subscription_period: str,
    amount: str,
    currency: str = "USD",
):

    if not customer_name:
        raise ValueError("Customer name is required.")

    if not customer_email:
        raise ValueError("Customer email is required.")

    if not plan_name:
        raise ValueError("Plan name is required.")

    if not subscription_id:
        raise ValueError("Subscription ID is required.")

    if not subscription_period:
        raise ValueError("Subscription period is required.")

    try:
        invoice_amount = Decimal(str(amount))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError("Invalid invoice amount.") from exc

    if not invoice_amount.is_finite() or invoice_amount <= 0:
        raise ValueError("Invoice amount must be greater than zero.")

    currency = currency.upper()

    # Split the profile name into PayPal's given_name
    # and surname fields.
    name_parts = customer_name.strip().split(maxsplit=1)

    given_name = name_parts[0]
    surname = name_parts[1] if len(name_parts) > 1 else ""

    # -----------------------------------------------------
    # CONNECT TO PAYPAL
    # -----------------------------------------------------

    async with httpx.AsyncClient(
        timeout=PAYPAL_TIMEOUT
    ) as client:

        access_token = await get_paypal_access_token(client)

        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

        # -------------------------------------------------
        # STEP 1: BUILD INVOICE
        # -------------------------------------------------

        payload = {
            "detail": {
                "currency_code": currency,

                # Make the Lumina subscription ID visible
                # as the invoice reference.
                "reference": subscription_id,

                # Payment must be made immediately.
                "payment_term": {
                    "term_type": "DUE_ON_RECEIPT",
                },

                # Visible invoice note.
                "note": (
                    f"Subscription period: {subscription_period}"
                ),
            },

            # Lumina business information.
            "invoicer": {
                "business_name": LUMINA_BUSINESS_NAME,

                "name": {
                    "given_name": "Lumina",
                    "surname": "Subscriptions",
                },

                "website": LUMINA_WEBSITE,
                "logo_url": LUMINA_LOGO_URL,
            },

            # Customer information.
            # No shipping_info is supplied.
            "primary_recipients": [
                {
                    "billing_info": {
                        "name": {
                            "given_name": given_name,
                            "surname": surname,
                        },
                        "email_address": customer_email,
                    }
                }
            ],

            # Subscription line item.
            "items": [
                {
                    "name": plan_name,
                    "description": (
                        f"Subscription ID: {subscription_id}\n"
                        f"Subscription period: {subscription_period}"
                    ),
                    "quantity": "1",
                    "unit_amount": {
                        "currency_code": currency,
                        "value": format(invoice_amount, ".2f"),
                    },
                }
            ],
        }

        # -------------------------------------------------
        # STEP 2: CREATE INVOICE
        # -------------------------------------------------

        create_response = await client.post(
            f"{PAYPAL_BASE_URL}/v2/invoicing/invoices",
            headers={
                **headers,
                "Prefer": "return=representation",
            },
            json=payload,
        )

        create_response.raise_for_status()

        invoice_data = create_response.json()

        invoice_id = invoice_data.get("id")

        if not invoice_id:
            raise RuntimeError(
                "PayPal did not return an invoice ID."
            )

        # -------------------------------------------------
        # STEP 3: SEND INVOICE
        # -------------------------------------------------

        send_response = await client.post(
            f"{PAYPAL_BASE_URL}/v2/invoicing/invoices/{invoice_id}/send",
            headers=headers,
        )

        send_response.raise_for_status()

        # -------------------------------------------------
        # STEP 4: EXTRACT CUSTOMER PAYMENT URL
        # -------------------------------------------------

        invoice_url = None

        if send_response.content:
            send_data = send_response.json()

            if send_data.get("rel") == "payer-view":
                invoice_url = send_data.get("href")

        # If the send response does not include the payer URL,
        # try the links returned when the invoice was created.
        if not invoice_url:
            for link in invoice_data.get("links", []):
                if link.get("rel") == "payer-view":
                    invoice_url = link.get("href")
                    break

        if not invoice_url:
            raise RuntimeError(
                "PayPal sent the invoice but did not return "
                "a customer payment URL."
            )

        # -------------------------------------------------
        # STEP 5: RETURN CHECKOUT INFORMATION
        # -------------------------------------------------

        return {
            "success": True,
            "invoice_id": invoice_id,
            "invoice_status": "SENT",
            "invoice_url": invoice_url,
            "payment_status": "pending",
            "amount": format(invoice_amount, ".2f"),
            "currency": currency,
        }
