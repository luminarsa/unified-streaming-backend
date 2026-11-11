
import base64

import httpx

from app.core.config import settings


class PayPalError(RuntimeError):
    pass


# ---------------------------------------------------------
# 1. PAYPAL CONFIGURATION
# ---------------------------------------------------------

def get_paypal_base_url() -> str:
    if settings.paypal_environment.lower() == "live":
        return "https://api-m.paypal.com"

    return "https://api-m.sandbox.paypal.com"


def _get_credentials():
    client_id = settings.paypal_client_id
    client_secret = settings.paypal_client_secret

    if not client_id or not client_secret:
        raise PayPalError(
            "PayPal client ID or client secret is missing."
        )

    return client_id, client_secret


# ---------------------------------------------------------
# 2. GET PAYPAL ACCESS TOKEN
# ---------------------------------------------------------

async def get_access_token() -> str:
    client_id, client_secret = _get_credentials()

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
                data={"grant_type": "client_credentials"},
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
            raise PayPalError(
                f"PayPal authentication failed with HTTP "
                f"{exc.response.status_code}."
            ) from exc

        except httpx.HTTPError as exc:
            raise PayPalError(
                "Unable to authenticate with PayPal."
            ) from exc


# ---------------------------------------------------------
# 3. COMMON PAYPAL API REQUEST
# ---------------------------------------------------------

async def paypal_request(
    method: str,
    path: str,
    payload: dict | None = None,
    request_id: str | None = None,
):
    access_token = await get_access_token()

    url = f"{get_paypal_base_url()}{path}"

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    # PayPal idempotency support.
    # Reuse the same request ID when retrying the same operation.
    if request_id:
        headers["PayPal-Request-Id"] = request_id

    timeout = settings.paypal_api_timeout_seconds

    async with httpx.AsyncClient(timeout=timeout) as client:
        try:
            response = await client.request(
                method=method,
                url=url,
                headers=headers,
                json=payload,
            )

            response.raise_for_status()

            if not response.content:
                return {}

            return response.json()

        except httpx.HTTPStatusError as exc:
            raise PayPalError(
                f"PayPal request failed with HTTP "
                f"{exc.response.status_code}."
            ) from exc

        except httpx.HTTPError as exc:
            raise PayPalError(
                "Unable to communicate with PayPal."
            ) from exc


# ---------------------------------------------------------
# 4. CREATE A STANDARD CHECKOUT ORDER
# ---------------------------------------------------------

async def create_order(
    amount: str,
    currency: str,
    subscription_id: str,
    plan_name: str,
    request_id: str | None = None,
):
    payload = {
        "intent": "CAPTURE",
        "purchase_units": [
            {
                "reference_id": subscription_id,
                "custom_id": subscription_id,
                "description": plan_name,
                "amount": {
                    "currency_code": currency,
                    "value": amount,
                },
            }
        ],
    }

    return await paypal_request(
        method="POST",
        path="/v2/checkout/orders",
        payload=payload,
        request_id=request_id,
    )


# ---------------------------------------------------------
# 5. CREATE A CARD CHECKOUT ORDER WITH VAULTING
# ---------------------------------------------------------

async def create_card_order(
    amount: str,
    currency: str,
    subscription_id: str,
    plan_name: str,
    card_single_use_token: str,
    request_id: str | None = None,
):
    """
    Creates an initial card payment and requests card vaulting.

    card_single_use_token must be generated through an approved
    PayPal-hosted card integration.

    Never pass raw card numbers or CVV values to this function.
    """

    if not card_single_use_token:
        raise PayPalError(
            "A valid PayPal card token is required."
        )

    payload = {
        "intent": "CAPTURE",
        "payment_source": {
            "card": {
                "single_use_token": card_single_use_token,
                "attributes": {
                    "verification": {
                        "method": "SCA_WHEN_REQUIRED",
                    },
                    "vault": {
                        "store_in_vault": "ON_SUCCESS",
                        "usage_type": "MERCHANT",
                    },
                },
            }
        },
        "purchase_units": [
            {
                "reference_id": subscription_id,
                "custom_id": subscription_id,
                "description": plan_name,
                "amount": {
                    "currency_code": currency,
                    "value": amount,
                },
            }
        ],
    }

    return await paypal_request(
        method="POST",
        path="/v2/checkout/orders",
        payload=payload,
        request_id=request_id,
    )


# ---------------------------------------------------------
# 6. CAPTURE AN INITIAL PAYMENT
# ---------------------------------------------------------

async def capture_order(
    order_id: str,
    request_id: str | None = None,
):
    if not order_id:
        raise PayPalError(
            "PayPal order ID is required."
        )

    return await paypal_request(
        method="POST",
        path=f"/v2/checkout/orders/{order_id}/capture",
        payload={},
        request_id=request_id,
    )


