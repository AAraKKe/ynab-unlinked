import re

_NOT_PART_OF_A_NUMBER = re.compile(r"[^\d.,-]")


def parse_amount(raw: str) -> float:
    """
    Parse an amount written with either separator convention.

    Bank exports do not agree on the format: Sabadell and BBVA write "1.234,56 €" while Cobee
    writes "1,234.56 €" or just "21.90 €". The last separator present is the decimal one when
    it is followed by one or two digits; everything else is a thousands separator.
    """
    digits = _NOT_PART_OF_A_NUMBER.sub("", raw)
    if not digits:
        raise ValueError(f"{raw!r} does not contain an amount")

    separators = [index for index, char in enumerate(digits) if char in ".,"]
    if not separators:
        return float(digits)

    last = separators[-1]
    decimals = len(digits) - last - 1
    if 1 <= decimals <= 2 and digits[last + 1 :].isdigit():
        integer_part, fraction = digits[:last], digits[last + 1 :]
        return float(f"{integer_part.replace('.', '').replace(',', '')}.{fraction}")

    return float(digits.replace(".", "").replace(",", ""))
