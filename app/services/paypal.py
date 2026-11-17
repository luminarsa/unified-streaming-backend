
import base64
import logging
import hashlib
import httpx

from app.core.config import settings


logger = logging.getLogger(__name__)


class PayPalError(RuntimeError):
    pass

def get_paypal_diagnostics():
    client_id, _ = get_paypal_credentials()

    fingerprint = hashlib.sha256(
        client_id.encode("utf-8")
    ).hexdigest()[:12]

    return {
        "environment": settings.paypal_environment,
        "base_url": get_paypal_base_url(),
        "client_id_fingerprint": fingerprint,
    }
# =========================================================
# 1. PAYPAL CONFIGURATION
# =========================================================

async def inspect_paypal_identity():
    return await paypal_request(
        method="GET",
        path="/v1/identity/oauth2/userinfo",
        params={"schema": "paypalv1.1"},
    )

def get_paypal_base_url() -> str:
    if settings.paypal_environment.lower() == "live":
        return "https://api-m.paypal.com"

    return "https://api-m.sandbox.paypal.com"


def get_paypal_credentials():
    client_id = settings.paypal_client_id
    client_secret = settings.paypal_client_secret

    if not client_id or not client_secret:
        raise PayPalError(
            "PayPal client ID or client secret is missing."
        )

    return client_id, client_secret


# =========================================================
# 2. PAYPAL AUTHENTICATION
# =========================================================

async def get_access_token() -> str:
    client_id, client_secret = get_paypal_credentials()

    credentials = f"{client_id}:{client_secret}"

    encoded_credentials = base64.b64encode(
        credentials.encode("utf-8")
    ).decode("utf-8")

    url = f"{get_paypal_base_url()}/v1/oauth2/token"

    headers = {
        "Authorization": f"Basic {encoded_credentials}",
        "Content-Type": "application/x-www-form-urlencoded",
    }

    timeout = settings.paypal_api_timeout_seconds

    async with httpx.AsyncClient(timeout=timeout) as client:
        try:
            response = await client.post(
                url,
                headers=headers,
                data={
                    "grant_type": "client_credentials",
                },
            )

            response.raise_for_status()

            data = response.json()

            access_token = data.get("access_token")

            if not access_token:
                raise PayPalError(
                    "PayPal did not return an access token."
                )

            return access_token

        except httpx.HTTPStatusError as exc:
            logger.error(
                "PayPal authentication failed: HTTP %s",
                exc.response.status_code,
            )

            raise PayPalError(
                "PayPal authentication failed."
            ) from exc

        except httpx.HTTPError as exc:
            raise PayPalError(
                "Unable to connect to PayPal authentication."
            ) from exc


# =========================================================
# 3. COMMON PAYPAL API REQUEST
# =========================================================

async def paypal_request(
    method: str,
    path: str,
    payload: dict | None = None,
    params: dict | None = None,
    request_id: str | None = None,
    prefer: str | None = None,
):
    access_token = await get_access_token()

    url = f"{get_paypal_base_url()}{path}"

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    # PayPal idempotency key.
    # Reusing the same key for a retry helps prevent
    # duplicate invoice creation.
    if request_id:
        headers["PayPal-Request-Id"] = request_id

    if prefer:
        headers["Prefer"] = prefer

    timeout = settings.paypal_api_timeout_seconds

    async with httpx.AsyncClient(timeout=timeout) as client:
        try:
            response = await client.request(
                method=method,
                url=url,
                headers=headers,
                json=payload,
                params=params,
            )

            if response.is_error:
                try:
                    error_data = response.json()
                except ValueError:
                    error_data = {
                        "raw_response": response.text
                    }

                logger.error(
                    "PayPal API error. HTTP %s. Full response: %s",
                    response.status_code,
                    error_data,
                )

                details = error_data.get("details", [])

                error_messages = []

                for item in details:
                    error_messages.append(
                        f"Field: {item.get('field', 'Unknown')}, "
                        f"Issue: {item.get('issue', 'Unknown')}, "
                        f"Description: {item.get('description', 'No description')}"
                    )

                raise PayPalError(
                    f"PayPal API request failed with HTTP "
                    f"{response.status_code}: "
                    f"{error_data.get('message', 'Unknown error')}. "
                    f"Details: {'; '.join(error_messages)}"
                )
            # Some PayPal operations return HTTP 204.
            if response.status_code == 204 or not response.content:
                return {}

            return response.json()

        except httpx.TimeoutException as exc:
            raise PayPalError(
                "PayPal request timed out."
            ) from exc

        except httpx.HTTPError as exc:
            raise PayPalError(
                "Unable to communicate with PayPal."
            ) from exc



