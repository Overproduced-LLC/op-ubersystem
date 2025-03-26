"""
IMPORTANT NOTES FOR CHANGING/ADDING EMAIL CATEGORIES:

'ident' is a unique ID for that email category that must not change after
emails in that category have started to send.

*****************************************************************************
IF YOU CHANGE THE IDENT FOR A CATEGORY, IT WILL CAUSE ANY EMAILS THAT HAVE
ALREADY SENT FOR THAT CATEGORY TO RE-SEND.
*****************************************************************************

"""

import os
import jinja2
from datetime import datetime, timedelta
import pathlib

from pockets import listify
from pytz import UTC
from sqlalchemy.orm import joinedload, subqueryload

from uber.config import c
from uber import decorators
from uber.jinja import JinjaEnv
from uber.models import (AdminAccount, Attendee, AttendeeAccount, AutomatedEmail, Department,
                         Group, PromoCodeGroup, Room, RoomAssignment, LotteryApplication, Shift)
from uber.utils import after, before, days_after, days_before, days_between, localized_now, DeptChecklistConf


class AutomatedEmailFixture:
    """
    Represents one category of emails that we send out.
    An example of an email category would be "Your registration has been confirmed".
    """

    # a list of queries to run during each automated email sending run to
    # return particular model instances of a given type.
    queries = {
        Attendee: lambda session: session.all_attendees().options(
            subqueryload(Attendee.admin_account),
            subqueryload(Attendee.group),
            subqueryload(Attendee.shifts).subqueryload(Shift.job),
            subqueryload(Attendee.assigned_depts),
            subqueryload(Attendee.dept_membership_requests),
            subqueryload(Attendee.checklist_admin_depts).subqueryload(Department.dept_checklist_items),
            subqueryload(Attendee.dept_memberships),
            subqueryload(Attendee.dept_memberships_with_role),
            subqueryload(Attendee.depts_where_working),
            subqueryload(Attendee.hotel_requests)),
        AttendeeAccount: lambda session: session.query(AttendeeAccount).options(
            subqueryload(AttendeeAccount.attendees)),
        Group: lambda session: session.query(Group).options(
            subqueryload(Group.attendees)).order_by(Group.id),
        LotteryApplication: lambda session: session.query(LotteryApplication).options(
            subqueryload(LotteryApplication.attendee)),
        PromoCodeGroup: lambda session: session.query(PromoCodeGroup).options(
            subqueryload(PromoCodeGroup.buyer)).order_by(PromoCodeGroup.id),
        Room: lambda session: session.query(Room).options(
            subqueryload(Room.assignments).subqueryload(RoomAssignment.attendee)),
    }

    def __init__(
            self,
            model,
            subject,
            template,
            filter,
            ident,
            *,
            query=(),
            query_options=(),
            when=(),
            sender=None,
            cc=(),
            bcc=(),
            replyto=(),
            needs_approval=True,
            allow_at_the_con=False,
            allow_post_con=False,
            extra_data=None):

        assert ident, 'AutomatedEmail ident may not be empty.'
        assert ident not in AutomatedEmail._fixtures, 'AutomatedEmail ident "{}" already registered.'.format(ident)

        AutomatedEmail._fixtures[ident] = self

        self.model = model
        self.subject = subject \
            .replace('{EVENT_NAME}', c.EVENT_NAME) \
            .replace('{EVENT_YEAR}', c.EVENT_YEAR) \
            .replace('{EVENT_DATE}', c.EPOCH.strftime('%b %Y'))
        self.template = template
        self.format = 'text' if template.endswith('.txt') else 'html'
        self.filter = lambda x: (x.gets_emails and filter(x))
        self.ident = ident
        self.query = listify(query)
        self.query_options = listify(query_options)
        self.sender = sender or c.REGDESK_EMAIL
        self.cc = listify(cc)
        self.bcc = listify(bcc)
        self.replyto = listify(replyto)
        self.needs_approval = needs_approval
        self.allow_at_the_con = allow_at_the_con
        self.allow_post_con = allow_post_con
        self.extra_data = extra_data or {}

        when = listify(when)

        after = [d.active_after for d in when if d.active_after]
        self.active_after = min(after) if after else None

        before = [d.active_before for d in when if d.active_before]
        self.active_before = max(before) if before else None

        self.template_plugin_name = ""
        self.template_url = ""

    def update_template_plugin_info(self):
        env = JinjaEnv.env()
        try:
            template_path = pathlib.Path(env.get_or_select_template(os.path.join('emails', self.template)).filename)
            path_offset = 0
            if template_path.parts[2] == 'plugins':
                path_offset = 2
            self.template_plugin_name = template_path.parts[2 + path_offset]
            self.template_url = (f"https://github.com/magfest/{self.template_plugin_name}/tree/main/"
                                 f"{self.template_plugin_name}/{pathlib.Path(*template_path.parts[(3 + path_offset):]).as_posix()}")
        except jinja2.exceptions.TemplateNotFound:
            self.template_plugin_name = "ERROR: TEMPLATE NOT FOUND"
            self.template_url = ""
        return self.template_plugin_name, self.template_url

    def update_subject_line(self, subject):
        self.subject = subject \
            .replace('{EVENT_NAME}', c.EVENT_NAME) \
            .replace('{EVENT_YEAR}', c.EVENT_YEAR) \
            .replace('{EVENT_DATE}', c.EPOCH.strftime('%b %Y'))

        AutomatedEmail._fixtures[self.ident] = self

    @property
    def body(self):
        return decorators.render_empty(os.path.join('emails', self.template))


