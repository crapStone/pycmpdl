#!/usr/bin/env python3
# pycmpdl.py

import sys

import argparse
import signal

VERSION = "0.0.0"

# Exit codes
EXIT_NO_ERROR = 0
EXIT_TERMINATED_BY_USER = 99
EXIT_UNKNOWN_ERROR = 100

PROJECT_BASE_URL = "https://minecraft.curseforge.com/mc-mods/"


def exit_program(status):
    sys.exit(status)


def exit_with_message(prompt, status):
    print(prompt)
    exit_program(status)


def signal_handler(signum, frame):
    print(signum)
    if signum == signal.SIGINT:
        exit_with_message("Terminated by user", EXIT_TERMINATED_BY_USER)


def download_file(url):
    pass
    '''
    with urllib.request.urlopen(url) as response, open(file_name, 'wb') as out_file:
        shutil.copyfileobj(response, out_file)
    '''


def main():
    for signum in [signal.SIGINT]:
        try:
            signal.signal(signum, signal_handler)
        except OSError:
            print("Skipping {}".format(signum))

    parser = argparse.ArgumentParser(description="Curse Modpack Downloader",
                                     epilog="Report Bugs to https://github.com/crapStone/pycmpdl/issues")

    parser.add_argument("file", help="URL to Modpack file")
    parser.add_argument("-e", "--exclude", metavar="file", help="json or csv file with mods to ignore")
    parser.add_argument("-s", "--server", action="store_true", help="install server specific files")
    parser.add_argument("-v", "--version", action="version", version=VERSION, help="show version and exit")
    parser.add_argument("-z", "--zip", action="store_true", help="use a zip file instead of URL")

    args = parser.parse_args()

    if not args.zip:
        pass


if __name__ == '__main__':
    main()
