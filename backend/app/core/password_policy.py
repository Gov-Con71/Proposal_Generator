"""Password strength policy (GAP_ANALYSIS.md §2.4).

There was no policy at all: a one-character password was accepted at
registration, and nothing could change a password afterwards anyway (§4.3).

The rules here are deliberately few, and deliberately not the classic
"uppercase + digit + symbol" set. Composition rules push people toward
`P@ssw0rd1` — which satisfies every one of them and is in the first thousand
guesses of any real cracking run — while banning the long passphrases that
actually resist attack. Length and a blocklist do the work instead:

* **Length** is the dimension that scales the search space and cannot be
  gamed. 12 is the floor (`settings.password_min_length`).
* **Not obviously guessable** — a small blocklist of the passwords that appear
  at the top of every breach corpus, plus anything derived from the user's own
  email or name, which is where a targeted guess starts.

This is intentionally not a zxcvbn dependency. It could be, and the interface
here would not change; the value of a strength estimator is mostly in the
feedback it gives while typing, which belongs in the client.
"""

import re

from app.core.config import settings


class WeakPasswordError(ValueError):
    """Raised with a message intended to be shown to the person choosing it."""


# The head of the distribution in every published breach corpus. A blocklist
# cannot be exhaustive and is not trying to be: it catches the guesses an
# attacker makes first, which is where the risk is concentrated.
_COMMON = frozenset(
    {
        "password", "passw0rd", "password1", "password123", "passwords",
        "123456", "1234567", "12345678", "123456789", "1234567890",
        "qwerty", "qwertyuiop", "qwerty123", "letmein", "welcome",
        "admin", "administrator", "iloveyou", "monkey", "dragon",
        "football", "baseball", "sunshine", "princess", "trustno1",
        "changeme", "secret", "default", "test1234", "abc123",
        "proposal", "proposalai", "government", "contract",
    }
)

_ALPHANUM_RUN = re.compile(r"[^a-z0-9]")


def _normalise(value: str) -> str:
    """Lowercased, stripped of non-alphanumerics.

    So `P@ssw0rd` and `password` collapse together — leetspeak substitution is
    the first thing a cracking rule set expands, so treating it as strength
    would be pretending.
    """
    swapped = (
        value.lower()
        .replace("@", "a")
        .replace("$", "s")
        .replace("0", "o")
        .replace("1", "i")
        .replace("3", "e")
        .replace("!", "i")
    )
    return _ALPHANUM_RUN.sub("", swapped)


def validate_password(password: str, *, email: str = "", name: str = "") -> None:
    """Raises WeakPasswordError if `password` is unacceptable, else returns None.

    `email` and `name` are optional context: a password built from the account's
    own identifiers is the first targeted guess, and it survives every
    length-and-composition rule ever written.
    """
    if not password or password.strip() != password:
        raise WeakPasswordError(
            "Password cannot be empty or start or end with a space."
        )

    minimum = settings.password_min_length
    if len(password) < minimum:
        raise WeakPasswordError(
            f"Password must be at least {minimum} characters. Length is what "
            "makes a password hard to crack — a short complicated one is weaker "
            "than a long simple phrase."
        )

    # bcrypt truncates at 72 bytes; accepting more silently ignores the rest,
    # so two different passwords could open the same account.
    if len(password.encode("utf-8")) > 72:
        raise WeakPasswordError("Password must be at most 72 bytes.")

    flat = _normalise(password)
    if _is_padded_common_word(flat):
        raise WeakPasswordError(
            "That password appears in every breached-password list. Choose "
            "something unrelated to common words."
        )

    if len(set(password)) < 5:
        raise WeakPasswordError(
            "Password repeats too few distinct characters."
        )

    for label, source in (("email address", email), ("name", name)):
        for part in _identifier_parts(source):
            if part and part in flat:
                raise WeakPasswordError(
                    f"Password must not contain your {label}."
                )


# How much trailing padding still counts as "the same common word". `password`
# reaches the 12-character floor as `password1234` or `P@ssw0rd!!!!!`, and an
# exact-match blocklist waves both through — which is precisely the mutation a
# cracking rule set tries first, so a length floor without this is theatre.
_MAX_PADDING = 6


def _is_padded_common_word(flat: str) -> bool:
    """True when `flat` is a blocklisted word plus a short suffix.

    Prefix rather than substring: a common word buried inside a long passphrase
    (`correcthorsesecretbattery`) is not what gets cracked first, and rejecting
    it would push people toward shorter passwords to satisfy the checker.
    """
    if flat in _COMMON:
        return True
    return any(
        flat.startswith(word) and len(flat) - len(word) <= _MAX_PADDING
        for word in _COMMON
    )


def _identifier_parts(source: str) -> list[str]:
    """Meaningful fragments of an email or name, normalised for comparison.

    The local part of an address and each name token, minus anything so short
    that requiring its absence would reject sensible passwords.
    """
    if not source:
        return []
    local = source.split("@")[0]
    parts = re.split(r"[^A-Za-z0-9]+", local)
    return [p for p in (_normalise(x) for x in parts) if len(p) >= 4]
