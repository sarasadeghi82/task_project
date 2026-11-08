import smtplib

TRANSIENT = "transient"
PERMANENT = "permanent"


def classify_error(exc):
    if isinstance(exc, smtplib.SMTPRecipientsRefused):
        codes = [code for code, _ in exc.recipients.values()]
        if codes and all(code >= 500 for code in codes):
            return PERMANENT, "recipient_refused"
        return TRANSIENT, "recipient_temp"

    if isinstance(exc, smtplib.SMTPResponseException):
        kind = PERMANENT if exc.smtp_code >= 500 else TRANSIENT
        return kind, f"smtp_{exc.smtp_code}"

    if isinstance(exc, smtplib.SMTPServerDisconnected):
        return TRANSIENT, "disconnected"

    if isinstance(exc, OSError):
        return TRANSIENT, "network"

    return TRANSIENT, "unknown"