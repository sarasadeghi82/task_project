from django.core.mail.backends.base import BaseEmailBackend


class FakeEmailBackend(BaseEmailBackend):
    outbox = []
    failures = []

    def send_messages(self, email_messages):
        if FakeEmailBackend.failures:
            raise FakeEmailBackend.failures.pop(0)
        FakeEmailBackend.outbox.extend(email_messages)
        return len(email_messages)

    @classmethod
    def reset(cls):
        cls.outbox = []
        cls.failures = []