import math
from datetime import datetime
from uuid import uuid4

from pytz import UTC
from residue import CoerceUTF8 as UnicodeText, UTCDateTime, UUID
from sqlalchemy import and_, exists, or_, func, select
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.orm import backref
from sqlalchemy.schema import ForeignKey
from sqlalchemy.sql.expression import not_
from sqlalchemy.types import Boolean, Integer, Numeric

from uber.config import c
from uber.custom_tags import format_currency
from uber.decorators import presave_adjustment
from uber.models import MagModel
from uber.models.types import default_relationship as relationship, utcnow, Choice, DefaultColumn as Column, \
    MultiChoice, TakesPaymentMixin
from uber.utils import add_opt


__all__ = ['Group']


class Group(MagModel, TakesPaymentMixin):
    public_id = Column(UUID, default=lambda: str(uuid4()))
    shared_with_id = Column(UUID, ForeignKey('group.id', ondelete='SET NULL'), nullable=True)
    shared_with = relationship(
        'Group',
        foreign_keys='Group.shared_with_id',
        backref=backref('table_shares', viewonly=True),
        cascade='save-update,merge,refresh-expire,expunge',
        remote_side='Group.id',
        single_parent=True)
    name = Column(UnicodeText)
    tables = Column(Numeric, default=0)
    zip_code = Column(UnicodeText)
    address1 = Column(UnicodeText)
    address2 = Column(UnicodeText)
    city = Column(UnicodeText)
    region = Column(UnicodeText)
    country = Column(UnicodeText)
    email_address = Column(UnicodeText)
    phone = Column(UnicodeText)
    website = Column(UnicodeText)
    description = Column(UnicodeText)
    special_needs = Column(UnicodeText)

    cost = Column(Integer, default=0, admin_only=True)
    auto_recalc = Column(Boolean, default=True, admin_only=True)

    can_add = Column(Boolean, default=False, admin_only=True)
    convert_badges = Column(Boolean, default=False, admin_only=True)
    admin_notes = Column(UnicodeText, admin_only=True)
    status = Column(Choice(c.DEALER_STATUS_OPTS), default=c.UNAPPROVED, admin_only=True)
    registered = Column(UTCDateTime, server_default=utcnow(), default=lambda: datetime.now(UTC))
    approved = Column(UTCDateTime, nullable=True)
    leader_id = Column(UUID, ForeignKey('attendee.id', use_alter=True, name='fk_leader', ondelete='SET NULL'),
                       nullable=True)
    creator_id = Column(UUID, ForeignKey('attendee.id'), nullable=True)

    creator = relationship(
        'Attendee',
        foreign_keys=creator_id,
        backref=backref('created_groups', order_by='Group.name'),
        cascade='save-update,merge,refresh-expire,expunge',
        remote_side='Attendee.id',
        single_parent=True)
    leader = relationship('Attendee', foreign_keys=leader_id, post_update=True, cascade='all')
    active_receipt = relationship(
        'ModelReceipt',
        cascade='save-update,merge,refresh-expire,expunge',
        primaryjoin='and_(remote(ModelReceipt.owner_id) == foreign(Group.id),'
        'ModelReceipt.owner_model == "Group",'
        'ModelReceipt.closed == None)',
        uselist=False)

    _repr_attr_names = ['name']

    @presave_adjustment
    def _cost_and_leader(self):
        assigned = [a for a in self.attendees if not a.is_unassigned]
        if len(assigned) == 1:
            [self.leader] = assigned
        if self.auto_recalc:
            self.cost = self.calc_default_cost()
        elif not self.cost:
            self.cost = 0
        if self.status == c.APPROVED and not self.approved:
            self.approved = datetime.now(UTC)
        if not self.is_unpaid or self.orig_value_of('status') != self.status:
            for a in self.attendees:
                a.presave_adjustments()

    @presave_adjustment
    def assign_creator(self):
        if self.is_new and not self.creator_id:
            self.creator_id = self.session.admin_attendee().id if self.session.admin_attendee() else None

    @hybrid_property
    def cost_cents(self):
        return self.cost * 100

    @property
    def signnow_texts_list(self):
        """
        Returns a list of JSON representing uneditable texts fields to use for this group's document in SignNow.
        """
        page_number = 2
        textFont = 'Arial'
        textLineHeight = 12
        textSize = 10

        texts_config = [(self.name, 73, 392), (self.email, 73, 436), (self.id, 200, 748)]

        texts = []

        for field, x, y in texts_config:
            texts.append({
                "page_number": page_number,
                "data":        field,
                "x":           x,
                "y":           y,
                "font":        textFont,
                "line_height": textLineHeight,
                "size":        6 if field == self.id else textSize,
            })

        return texts

    @property
    def signnow_document_signed(self):
        signed = True
    
    def convert_to_shared(self, session):
        self.tables = 0
        if len(self.floating) < abs(1 - self.badges):
            new_badges_count = self.badges - len(self.floating)
        else:
            new_badges_count = 1

        session.assign_badges(self, new_badges_count)

    @property
    def shared_with_name(self):
        if self.shared_with:
            return self.shared_with.name

    def set_shared_with_name(self, value):
        # This is not a setter function in order to avoid being processed inside WTForms
        # TODO: Make that work

        from uber.models import Session
        if value == '':
            self.shared_with = None
    
    @presave_adjustment
    def unshare_table(self):
        if self.status != c.SHARED:
            self.shared_with = None

    @property
    def sorted_attendees(self):
        return list(sorted(self.attendees, key=lambda a: (a.is_unassigned, a.id != self.leader_id, a.full_name)))

    @property
    def unassigned(self):
        """
        Returns a list of the unassigned badges for this group, sorted so that
        the paid-by-group badges come last, because when claiming unassigned
        badges we want to claim the "weird" ones first.
        """
        unassigned = [a for a in self.attendees if a.is_unassigned]
        return sorted(unassigned, key=lambda a: a.paid == c.PAID_BY_GROUP)

    @property
    def floating(self):
        """
        Returns the list of paid-by-group unassigned badges for this group.
        This is a separate property from the "Group.unassigned" property
        because when automatically adding or removing unassigned badges, we
        care specifically about paid-by-group badges rather than all unassigned
        badges.
        """
        return [a for a in self.attendees if a.is_unassigned and a.paid in [c.PAID_BY_GROUP, c.NEED_NOT_PAY]]

    @hybrid_property
    def normalized_name(self):
        return self.name.strip().lower()

    @normalized_name.expression
    def normalized_name(cls):
        return func.lower(func.trim(cls.name))

    @hybrid_property
    def is_valid(self):
        return self.status not in [c.CANCELLED, c.DECLINED, c.IMPORTED]

    @is_valid.expression
    def is_valid(cls):
        return not_(cls.status.in_([c.CANCELLED, c.DECLINED, c.IMPORTED]))

    @hybrid_property
    def attendees_have_badges(self):
        return self.is_valid

    @attendees_have_badges.expression
    def attendees_have_badges(cls):
        return and_(cls.is_valid)  # noqa: E712

    @property
    def access_sections(self):
        """
        Returns what site sections a group 'belongs' to based on their properties.
        We use this list to determine which admins can view the group.
        In some cases, we rely on the group's leader to tell us what kind of group this is.
        """
        section_list = []
        if self.leader:
            if self.leader.badge_type in [c.STAFF_BADGE, c.CONTRACTOR_BADGE]:
                section_list.append('shifts_admin')
        return section_list

    @property
    def new_ribbon(self):
        return ''

    @property
    def ribbon_and_or_badge(self):
        badge = self.unassigned[0]
        if badge.ribbon and badge.badge_type != c.ATTENDEE_BADGE:
            return ' / '.join([badge.badge_type_label] + self.ribbon_labels)
        elif badge.ribbon:
            return ' / '.join(badge.ribbon_labels)
        else:
            return badge.badge_type_label

    @hybrid_property
    def is_unpaid(self):
        return self.cost > 0 and self.amount_paid == 0

    @is_unpaid.expression
    def is_unpaid(cls):
        return and_(cls.cost > 0, cls.amount_paid == 0)

    @property
    def email(self):
        if self.email_address:
            return self.email_address
        if self.studio and self.studio.email:
            return self.studio.email
        elif self.leader and self.leader.email:
            return self.leader.email
        elif self.leader_id:  # unattached groups
            [leader] = [a for a in self.attendees if a.id == self.leader_id]
            return leader.email
        else:
            emails = [a.email for a in self.attendees if a.email]
            if len(emails) == 1:
                return emails[0]

    @property
    def gets_emails(self):
        return self.status not in [c.DECLINED, c.CANCELLED] and not self.leader or self.leader.is_valid

    @hybrid_property
    def badges_purchased(self):
        return len([a for a in self.attendees if a.paid == c.PAID_BY_GROUP])

    @badges_purchased.expression
    def badges_purchased(cls):
        from uber.models import Attendee
        return select([func.count(Attendee.id)]
                      ).where(and_(Attendee.group_id == cls.id, Attendee.paid == c.PAID_BY_GROUP)
                              ).label('badges_purchased')

    @property
    def badges(self):
        return len(self.attendees)

    @hybrid_property
    def unregistered_badges(self):
        return len([a for a in self.attendees if a.is_unassigned])

    @unregistered_badges.expression
    def unregistered_badges(cls):
        from uber.models import Attendee
        return exists().where(and_(Attendee.group_id == cls.id, Attendee.first_name == ''))

    @property
    def current_badge_cost(self):
        total_badge_cost = 0

        if not self.auto_recalc:
            return 0

        for attendee in self.attendees:
            if attendee.paid == c.PAID_BY_GROUP and attendee.badge_cost:
                total_badge_cost += attendee.badge_cost

        return total_badge_cost

    @property
    def new_badge_cost(self):
        return c.get_group_price()

    @property
    def amount_extra(self):
        if self.is_new:
            return sum(a.total_cost - a.badge_cost for a in self.attendees if a.paid == c.PAID_BY_GROUP) / 100
        else:
            return 0

    @property
    def total_cost(self):
        if not self.is_valid:
            return 0

        if self.active_receipt:
            return self.active_receipt.item_total / 100
        return (self.cost or self.calc_default_cost()) + self.amount_extra

    @property
    def is_paid(self):
        return self.active_receipt and self.active_receipt.current_amount_owed == 0

    @property
    def amount_unpaid(self):
        if self.registered:
            return max(0, ((self.total_cost * 100) - self.amount_paid) / 100)
        else:
            return self.total_cost

    @property
    def amount_pending(self):
        return self.active_receipt.pending_total if self.active_receipt else 0

    @property
    def amount_paid_repr(self):
        return format_currency(self.amount_paid / 100)

    @property
    def amount_refunded_repr(self):
        return format_currency(self.amount_refunded / 100)

    @hybrid_property
    def amount_paid(self):
        return self.active_receipt.payment_total if self.active_receipt else 0

    @amount_paid.expression
    def amount_paid(cls):
        from uber.models import ModelReceipt

        return select([ModelReceipt.payment_total_sql]).outerjoin(ModelReceipt.receipt_txns
                      ).where(and_(ModelReceipt.owner_id == cls.id,
                                   ModelReceipt.owner_model == "Group",
                                   ModelReceipt.closed == None)).label('amount_paid')  # noqa: E711

    @hybrid_property
    def amount_refunded(self):
        return self.active_receipt.refund_total if self.active_receipt else 0

    @amount_refunded.expression
    def amount_refunded(cls):
        from uber.models import ModelReceipt

        return select([ModelReceipt.refund_total_sql]).outerjoin(ModelReceipt.receipt_txns
                      ).where(and_(ModelReceipt.owner_id == cls.id,
                                   ModelReceipt.owner_model == "Group")).label('amount_refunded')

    @property
    def hours_since_registered(self):
        if not self.registered:
            return 0
        delta = datetime.now(UTC) - self.registered
        return max(0, delta.total_seconds()) / 60.0 / 60.0

    @property
    def hours_remaining_in_grace_period(self):
        return max(0, c.GROUP_UPDATE_GRACE_PERIOD - self.hours_since_registered)

    @property
    def is_in_grace_period(self):
        return self.hours_remaining_in_grace_period > 0

    @property
    def min_badges_addable(self):
        if not c.PRE_CON:
            return 0

        if not self.auto_recalc:
            return 0
        elif self.can_add:
            return 1
        else:
            return c.MIN_GROUP_ADDITION

    @property
    def physical_address(self):
        address1 = self.address1.strip()
        address2 = self.address2.strip()
        city = self.city.strip()
        region = self.region.strip()
        zip_code = self.zip_code.strip()
        country = self.country.strip()

        country = '' if country == 'United States' else country.strip()

        if city and region:
            city_region = '{}, {}'.format(city, region)
        else:
            city_region = city or region
        city_region_zip = '{} {}'.format(city_region, zip_code).strip()

        physical_address = [address1, address2, city_region_zip, country]
        return '\n'.join([s for s in physical_address if s])
    