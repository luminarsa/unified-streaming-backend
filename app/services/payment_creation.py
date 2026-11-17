
from decimal import Decimal, InvalidOperation
from uuid import UUID
from urllib.parse import urlparse
import logging

from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from app.models.identity import Account
from app.models.commercial import Plan, Subscription
from app.models.payment_transaction import PaymentTransaction

from app.services.paypal import (
    create_invoice,
    send_invoice,
    get_invoice,
    PayPalError,
)


logger = logging.getLogger(__name__)


class PaymentCreationError(Exception):
    """Raised when a subscription payment cannot be created."""


# =========================================================
# 1. GET PLAN PRICE
# =========================================================

def get_plan_paypal_price(plan: Plan) -> Decimal:
    """
    Prefer paypal_price when configured.
    Otherwise, convert price_minor from cents to a normal amount.
    """

    try:
        if plan.paypal_price is not None:
            amount = Decimal(str(plan.paypal_price))
        else:
            amount = Decimal(str(plan.price_minor)) / Decimal("100")

        amount = amount.quantize(Decimal("0.01"))

    except (InvalidOperation, TypeError, ValueError):
        raise PaymentCreationError(
            "The selected plan has an invalid price."
        )

    if not amount.is_finite() or amount <= 0:
        raise PaymentCreationError(
            "The selected plan price must be greater than zero."
        )

    return amount


# =========================================================
# 2. EXTRACT PAYPAL INVOICE ID
# =========================================================

def extract_paypal_invoice_id(response: dict) -> str | None:
    """
    Extract the PayPal invoice ID from a full invoice response
    or a response containing HATEOAS links.
    """

    if not isinstance(response, dict):
        return None

    invoice_id = response.get("id")

    if invoice_id:
        return str(invoice_id)

    href = response.get("href")

    if not href:
        for link in response.get("links", []):
            if link.get("rel") == "self":
                href = link.get("href")
                break

    if not href:
        return None

    path_parts = [
        part for part in urlparse(href).path.split("/")
        if part
    ]

    if path_parts:
        return path_parts[-1]

    return None


# =========================================================
# 3. FORMAT PAYMENT RESPONSE
# =========================================================

def format_payment_response(
    subscription: Subscription,
    transaction: PaymentTransaction,
):
    return {
        "success": True,
        "message": "Payment invoice is ready.",
        "subscription_id": str(subscription.id),
        "transaction_id": str(transaction.id),
        "invoice_id": transaction.provider_invoice_id,
        "invoice_url": transaction.provider_invoice_url,
        "amount": str(transaction.amount),
        "currency": transaction.currency,
        "payment_status": transaction.status,
        "invoice_status": transaction.provider_invoice_status,
    }


# =========================================================
# 4. CREATE OR RESUME PAYPAL INVOICE
# =========================================================

