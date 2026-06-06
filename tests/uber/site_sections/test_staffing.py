import cherrypy
import pytest

from uber.config import c
from uber.errors import HTTPRedirect
from uber.models import Attendee, Session
from uber.site_sections import staffing
from uber.utils import localized_now


def test_login_allows_unassigned_volunteer_before_con(monkeypatch):
    monkeypatch.setattr(c, 'AT_THE_CON', False)

    with Session() as session:
        attendee = Attendee(
            first_name='Unassigned',
            last_name='Volunteer',
            email='unassigned@example.com',
            zip_code='21211',
            registered=localized_now(),
            staffing=True)
        session.add(attendee)
        session.commit()
        attendee_id = attendee.id

    with Session() as session, pytest.raises(HTTPRedirect) as excinfo:
        staffing.Root().login(
            session,
            first_name='Unassigned',
            last_name='Volunteer',
            email='unassigned@example.com',
            zip_code='21211')

    assert '/staffing/index' in excinfo.value.urls[0]
    assert cherrypy.session['staffer_id'] == attendee_id
