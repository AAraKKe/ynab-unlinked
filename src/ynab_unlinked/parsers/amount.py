import re

_CURRENCY_MARKERS = re.compile(r"€|EUR|\s")
_AMOUNT = re.compile(r"^-?[\d.,]+$")


def parse_amount(raw: str) -> float:
    """
    Parse an amount written with either separator convention.

    Bank exports do not agree on the format: Sabadell and BBVA write "1.234,56 €" while Cobee
    writes "€1,234.56" or just "21.90 €". The last separator present is the decimal one when
    it is followed by one or two digits; everything else is a thousands separator.

    Anything beyond a sign, digits, separators and the currency marker is not an amount, so a
    line such as "Ahorras €9.86" raises rather than parsing as 9.86.
    """
    digits = _CURRENCY_MARKERS.sub("", raw)
    if not _AMOUNT.match(digits):
        raise ValueError(f"{raw!r} is not an amount")

    separators = [index for index, char in enumerate(digits) if char in ".,"]
    if not separators:
        return float(digits)

    last = separators[-1]
    decimals = len(digits) - last - 1
    if 1 <= decimals <= 2:
        integer_part, fraction = digits[:last], digits[last + 1 :]
        return float(f"{integer_part.replace('.', '').replace(',', '')}.{fraction}")

    return float(digits.replace(".", "").replace(",", ""))
