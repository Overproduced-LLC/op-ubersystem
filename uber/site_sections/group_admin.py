import cherrypy

from collections import defaultdict
from datetime import datetime
from pockets import readable_join
from pockets.autolog import log
from pytz import UTC
from sqlalchemy import and_, or_
from sqlalchemy.orm import joinedload

from uber.config import c
from uber.custom_tags import format_currency
from uber.decorators import ajax, any_admin_access, all_renderable, csrf_protected, log_pageview
from uber.errors import HTTPRedirect
from uber.forms import load_forms
from uber.models import AdminAccount, Attendee, Email, Group, PageViewTracking, Tracking
from uber.utils import check, validate_model, add_opt
from uber.payments import ReceiptManager


@all_renderable()
class Root:
    def _required_message(self, params, fields):
        missing = [s for s in fields if not params.get(s, '').strip() or params.get(s, '') == "0"]
        if missing:
            return '{} {} required field{}'.format(
                readable_join([s.replace('_', ' ').title() for s in missing]),
                'is a' if len(missing) == 1 else 'are',
                's' if len(missing) > 1 else '')
        return ''

    def index(self, session, message='', show_all=None):
        groups = session.viewable_groups().options(joinedload(Group.attendees))

        if not show_all:
            groups = groups.filter(Group.status != c.IMPORTED)

        return {
            'message': message,
            'show_all': show_all,
            'all_groups': groups,
        }

    def new_group_from_attendee(self, session, id):
        attendee = session.attendee(id)
        if attendee.group:
            if c.HAS_REGISTRATION_ACCESS:
                link = '../registration/form?id={}&'.format(attendee.id)
            else:
                link = '../accounts/homepage?'
            raise HTTPRedirect('{}message={}', link, "That attendee is already in a group!")
        group = Group(name="{}'s Group".format(attendee.display_name))
        attendee.group = group
        group.leader = attendee
        session.add(group)

        raise HTTPRedirect('form?id={}&message={}', group.id, "Group successfully created.")

    @log_pageview
    def form(self, session, message='', **params):
        reg_station_id = cherrypy.session.get('reg_station', '')

        if params.get('id') not in [None, '', 'None']:
            group = session.group(params.get('id'))
            if not session.admin_group_max_access(group):
                raise HTTPRedirect('index?message={}', f"You are not allowed to view this group. If you think this is an error, \
                                   please email us at {c.DEVELOPER_EMAIL}")
            if cherrypy.request.method == 'POST':
                receipt_items = ReceiptManager.auto_update_receipt(group, session.get_receipt_by_model(group), params.copy())
                session.add_all(receipt_items)
        else:
            group = Group()

        form_list = ['AdminGroupInfo']

        if group.is_new:
            form_list.append('LeaderInfo')

        forms = load_forms(params, group, form_list)
        for form_name, form in forms.items():
            if cherrypy.request.method != 'POST':
                if hasattr(form, 'new_badge_type') and not params.get('new_badge_type'):
                    form['new_badge_type'].data = group.leader.badge_type if group.leader else c.ATTENDEE_BADGE
                if hasattr(form, 'new_ribbons') and not params.get('new_ribbons'):
                    form['new_ribbons'].data = group.leader.ribbon_ints if group.leader else []
            form.populate_obj(group, is_admin=True)

        group_info_form = forms.get('group_info', forms.get('table_info'))

        if cherrypy.request.method == 'POST':
            session.add(group)

            if group.is_new or group.badges != group_info_form.badges.data:
                if c.ADMIN_BADGES_NEED_APPROVAL and not session.current_admin_account().full_registration_admin:
                    new_badge_status = c.PENDING_STATUS
                else:
                    new_badge_status = c.NEW_STATUS
                message = session.assign_badges(
                    group,
                    group_info_form.badges.data or int(bool(group.leader_first_name)),
                    new_badge_type=group.new_badge_type,
                    new_ribbon_type=group.new_ribbons,
                    badge_status=new_badge_status,
                    )

            if not message and group.is_new and group.leader_first_name:
                session.commit()
                leader = group.leader = group.attendees[0]
                leader.placeholder = True
                leader.badge_type = group.new_badge_type
                leader.ribbon_ints = group.new_ribbons
                leader_params = {key[7:]: val for key, val in params.items() if key.startswith('leader_')}
                leader_forms = load_forms(leader_params, leader, ['PersonalInfo'])
                all_errors = validate_model(leader_forms, leader, Attendee(**leader.to_dict()), is_admin=True)
                if all_errors:
                    session.delete(group)
                    session.commit()
                    message = ' '.join([item for sublist in all_errors.values() for item in sublist])
                else:
                    forms['personal_info'] = leader_forms['personal_info']
                    forms['personal_info'].populate_obj(leader, is_admin=True)

            if not message:
                raise HTTPRedirect('form?id={}&message={}', group.id, message or (group.name + " has been saved"))

        receipt = session.get_receipt_by_model(group) if not group.is_new else None

        return {
            'message': message,
            'group': group,
            'receipt': receipt,
            'forms': forms,
            'signnow_last_emailed': False,
            'signnow_signed': True,
            'payment_enabled': True if reg_station_id else False,
        }

    @ajax
    @any_admin_access
    def validate_group(self, session, form_list=[], **params):
        if params.get('id') in [None, '', 'None']:
            group = Group()
        else:
            group = session.group(params.get('id'))

        if not form_list:
            form_list = ['AdminGroupInfo']

            if group.is_new:
                form_list.append('LeaderInfo')
        elif isinstance(form_list, str):
            form_list = [form_list]
        forms = load_forms(params, group, form_list, get_optional=False)

        all_errors = validate_model(forms, group, Group(**group.to_dict()), is_admin=True)
        if all_errors:
            return {"error": all_errors}

        return {"success": True}

    def paid_with_cash(self, session, id):
        if not cherrypy.session.get('reg_station'):
            return {'success': False, 'message': 'You must set a workstation ID to take payments.'}

        group = session.group(id)
        receipt = session.get_receipt_by_model(group, create_if_none="DEFAULT")
        amount_owed = receipt.current_amount_owed
        if not amount_owed:
            raise HTTPRedirect('form?id={}&message={}', id, "This group does not owe any money.")

        receipt_manager = ReceiptManager(receipt)
        error = receipt_manager.create_payment_transaction(f"Marked as paid with cash by {AdminAccount.admin_name()}",
                                                           amount=amount_owed, method=c.CASH)
        if error:
            session.rollback()
            raise HTTPRedirect('form?id={}&message={}', id, f"An error occurred: {error}")

        session.add_all(receipt_manager.items_to_add)
        session.commit()
        session.check_receipt_closed(receipt)
        raise HTTPRedirect('form?id={}&message={}', id,
                           f"Cash payment of {format_currency(amount_owed / 100)} recorded.")

    def history(self, session, id):
        group = session.group(id)

        if group.leader:
            emails = session.query(Email).filter(
                or_(Email.to == group.leader.email, Email.fk_id == id)).order_by(Email.when).all()
        else:
            emails = {}

        return {
            'group': group,
            'emails': emails,
            'changes': session.query(Tracking).filter(or_(
                Tracking.links.like('%group({})%'.format(id)),
                and_(Tracking.model == 'Group', Tracking.fk_id == id))).order_by(Tracking.when).all(),
            'pageviews': session.query(PageViewTracking).filter(PageViewTracking.which == repr(group))
        }

    @csrf_protected
    def delete(self, session, id, confirmed=None):
        group = session.group(id)
        if group.badges - group.unregistered_badges and not confirmed:
            raise HTTPRedirect('deletion_confirmation?id={}', id)
        else:
            for attendee in group.attendees:
                session.delete(attendee)
            session.delete(group)
            raise HTTPRedirect('index?message={}', 'Group deleted')

    def deletion_confirmation(self, session, id):
        return {'group': session.group(id)}

    @csrf_protected
    def assign_leader(self, session, group_id, attendee_id):
        group = session.group(group_id)
        attendee = session.attendee(attendee_id)
        if attendee not in group.attendees:
            raise HTTPRedirect('form?id={}&message={}', group_id, 'That attendee has been removed from the group')
        else:
            group.leader_id = attendee_id
            raise HTTPRedirect('form?id={}&message={}', group_id, 'Group leader set')
        