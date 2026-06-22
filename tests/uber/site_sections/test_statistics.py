from datetime import date

import pytest

from uber.config import c
from uber.models import Attendee, FoodRestrictions, Session
from uber.site_sections import statistics


def _make_attendee(session, first_name, arrival, departure, restrictions=None, badge_status=None):
    attendee = Attendee(
        first_name=first_name,
        last_name='Test',
        email=first_name.lower() + '@example.com',
        registered=date(2026, 1, 1),
        arrival_date=arrival,
        departure_date=departure,
        badge_status=badge_status if badge_status else c.NEW_STATUS,
    )
    session.add(attendee)
    session.commit()
    if restrictions:
        fr = FoodRestrictions(
            attendee_id=attendee.id,
            standard=','.join(str(r) for r in restrictions),
        )
        session.add(fr)
        session.commit()
    return attendee


def test_dietary_counts_by_day():
    with Session() as session:
        _make_attendee(session, 'GlutenFree', date(2026, 6, 1), date(2026, 6, 4), [c.GLUTEN])
        _make_attendee(session, 'Vegan', date(2026, 6, 2), date(2026, 6, 5), [c.VEGAN])
        _make_attendee(session, 'NoRestrictions', date(2026, 6, 1), date(2026, 6, 3), [])

        result = statistics._dietary_counts(session)

    assert result['dates'] == [date(2026, 6, 1), date(2026, 6, 2), date(2026, 6, 3), date(2026, 6, 4), date(2026, 6, 5)]

    gluten_label = c.FOOD_RESTRICTIONS[c.GLUTEN]
    vegan_label = c.FOOD_RESTRICTIONS[c.VEGAN]

    day_rows = {row['date']: row for row in result['rows']}
    assert day_rows[date(2026, 6, 1)]['counts'][gluten_label] == 1
    assert day_rows[date(2026, 6, 1)]['counts'][vegan_label] == 0
    assert day_rows[date(2026, 6, 1)]['total_present'] == 2

    assert day_rows[date(2026, 6, 2)]['counts'][gluten_label] == 1
    assert day_rows[date(2026, 6, 2)]['counts'][vegan_label] == 1
    assert day_rows[date(2026, 6, 2)]['total_present'] == 3

    assert day_rows[date(2026, 6, 3)]['counts'][gluten_label] == 1
    assert day_rows[date(2026, 6, 3)]['counts'][vegan_label] == 1
    assert day_rows[date(2026, 6, 3)]['total_present'] == 2

    assert day_rows[date(2026, 6, 4)]['counts'][gluten_label] == 0
    assert day_rows[date(2026, 6, 4)]['counts'][vegan_label] == 1
    assert day_rows[date(2026, 6, 4)]['total_present'] == 1

    assert day_rows[date(2026, 6, 5)]['counts'][gluten_label] == 0
    assert day_rows[date(2026, 6, 5)]['counts'][vegan_label] == 0
    assert day_rows[date(2026, 6, 5)]['total_present'] == 0

    totals = result['totals']
    assert totals[gluten_label] == 3
    assert totals[vegan_label] == 3
    assert totals['total_present'] == 8


def test_dietary_counts_excludes_invalid_badges():
    with Session() as session:
        _make_attendee(session, 'Valid', date(2026, 6, 1), date(2026, 6, 3), [c.GLUTEN])
        _make_attendee(session, 'Invalid', date(2026, 6, 1), date(2026, 6, 3), [c.GLUTEN], badge_status=c.INVALID_STATUS)

        result = statistics._dietary_counts(session)

    gluten_label = c.FOOD_RESTRICTIONS[c.GLUTEN]
    assert result['totals'][gluten_label] == 2
    assert result['totals']['total_present'] == 2
