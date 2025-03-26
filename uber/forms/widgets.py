from markupsafe import escape, Markup
from wtforms.widgets import NumberInput, html_params, CheckboxInput, Select
from uber.config import c
from uber.custom_tags import linebreaksbr

class FileInput():
    """
    Renders a file input field with a custom label.
    """
    def __call__(self, field, **kwargs):
        field_id = kwargs.pop('id', field.id)
        options = dict(kwargs, id=field_id, name=field.name)
        if 'readonly' in options:
            options['disabled'] = True
        html = ['<div class="form-file">']
        html.append('<input type="file" {} />'.format(html_params(**options)))
        html.append('<label for="{}" class="form-label form-file-label">{}</label>'.format(field_id, field.label.text))
        html.append('</div>')
        return Markup(''.join(html))

class MultiCheckbox():
    """
    Renders a MultiSelect field as a set of checkboxes, e.g., "What interests you?"
    """
    def __call__(self, field, div_class='checkgroup', **kwargs):
        kwargs.setdefault('type', 'checkbox')
        field_id = kwargs.pop('id', field.id)
        html = ['<div {}>'.format(html_params(class_=div_class))]
        html.append(f'<fieldset {html_params(id=field_id)}>')
        html.append(f'<legend class="form-text mt-0"><span class="form-label">{field.label.text}</span>'
                    '{}</legend>'.format(Markup(' <span class="required-indicator text-danger">*</span>')
                                         if field.flags.required else ''))
        for value, label, checked, _html_attribs in field.iter_choices():
            choice_id = '{}-{}'.format(field_id, value)
            options = dict(kwargs, name=field.name, value=value, id=choice_id)
            if value == c.OTHER:
                html.append('<br/>')
            if checked:
                options['checked'] = 'checked'
            html.append('<label for="{}" class="checkbox-label">'.format(choice_id))
            html.append('<input {} /> '.format(html_params(**options)))
            html.append('{}</label>'.format(label))
        html.append('</fieldset>')
        html.append('</div>')
        return Markup(''.join(html))


class IntSelect():
    """
    Renders an Integer or Decimal field as a select dropdown, e.g., the "badges" dropdown for groups.
    The list of choices can be provided on init or during render and should be a list of (value, label) tuples.
    Note that choices must include a null/zero option if you want one.
    """
    def __init__(self, choices=None, **kwargs):
        self.choices = choices

    def __call__(self, field, choices=None, **kwargs):
        choices = choices or self.choices or [('', "ERROR: No choices provided")]
        field_id = kwargs.pop('id', field.id)
        options = dict(kwargs, id=field_id, name=field.name)
        if 'readonly' in options:
            options['disabled'] = True
        html = ['<select class="form-select" {}>'.format(html_params(**options))]
        for value, label in choices:
            choice_id = '{}-{}'.format(field_id, value)
            choice_options = dict(value=value, id=choice_id)
            if value == field.data:
                choice_options['selected'] = 'selected'
            html.append('<option value="{}" {}>{}</option>'.format(value, html_params(**choice_options), label))
        html.append('</select>')
        return Markup(''.join(html))


# Dummy class for get_field_type() -- switches in Bootstrap are set in the scaffolding, not on the input
class SwitchInput(CheckboxInput):
    pass


class NumberInputGroup(NumberInput):
    def __init__(self, prefix='$', suffix='.00', **kwargs):
        self.prefix = prefix
        self.suffix = suffix
        super().__init__(**kwargs)

    def __call__(self, field, **kwargs):
        html = []
        if self.prefix:
            html.append('<span class="input-group-text">{}</span>'.format(self.prefix))
        html.append(super().__call__(field, **kwargs))
        if self.suffix:
            html.append('<span class="input-group-text rounded-end">{}</span>'.format(self.suffix))

        return Markup(''.join(html))


class CountrySelect(Select):
    """
    Renders a custom select field for countries.
    This is the same as Select but it adds data-alternative-spellings and data-relevancy-booster flags.
    """

    @classmethod
    def render_option(cls, value, label, selected, **kwargs):
        if value is True:
            # Handle the special case of a 'True' value.
            value = str(value)

        options = dict(kwargs, value=value)
        if c.COUNTRY_ALT_SPELLINGS.get(value):
            options["data-alternative-spellings"] = c.COUNTRY_ALT_SPELLINGS[value]
            if value == 'United States':
                options["data-relevancy-booster"] = 3
            elif value in ['Australia', 'Canada', 'United Kingdom']:
                options["data-relevancy-booster"] = 2
        if selected:
            options["selected"] = True
        return Markup(
            "<option {}>{}</option>".format(html_params(**options), escape(label))
        )