# Payment reminder emails, including ones for groups, which are always safe to be here, since they just
# won't get sent if group registration is turned off.

AutomatedEmailFixture(
    Attendee,
    '{EVENT_NAME} registration confirmed',
    'reg_workflow/attendee_confirmation.html',
    lambda a: (a.paid == c.HAS_PAID and not a.promo_code_groups) or
              (a.paid == c.NEED_NOT_PAY and (a.confirmed or a.promo_code_id or a.age_discount)),
    # query=Attendee.paid == c.HAS_PAID,
    needs_approval=False,
    allow_at_the_con=True,
    ident='attendee_badge_confirmed')

if c.ATTENDEE_ACCOUNTS_ENABLED:
    AutomatedEmailFixture(
        AttendeeAccount,
        '{EVENT_NAME} account creation confirmed',
        'reg_workflow/account_confirmation.html',
        lambda a: not a.imported and a.hashed and not a.password_reset and not a.is_sso_account,
        needs_approval=False,
        allow_at_the_con=True,
        ident='attendee_account_confirmed')

AutomatedEmailFixture(
    PromoCodeGroup,
    '{EVENT_NAME} group registration successful',
    'reg_workflow/promo_code_group_confirmation.html',
    lambda g: g.buyer and g.buyer.amount_paid > 0,
    needs_approval=False,
    allow_at_the_con=True,
    ident='pc_group_payment_received')

AutomatedEmailFixture(
    Group,
    '{EVENT_NAME} group payment received',
    'reg_workflow/group_confirmation.html',
    lambda g: g.amount_paid == g.cost * 100 and g.cost != 0 and g.leader_id,
    # query=and_(Group.amount_paid >= Group.cost, Group.cost > 0, Group.leader_id != None),
    needs_approval=False,
    ident='group_payment_received')

AutomatedEmailFixture(
    Attendee,
    '{EVENT_NAME} group registration confirmed',
    'reg_workflow/attendee_confirmation.html',
    lambda a: a.group and (a.id != a.group.leader_id or a.group.cost == 0) and not a.placeholder,
    # query=and_(
    #     Attendee.placeholder == False,
    #     Attendee.group_id != None,
    #     or_(Attendee.id != Group.leader_id, Group.cost == 0)),
    needs_approval=False,
    allow_at_the_con=True,
    ident='attendee_group_reg_confirmation')

