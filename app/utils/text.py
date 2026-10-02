from html import escape


LRM = "\u200e"


def tg_name(name: str | None) -> str:
    """Format a Telegram display name so mixed RTL/LTR text stays visually stable."""
    return f"{LRM}{escape(name or 'بازیکن')}{LRM}"


def tg_plain_name(name: str | None) -> str:
    """Direction-isolate a name for plain text contexts such as inline buttons."""
    return f"{LRM}{name or 'بازیکن'}{LRM}"



def tg_mention(user_id: int, name: str | None) -> str:
    """Return a bold Telegram HTML mention for a known user."""
    return f'<b><a href="tg://user?id={int(user_id)}">{escape(name or "بازیکن")}</a></b>'
