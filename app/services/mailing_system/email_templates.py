
from html import escape


def registration_verification_email(
    verification_code: str,
    platform_name: str = "Your Streaming Platform",
    expiry_minutes: int = 10,
) -> dict:
    """
    Generate the registration verification email.

    Returns:
        subject
        html
        text
    """

    safe_platform_name = escape(platform_name)
    safe_code = escape(verification_code)

    subject = f"Verify your email address - {platform_name}"

    html_body = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Verify your email</title>
    </head>

    <body style="
        margin: 0;
        padding: 30px 15px;
        background-color: #f4f5f7;
        font-family: Arial, Helvetica, sans-serif;
        color: #222222;
    ">

        <div style="
            max-width: 520px;
            margin: 0 auto;
            background-color: #ffffff;
            border-radius: 12px;
            overflow: hidden;
            border: 1px solid #e5e7eb;
        ">

            <div style="
                background-color: #111827;
                padding: 28px 25px;
                text-align: center;
            ">
                <h1 style="
                    margin: 0;
                    color: #ffffff;
                    font-size: 23px;
                    font-weight: 700;
                ">
                    {safe_platform_name}
                </h1>
            </div>

            <div style="padding: 35px 28px;">

                <h2 style="
                    margin-top: 0;
                    font-size: 22px;
                    color: #111827;
                ">
                    Verify your email address
                </h2>

                <p style="
                    font-size: 15px;
                    line-height: 1.7;
                    color: #4b5563;
                ">
                    Welcome! Thank you for creating an account
                    with {safe_platform_name}.
                </p>

                <p style="
                    font-size: 15px;
                    line-height: 1.7;
                    color: #4b5563;
                ">
                    To complete your registration, enter the
                    verification code below.
                </p>

                <div style="
                    margin: 30px 0;
                    padding: 25px 15px;
                    background-color: #f3f4f6;
                    border-radius: 10px;
                    text-align: center;
                ">

                    <div style="
                        font-size: 34px;
                        font-weight: 700;
                        letter-spacing: 9px;
                        color: #111827;
                    ">
                        {safe_code}
                    </div>

                </div>

                <p style="
                    text-align: center;
                    font-size: 14px;
                    color: #6b7280;
                ">
                    This verification code expires in
                    <strong>{expiry_minutes} minutes</strong>.
                </p>

                <p style="
                    margin-top: 30px;
                    font-size: 14px;
                    line-height: 1.7;
                    color: #6b7280;
                ">
                    If you did not create this account,
                    you can safely ignore this email.
                </p>

            </div>

            <div style="
                padding: 20px;
                background-color: #f9fafb;
                border-top: 1px solid #e5e7eb;
                text-align: center;
            ">

                <p style="
                    margin: 0;
                    font-size: 12px;
                    color: #9ca3af;
                ">
                    This is an automated account notification.
                    Please do not reply to this email.
                </p>

                <p style="
                    margin: 10px 0 0;
                    font-size: 12px;
                    color: #9ca3af;
                ">
                    &copy; {safe_platform_name}
                </p>

            </div>

        </div>

    </body>
    </html>
    """

    text_body = f"""
{platform_name}

VERIFY YOUR EMAIL ADDRESS

Welcome! Thank you for creating an account.

Your registration verification code is:

{verification_code}

This code expires in {expiry_minutes} minutes.

If you did not create this account, you can safely ignore this email.

This is an automated notification. Please do not reply.
"""

    return {
        "subject": subject,
        "html": html_body,
        "text": text_body,
    }
