from urllib.parse import urlparse

from pockets import listify
from pockets.autolog import log

from uber.config import c


class MenuItem:
    href = None     # link to render
    submenu = None  # submenu to show
    name = None     # name of Menu item to show

    def __init__(self, href=None, submenu=None, name=None, access_override=None):
        assert submenu or href, "menu items must contain ONE nonempty: href or submenu"
        assert not submenu or not href, "menu items must not contain both a href and submenu"

        if submenu:
            self.submenu = listify(submenu)
        else:
            self.href = href

        self.name = name
        self.access_override = access_override

    def append_menu_item(self, m, position=None):
        """
        If we're appending a new menu item, and we aren't a submenu, convert us to one now.
        Create a new submenu and append a new item to it with the same name and href as us.

        Example:
            Original menu:
                (name='Rectangles', href="rectangle.html')

            Append to it a new menu item:
                [name='Squares', href='square.html']

            New result is:
                (name='Rectangles', submenu=
                    [
                        (Name='Rectangles', href="rectangle.html"),
                        (Name='Squares', href="square.html")
                    ]
                )
        """
        if not self.submenu and self.href:
            self.submenu = [MenuItem(name=self.name, href=self.href)]
            self.href = None

        if position:
            self.submenu.insert(position, m)
        else:
            self.submenu.append(m)

    def render_items_filtered_by_current_access(self):
        """
        Returns: dict of menu items which are allowed to be seen by the logged in user's access levels
        """
        out = {}

        page_path = self.access_override or self.href

        if self.href and not c.has_section_or_page_access(page_path=page_path.strip('.'), include_read_only=True):
            return None

        out['name'] = self.name
        if self.submenu:
            out['submenu'] = []
            for menu_item in self.submenu:
                filtered_menu_items = menu_item.render_items_filtered_by_current_access()
                if filtered_menu_items:
                    out['submenu'].append(filtered_menu_items)
        else:
            out['href'] = self.href

        return out

    def __getitem__(self, key):
        for sm in self.submenu:
            if sm.name == key:
                return sm

c.MENU = MenuItem(name='Root', submenu=[
    MenuItem(name='Admin', submenu=[
        MenuItem(name='Admin Accounts', href='../accounts/'),
        MenuItem(name='Access Groups', href='../accounts/access_groups'),
        MenuItem(name='API Access', href='../api/'),
        MenuItem(name='Pending Emails', href='../email_admin/pending'),
        MenuItem(name='Sent Emails', href='../email_admin/'),
        MenuItem(name='Feed of Database Changes', href='../registration/feed'),
        MenuItem(name='Watchlist', href='../security_admin/index'),
    ]),

    MenuItem(name='Staffing', submenu=[
        MenuItem(name='Staffers', href='../shifts_admin/staffers'),
        MenuItem(name='Pending Staffers', href='../staffing_admin/pending_badges'),
        MenuItem(name='View/Edit Shift Schedule', href='../shifts_admin/'),
        MenuItem(name='Unfilled Shifts', href='../shifts_admin/unfilled_shifts'),
        MenuItem(name='Departments', href='../dept_admin/'),
        MenuItem(name='Department Checklists', href='../dept_checklist/overview'),
    ]),

    MenuItem(name='People', submenu=[
        MenuItem(name='Attendees', href='../registration/'),
    ]),

    MenuItem(name='Statistics', submenu=[
        MenuItem(name='Summary', href='../statistics/'),
        MenuItem(name='Badges Sold Graph', href='../statistics/badges_sold'),
    ]),
])

if c.GROUPS_ENABLED:
    c.MENU['People'].append_menu_item(MenuItem(name='Promo Code Groups',
                                               href='../registration/promo_code_groups'), position=2)


if c.ATTENDEE_ACCOUNTS_ENABLED:
    c.MENU['People'].append_menu_item(MenuItem(name='Attendee Accounts',
                                               href='../reg_admin/attendee_accounts'), position=1)


if c.ADMIN_BADGES_NEED_APPROVAL:
    c.MENU['People'].append_menu_item(MenuItem(name='Pending Badges',
                                               href='../registration/pending_badges'), position=1)

if c.BADGE_PRINTING_ENABLED:
    c.MENU.append_menu_item(MenuItem(name='Badge Printing', submenu=[
        MenuItem(name='Printed Badges', href='../badge_printing/'),
        MenuItem(name='Print Jobs', href='../badge_printing/print_jobs_list'),
    ]))
