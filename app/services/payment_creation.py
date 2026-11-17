
from decimal import Decimal, InvalidOperation
from uuid import UUID
from urllib.parse import urlparse
import logging

from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from app.models.identity import Account
from app.models.commercial import Plan, Subscription
from app.models.payment_transaction import PaymentTransaction


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

    The checkout creation function is responsible only for:
    1. Creating the PayPal invoice.
    2. Extracting the PayPal invoice ID.
    3. Saving the invoice ID in the database.
    4. Returning the pending checkout response.

    Invoice retrieval and payment verification belong
    to the separate reconciliation engine.
    """

    # -----------------------------------------------------
    # A. REUSE EXISTING INVOICE IF ONE IS ALREADY SAVED
    # -----------------------------------------------------

    if transaction.provider_invoice_id:

        logger.info(
            "LUMINA PAYPAL: Existing invoice found. "
            "Transaction=%s Invoice=%s",
            transaction.id,
            transaction.provider_invoice_id,
        )

        return format_payment_response(
            subscription,
            transaction,
        )

    # -----------------------------------------------------
    # B. CREATE NEW PAYPAL INVOICE
    # -----------------------------------------------------

    try:

        logger.info(
            "LUMINA PAYPAL STAGE 1: Creating invoice. "
            "Transaction=%s",
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

        logger.exception(
            "LUMINA PAYPAL: Invoice creation failed. "
            "Transaction=%s",
            transaction.id,
        )

        raise PaymentCreationError(
            "PayPal invoice creation failed. "
            f"PayPal error: {str(exc)}"
        ) from exc

    # -----------------------------------------------------
    # C. EXTRACT AND VALIDATE INVOICE ID
    # -----------------------------------------------------

    invoice_id = extract_paypal_invoice_id(
        invoice_response
    )

    if not invoice_id:

        logger.error(
            "LUMINA PAYPAL: No invoice ID returned. "
            "Transaction=%s Response=%s",
            transaction.id,
            invoice_response,
        )

        raise PaymentCreationError(
            "PayPal did not return a valid invoice ID."
        )

    logger.info(
        "LUMINA PAYPAL STAGE 1 SUCCESS: "
        "Invoice ID received. Transaction=%s Invoice=%s",
        transaction.id,
        invoice_id,
    )

    # -----------------------------------------------------
    # D. SAVE INVOICE ID
    # -----------------------------------------------------

    try:

        transaction.provider_invoice_id = invoice_id

        transaction.provider_invoice_status = (
            invoice_response.get("status", "CREATED")
        )

        db.add(transaction)
        db.commit()
        db.refresh(transaction)

        logger.info(
            "LUMINA PAYPAL STAGE 2 SUCCESS: "
            "Invoice ID saved. Transaction=%s Invoice=%s",
            transaction.id,
            invoice_id,
        )

    except Exception as exc:

        db.rollback()

        logger.exception(
            "LUMINA PAYPAL: Failed to save invoice ID. "
            "Transaction=%s Invoice=%s",
            transaction.id,
            invoice_id,
        )

        raise PaymentCreationError(
            "PayPal returned an invoice ID, but Lumina "
            "could not save it in the database."
        ) from exc

    # -----------------------------------------------------
    # E. RETURN PENDING CHECKOUT RESPONSE
    # -----------------------------------------------------

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
