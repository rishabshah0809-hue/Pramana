from datetime import date, datetime

from app.timeutil import IST, expected_last_session, market_is_open

HOL = {date(2026, 10, 2)}  # FIXTURE holiday for the test only


def at(y, m, d, hh, mm):
    return datetime(y, m, d, hh, mm, tzinfo=IST)


def test_market_open_hours():
    assert market_is_open(at(2026, 9, 25, 10, 0), "09:15", "15:30", set())   # Friday
    assert not market_is_open(at(2026, 9, 25, 9, 0), "09:15", "15:30", set())
    assert not market_is_open(at(2026, 9, 26, 11, 0), "09:15", "15:30", set())  # Saturday
    assert not market_is_open(at(2026, 10, 2, 11, 0), "09:15", "15:30", HOL)


def test_expected_last_session():
    assert expected_last_session(at(2026, 9, 25, 16, 0), "09:15", set()) == date(2026, 9, 25)
    assert expected_last_session(at(2026, 9, 25, 8, 0), "09:15", set()) == date(2026, 9, 24)
    assert expected_last_session(at(2026, 9, 27, 12, 0), "09:15", set()) == date(2026, 9, 25)
    # Saturday 3 Oct, with Fri 2 Oct a holiday -> Thursday 1 Oct
    assert expected_last_session(at(2026, 10, 3, 12, 0), "09:15", HOL) == date(2026, 10, 1)
