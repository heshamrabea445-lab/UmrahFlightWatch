from datetime import date
from html import escape


def escape_telegram_html(value: object | None) -> str:
    if value is None:
        return ""
    return escape(str(value), quote=False)


def escape_telegram_url(value: str) -> str:
    return escape(value, quote=True)


def html_link(url: str, label: str) -> str:
    return f'<a href="{escape_telegram_url(url)}">{escape_telegram_html(label)}</a>'


def format_currency_cad(price: int) -> str:
    return f"${price:,} CAD"


def format_date_short(value: date) -> str:
    return f"{value.strftime('%b')} {value.day}"


def format_minutes(total_minutes: int | None) -> str | None:
    if total_minutes is None:
        return None
    hours, minutes = divmod(total_minutes, 60)
    if minutes == 0:
        return f"{hours}h"
    return f"{hours}h {minutes}m"
