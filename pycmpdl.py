#!/usr/bin/env python3
# pycmpdl.py

import argparse
import json
import logging
import os
import shutil
import signal
import subprocess
import sys
import threading
from queue import Queue
from zipfile import ZipFile

from requests import Session

VERSION = "1.2.0"

# Exit codes
EXIT_NO_ERROR = 0
EXIT_NO_MODPACK = 2
EXIT_UNKNOWN_MANIFEST_VERSION = 3
EXIT_TERMINATED_BY_USER = 99
EXIT_UNKNOWN_ERROR = 100

PROJECT_BASE_URL = "https://minecraft.curseforge.com/mc-mods/"

# runtime variables
session = Session()
print_messages = True

# directories
cache_dir = None
modpack_cachedir = None
modpack_basedir = None

LOCK = threading.Lock()


def log(message, level=logging.INFO):
    logging.log(level, message)


def prompt(message):
    global print_messages

    if print_messages:
        with LOCK:
            print(message)


def exit_program(status):
    sys.exit(status)


def exit_with_message(message, status):
    if status != 0:
        log(message, logging.ERROR)
    else:
        log(message)

    exit_program(status)


def signal_handler(signum, frame):
    if signum == signal.SIGINT:
        exit_with_message("Terminated by user", EXIT_TERMINATED_BY_USER)


def check_dir(path, dir_description):
    if not os.path.isdir(path):
        log("creating " + dir_description, logging.DEBUG)
        os.mkdir(path)


def download_file(url, folder=None, s=session):
    with s.get(url, allow_redirects=False) as response:
        if 'Location' in response.headers:
            url = response.headers['Location']

        filename = url.split('/')[-1]

        if folder:
            filename = os.path.join(folder, filename)

    with s.get(url, stream=True) as response:
        if os.path.exists(filename):
            remote_size = response.headers['Content-Length']
            local_size = os.path.getsize(filename)

            if int(local_size) == int(remote_size):
                return filename

        with open(filename, 'wb') as out_file:
            for chunk in response.iter_content(chunk_size=1024):
                out_file.write(chunk)

    return filename


def download_modpack_file(url):
    global cache_dir

    if url.split('/')[2] == "minecraft.curseforge.com":
        if not url.endswith('files'):
            url += '/files'

        if not url.endswith('latest'):
            url += '/latest'

    modpackfile_dir = os.path.join(cache_dir, "modpackfiles")
    check_dir(modpackfile_dir, "modpack files directory")

    prompt("Downloading Modpack file...")

    file = download_file(url, modpackfile_dir)

    prompt("Modpack file downloaded")

    return file


def unzip_modpack(file):
    global cache_dir, modpack_basedir, modpack_cachedir

    prompt("Unzipping Modpack file...")

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

    prompt("Modpack file unzipped")

    return manifest


def download_mods(manifest):
    global modpack_basedir

    download_queue = Queue()

    def download_mod():
        global download_count

        # Totally hacky, but i couldn't find something else
        try:
            if not download_count:
                download_count = 0
        except NameError:
            download_count = 0

        with Session() as s:
            while True:
                file = download_queue.get()

                project_url = s.get(PROJECT_BASE_URL + str(file['projectID'])).url

                project_url += "/files/{}/download".format(file['fileID'])

                filename = download_file(project_url, os.path.join(modpack_basedir, "mods"), s)
                filename = str(filename).split('/')[-1]

                with LOCK:
                    download_count += 1
                prompt(f"Downloaded mod {download_count} of {mod_count}: {filename}")

                download_queue.task_done()

    prompt("Downloading mods...")

    check_dir(os.path.join(modpack_basedir, "mods"), "mods directory")

    mod_count = len(manifest['files'])

    for i in range(4):
        thread = threading.Thread(target=download_mod)
        thread.daemon = True
        thread.start()

    for file in manifest['files']:
        download_queue.put(file)

    download_queue.join()

    prompt("Mods downloaded")


def copy_overrides(manifest):
    global modpack_cachedir, modpack_basedir

    prompt("Copying overrides...")

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

    prompt("Overrides copied")


