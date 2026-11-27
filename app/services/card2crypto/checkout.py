
import hashlib
import logging
import secrets

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from urllib.parse import urlencode
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.identity import Account
from app.models.commercial import (
    Plan,
    Subscription,
    Card2CryptoPayment,
)

from app.models.payment_transaction import PaymentTransaction

from app.services.payment_security import (
    encrypt_payment_token,
    fingerprint_payment_token,
)

from app.services.card2crypto.client import (
    convert_zar_to_usd,
    create_payment_wallet,
    Card2CryptoError,
)


logger = logging.getLogger(__name__)


CARD2CRYPTO_CHECKOUT_BASE_URL = (
    "https://pay.card2crypto.org/pay.php"
)

CARD2CRYPTO_PROVIDER = "hosted"

CARD2CRYPTO_DOMAIN = "pay.card2crypto.org"

CARD2CRYPTO_CALLBACK_PATH = (
    "/api/v1/card2crypto/callback"
)

USD_CENT = Decimal("0.01")


def _money(value: Decimal) -> Decimal:
    """
    Round a monetary amount to two decimal places.
    """

    return value.quantize(
        USD_CENT,
        rounding=ROUND_HALF_UP,
    )


async def create_card2crypto_checkout(
    db: Session,
    account_id: UUID,
    plan_id: UUID,
    idempotency_key: str,
) -> dict:
    """
    Create a Card2Crypto subscription checkout.

    This function:
    1. Validates the account and plan.
    2. Converts the plan price from ZAR to USD.
    3. Creates a pending Lumina subscription.
    4. Creates a pending payment transaction.
    5. Generates a Card2Crypto payment wallet.
    6. Stores the provider payment information.
    7. Returns the hosted checkout URL.

    Subscription activation happens later through the
    Card2Crypto callback processor.
    """

    if not idempotency_key:
        raise ValueError("An idempotency key is required.")

    merchant_wallet = getattr(
        settings,
        "card2crypto_merchant_wallet",
        "",
    )

    public_backend_url = getattr(
        settings,
        "public_backend_url",
        "",
    )

    if not merchant_wallet:
        raise ValueError(
            "CARD2CRYPTO_MERCHANT_WALLET is not configured."
        )

    if not public_backend_url:
        raise ValueError(
            "PUBLIC_BACKEND_URL is not configured."
        )

    if not public_backend_url.startswith("https://"):
        raise ValueError(
            "PUBLIC_BACKEND_URL must use HTTPS."
        )

    try:
        # --------------------------------------------------
        # 1. Check for an existing checkout attempt.
        # --------------------------------------------------

        existing_transaction = (
            db.query(PaymentTransaction)
            .filter(
                PaymentTransaction.account_id == account_id,
                PaymentTransaction.provider == "card2crypto",
                PaymentTransaction.idempotency_key == idempotency_key,
            )
            .first()
        )

        if existing_transaction:
            existing_payment = (
                db.query(Card2CryptoPayment)
                .filter(
                    Card2CryptoPayment.payment_transaction_id
                    == existing_transaction.id
                )
                .first()
            )

            if (
                existing_payment
                and existing_transaction.status == "pending"
                and existing_payment.status == "pending"
            ):
                return {
                    "success": True,
                    "message": "Existing Card2Crypto checkout returned.",
                    "subscription_id": str(
                        existing_transaction.subscription_id
                    ),
                    "transaction_id": str(
                        existing_transaction.id
                    ),
                    "payment_reference": (
                        existing_payment.payment_reference
                    ),
                    "checkout_url": existing_payment.checkout_url,
                    "amount": str(existing_payment.usd_amount),
                    "currency": "USD",
                    "payment_status": "pending",
                }

            raise ValueError(
                "This idempotency key has already been used. "
                "Please use a new key for another checkout."
            )

        # --------------------------------------------------
        # 2. Validate account.
        # --------------------------------------------------

        account = (
            db.query(Account)
            .filter(Account.id == account_id)
            .first()
        )

        if not account:
            raise ValueError("Account not found.")

        # --------------------------------------------------
        # 3. Validate plan.
        # --------------------------------------------------

        plan = (
            db.query(Plan)
            .filter(Plan.id == plan_id)
            .first()
        )

        if not plan:
            raise ValueError("Subscription plan not found.")

        if not plan.is_active:
            raise ValueError("This subscription plan is inactive.")

        if not plan.card2crypto_enabled:
            raise ValueError(
                "Card2Crypto checkout is not available for this plan."
            )

        if plan.billing_interval.lower() != "monthly":
            raise ValueError(
                "Card2Crypto currently supports monthly subscriptions only."
            )

        if plan.currency != "ZAR":
            raise ValueError(
                "Card2Crypto checkout currently requires ZAR plans."
            )

        # --------------------------------------------------
        # 4. Calculate original ZAR amount.
        # --------------------------------------------------

        zar_amount = (
            Decimal(str(plan.price_minor)) / Decimal("1000")
        )

        zar_amount = zar_amount.quantize(
            USD_CENT,
            rounding=ROUND_HALF_UP,
        )

        if zar_amount <= 0:
            raise ValueError(
                "The subscription plan price must be greater than zero."
            )

        # --------------------------------------------------
        # 5. Convert ZAR to USD.
        # --------------------------------------------------

        conversion = await convert_zar_to_usd(zar_amount)

        usd_amount = _money(
            conversion["usd_amount"]
        )

        exchange_rate = conversion["exchange_rate"]

        minimum_usd = max(
            Decimal(str(plan.card2crypto_minimum_usd)),
            Decimal("5.00"),
        )

        if usd_amount < minimum_usd:
            raise ValueError(
                f"Card2Crypto PayPal requires a minimum payment of "
                f"${minimum_usd:.2f} USD. Your checkout amount is "
                f"${usd_amount:.2f} USD."
            )

        # --------------------------------------------------
        # 6. Create pending Lumina subscription.
        # --------------------------------------------------

        subscription = Subscription(
            account_id=account.id,
            plan_id=plan.id,
            status="pending",
            provider="card2crypto",
        )

        db.add(subscription)
        db.flush()

        # --------------------------------------------------
        # 7. Create pending payment transaction.
        # --------------------------------------------------

        transaction = PaymentTransaction(
            account_id=account.id,
            subscription_id=subscription.id,
            transaction_type="initial",
            provider="card2crypto",
            amount=usd_amount,
            currency="USD",
            status="pending",
            idempotency_key=idempotency_key,
        )

        db.add(transaction)
        db.flush()

        # Use the Lumina transaction UUID as the provider reference.
        payment_reference = str(transaction.id)

        # --------------------------------------------------
        # 8. Generate callback authentication token.
        # --------------------------------------------------

        callback_token = secrets.token_urlsafe(48)

        callback_token_hash = fingerprint_payment_token(
            callback_token
        )

        callback_url = (
            public_backend_url.rstrip("/")
            + CARD2CRYPTO_CALLBACK_PATH
        )

        callback_url += "?" + urlencode({
            "number": payment_reference,
            "callback_token": callback_token,
        })

        # --------------------------------------------------
        # 9. Generate Card2Crypto receiving wallet.
        # --------------------------------------------------

        wallet = await create_payment_wallet(
            merchant_wallet=merchant_wallet,
            callback_url=callback_url,
        )

        # --------------------------------------------------
        # 10. Build hosted checkout URL.
        # --------------------------------------------------

        checkout_params = {
            "address": wallet["address_in"],
            "amount": f"{usd_amount:.2f}",
            "email": account.email,
            "currency": "USD",
            "provider": CARD2CRYPTO_PROVIDER,
        }

        checkout_url = (
            CARD2CRYPTO_CHECKOUT_BASE_URL
            + "?"
            + urlencode(checkout_params)
        )
        # --------------------------------------------------
        # 11. Store Card2Crypto-specific information.
        # --------------------------------------------------

        card2crypto_payment = Card2CryptoPayment(
            payment_transaction_id=transaction.id,
            payment_reference=payment_reference,

            encrypted_address_in=wallet["address_in"],
            polygon_address_in=wallet["polygon_address_in"],

            encrypted_ipn_token=encrypt_payment_token(
                wallet["ipn_token"]
            ),

            callback_token_hash=callback_token_hash,

            zar_amount=zar_amount,
            usd_amount=usd_amount,
            exchange_rate=exchange_rate,

            checkout_url=checkout_url,

            status="pending",
        )

        db.add(card2crypto_payment)

        # --------------------------------------------------
        # 12. Commit checkout records.
        # --------------------------------------------------

        db.commit()

        db.refresh(subscription)
        db.refresh(transaction)
        db.refresh(card2crypto_payment)

        logger.info(
            "Card2Crypto checkout created. "
            "Transaction: %s, Account: %s",
            transaction.id,
            account.id,
        )

        return {
            "success": True,
            "message": "Card2Crypto checkout created successfully.",
            "subscription_id": str(subscription.id),
            "transaction_id": str(transaction.id),
            "payment_reference": payment_reference,
            "checkout_url": checkout_url,
            "amount": str(usd_amount),
            "currency": "USD",
            "original_amount": str(zar_amount),
            "original_currency": "ZAR",
            "exchange_rate": str(exchange_rate),
            "payment_status": "pending",
        }

    except Card2CryptoError:
        db.rollback()
        logger.exception(
            "Card2Crypto provider request failed."
        )
        raise

    except IntegrityError:
        db.rollback()
        logger.exception(
            "Card2Crypto checkout database integrity error."
        )
        raise ValueError(
            "Unable to create checkout because of a database conflict. "
            "Please retry with a new idempotency key."
        )

    except Exception:
        db.rollback()
        logger.exception(
            "Card2Crypto checkout creation failed."
        )
        raise