AutomatedEmailFixture(
    Attendee,
    '{EVENT_NAME} merch pre-order received',
    'reg_workflow/group_donation.txt',
    lambda a: a.paid == c.PAID_BY_GROUP and a.amount_extra and a.amount_paid >= (a.amount_extra * 100),
    # query=and_(
    #     Attendee.paid == c.PAID_BY_GROUP,
    #     Attendee.amount_extra != 0,
    #     Attendee.amount_paid >= Attendee.amount_extra),
    needs_approval=False,
    sender=c.MERCH_EMAIL,
    ident='group_extra_payment_received')


# Reminder emails for groups to allocated their unassigned badges.  These emails are safe to be turned on for
# all events, because they will only be sent for groups with unregistered badges, so if group preregistration
# has been turned off, they'll just never be sent.

AutomatedEmailFixture(
    Group,
    'Reminder to pre-assign {EVENT_NAME} group badges',
    'reg_workflow/group_preassign_reminder.txt',
    lambda g: (
        c.BEFORE_GROUP_PREREG_TAKEDOWN
        and days_after(30, g.registered)()
        and g.unregistered_badges),
    when=before(c.GROUP_PREREG_TAKEDOWN),
    needs_approval=False,
    ident='group_preassign_badges_reminder',
    sender=c.REGDESK_EMAIL)

AutomatedEmailFixture(
    Group,
    'Last chance to pre-assign {EVENT_NAME} group badges',
    'reg_workflow/group_preassign_reminder.txt',
    lambda g: (
      c.AFTER_GROUP_PREREG_TAKEDOWN
      and g.unregistered_badges),
    when=after(c.GROUP_PREREG_TAKEDOWN),
    needs_approval=False,
    allow_at_the_con=True,
    ident='group_preassign_badges_reminder_last_chance',
    sender=c.REGDESK_EMAIL)

# Placeholder badge emails; when an admin creates a "placeholder" badge, we send an email asking them to fill in the
# rest of their information. We also send two reminder emails before the placeholder deadline explaining that the
# badge must be explicitly accepted or we'll assume the person isn't coming.
#
# We usually import a bunch of last year's staffers before preregistration goes live with placeholder badges, so there's
# a special email for those people, which is basically the same as the normal email except it includes a special thanks
# message. We identify those people by checking for volunteer placeholders which were created before prereg opens.
#
# These emails are safe to be turned on for all events because none of them are sent unless an administrator explicitly
# creates a "placeholder" registration.

class StopsEmailFixture(AutomatedEmailFixture):
    def __init__(self, subject, template, filter, ident, **kwargs):
        AutomatedEmailFixture.__init__(
            self,
            Attendee,
            subject,
            template,
            lambda a: a.staffing and filter(a),
            ident,
            # query=[Attendee.staffing == True] + listify(query),
            sender=c.STAFF_EMAIL,
            **kwargs)


# TODO: Refactor all this into something less lazy
earliest_opening_date = c.PREREG_OPEN


def deferred_attendee_placeholder(a): return a.placeholder and (a.registered_local <= earliest_opening_date
                                                                and a.badge_type == c.ATTENDEE_BADGE
                                                                and a.paid == c.NEED_NOT_PAY
                                                                and "staff import".lower() not in a.admin_notes.lower()
                                                                and not a.admin_account)


def staff_import_placeholder(a): return a.placeholder and (a.registered_local <= c.PREREG_OPEN
                                                           and (a.admin_account or
                                                                "staff import" in a.admin_notes.lower()))


def volunteer_placeholder(a): return a.staffing and a.placeholder and a.registered_local > c.PREREG_OPEN and \
                                                    a.badge_type not in [c.STAFF_BADGE, c.CONTRACTOR_BADGE]


# and an email for group-leader-created badges
def generic_placeholder(a): return a.placeholder and (not deferred_attendee_placeholder(a)
                                                      and not staff_import_placeholder(a)
                                                      and not volunteer_placeholder(a)
                                                      and a.registered_local > earliest_opening_date)


AutomatedEmailFixture(
    Attendee,
    'Claim your badge for {EVENT_NAME} {EVENT_YEAR}!',
    'placeholders/regular.txt',
    lambda a: generic_placeholder(a) and a.paid == c.NEED_NOT_PAY,
    sender=c.CONTACT_EMAIL,
    allow_at_the_con=True,
    ident='generic_badge_confirmation_comped')

