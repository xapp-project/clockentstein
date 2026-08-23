import locale
import re


def capitalize_first(value):
    return value[:1].upper() + value[1:]


def format_time(value):
    pattern = locale.nl_langinfo(locale.T_FMT)
    if "%I" in pattern or "%r" in pattern:
        return value.strftime("%l:%M%P").strip()

    pattern = pattern.replace("%T", "%H:%M:%S")
    pattern = re.sub(r"([:.])?%S", "", pattern)
    return value.strftime(pattern).strip()