class Ranking():
    def __init__(self, choices=None, **kwargs):
        self.choices = choices
        super().__init__(**kwargs)
    
    def extra_info_list(self, choice_item, show_staff_rates=False):
        # Rankings can have a few properties that are displayed differently, but all of them are optional
        # They can be: price (sub-header), staff_price (sub-header displayed during staff lottery),
        #              description (text), description_right (right-aligned text), footnote (form-text text)
        extra_info = []
        if choice_item.get('price'):
            price_str = f"{choice_item['price']}"
            if show_staff_rates and choice_item.get('staff_price'):
                price_str = price_str + f"/{choice_item['staff_price']}"
            extra_info.append(f"""<h5 class="card-subtitle mb-2 text-muted">{price_str}</h5>""")
        if choice_item.get('description') or choice_item.get('description_right'):
            extra_info.append("""<div class="card-text">""")
            if choice_item.get('description'):
                extra_info.append(linebreaksbr(choice_item["description"]))
            if choice_item.get('description_right'):
                extra_info.append(f"""<br/><span class="pull-right text-end">{linebreaksbr(choice_item["description_right"])}</span>""")
            extra_info.append("""</div>""")
        if choice_item.get('footnote'):
            extra_info.append(f"""<div class="form-text">{linebreaksbr(choice_item["footnote"])}</div>""")
        return extra_info
    
    def __call__(self, field, choices=None, show_staff_rates=False, **kwargs):
        choices = choices or self.choices or [('', {"name": "Error", "description": "No choices are configured"})]
        id = kwargs.pop('id', field.id) or "ranking"
        selected_choices = field.data if isinstance(field.data, list) else [str(field.data)]
        read_only = 'readonly' in kwargs and kwargs['readonly']

        deselected_html = []
        selected_html = []
        choice_dict = {key: val for key, val in choices}
        for choice_id in selected_choices:
            try:
                choice_item = choice_dict[choice_id]
                extra_info = self.extra_info_list(choice_item, show_staff_rates=show_staff_rates)
                selected_html.append(f"""
                <li class="card card-body border-dark p-2 p-sm-3" value="{choice_id}">
                    <h4 class="card-title {'mb-0' if not extra_info else 'mb-1 mb-sm-2'}">
                        {choice_item["name"]}
                    </h4>""")
                selected_html.extend(extra_info)
                selected_html.append(f"""
                    <input type="hidden" name="{id}" value="{choice_id}">
                </li>""")
            except KeyError:
                continue
        for choice_id, choice_item in choices:
            if not choice_id in selected_choices:
                extra_info = self.extra_info_list(choice_item, show_staff_rates=show_staff_rates)
                deselected_html.append(f"""
                <li class="card card-body border-dark p-2 p-sm-3" value="{choice_id}">
                    <h4 class="card-title {'mb-0' if not extra_info else 'mb-1 mb-sm-2'}">
                        {choice_item["name"]}
                    </h4>""")
                deselected_html.extend(extra_info)
                deselected_html.append(f"""
                    <input type="hidden" value="{choice_id}">
                </li>""")

        script = f"""
        <script type="text/javascript">
            var showOrHidePlaceholders_{ id } = function(select_or_deselect) {{
                let ulOpts = document.getElementById(select_or_deselect + "ed_{ id }");
                if (ulOpts.children.length == 0) {{
                    ulOpts.classList.add('placeholder-'+ select_or_deselect +'-opt');
                }} else {{
                    ulOpts.classList.remove('placeholder-'+ select_or_deselect +'-opt');
                }}
            }}

            Sortable.create(deselected_{ id }, {{
                group: '{ id }',
                animation: 100
            }});

            Sortable.create(selected_{ id }, {{
                group: '{ id }',
                animation: 100,
                onSort: function(evt) {{
                    el = document.getElementById("selected_{ id }");
                    showOrHidePlaceholders_{ id }("select");
                    for (let i=0; i<el.children.length; i++) {{
                        el.children[i].querySelector("input").setAttribute("name", "{ id }");
                    }}

                    dl = document.getElementById("deselected_{ id }");
                    showOrHidePlaceholders_{ id }("deselect");
                    for (let i=0; i<dl.children.length; i++) {{
                        dl.children[i].querySelector("input").removeAttribute("name");
                    }}
                    
                }}
            }});

            $().ready(function() {{
                showOrHidePlaceholders_{ id }("select");
                showOrHidePlaceholders_{ id }("deselect");
            }});
        </script>"""

        if read_only:
            html = []
        else:
            html = ['<div class="row">']

        if not read_only:
            html.extend([
                '<div class="col-sm-6">',
                f'<span class="form-text">Available {field.label.text}</span>',
                f'<ul class="card card-body bg-light gap-2 p-2 p-sm-3" id="deselected_{id}">',
                *deselected_html,
                '</ul></div>'
                ])
        html.extend([
            '<div class="col-sm-6">',
            f'<span class="form-text">{'' if read_only else 'Selected '}{field.label.text} <em>(ranked top to bottom)</em></span>',
            f'<ul class="card card-body bg-light gap-2 p-2 p-sm-3" id="selected_{id}">',
            *selected_html,
            f'</ul></div>',
            script if not read_only else ''
            ])

        if not read_only:
            html.append('</div>')

        return Markup(''.join(html))