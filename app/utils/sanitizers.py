import re


def clean_digits(value: str | None) -> str | None:
    """Strip all non-digit characters from the input string."""
    if not value:
        return None
    digits = re.sub(r"\D", "", str(value).strip())
    return digits or None


def clean_phone(value: str | None) -> str | None:
    """Strip punctuation and whitespace from phone, preserving leading + if present."""
    if not value:
        return None
    val = str(value).strip()
    has_plus = val.startswith("+")
    digits = re.sub(r"\D", "", val)
    if not digits:
        return None
    return f"+{digits}" if has_plus else digits


def clean_email(value: str | None) -> str | None:
    """Normalize emails, converting empty or whitespace-only strings to None."""
    if not value:
        return None
    cleaned = str(value).strip().lower()
    return cleaned or None


def validate_cpf(cpf: str | None) -> bool:
    """
    Validate Brazilian CPF format and check digits (modulo 11).
    Returns True if valid or None/empty (optional validation), False if invalid.
    """
    digits = clean_digits(cpf)
    if not digits:
        return True
    if len(digits) != 11:
        return False
    # Reject known invalid sequences like 11111111111
    if len(set(digits)) == 1:
        return False

    # Check first verification digit
    sum1 = sum(int(digits[i]) * (10 - i) for i in range(9))
    d1 = (sum1 * 10 % 11) % 10
    if d1 != int(digits[9]):
        return False

    # Check second verification digit
    sum2 = sum(int(digits[i]) * (11 - i) for i in range(10))
    d2 = (sum2 * 10 % 11) % 10
    if d2 != int(digits[10]):
        return False

    return True
