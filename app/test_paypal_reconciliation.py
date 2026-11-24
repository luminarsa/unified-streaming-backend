
import asyncio
import httpx

from app.services.paypal_reconciliation.paypal_client import (
    get_paypal_access_token,
    search_paid_invoices,
)


async def main():
    async with httpx.AsyncClient() as client:

        print("Connecting to PayPal...")

        access_token = await get_paypal_access_token(client)

        print("PayPal authentication successful.")

        print("Searching for paid invoices...")

        result = await search_paid_invoices(
            client=client,
            access_token=access_token,
            page=1,
            page_size=10,
        )

        invoices = result.get("items", [])

        print(f"Total invoices returned: {len(invoices)}")

        for invoice in invoices:
            print({
                "id": invoice.get("id"),
                "status": invoice.get("status"),
                "invoice_number": invoice.get("detail", {}).get("invoice_number"),
            })


if __name__ == "__main__":
    asyncio.run(main())