AutomatedEmailFixture(
    Attendee,
    'Please complete your {EVENT_NAME} {EVENT_YEAR} registration',
    'placeholders/regular.txt',
    lambda a: generic_placeholder(a) and a.paid != c.NEED_NOT_PAY and "converted badge" not in a.admin_notes.lower(),
    sender=c.CONTACT_EMAIL,
    allow_at_the_con=True,
    ident='generic_badge_confirmation')

AutomatedEmailFixture(
    Attendee,
    'Claim your deferred badge for {EVENT_NAME} {EVENT_YEAR}!',
    'placeholders/deferred.html',
    deferred_attendee_placeholder,
    when=after(c.PREREG_OPEN),
    ident='claim_deferred_badge')

StopsEmailFixture(
    'Claim your Staff badge for {EVENT_NAME} {EVENT_YEAR}!',
    'placeholders/imported_volunteer.txt',
    staff_import_placeholder,
    ident='volunteer_again_inquiry')

StopsEmailFixture(
    'Claim your Volunteer badge for {EVENT_NAME} {EVENT_YEAR}',
    'placeholders/volunteer.txt',
    volunteer_placeholder,
    ident='volunteer_badge_confirmation')

AutomatedEmailFixture(
    Attendee,
    '{EVENT_NAME} Badge Confirmation Reminder',
    'placeholders/reminder.txt',
    lambda a: days_after(7, a.registered)() and a.placeholder,
    ident='badge_confirmation_reminder')

AutomatedEmailFixture(
    Attendee,
    'Last Chance to Accept Your {EVENT_NAME} ({EVENT_DATE}) Badge',
    'placeholders/reminder.txt',
    lambda a: a.placeholder,
    when=days_before(7, c.PLACEHOLDER_DEADLINE if c.PLACEHOLDER_DEADLINE else c.UBER_TAKEDOWN),
    ident='badge_confirmation_reminder_last_chance')


# Volunteer emails; none of these will be sent unless VOLUNTEER_CHECKLIST_OPEN is set.

StopsEmailFixture(
    'Please complete your {EVENT_NAME} Staff/Volunteer Checklist',
    'shifts/created.txt',
    lambda a: a.staffing,
    when=after(c.VOLUNTEER_CHECKLIST_OPEN),
    allow_at_the_con=True,
    ident='volunteer_checklist_completion_request')

StopsEmailFixture(
    '{EVENT_NAME} ({EVENT_DATE}) shifts are live!',
    'shifts/shifts_created.txt',
    lambda a: (
        c.AFTER_SHIFTS_CREATED
        and a.badge_type != c.CONTRACTOR_BADGE
        and a.takes_shifts
        and a.registered_local <= c.SHIFTS_CREATED),
    when=before(c.PREREG_TAKEDOWN),
    ident='volunteer_shift_signup_notification')

StopsEmailFixture(
    'Reminder to sign up for {EVENT_NAME} ({EVENT_DATE}) shifts',
    'shifts/reminder.txt',
    lambda a: (
        c.AFTER_SHIFTS_CREATED
        and a.badge_type != c.CONTRACTOR_BADGE
        and days_after(14, max(a.registered_local, c.SHIFTS_CREATED))()
        and a.takes_shifts
        and not a.shift_minutes),
    when=before(c.PREREG_TAKEDOWN),
    ident='volunteer_shift_signup_reminder')

StopsEmailFixture(
    'Last chance to sign up for {EVENT_NAME} ({EVENT_DATE}) shifts',
    'shifts/reminder.txt',
    lambda a: (c.AFTER_SHIFTS_CREATED and a.badge_type != c.CONTRACTOR_BADGE
               and (not c.PREREG_TAKEDOWN or c.BEFORE_PREREG_TAKEDOWN) and a.takes_shifts and not a.shift_minutes),
    when=days_before(10, c.EPOCH),
    ident='volunteer_shift_signup_reminder_last_chance')

