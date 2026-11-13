# Reliable email delivery

A small Django service that queues emails in the same database
transaction as the change that caused them, and a worker that sends them
with retries.

## Requirements

- Python 3.13 (tested), Django 6.1, PostgreSQL
- Only Django, psycopg and the standard library are used.

## How to run

1. Create the database (once), in `psql`:

   ```sql
   CREATE USER email_user WITH PASSWORD 'email_password' CREATEDB;
   CREATE DATABASE email_service OWNER email_user;
   ```

   These names and the password match `DATABASES` in `settings.py`.
   `CREATEDB` is needed because the test runner creates a temporary database.

2. Install and migrate:

   ```bash
   python -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   python manage.py migrate
   ```

3. Start the worker (stop it with Ctrl+C):

   ```bash
   python manage.py send_emails
   ```

4. In another terminal, open the shell and sign someone up:

   ```bash
   python manage.py shell
   ```

   ```python
   from App.email_processing import sign_up
   sign_up(email="a@example.com")
   ```

   The email is printed in the worker's terminal (console backend, for
   development only: it prints the verification link).

## How to run the tests

```bash
python manage.py test
```

## How it works

- `sign_up` creates the user and queues the email in one transaction.
- The worker checks for due emails every few seconds and sends them with
  `django.core.mail`.
- On a transient failure (timeout, 4xx reply) the email is retried after
  30 seconds, 2 minutes, 10 minutes, 30 minutes, then 1 hour.
- After 6 failed attempts, or at once on a permanent failure (5xx reply,
  rejected address), the email is marked as `failed`.

## Decisions and why

- `Email` table as an outbox, written in the same transaction as the user,
  so a rollback leaves nothing to send.
- `queue_email` raises outside a transaction, because an email committed on
  its own could outlive a rolled-back change.
- `select_for_update(skip_locked=True)` so two workers never take the same
  email and never wait for each other.
- Sending inside the transaction, to keep the code simple. In production, set
  `"timeout"` in the SMTP `OPTIONS` of `MAILERS` so a hanging mail server
  cannot hold a row lock forever.
- Retry time is stored as an absolute timestamp (`next_attempt_at`), so it
  survives restarts.
- Only a short error code is stored, never the exception text, so the link
  cannot leak.
- `Email` has no foreign key to `User`, so the outbox works for any kind of
  email.

## When can an email be sent twice?

The worker sends an email and records the result in the same database
transaction. If the worker dies after the mail server accepted the message
but before that transaction commits, the database rolls back. The email is
still `pending`, so another worker sends it again.

This means delivery is "at least once", not "exactly once": an email is never
lost, but in this rare case it can arrive twice. In normal operation, two
workers do not send the same email, because each one locks the row it is
working on and the other skips it (`SELECT ... FOR UPDATE SKIP LOCKED`).

## What I would do next

- Send the email outside the database transaction. The worker would first
  claim the email with a short transaction and a lease (a "locked until"
  time), then send, then record the result. This way a slow mail server would
  not hold a database connection and a row lock.
- Remove the email body (which contains the verification link) from the
  database once the email is sent.
- Add a test that runs two workers at the same time and shows that no email
  is sent twice.
- Add a test that simulates a worker dying in the middle of a send and shows
  that the email still goes out.


