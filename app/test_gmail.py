
import os
import traceback

from dotenv import load_dotenv

load_dotenv(override=True)

from app.services.mailing_system.email_service import send_email

recipient = os.getenv("MAIL_USERNAME")

print("\n========== EMAIL SERVICE TEST ==========")

try:
    result = send_email(
        recipient=recipient,
        subject="Lumina RSA - SMTP Integration Test",
        html_body="""
            <html>
                <body>
                    <h2>Lumina RSA</h2>
                    <p>Your email service is working correctly!</p>
                    <p>This is a test email from your FastAPI backend.</p>
                </body>
            </html>
        """,
        text_body="""
        Lumina RSA

        Your email service is working correctly!

        This is a test email from your FastAPI backend.
        """,
    )

    print("\nSUCCESS:", result)
    print("Test email submitted successfully.")

except Exception as exc:
    print("\nEMAIL SERVICE FAILED")
    print("Exception:", type(exc).__name__)
    print("Message:", str(exc))

    print("\nFULL ERROR TRACEBACK:")
    traceback.print_exc()

print("\n========== TEST FINISHED ==========\n")