StopsEmailFixture(
    'Still want to volunteer at {EVENT_NAME} ({EVENT_DATE})?',
    'shifts/volunteer_check.txt',
    lambda a: (
        c.VOLUNTEER_CHECKLIST_OPEN
        and a.badge_type != c.CONTRACTOR_BADGE
        and c.VOLUNTEER_RIBBON in a.ribbon_ints
        and a.takes_shifts
        and a.weighted_hours == 0),
    when=days_before(28, c.FINAL_EMAIL_DEADLINE),
    ident='volunteer_still_interested_inquiry')

StopsEmailFixture(
    'Your {EVENT_NAME} ({EVENT_DATE}) shift schedule',
    'shifts/schedule.html',
    lambda a: c.SHIFTS_CREATED and a.weighted_hours and a.badge_type != c.CONTRACTOR_BADGE,
    allow_at_the_con=True,
    when=days_before(1, c.FINAL_EMAIL_DEADLINE),
    ident='volunteer_shift_schedule')

StopsEmailFixture(
    'Please review your worked shifts for {EVENT_NAME}!',
    'shifts/shifts_worked.html',
    lambda a: (a.weighted_hours or a.nonshift_minutes) and a.badge_type != c.CONTRACTOR_BADGE,
    when=days_after(1, c.ESCHATON),
    ident='volunteer_shifts_worked',
    allow_post_con=True)

if c.VOLUNTEER_AGREEMENT_ENABLED:
    StopsEmailFixture(
        'Reminder: Please agree to terms of {EVENT_NAME} ({EVENT_DATE}) volunteer agreement',
        'staffing/volunteer_agreement.txt',
        lambda a: c.VOLUNTEER_CHECKLIST_OPEN and c.VOLUNTEER_AGREEMENT_ENABLED and not a.agreed_to_volunteer_agreement,
        when=days_before(45, c.FINAL_EMAIL_DEADLINE),
        ident='volunteer_agreement')


# For events with customized badges, these emails remind people to let us know what we want on their badges.  We have
# one email for our volunteers who haven't bothered to confirm they're coming yet (bleh) and one for everyone else.

if c.PRINTED_BADGE_DEADLINE:
    StopsEmailFixture(
        'Last chance to personalize your {EVENT_NAME} ({EVENT_DATE}) badge',
        'personalized_badges/volunteers.txt',
        lambda a: (a.staffing and a.has_personalized_badge and a.placeholder
                   and a.badge_type != c.CONTRACTOR_BADGE),
        when=days_before(7, c.PRINTED_BADGE_DEADLINE),
        ident='volunteer_personalized_badge_reminder')

    if [badge_type for badge_type in c.PREASSIGNED_BADGE_TYPES if badge_type not in [c.STAFF_BADGE,
                                                                                     c.CONTRACTOR_BADGE]]:
        AutomatedEmailFixture(
            Attendee,
            'Personalized {EVENT_NAME} ({EVENT_DATE}) badges will be ordered next week',
            'personalized_badges/reminder.txt',
            lambda a: a.has_personalized_badge and not a.placeholder,
            when=days_before(7, c.PRINTED_BADGE_DEADLINE),
            ident='personalized_badge_reminder')


# MAGFest requires signed and notarized parental consent forms for anyone under 18.  This automated email reminder to
# bring the consent form only happens if this feature is turned on by setting the CONSENT_FORM_URL config option.
AutomatedEmailFixture(
    Attendee,
    '{EVENT_NAME} ({EVENT_DATE}) parental consent form reminder',
    'reg_workflow/under_18_reminder.txt',
    lambda a: c.CONSENT_FORM_URL and a.age_group_conf['consent_form'] and days_after(14, a.registered)(),
    when=days_before(60, c.EPOCH),
    allow_at_the_con=True,
    ident='under_18_parental_consent_reminder')


# Emails sent out to all attendees who can check in. These emails contain useful information about the event and are
# sent close to the event start date.
AutomatedEmailFixture(
    Attendee,
    'Check in faster at {EVENT_NAME}',
    'reg_workflow/attendee_qrcode.html',
    lambda a: not a.cannot_check_in_reason and c.USE_CHECKIN_BARCODE,
    when=days_before(7, c.EPOCH),
    allow_at_the_con=True,
    ident='qrcode_for_checkin')


