
import httpx

from app.services.paypal_reconciliation.paypal_client import (
    get_paypal_access_token,
    search_paid_invoices,
    get_invoice_details,
)


async def scan_paid_invoices(
    client: httpx.AsyncClient,
) -> list[dict]:
    """
    Searches PayPal for all paid invoices and retrieves
    their complete invoice details.

    This function does not modify the database.
    """

    access_token = await get_paypal_access_token(client)

    paid_invoices = []

    page = 1
    page_size = 100

    while True:

        result = await search_paid_invoices(
            client=client,
            access_token=access_token,
            page=page,
            page_size=page_size,
        )

        invoices = result.get("items", [])

        if not invoices:
            break

        for invoice in invoices:

            invoice_id = invoice.get("id")

            if not invoice_id:
                continue

            invoice_status = invoice.get("status")

            if invoice_status != "PAID":
                continue

            invoice_details = await get_invoice_details(
                client=client,
                access_token=access_token,
                invoice_id=invoice_id,
            )

            if invoice_details.get("status") != "PAID":
                continue

            paid_invoices.append(invoice_details)

        total_pages = result.get("total_pages")

        if total_pages is not None:
            if page >= total_pages:
                break
        elif len(invoices) < page_size:
            break

        page += 1

    return paid_invoices
