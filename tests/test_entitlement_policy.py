from datetime import datetime, timedelta, timezone

import pytest
from serentable.payments import add_calendar_months

SEOUL = timezone(timedelta(hours=9))


@pytest.mark.parametrize(
    ("start", "months", "expected"),
    [
        # End-of-month clamping, never a 30-day approximation.
        ((2027, 1, 31, 20, 15), 1, (2027, 2, 28, 20, 15)),
        ((2028, 1, 31, 9, 0), 1, (2028, 2, 29, 9, 0)),
        ((2027, 1, 30, 9, 0), 1, (2027, 2, 28, 9, 0)),
        ((2027, 3, 31, 9, 0), 1, (2027, 4, 30, 9, 0)),
        ((2027, 2, 28, 9, 0), 1, (2027, 3, 28, 9, 0)),
        ((2027, 8, 31, 9, 0), 6, (2028, 2, 29, 9, 0)),
        ((2027, 11, 30, 9, 0), 3, (2028, 2, 29, 9, 0)),
        # Year rollover.
        ((2026, 12, 15, 23, 59), 1, (2027, 1, 15, 23, 59)),
        ((2026, 12, 31, 12, 0), 3, (2027, 3, 31, 12, 0)),
        ((2026, 10, 16, 18, 0), 6, (2027, 4, 16, 18, 0)),
    ],
)
def test_calendar_months_clamp_to_month_end_in_seoul(start, months, expected):
    result = add_calendar_months(datetime(*start, tzinfo=SEOUL), months)
    assert result == datetime(*expected, tzinfo=SEOUL)


def test_calendar_months_count_in_seoul_local_date_not_utc():
    # 2027-01-31 15:30 UTC is already 2027-02-01 00:30 in Seoul.
    paid = datetime(2027, 1, 31, 15, 30, tzinfo=timezone.utc)
    result = add_calendar_months(paid, 1)
    assert result == datetime(2027, 3, 1, 0, 30, tzinfo=SEOUL)
    # 2027-01-30 15:30 UTC is 2027-01-31 00:30 in Seoul: clamps to Feb 28.
    assert add_calendar_months(datetime(2027, 1, 30, 15, 30, tzinfo=timezone.utc), 1) == (
        datetime(2027, 2, 28, 0, 30, tzinfo=SEOUL)
    )
