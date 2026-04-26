import json

from django import template

register = template.Library()


@register.filter
def get_item(mapping, key):
    if not mapping:
        return None
    return mapping.get(key)


@register.filter
def json_pretty(value):
    """Pretty-print dict/list for <pre> blocks (safe for HTML-escaped output)."""
    if value is None:
        return ""
    try:
        return json.dumps(value, indent=2, default=str)
    except TypeError:
        return str(value)