# =========================================================
# 4. CREATE PAYPAL INVOICE
# =========================================================

async def create_invoice(
    customer_email: str,
    plan_name: str,
    amount: str,
    currency: str,
):
    """
    Create a PayPal invoice using the same payload
    structure as the successful standalone test.
    """

    if not customer_email:
        raise PayPalError("Customer email is required.")

    if not plan_name:
        raise PayPalError("Subscription plan name is required.")

    if not amount or not currency:
        raise PayPalError("Invoice amount and currency are required.")

    payload = {
        "detail": {
            "currency_code": currency.upper(),
            "note": "Lumina subscription payment",
        },
        "invoicer": {
            "name": {
                "given_name": "Lumina",
                "surname": "Subscriptions",
            }
        },
        "primary_recipients": [
            {
                "billing_info": {
                    "email_address": customer_email,
                }
            }
        ],
        "items": [
            {
                "name": plan_name,
                "quantity": "1",
                "unit_amount": {
                    "currency_code": currency.upper(),
                    "value": amount,
                },
            }
        ],
    }

    return await paypal_request(
        method="POST",
        path="/v2/invoicing/invoices",
        payload=payload,
        prefer="return=representation",
    )
# =========================================================
# 5. SEND PAYPAL INVOICE TO CUSTOMER
# =========================================================

async def send_invoice(invoice_id: str):

    if not invoice_id:
        raise PayPalError("PayPal invoice ID is required.")

    return await paypal_request(
        method="POST",
        path=f"/v2/invoicing/invoices/{invoice_id}/send",
    )

# =========================================================
# 6. GET PAYPAL INVOICE DETAILS
# =========================================================

async def get_invoice(invoice_id: str):
    """
    Retrieves the latest PayPal invoice details.
    """

    if not invoice_id:
        raise PayPalError(
            "PayPal invoice ID is required."
        )

    return await paypal_request(
        method="GET",
        path=f"/v2/invoicing/invoices/{invoice_id}",
    )


# =========================================================
# 7. SEARCH PAYPAL INVOICES
# =========================================================

async def search_invoices(search_payload: dict):
    """
    Searches PayPal invoices using the Invoicing API.
    """

    if not isinstance(search_payload, dict):
        raise PayPalError(
            "Invoice search payload must be a dictionary."
        )

    return await paypal_request(
        method="POST",
        path="/v2/invoicing/search-invoices",
        payload=search_payload,
    )


# =========================================================
# 8. SEND PAYMENT REMINDER
# =========================================================

async def send_invoice_reminder(invoice_id: str):
    """
    Sends a reminder for an existing unpaid invoice.
    """

    if not invoice_id:
        raise PayPalError(
            "PayPal invoice ID is required."
        )

    return await paypal_request(
        method="POST",
        path=f"/v2/invoicing/invoices/{invoice_id}/remind",
        payload={
            "send_to_recipient": True,
            "send_to_invoicer": False,
        },
    )


# =========================================================
# 9. CANCEL PAYPAL INVOICE
# =========================================================

async def cancel_invoice(invoice_id: str):
    """
    Cancels an already-sent unpaid invoice.
    """

    if not invoice_id:
        raise PayPalError(
            "PayPal invoice ID is required."
        )

    return await paypal_request(
        method="POST",
        path=f"/v2/invoicing/invoices/{invoice_id}/cancel",
        payload={
            "subject": "Lumina invoice cancelled",
            "note": (
                "This invoice has been cancelled. "
                "Please contact Lumina if you still wish to subscribe."
            ),
            "send_to_recipient": True,
            "send_to_invoicer": False,
        },
    )
