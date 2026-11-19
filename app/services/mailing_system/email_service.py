
import os
import smtplib
import logging

from email.message import EmailMessage
from email.utils import formataddr
from email.headerregistry import Address
from ssl import create_default_context
from dotenv import load_dotenv


load_dotenv()

logger = logging.getLogger(__name__)


MAIL_USERNAME = os.getenv("MAIL_USERNAME")
MAIL_PASSWORD = os.getenv("MAIL_PASSWORD")
MAIL_FROM_EMAIL = os.getenv("MAIL_FROM_EMAIL")
MAIL_FROM_NAME = os.getenv("MAIL_FROM_NAME", "Your Streaming Platform")

MAIL_SERVER = os.getenv("MAIL_SERVER", "smtp.gmail.com")
MAIL_PORT = int(os.getenv("MAIL_PORT", "587"))
MAIL_USE_TLS = os.getenv("MAIL_USE_TLS", "True").lower() == "true"
MAIL_TIMEOUT = int(os.getenv("MAIL_TIMEOUT", "20"))


class EmailDeliveryError(Exception):
    """Raised when an email cannot be delivered."""


def send_email(
    recipient: str,
    subject: str,
    html_body: str,
    text_body: str,
) -> bool:
    """
    Send an HTML email with a plain-text fallback.

    This function can be reused for registration,
    password resets, subscription reminders, and more.
    """

    if not all([
        MAIL_USERNAME,
        MAIL_PASSWORD,
        MAIL_FROM_EMAIL,
    ]):
        raise EmailDeliveryError(
            "Email configuration is incomplete. "
            "Check your environment variables."
        )

    if "\r" in recipient or "\n" in recipient:
        raise EmailDeliveryError("Invalid recipient address.")

    try:
        message = EmailMessage()

        message["Subject"] = subject
        message["From"] = formataddr(
            (MAIL_FROM_NAME, MAIL_FROM_EMAIL)
        )
        message["To"] = recipient

        # Plain-text fallback.
        message.set_content(text_body)

        # HTML version.
        message.add_alternative(
            html_body,
            subtype="html",
        )

        smtp_context = create_default_context()

        if MAIL_USE_TLS:
            with smtplib.SMTP(
                MAIL_SERVER,
                MAIL_PORT,
                timeout=MAIL_TIMEOUT,
            ) as server:

                server.ehlo()

                server.starttls(context=smtp_context)

                server.ehlo()

                server.login(
                    MAIL_USERNAME,
                    MAIL_PASSWORD,
                )

                server.send_message(message)

        else:
            raise EmailDeliveryError(
                "Unencrypted SMTP connections are not supported."
            )

        logger.info(
            "Email successfully submitted to SMTP for delivery: %s",
            recipient,
        )

        return True

    except EmailDeliveryError:
        raise

    except smtplib.SMTPAuthenticationError as exc:
        logger.exception(
            "Gmail SMTP authentication failed. SMTP code: %s",
            exc.smtp_code,
        )

        raise EmailDeliveryError(
            "Gmail rejected the SMTP credentials. "
            "Check your Gmail App Password."
        ) from exc

    except smtplib.SMTPConnectError as exc:
        logger.exception("Could not connect to Gmail SMTP.")

        raise EmailDeliveryError(
            "Could not establish a connection to Gmail."
        ) from exc

    except smtplib.SMTPException as exc:
        logger.exception(
            "Gmail SMTP error: %s",
            exc,
        )

        raise EmailDeliveryError(
            "Gmail encountered an SMTP delivery error."
        ) from exc

    except OSError as exc:
        logger.exception(
            "Network or operating system error during email delivery."
        )

        raise EmailDeliveryError(
            "Could not connect to the email server."
        ) from exc