async def create_or_resume_invoice(
    db: Session,
    subscription: Subscription,
    transaction: PaymentTransaction,
    account: Account,
    plan: Plan,
):
    """
    Creates a PayPal invoice if one does not already exist.

    If an invoice already exists, retrieves and resumes that
    same invoice rather than creating another one.
    """

    # -----------------------------------------------------
    # A. CREATE INVOICE ONLY IF NO INVOICE ID IS SAVED
    # -----------------------------------------------------

    if not transaction.provider_invoice_id:

        try:
            logger.info(
                "LUMINA PAYPAL STAGE 1: Creating invoice. Transaction=%s",
                transaction.id,
            )

            invoice_response = await create_invoice(
                transaction_id=str(transaction.id),
                customer_email=account.email,
                plan_name=plan.name,
                amount=str(transaction.amount),
                currency=transaction.currency,
                request_id=str(transaction.id),
            )

        except PayPalError as exc:
            raise PaymentCreationError(
                "PayPal invoice creation failed. "
                "The existing checkout can be retried using "
                "the same idempotency key. "
                f"PayPal error: {str(exc)}"
            ) from exc

        invoice_id = extract_paypal_invoice_id(invoice_response)

        if not invoice_id:
            logger.error(
                "PayPal invoice creation returned no extractable ID. "
                "Response keys: %s",
                list(invoice_response.keys())
                if isinstance(invoice_response, dict)
                else type(invoice_response).__name__,
            )

            raise PaymentCreationError(
                "PayPal's invoice creation response did not contain "
                "a recognizable invoice ID. Check the backend logs."
            )

        # Save the invoice ID before attempting to send it.
        try:
            transaction.provider_invoice_id = invoice_id
            transaction.provider_invoice_status = (
                invoice_response.get("status", "DRAFT")
            )

            db.add(transaction)
            db.commit()
            db.refresh(transaction)

        except Exception as exc:
            db.rollback()

            raise PaymentCreationError(
                "PayPal created the invoice, but Lumina could "
                "not save its invoice ID. Retry the same "
                "checkout using the same idempotency key."
            ) from exc

    # -----------------------------------------------------
    # B. RETRIEVE THE EXISTING INVOICE FROM PAYPAL
    # -----------------------------------------------------

    invoice_id = transaction.provider_invoice_id

    try:
        logger.info(
            "LUMINA PAYPAL STAGE 2: Retrieving invoice. Invoice=%s",
            invoice_id,
        )

        invoice_details = await get_invoice(invoice_id)

    except PayPalError as exc:
        raise PaymentCreationError(
            "The existing PayPal invoice could not be retrieved. "
            "Retry this checkout using the same idempotency key. "
            f"PayPal error: {str(exc)}"
        ) from exc

    invoice_status = invoice_details.get("status", "").upper()

    if invoice_status in (
        "CANCELLED",
        "REFUNDED",
        "MARKED_AS_REFUNDED",
    ):
        raise PaymentCreationError(
            "This PayPal invoice is no longer payable. "
            "A new checkout is required."
        )

    # -----------------------------------------------------
    # C. SEND ONLY INVOICES THAT ARE STILL DRAFTS
    # -----------------------------------------------------

    if invoice_status == "DRAFT":

        try:
            logger.info(
                "LUMINA PAYPAL STAGE 3: Sending invoice. Invoice=%s",
                invoice_id,
            )

            await send_invoice(invoice_id)

            logger.info(
                "LUMINA PAYPAL STAGE 4: Invoice send request completed."
            )

        except PayPalError as exc:
            raise PaymentCreationError(
                "The invoice exists but could not be sent. "
                "Retry this checkout using the same idempotency key. "
                f"PayPal error: {str(exc)}"
            ) from exc

        # Retrieve the invoice again after sending.
        try:
            invoice_details = await get_invoice(invoice_id)

        except PayPalError as exc:
            raise PaymentCreationError(
                "The invoice was sent, but its latest status "
                "could not be retrieved. Retry using the same "
                "idempotency key."
            ) from exc

        invoice_status = invoice_details.get(
            "status",
            "SENT",
        ).upper()

    # -----------------------------------------------------
    # D. SAVE LATEST INVOICE DETAILS
    # -----------------------------------------------------

    invoice_url = (
        invoice_details
        .get("detail", {})
        .get("metadata", {})
        .get("recipient_view_url")
    )

    try:
        transaction.provider_invoice_status = invoice_status

        if invoice_url:
            transaction.provider_invoice_url = invoice_url

        db.add(transaction)
        db.commit()
        db.refresh(transaction)

    except Exception as exc:
        db.rollback()

        raise PaymentCreationError(
            "The latest PayPal invoice details could not "
            "be saved. The existing invoice can be retrieved again."
        ) from exc

    if not transaction.provider_invoice_url:
        raise PaymentCreationError(
            "The PayPal invoice exists, but its hosted payment URL "
            "was not returned. Retry this checkout using the same "
            "idempotency key."
        )

    return format_payment_response(
        subscription,
        transaction,
    )


# =========================================================
# 5. CREATE SUBSCRIPTION PAYMENT
# =========================================================

