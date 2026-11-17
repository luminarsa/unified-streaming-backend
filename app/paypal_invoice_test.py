
import asyncio
import base64
import httpx


# -----------------------------------------
# PAYPAL SANDBOX CREDENTIALS
# -----------------------------------------

import hashlib

CLIENT_ID = "BAAkOCt7bqHguWccAM0613fyP58PaxVMf9pp_nNS-Mlsc2B0gRGDtaal1WR9AVZOogv-1B3fPR4sKtCzM8"
CLIENT_SECRET = "EMVwxlAPZzShVbIQeoGomMW0XDzIwGKqez7xXN29XM5HgueSN29jfQvXIihVxqL7u2rP66a-AToA0NeT"

BASE_URL = "https://api-m.sandbox.paypal.com"


async def main():

    async with httpx.AsyncClient(timeout=30) as client:

        # 1. Authenticate with PayPal

        credentials = f"{CLIENT_ID}:{CLIENT_SECRET}"

        encoded = base64.b64encode(
            credentials.encode()
        ).decode()

        response = await client.post(
            f"{BASE_URL}/v1/oauth2/token",
            headers={
                "Authorization": f"Basic {encoded}",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            data={
                "grant_type": "client_credentials"
            },
        )

        response.raise_for_status()

        access_token = response.json()["access_token"]

        print("PayPal authentication successful.")

        # 2. Create invoice

        payload = {
            "detail": {
                "currency_code": "USD",
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
                        "email_address": "escapetv.co.za@gmail.com"
                    }
                }
            ],
            "items": [
                {
                    "name": "Lumina Subscription",
                    "quantity": "1",
                    "unit_amount": {
                        "currency_code": "USD",
                        "value": "10.00",
                    },
                }
            ],
        }

        response = await client.post(
            f"{BASE_URL}/v2/invoicing/invoices",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
                "Prefer": "return=representation",
            },
            json=payload,
        )

        print("HTTP STATUS:", response.status_code)
        print("PAYPAL RESPONSE:", response.text)

        response.raise_for_status()

        invoice = response.json()

        print("\nINVOICE CREATED SUCCESSFULLY")
        print("Invoice ID:", invoice.get("id"))
        print("Status:", invoice.get("status"))


        # 3. Send the invoice

        invoice_id = invoice["id"]

        print("\nSending invoice to customer...")

        send_response = await client.post(
            f"{BASE_URL}/v2/invoicing/invoices/{invoice_id}/send",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
            },
        )

        print("SEND HTTP STATUS:", send_response.status_code)
        print("SEND RESPONSE:", send_response.text)

        send_response.raise_for_status()

        print("\nINVOICE SENT SUCCESSFULLY")
        print("Invoice ID:", invoice_id)

import hashlib

print("BASE URL:", BASE_URL)

print(
    "CLIENT ID FINGERPRINT:",
    hashlib.sha256(
        CLIENT_ID.encode("utf-8")
    ).hexdigest()[:12],
)

if __name__ == "__main__":
    asyncio.run(main())
