#!/usr/bin/env python3
# pycmpdl.py

import argparse
import json
import logging
import os
import shutil
import signal
import sys
import threading
from multiprocessing import Queue
from multiprocessing.pool import Pool
from zipfile import ZipFile

from requests import Session

VERSION = "1.0.0"

# Exit codes
EXIT_NO_ERROR = 0
EXIT_NO_MODPACK = 2
EXIT_UNKNOWN_MANIFEST_VERSION = 3
EXIT_TERMINATED_BY_USER = 99
EXIT_UNKNOWN_ERROR = 100

PROJECT_BASE_URL = "https://minecraft.curseforge.com/mc-mods/"

# runtime variables
session = Session()
copy_queue = Queue()

# directories
cache_dir = None
modpack_cachedir = None
modpack_basedir = None

logging_lock = threading.Lock()


def log(message, level=logging.INFO):
    with logging_lock:
        logging.log(level, message)


def message(message):
    with logging_lock:
        print(message)


def exit_program(status):
    sys.exit(status)


def exit_with_message(prompt, status):
    if status != 0:
        log(prompt, logging.ERROR)
    else:
        log(prompt)

    exit_program(status)


def signal_handler(signum, frame):
    if signum == signal.SIGINT:
        exit_with_message("Terminated by user", EXIT_TERMINATED_BY_USER)


def check_dir(path, dir_description):
    if not os.path.isdir(path):
        log("creating " + dir_description, logging.DEBUG)
        os.mkdir(path)


def download_file(url, folder=None):
    with session.get(url, allow_redirects=False) as response:
        if 'Location' in response.headers:
            url = response.headers['Location']

        filename = url.split('/')[-1]

        if folder:
            filename = os.path.join(folder, filename)

    with session.get(url, stream=True) as response:
        if os.path.exists(filename):
            remote_size = response.headers['Content-Length']
            local_size = os.path.getsize(filename)

            if int(local_size) == int(remote_size):
                return filename

        with open(filename, 'wb') as out_file:
            for chunk in response.iter_content(chunk_size=1024):
                out_file.write(chunk)

    return filename


def download_mod(file):
    project_url = session.get(PROJECT_BASE_URL + str(file['projectID'])).url

    project_url += "/files/{}/download".format(file['fileID'])

    filename = download_file(project_url, os.path.join(modpack_basedir, "mods"))
    log("Downloaded mod: " + str(filename).split('/')[-1])


def download_mods(manifest):
    global modpack_basedir

    message("Downloading mods...")

    check_dir(os.path.join(modpack_basedir, "mods"), "mods directory")

    download_pool = Pool(4)

    download_pool.map(download_mod, manifest['files'])

    download_pool.close()
    download_pool.join()

    message("Mods downloaded")


def copy_overrides(manifest):
    global modpack_cachedir, modpack_basedir, copy_queue

    message("Copying overrides...")

    override_dir = os.path.join(modpack_cachedir, manifest['overrides'])

    for dirname, dirnames, filenames in os.walk(override_dir):
        for subdirname in dirnames:
            path = os.path.join(dirname, subdirname).replace(override_dir, modpack_basedir)

            check_dir(path, "directory: " + subdirname)

        for filename in filenames:
            path_in = os.path.join(dirname, filename)
            path_out = path_in.replace(override_dir, modpack_basedir)

            shutil.copyfile(path_in, path_out)
            log("Override: " + filename)

    message("Overrides copied")


def main():
    global cache_dir, modpack_cachedir, modpack_basedir

    for signum in [signal.SIGINT]:
        try:
            signal.signal(signum, signal_handler)
        except OSError:
            log("Skipping {}".format(signum), logging.WARNING)

    parser = argparse.ArgumentParser(description="Curse Modpack Downloader",
                                     epilog="Report Bugs to https://github.com/crapStone/pycmpdl/issues")

    parser.add_argument("file", help="URL to Modpack file")
    parser.add_argument("-e", "--exclude", metavar="file", help="json or csv file with mods to ignore")
    parser.add_argument("-s", "--server", action="store_true", help="install server specific files")
    parser.add_argument("-v", "--version", action="version", version=VERSION, help="show version and exit")
    parser.add_argument("-z", "--zip", action="store_true", help="use a zip file instead of URL")

    args = parser.parse_args()

    logging.basicConfig(format='[%(levelname)s]: %(message)s', level=logging.INFO)

    message("Starting Curse server odyssey!")

    cache_dir = os.path.expanduser("~/.cache/pycmpdl/")

    check_dir(cache_dir, "cache directory")

    if not args.zip:
        modpackfile_dir = os.path.join(cache_dir, "modpackfiles")
        check_dir(modpackfile_dir, "modpack files directory")
        message("Downloading Modpack file...")
        file = download_file(args.file, modpackfile_dir)
        message("Modpack file downloaded")
    else:
        file = args.file

    message("Unzipping Modpack file...")

    with ZipFile(file) as zip_file:
        with zip_file.open("manifest.json") as manifest_file:
            manifest = json.load(manifest_file)

            if 'manifestType' not in manifest or not (manifest['manifestType'] == 'minecraftModpack'):
                exit_with_message("Not a Minecraft Modpack!", EXIT_NO_MODPACK)

            if manifest['manifestVersion'] is not 1:
                exit_with_message("Can't read manifest", EXIT_UNKNOWN_MANIFEST_VERSION)

            modpack_basedir = manifest['name']

            modpack_cachedir = os.path.join(cache_dir, modpack_basedir)

            check_dir(modpack_cachedir, "modpack cache directory")

            zip_file.extractall(modpack_cachedir)

    message("Modpack file unzipped")

    check_dir(modpack_basedir, "modpack base directory")

    download_mods(manifest)

    copy_overrides(manifest)

    exit_program(EXIT_NO_ERROR)


if __name__ == '__main__':
    main()