async def create_subscription_payment(
    db: Session,
    account_id: UUID,
    plan_id: UUID,
    idempotency_key: str,
):
    """
    Create a subscription payment or resume an existing checkout.

    The idempotency key identifies one checkout attempt.

    A retry must use the same key.
    A deliberately new purchase must use a new key.
    """

    # -----------------------------------------------------
    # A. VALIDATE IDEMPOTENCY KEY
    # -----------------------------------------------------

    if not idempotency_key or not idempotency_key.strip():
        raise PaymentCreationError(
            "An idempotency key is required."
        )

    idempotency_key = idempotency_key.strip()

    if len(idempotency_key) > 100:
        raise PaymentCreationError(
            "The idempotency key cannot exceed 100 characters."
        )

    # -----------------------------------------------------
    # B. FIND AND VALIDATE CUSTOMER ACCOUNT
    # -----------------------------------------------------

    account = (
        db.query(Account)
        .filter(
            Account.id == account_id,
            Account.status == "active",
        )
        .first()
    )

    if not account:
        raise PaymentCreationError(
            "Account does not exist or is inactive."
        )

    customer_email = account.email

    # -----------------------------------------------------
    # C. LOOK FOR AN EXISTING CHECKOUT
    # -----------------------------------------------------

    existing_transaction = (
        db.query(PaymentTransaction)
        .filter(
            PaymentTransaction.account_id == account.id,
            PaymentTransaction.idempotency_key == idempotency_key,
        )
        .first()
    )

    if existing_transaction:

        if not existing_transaction.subscription_id:
            raise PaymentCreationError(
                "This payment transaction has no associated subscription."
            )

        existing_subscription = (
            db.query(Subscription)
            .filter(
                Subscription.id == existing_transaction.subscription_id
            )
            .first()
        )

        if not existing_subscription:
            raise PaymentCreationError(
                "The subscription associated with this checkout "
                "could not be found."
            )

        # Never allow the same key to purchase a different plan.
        if existing_subscription.plan_id != plan_id:
            raise PaymentCreationError(
                "This idempotency key is already associated with "
                "a different subscription plan. "
                "Start a new checkout using a new idempotency key."
            )

        # A completed payment must never create another invoice.
        if existing_transaction.status == "completed":
            return format_payment_response(
                existing_subscription,
                existing_transaction,
            )

        # Failed, cancelled and refunded transactions require
        # a new checkout.
        if existing_transaction.status in (
            "failed",
            "cancelled",
            "refunded",
        ):
            raise PaymentCreationError(
                "This checkout is no longer active. "
                "Start a new checkout with a new idempotency key."
            )

        existing_plan = (
            db.query(Plan)
            .filter(Plan.id == existing_subscription.plan_id)
            .first()
        )

        if not existing_plan:
            raise PaymentCreationError(
                "The plan associated with this checkout "
                "could not be found."
            )

        return await create_or_resume_invoice(
            db=db,
            subscription=existing_subscription,
            transaction=existing_transaction,
            account=account,
            plan=existing_plan,
        )

    # -----------------------------------------------------
    # D. VALIDATE SELECTED PLAN FOR A NEW CHECKOUT
    # -----------------------------------------------------

    plan = (
        db.query(Plan)
        .filter(
            Plan.id == plan_id,
            Plan.is_active.is_(True),
        )
        .first()
    )

    if not plan:
        raise PaymentCreationError(
            "The selected plan does not exist or is inactive."
        )

    amount = get_plan_paypal_price(plan)

    currency = (
        plan.paypal_currency
        if plan.paypal_currency
        else plan.currency
    )

    if not currency:
        raise PaymentCreationError(
            "The selected plan does not have a currency configured."
        )

    currency = currency.upper()

    if len(currency) != 3:
        raise PaymentCreationError(
            "The plan has an invalid currency."
        )

    # -----------------------------------------------------
    # E. CREATE PENDING SUBSCRIPTION AND TRANSACTION
    # -----------------------------------------------------

    subscription = Subscription(
        account_id=account.id,
        plan_id=plan.id,
        status="pending",
        provider="paypal",
    )

    db.add(subscription)
    db.flush()

    transaction = PaymentTransaction(
        account_id=account.id,
        subscription_id=subscription.id,
        idempotency_key=idempotency_key,
        provider="paypal",
        transaction_type="initial",
        amount=amount,
        currency=currency,
        status="pending",
    )

    db.add(transaction)

    try:
        db.commit()
        db.refresh(subscription)
        db.refresh(transaction)

    except IntegrityError as exc:
        db.rollback()

        # Another request may have created this checkout
        # using the same account and idempotency key.
        existing_transaction = (
            db.query(PaymentTransaction)
            .filter(
                PaymentTransaction.account_id == account.id,
                PaymentTransaction.idempotency_key == idempotency_key,
            )
            .first()
        )

        if not existing_transaction:
            raise PaymentCreationError(
                "The checkout could not be saved because of "
                "a database constraint. Please try again."
            ) from exc

        existing_subscription = (
            db.query(Subscription)
            .filter(
                Subscription.id == existing_transaction.subscription_id
            )
            .first()
        )

        if not existing_subscription:
            raise PaymentCreationError(
                "The existing checkout has no associated subscription."
            )

        if existing_subscription.plan_id != plan.id:
            raise PaymentCreationError(
                "This idempotency key is already associated with "
                "a different plan. Use a new checkout key."
            )

        # The other request won the race.
        # Resume its existing invoice rather than creating another.
        return await create_or_resume_invoice(
            db=db,
            subscription=existing_subscription,
            transaction=existing_transaction,
            account=account,
            plan=plan,
        )

    except Exception as exc:
        db.rollback()

        raise PaymentCreationError(
            "The checkout could not be saved. "
            "Please retry the same checkout."
        ) from exc

    # -----------------------------------------------------
    # F. CREATE OR RESUME PAYPAL INVOICE
    # -----------------------------------------------------

    return await create_or_resume_invoice(
        db=db,
        subscription=subscription,
        transaction=transaction,
        account=account,
        plan=plan,
    )
