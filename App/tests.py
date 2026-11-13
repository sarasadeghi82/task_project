import smtplib
from datetime import timedelta

from django.contrib.auth.models import User
from django.db import transaction
from django.test import TransactionTestCase, override_settings
from django.utils import timezone

from .delivery import BACKOFF_SECONDS, MAX_ATTEMPTS, process_one
from .models import Email
from .email_processing import NotInTransactionError, queue_email, sign_up
from .testing import FakeEmailBackend


@override_settings(
    MAILERS={"default": {"BACKEND": "App.testing.FakeEmailBackend"}}
)
class EmailDeliveryTests(TransactionTestCase):
    def setUp(self):
        FakeEmailBackend.reset()

    def make_email(self, **kwargs):
        data = {"to": "a@example.com", "subject": "Hi", "body": "Body"}
        data.update(kwargs)
        return Email.objects.create(**data)

    def test_queue_email_outside_transaction_raises(self):
        with self.assertRaises(NotInTransactionError):
            queue_email(to="a@example.com", subject="Hi", body="Body")
        self.assertEqual(Email.objects.count(), 0)

    def test_sign_up_creates_user_and_pending_email(self):
        sign_up(email="a@example.com")
        self.assertEqual(User.objects.count(), 1)
        email = Email.objects.get()
        self.assertEqual(email.to, "a@example.com")
        self.assertEqual(email.status, Email.Status.PENDING)
        self.assertIn("token=", email.body)

    def test_rollback_leaves_nothing_to_send(self):
        with self.assertRaises(RuntimeError):
            with transaction.atomic():
                sign_up(email="a@example.com")
                raise RuntimeError("something failed after sign_up")
        self.assertEqual(User.objects.count(), 0)
        self.assertEqual(Email.objects.count(), 0)
        self.assertFalse(process_one())
        self.assertEqual(FakeEmailBackend.outbox, [])

    def test_successful_send_marks_email_sent(self):
        email = self.make_email()
        self.assertTrue(process_one())
        email.refresh_from_db()
        self.assertEqual(email.status, Email.Status.SENT)
        self.assertEqual(email.attempts, 1)
        self.assertEqual(len(FakeEmailBackend.outbox), 1)
        self.assertFalse(process_one())

    def test_transient_failure_is_retried_on_schedule(self):
        email = self.make_email()
        now = timezone.now()
        for attempt, delay in enumerate(BACKOFF_SECONDS, start=1):
            FakeEmailBackend.failures = [TimeoutError()]
            self.assertTrue(process_one(now=now))
            email.refresh_from_db()
            self.assertEqual(email.status, Email.Status.PENDING)
            self.assertEqual(email.attempts, attempt)
            self.assertEqual(email.next_attempt_at, now + timedelta(seconds=delay))
            self.assertFalse(process_one(now=now + timedelta(seconds=delay - 1)))
            now += timedelta(seconds=delay)

        self.assertTrue(process_one(now=now))
        email.refresh_from_db()
        self.assertEqual(email.status, Email.Status.SENT)
        self.assertEqual(email.attempts, 6)

    def test_permanent_failure_stops_at_once(self):
        email = self.make_email()
        FakeEmailBackend.failures = [smtplib.SMTPResponseException(550, b"no such user")]
        process_one()
        email.refresh_from_db()
        self.assertEqual(email.status, Email.Status.FAILED)
        self.assertEqual(email.attempts, 1)
        self.assertEqual(email.last_error, "smtp_550")
        self.assertFalse(process_one(now=timezone.now() + timedelta(days=1)))

    def test_sixth_failed_attempt_marks_email_failed(self):
        email = self.make_email(attempts=MAX_ATTEMPTS - 1)
        FakeEmailBackend.failures = [TimeoutError()]
        process_one()
        email.refresh_from_db()
        self.assertEqual(email.status, Email.Status.FAILED)
        self.assertEqual(email.attempts, MAX_ATTEMPTS)
        self.assertEqual(email.last_error, "network")

    def test_error_field_never_contains_message_text(self):
        email = self.make_email(body="https://example.com/verify/?token=SECRET")
        FakeEmailBackend.failures = [
            smtplib.SMTPResponseException(451, b"rejected token=SECRET")
        ]
        process_one()
        email.refresh_from_db()
        self.assertEqual(email.last_error, "smtp_451")
        self.assertNotIn("SECRET", email.last_error)