def setup_multimc_instance(manifest):
    global modpack_basedir

    def get_forge():
        forge_version = manifest['minecraft']['modLoaders'][0]['id']
        if forge_version.startswith("forge-"):
            return f" Using Forge {forge_version.lstrip('forge-')}."

    prompt("Setting up MultiMC instance...")

    with open(os.path.join(modpack_basedir, "instance.cfg"), "w") as instance_config:
        instance_config.write("InstanceType=OneSix\n"
                              f"IntendedVersion={manifest['minecraft']['version']}\n"
                              "LogPrePostOutput=true\n"
                              "OverrideCommands=false\n"
                              "OverrideConsole=false\n"
                              "OverrideJavaArgs=false\n"
                              "OverrideJavaLocation=false\n"
                              "OverrideMemory=false\n"
                              "OverrideWindow=false\n"
                              "iconKey=default\n"
                              "lastLaunchTime=0\n"
                              f"name={manifest['name']}{manifest['version']}\n"
                              f"notes=Modpack by {manifest['author']}. Generated by CMPDL.{get_forge()}\n"
                              "totalTimePlayed=0\n")

    prompt("MultiMC instance set up")


def setup_server_instance(manifest):
    global modpack_basedir

    def check_java():
        try:
            subprocess.run(["java", "-version"])
            return True

        except FileNotFoundError:
            return False

    prompt("Downloading and installing forge server...")

    minecraft_version = manifest['minecraft']['version']
    forge_version = minecraft_version + "-" + manifest['minecraft']['modLoaders'][0]['id'].lstrip('forge-')
    forge_jar = f"forge-{forge_version}-installer.jar"

    download_file(f"http://files.minecraftforge.net/maven/net/minecraftforge/forge/"
                  f"{forge_version}/forge-{forge_version}-installer.jar", modpack_basedir)

    if not check_java():
        prompt("*************************************************"
               "Can't find java. Please install forge by yourself"
               "*************************************************")
        return

    old_wd = os.getcwd()
    os.chdir(modpack_basedir)
    subprocess.run(["java", "-jar", forge_jar, "--installServer"])
    os.remove(forge_jar)
    os.remove(forge_jar + ".log")
    os.chdir(old_wd)

    prompt("Installed forge")


def main():
    global cache_dir, modpack_cachedir, modpack_basedir, print_messages

    class ActionClearCache(argparse.Action):

        def __call__(self, parser, namespace, values, option_string=None):
            shutil.rmtree(cache_dir)
            exit_program(EXIT_NO_ERROR)

    for signum in [signal.SIGINT]:
        try:
            signal.signal(signum, signal_handler)
        except OSError:
            log("Skipping {}".format(signum), logging.WARNING)

    os_cache_dir = os.path.join(os.path.expanduser("~"), ".cache")
    check_dir(os_cache_dir, "os cache directory")

    cache_dir = os.path.join(os_cache_dir, "pycmpdl")
    check_dir(cache_dir, "cache directory")

    parser = argparse.ArgumentParser(description="Curse Modpack Downloader",
                                     epilog="Report Bugs to https://github.com/crapStone/pycmpdl/issues")

    parser.add_argument("file", help="URL to Modpack file")
    parser.add_argument("--clear-cache", nargs=0, action=ActionClearCache, help="clear cache directory")
    # parser.add_argument("-e", "--exclude", metavar="file", help="json or csv file with mods to ignore")
    parser.add_argument("-m", "--multimc", action="store_true", help="setup a multimc instance")
    parser.add_argument("-s", "--server", action="store_true", help="install server specific files")
    parser.add_argument("-v", "--version", action="version", version=VERSION, help="show version and exit")
    parser.add_argument("-z", "--zip", action="store_true", help="use a zip file instead of URL")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("-q", "--quiet", action="store_true", help="write nothing to output")
    group.add_argument("-d", "--debug", action="store_true", help="write debug messages to output")

    args = parser.parse_args()

    if args.debug:
        logging.basicConfig(format='[%(levelname)s]: %(message)s', level=logging.DEBUG)
    elif args.quiet:
        print_messages = False
    else:
        logging.basicConfig(format='[%(levelname)s]: %(message)s', level=None)

    prompt("Starting Curse server odyssey!")

    if not args.zip:
        file = download_modpack_file(args.file)
    else:
        file = args.file

    manifest = unzip_modpack(file)

    check_dir(modpack_basedir, "modpack base directory")

    download_mods(manifest)

    copy_overrides(manifest)

    if args.server:
        setup_server_instance(manifest)

    elif args.multimc:
        setup_multimc_instance(manifest)

    exit_program(EXIT_NO_ERROR)


if __name__ == '__main__':
    main()
