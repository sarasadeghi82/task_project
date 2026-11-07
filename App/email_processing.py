import secrets
from django.contrib.auth.models import User
from django.db import connection, transaction
from .models import Email


class NotInTransactionError(RuntimeError):
    pass


def queue_email(*, to, subject, body):
    if not connection.in_atomic_block:
        raise NotInTransactionError(
            "queue_email must be called inside a database transaction"
        )
    return Email.objects.create(to=to, subject=subject, body=body)


def sign_up(*, email):
    token = secrets.token_urlsafe(32)
    link = f"https://example.com/verify/?token={token}"
    with transaction.atomic():
        user = User.objects.create_user(username=email, email=email)
        queue_email(
            to=email,
            subject="Verify your email",
            body=f"Welcome! Verify your account here: {link}",
        )
    return user