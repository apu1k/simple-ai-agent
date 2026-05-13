from colorama import Fore, Style, init


init(autoreset=True)


_DEBUG_ENABLED = False


def set_debug(enabled: bool):
    global _DEBUG_ENABLED
    _DEBUG_ENABLED = bool(enabled)


def is_debug_enabled():
    return _DEBUG_ENABLED


def user(msg):
    print(Fore.CYAN + msg)


def ai(msg):
    print(Fore.WHITE + msg)


def debug(msg):
    if _DEBUG_ENABLED:
        print(Fore.YELLOW + msg)


def tool(msg):
    if _DEBUG_ENABLED:
        print(Fore.GREEN + msg)


def raw(msg):
    if _DEBUG_ENABLED:
        print(Fore.BLUE + msg)


def error(msg):
    print(Fore.RED + msg)