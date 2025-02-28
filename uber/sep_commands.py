import sys
from glob import glob
from json import dumps
from os.path import join
from pprint import pprint

from sqlalchemy.orm import subqueryload

from uber.config import c, plugins_dir
from uber.decorators import timed
from uber.models import AdminAccount, Attendee, AutomatedEmail, Group, Session

def entry_point(func):
    """
    Decorator used to define entry points for command-line scripts.  Ubersystem
    ships with a "sep" (Sideboard Entry Point, for historical reasons) command
    line script which can be used to call into any plugin-defined entry point
    after deleting sys.argv[0] so that the entry point name will be the first
    argument.  For example, if a plugin had this entry point:

        @entry_point
        def some_action():
            print(sys.argv)

    Then someone in a shell ran the command:

        python sep.py some_action foo bar

    It would print:

        ['some_action', 'foo', 'bar']

    :param func: a function which takes no arguments; its name will be the name
                 of the command, and an exception is raised if a function with
                 the same name has already been registered as an entry point
    """
    assert func.__name__ not in _entry_points, 'An entry point named {} has already been implemented'.format(func.__name__)
    _entry_points[func.__name__] = func
    return func

_entry_points = {}

@entry_point
def alembic(*args):
    """
    Frontend for alembic script with additional uber specific facilities.

    "sep alembic" supports all the same arguments as the regular "alembic"
    command, with the addition of the "--plugin PLUGIN_NAME" option.

    Passing "--plugin PLUGIN_NAME" will choose the correct alembic version path
    for the given plugin. If "--plugin" is omitted, it will default to "uber".

    If "--version-path PATH" is also specified, it will override the version
    path chosen for the plugin. This functionality is rarely needed, and best
    left unused.

    If a new migration revision is created for a plugin that previously did
    not have any revisions, then a new branch label is applied using the
    plugin name. For example::

        sep alembic --plugin new_plugin revision --autogenerate -m "Initial migration"

    A new revision script will be created in "new_plugin/alembic/versions/"
    with a branch label of "new_plugin". The "new_plugin/alembic/versions/"
    directory will be created if it does not already exist.
    """
    from alembic.config import CommandLine
    from uber.migration import create_alembic_config, get_plugin_head_revision, version_locations

    argv = args if args else sys.argv[1:]

    # Extract the "--plugin" option from argv.
    plugin_name = 'uber'
    for plugin_opt in ('-p', '--plugin'):
        if plugin_opt in argv:
            plugin_index = argv.index(plugin_opt)
            argv.pop(plugin_index)
            plugin_name = argv.pop(plugin_index)

    assert plugin_name in version_locations, (
        'Plugin "{}" does not exist in {}'.format(
            plugin_name, plugins_dir))

    commandline = CommandLine(prog='sep alembic')
    if {'-h', '--help'}.intersection(argv):
        # If "--help" is passed, add a description of the "--plugin" option
        commandline.parser.add_argument(
            '-p', '--plugin',
            type=str,
            default='uber',
            help='Name of plugin in which to add new versions')

    options = commandline.parser.parse_args(argv)

    if not hasattr(options, 'cmd'):
        commandline.parser.error('too few arguments')

    kwarg_names = options.cmd[2]
    if 'version_path' in kwarg_names and not options.version_path:
        # If the command supports the "--version-path" option and it was not
        # specified, default to the version path of the given plugin.
        options.version_path = version_locations[plugin_name]

        if 'branch_label' in kwarg_names and options.version_path and \
                not glob(join(options.version_path, '*.py')):
            # If the command supports the "--branch-label" option and there
            # aren't any existing revisions, then always apply the plugin
            # name as the branch label.
            options.branch_label = plugin_name

    if 'head' in kwarg_names and not options.head:
        # If the command supports the "--head" option and it was not specified:
        # -> if we're not creating a new branch for the plugin, then make this
        #    this revision on top of the plugin's branch head
        # -> if we're creating the initial migration for a plugin, automatically
        #    set the head to the uber branch head revision
        if options.branch_label != plugin_name:
            revision = get_plugin_head_revision(plugin_name)
            options.head = revision.revision
            if revision.is_branch_point:
                options.splice = True
        elif not glob(join(options.version_path, '*.py')):
            revision = get_plugin_head_revision('uber')
            options.head = revision.revision

    commandline.run_cmd(create_alembic_config(cmd_opts=options), options)


@entry_point
def print_config():
    """
    print all config values to stdout, used for debugging / status checking
    useful if you want to verify that Ubersystem has pulled in the INI values
    you think it has.
    """
    from uber.config import _config
    pprint(_config.dict())


@entry_point
def resave_all_attendees_and_groups():
    """
    Re-save all valid attendees and groups in the database. this is useful to re-run all validation code
    and allow re-calculation of automatically calculated values.  This is sometimes needed when
    doing database changes and we need to re-save everything.

    SAFETY: This -should- be safe to run at any time, but, for safety sake, recommend turning off
    any running ubersystem servers before running this command.
    """
    Session.initialize_db(modify_tables=False, drop=False, initialize=True)
    with Session() as session:
        print("Re-saving all attendees....")
        for a in session.valid_attendees():
            try:
                a.presave_adjustments()
                session.add(a)
                session.commit()
            except Exception:
                pass
        print("Re-saving all groups....")
        for g in session.query(Group).all():
            try:
                g.presave_adjustments()
                session.add(g)
                session.commit()
            except Exception:
                pass
    print("Done!")


@entry_point
def insert_admin():
    Session.initialize_db(initialize=True)
    with Session() as session:
        if session.insert_test_admin_account():
            print("Test admin account created successfully")
        else:
            print("Not allowed to create admin account at this time")


@entry_point
def has_admin():
    Session.initialize_db(initialize=True)
    with Session() as session:
        if session.query(AdminAccount).first() is None:
            print('Could not find any admin accounts', file=sys.stderr)
            sys.exit(1)
        else:
            print('At least one admin account exists', file=sys.stderr)
            sys.exit(0)


@entry_point
def drop_uber_db():
    assert c.DEV_BOX, 'drop_uber_db is only available on development boxes'
    Session.initialize_db(modify_tables=False, drop=True)


@entry_point
def reset_uber_db():
    assert c.DEV_BOX, 'reset_uber_db is only available on development boxes'
    Session.initialize_db(modify_tables=True, drop=True)
    insert_admin()


@entry_point
def notify_admins_of_pending_emails():
    from uber.tasks.email import notify_admins_of_pending_emails as notify_admins
    Session.initialize_db(initialize=True)
    results = timed(notify_admins)()
    if results:
        print('Notification emails sent to:\n{}'.format(dumps(results, indent=2, sort_keys=True)))


@entry_point
def send_automated_emails():
    from uber.tasks.email import send_automated_emails as send_emails
    Session.initialize_db(initialize=True)
    timed(AutomatedEmail.reconcile_fixtures)()
    results = timed(send_emails)()
    if results:
        print('Unapproved email counts:\n{}'.format(dumps(results, indent=2, sort_keys=True)))


@entry_point
def check_stripe_payments():
    from uber.tasks.registration import check_missed_stripe_payments
    Session.initialize_db(initialize=True)
    results = timed(check_missed_stripe_payments)()
    if results:
        print('Marked the following payment intents as paid: {}'.format(", ".join(results)))


@entry_point
def process_api_queue():
    from uber.tasks.registration import process_api_queue
    Session.initialize_db(initialize=True)
    results = timed(process_api_queue)()
    for job_name, count in results.items():
        print('Processed {} API job(s) with ident "{}"'.format(count, job_name))