class DeptChecklistEmailFixture(AutomatedEmailFixture):
    def __init__(self, conf):
        when = [days_before(10, conf.deadline)]
        if conf.email_post_con:
            when.append(after(c.EPOCH))

        AutomatedEmailFixture.__init__(
            self,
            Attendee,
            '{EVENT_NAME} Department Checklist: ' + conf.name,
            'shifts/dept_checklist.txt',
            filter=lambda a: a.admin_account and any(
                not d.checklist_item_for_slug(conf.slug)
                for d in a.checklist_admin_depts),
            ident='department_checklist_{}'.format(conf.name),
            when=when,
            sender=c.STAFF_EMAIL,
            extra_data={'conf': conf},
            allow_post_con=conf.email_post_con)


for _conf in DeptChecklistConf.instances.values():
    DeptChecklistEmailFixture(_conf)


# =============================
# hotel
# =============================

if c.HOTELS_ENABLED:

    AutomatedEmailFixture(
        Attendee,
        'Want volunteer hotel room space at {EVENT_NAME}?',
        'hotel/hotel_rooms.txt',
        lambda a: (a.badge_type != c.CONTRACTOR_BADGE and a.hotel_eligible
                   and not a.hotel_requests and a.takes_shifts),
        sender=c.ROOM_EMAIL_SENDER,
        when=days_before(45, c.ROOM_DEADLINE, 14),
        ident='volunteer_hotel_room_inquiry')

    AutomatedEmailFixture(
        Attendee,
        'Reminder to sign up for {EVENT_NAME} hotel room space',
        'hotel/hotel_reminder.txt',
        lambda a: (a.badge_type != c.CONTRACTOR_BADGE and a.hotel_eligible
                   and not a.hotel_requests and a.takes_shifts),
        sender=c.ROOM_EMAIL_SENDER,
        when=days_before(14, c.ROOM_DEADLINE, 2),
        ident='hotel_sign_up_reminder')

    AutomatedEmailFixture(
        Attendee,
        'Last chance to sign up for {EVENT_NAME} hotel room space',
        'hotel/hotel_reminder.txt',
        lambda a: (a.badge_type != c.CONTRACTOR_BADGE and a.hotel_eligible
                   and not a.hotel_requests and a.takes_shifts),
        sender=c.ROOM_EMAIL_SENDER,
        when=days_before(2, c.ROOM_DEADLINE),
        ident='hotel_sign_up_reminder_last_chance')

    AutomatedEmailFixture(
        Attendee,
        'Reminder to meet your {EVENT_NAME} hotel room requirements',
        'hotel/hotel_hours.txt',
        lambda a: (a.badge_type != c.CONTRACTOR_BADGE and a.hotel_shifts_required
                   and a.weighted_hours < c.HOURS_FOR_HOTEL_SPACE),
        sender=c.ROOM_EMAIL_SENDER,
        when=days_before(14, c.FINAL_EMAIL_DEADLINE, 7),
        ident='hotel_requirements_reminder')

    AutomatedEmailFixture(
        Attendee,
        'Final reminder to meet your {EVENT_NAME} hotel room requirements',
        'hotel/hotel_hours.txt',
        lambda a: (a.badge_type != c.CONTRACTOR_BADGE and a.hotel_shifts_required
                   and a.weighted_hours < c.HOURS_FOR_HOTEL_SPACE),
        sender=c.ROOM_EMAIL_SENDER,
        when=days_before(7, c.FINAL_EMAIL_DEADLINE),
        ident='hotel_requirements_reminder_last_chance')

    if not c.HOTEL_REQUESTS_URL:
        AutomatedEmailFixture(
            Room,
            '{EVENT_NAME} Hotel Room Assignment',
            'hotel/room_assignment.txt',
            lambda r: r.locked_in,
            sender=c.ROOM_EMAIL_SENDER,
            ident='hotel_room_assignment')
