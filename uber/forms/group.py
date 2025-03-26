from markupsafe import Markup
from wtforms import (BooleanField, DecimalField, EmailField,
                     SelectField, SelectMultipleField, IntegerField,
                     StringField, TelField, validators, TextAreaField)
from wtforms.validators import ValidationError

from uber.config import c
from uber.forms import AddressForm, CustomValidation, MultiCheckbox, MagForm, IntSelect, NumberInputGroup, Ranking
from uber.forms.attendee import valid_cellphone
from uber.custom_tags import format_currency, pluralize
from uber.model_checks import invalid_phone_number

__all__ = ['GroupInfo', 'ContactInfo', 'AdminGroupInfo']


class GroupInfo(MagForm):
    name = StringField('Group Name', validators=[
        validators.DataRequired("Please enter a group name."),
        validators.Length(max=40, message="Group names cannot be longer than 40 characters.")
        ])
    badges = IntegerField('Badges', widget=IntSelect())
    tables = DecimalField('Tables', widget=IntSelect())

    def badges_label(self):
        return "Badges (" + format_currency(c.GROUP_PRICE) + " each)"

    def badges_desc(self):
        if c.GROUP_UPDATE_GRACE_PERIOD > 0:
            return f"You have {c.GROUP_UPDATE_GRACE_PERIOD} hour{pluralize(c.GROUP_UPDATE_GRACE_PERIOD)} "\
                   "after paying to add badges to your group without quantity restrictions. You may continue to add "\
                   "badges to your group after that, but you'll have to add at least "\
                   f"{c.MIN_GROUP_ADDITION} badges at a time."
        else:
            return "You may add badges to your group later, but you must add at least {} badges at a time.".format(
                c.MIN_GROUP_ADDITION)


class AdminGroupInfo(GroupInfo):
    can_add = BooleanField('This group may purchase additional badges.')
    new_badge_type = SelectField('Badge Type', choices=c.BADGE_OPTS, coerce=int)
    cost = IntegerField('Total Group Price', validators=[
        validators.NumberRange(min=0, message="Total Group Price must be a number that is 0 or higher.")
    ], widget=NumberInputGroup())
    auto_recalc = BooleanField('Automatically recalculate this number.')
    amount_paid_repr = StringField('Amount Paid', render_kw={'disabled': "disabled"})
    amount_refunded_repr = StringField('Amount Refunded', render_kw={'disabled': "disabled"})
    admin_notes = TextAreaField('Admin Notes')


class ContactInfo(AddressForm, MagForm):
    email_address = EmailField('Email Address', validators=[
        validators.DataRequired("Please enter your business email address."),
        validators.Length(max=255, message="Email addresses cannot be longer than 255 characters."),
        validators.Email(granular_message=True),
        ],
        render_kw={'placeholder': 'test@example.com'})
    phone = TelField('Phone Number', validators=[
        validators.DataRequired("Please enter your business' phone number."),
        ],
        render_kw={'placeholder': 'A phone number we can use to contact you during the event'})

    def get_optional_fields(self, group, is_admin=False):
        optional_list = super().get_optional_fields(group, is_admin)
        optional_list.extend(['address1', 'city', 'region', 'zip_code', 'country'])
        return optional_list

    def validate_phone(form, field):
        if field.data and invalid_phone_number(field.data):
            raise ValidationError('Your phone number was not a valid 10-digit US phone number. '
                                  'Please include a country code (e.g. +44) for international numbers.')

class LeaderInfo(MagForm):
    field_validation = CustomValidation()

    leader_first_name = StringField('First Name', validators=[
        validators.InputRequired("Please provide the group leader's first name.")
        ])
    leader_last_name = StringField('Last Name', validators=[
        validators.InputRequired("Please provide the group leader's last name.")
        ])
    leader_email = EmailField('Email Address', validators=[
        validators.InputRequired("Please enter an email address."),
        validators.Length(max=255, message="Email addresses cannot be longer than 255 characters."),
        validators.Email(granular_message=True),
        ],
        render_kw={'placeholder': 'test@example.com'})
    leader_cellphone = TelField('Phone Number', validators=[
        valid_cellphone
        ])

    def get_optional_fields(self, group, is_admin=False):
        optional_list = super().get_optional_fields(group, is_admin)
        optional_list.append('leader_email')
        # This mess is required because including a field in this list prevents
        # all validations from running if the field is not present
        if not getattr(group, 'leader_cellphone', None) and not getattr(group, 'leader_email', None):
            if not getattr(group, 'leader_first_name', None):
                optional_list.append('leader_last_name')
            if not getattr(group, 'leader_last_name', None):
                optional_list.append('leader_first_name')
        return optional_list