# ---------------------------------------------------------
# 7. GET ORDER DETAILS
# ---------------------------------------------------------

async def get_order(order_id: str):
    if not order_id:
        raise PayPalError(
            "PayPal order ID is required."
        )

    return await paypal_request(
        method="GET",
        path=f"/v2/checkout/orders/{order_id}",
    )


# ---------------------------------------------------------
# 8. GET SAVED PAYMENT TOKEN DETAILS
# ---------------------------------------------------------

async def get_payment_token(vault_id: str):
    if not vault_id:
        raise PayPalError(
            "PayPal vault ID is required."
        )

    return await paypal_request(
        method="GET",
        path=f"/v3/vault/payment-tokens/{vault_id}",
    )


# ---------------------------------------------------------
# 9. CREATE A RECURRING PAYMENT ORDER
# ---------------------------------------------------------

async def create_recurring_charge(
    amount: str,
    currency: str,
    vault_id: str,
    subscription_id: str,
    plan_name: str,
    previous_transaction_reference: str,
    request_id: str,
):
    """
    Creates a merchant-initiated recurring payment order
    using a previously saved PayPal card token.

    This function creates the order only.
    Call capture_recurring_charge() afterwards to collect payment.

    previous_transaction_reference must identify the qualifying
    original customer-authorized transaction.
    """

    if not vault_id:
        raise PayPalError(
            "A saved PayPal payment token is required."
        )

    if not previous_transaction_reference:
        raise PayPalError(
            "The previous transaction reference is required."
        )

    if not request_id:
        raise PayPalError(
            "A unique request ID is required for recurring billing."
        )

    payload = {
        "intent": "CAPTURE",
        "payment_source": {
            "card": {
                "vault_id": vault_id,
                "stored_credential": {
                    "payment_initiator": "MERCHANT",
                    "payment_type": "RECURRING",
                    "usage": "SUBSEQUENT",
                    "previous_transaction_reference": (
                        previous_transaction_reference
                    ),
                },
            }
        },
        "purchase_units": [
            {
                "reference_id": subscription_id,
                "custom_id": subscription_id,
                "description": plan_name,
                "amount": {
                    "currency_code": currency,
                    "value": amount,
                },
            }
        ],
    }

    return await paypal_request(
        method="POST",
        path="/v2/checkout/orders",
        payload=payload,
        request_id=request_id,
    )


# ---------------------------------------------------------
# 10. CAPTURE A RECURRING PAYMENT
# ---------------------------------------------------------

async def capture_recurring_charge(
    order_id: str,
    request_id: str | None = None,
):
    """
    Captures a recurring payment order created by
    create_recurring_charge().
    """

    if not order_id:
        raise PayPalError(
            "PayPal recurring order ID is required."
        )

    return await paypal_request(
        method="POST",
        path=f"/v2/checkout/orders/{order_id}/capture",
        payload={},
        request_id=request_id,
    )


# ---------------------------------------------------------
# 11. DELETE A SAVED PAYMENT TOKEN
# ---------------------------------------------------------

async def delete_payment_token(vault_id: str):
    """
    Deletes a saved PayPal payment token.

    Only call after confirming that the token belongs
    to the authenticated customer's payment method.
    """

    if not vault_id:
        raise PayPalError(
            "PayPal vault ID is required."
        )

    return await paypal_request(
        method="DELETE",
        path=f"/v3/vault/payment-tokens/{vault_id}",
    )


async def verify_webhook_signature(
    headers: dict,
    webhook_event: dict,
) -> bool:
    """
    Ask PayPal to verify the authenticity of an incoming webhook.

    Returns True only when PayPal confirms the signature.
    """

    webhook_id = settings.paypal_webhook_id

    if not webhook_id:
        raise PayPalError(
            "PayPal webhook ID is not configured."
        )

    required_headers = {
        "auth_algo": headers.get("paypal-auth-algo"),
        "cert_url": headers.get("paypal-cert-url"),
        "transmission_id": headers.get("paypal-transmission-id"),
        "transmission_sig": headers.get("paypal-transmission-sig"),
        "transmission_time": headers.get("paypal-transmission-time"),
    }

    # Reject requests that do not contain all required PayPal headers.
    if any(not value for value in required_headers.values()):
        return False

    payload = {
        **required_headers,
        "webhook_id": webhook_id,
        "webhook_event": webhook_event,
    }

    try:
        response = await paypal_request(
            method="POST",
            path="/v1/notifications/verify-webhook-signature",
            payload=payload,
        )

    except PayPalError:
        raise

    except Exception as exc:
        raise PayPalError(
            f"Could not verify PayPal webhook: {str(exc)}"
        ) from exc

    return (
        response.get("verification_status") == "SUCCESS"
    )
