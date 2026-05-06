from colorama import Fore, Style, init

init(autoreset=True)

def user(msg):
    print(Fore.CYAN + msg)

def ai(msg):
    print(Fore.WHITE + msg)

def debug(msg):
    print(Fore.YELLOW + msg)

def tool(msg):
    print(Fore.GREEN + msg)

def raw(msg):
    print(Fore.BLUE + msg)

def error(msg):
    print(Fore.RED + msg)