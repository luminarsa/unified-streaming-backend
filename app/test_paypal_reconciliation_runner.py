
import asyncio

import httpx

from app.db.session import SessionLocal
from app.services.paypal_reconciliation.reconciliation_runner import (
    run_paypal_reconciliation,
)


async def main():

    print("Starting PayPal reconciliation test...")

    db = SessionLocal()

    try:

        result = await run_paypal_reconciliation(db)

        print("\nRECONCILIATION RESULTS")
        print("----------------------")

        print(f"Success: {result['success']}")
        print(f"Invoices found: {result['invoices_found']}")
        print(f"Payments completed: {result['payments_completed']}")
        print(f"Already processed: {result['already_processed']}")
        print(f"Rejected: {result['rejected']}")
        print(f"Errors: {result['errors']}")

        print("\nInvoice details:")

        for item in result["details"]:
            print(item)

    except Exception as exc:

        print("\nTEST FAILED")
        print(str(exc))

        raise

    finally:

        db.close()


if __name__ == "__main__":
    asyncio.run(main())
