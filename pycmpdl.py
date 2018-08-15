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

VERSION = "1.3.0"

# Exit codes
EXIT_NO_ERROR = 0
EXIT_NO_MODPACK = 2
EXIT_UNKNOWN_MANIFEST_VERSION = 3
EXIT_TERMINATED_BY_USER = 9

PROJECT_BASE_URL = "https://minecraft.curseforge.com/mc-mods/"

# runtime variables
session = Session()
print_messages = True
is_os_windows = os.name == 'nt'

# directories
cache_dir = None
modpack_cachedir = None
modpack_basedir = None
minecraft_dir = None

LOCK = threading.Lock()


def log(message, level=logging.INFO):
    logging.log(level, message)


def safe_print(message):
    global print_messages

    if print_messages:
        with LOCK:
            print(message)


def ask_permission(prompt, default_yes=True):
    answer = None
    choice = '[Y/n]: ' if default_yes else '[y/N]: '
    while not (answer == 'n' or answer == 'y' or answer == ''):
        answer = str(input(prompt + choice)).lower()

    if answer == 'y':
        return True
    elif answer == 'n':
        return False
    elif answer == '':
        return default_yes
    else:
        return None


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

    splitted_url = url.split('/')

    if splitted_url[2] == "minecraft.curseforge.com":
        if not (splitted_url[-2] == "files" or splitted_url[-3] == "files"):
            if not url.endswith('files'):
                url += '/files'

            if not url.endswith('latest'):
                url += '/latest'
        elif splitted_url[-2] == 'files' and splitted_url[-1].isdecimal():
            url += '/download'

    modpackfile_dir = os.path.join(cache_dir, "modpackfiles")
    check_dir(modpackfile_dir, "modpack files directory")

    safe_print("Downloading Modpack file...")

    file = download_file(url, modpackfile_dir)

    safe_print("Modpack file downloaded")

    return file


def unzip_modpack(file):
    global cache_dir, modpack_basedir, modpack_cachedir

    safe_print("Unzipping Modpack file...")

    with ZipFile(file) as zip_file:
        with zip_file.open("manifest.json") as manifest_file:
            manifest = json.load(manifest_file)

            if 'manifestType' not in manifest or not (manifest['manifestType'] == 'minecraftModpack'):
                exit_with_message("Not a Minecraft Modpack!", EXIT_NO_MODPACK)

            if manifest['manifestVersion'] is not 1:
                exit_with_message("Can't read manifest", EXIT_UNKNOWN_MANIFEST_VERSION)

            modpack_basedir = os.path.join(os.getcwd(), manifest['name'])

            modpack_cachedir = os.path.join(cache_dir, modpack_basedir)

            check_dir(modpack_cachedir, "modpack cache directory")

            zip_file.extractall(modpack_cachedir)

    safe_print("Modpack file unzipped")

    return manifest


def download_mods(manifest):
    global minecraft_dir

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

                filename = download_file(project_url, os.path.join(minecraft_dir, "mods"), s)
                filename = str(filename).split('/')[-1]

                with LOCK:
                    download_count += 1
                safe_print(f"Downloaded mod {download_count} of {mod_count}: {filename}")

                download_queue.task_done()

    safe_print("Downloading mods...")

    check_dir(os.path.join(minecraft_dir, "mods"), "mods directory")

    mod_count = len(manifest['files'])

    for i in range(4):
        thread = threading.Thread(target=download_mod)
        thread.daemon = True
        thread.start()

    for file in manifest['files']:
        download_queue.put(file)

    download_queue.join()

    safe_print("Mods downloaded")


def copy_overrides(manifest):
    global modpack_cachedir, minecraft_dir

    safe_print("Copying overrides...")

    override_dir = os.path.join(modpack_cachedir, manifest['overrides'])

    for dirname, dirnames, filenames in os.walk(override_dir):
        for subdirname in dirnames:
            path = os.path.join(dirname, subdirname).replace(override_dir, minecraft_dir)

            check_dir(path, "directory: " + subdirname)

        for filename in filenames:
            path_in = os.path.join(dirname, filename)
            path_out = path_in.replace(override_dir, minecraft_dir)

            shutil.copyfile(path_in, path_out)
            log("Override: " + filename)

    safe_print("Overrides copied")


def setup_multimc_instance(manifest):
    global modpack_basedir

    def get_forge():
        forge_version = manifest['minecraft']['modLoaders'][0]['id']
        if forge_version.startswith("forge-"):
            return f" Using Forge {forge_version.lstrip('forge-')}."

    safe_print("Setting up MultiMC instance...")

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

    safe_print("MultiMC instance set up")


def install_forge_server(forge_version):
    global minecraft_dir

    def check_java():
        try:
            subprocess.run(["java", "-version"])
            return True

        except FileNotFoundError:
            return False

    forge_jar = f"forge-{forge_version}-installer.jar"

    download_file(f"http://files.minecraftforge.net/maven/net/minecraftforge/forge/"
                  f"{forge_version}/forge-{forge_version}-installer.jar", minecraft_dir)

    if not check_java():
        safe_print("*********************************************************"
                   "    Can't find java. Please install forge by yourself"
                   "*********************************************************")
        return

    old_wd = os.getcwd()
    os.chdir(minecraft_dir)
    subprocess.run(["java", "-jar", forge_jar, "--installServer"])
    os.remove(forge_jar)
    os.remove(forge_jar + ".log")
    os.chdir(old_wd)

    return forge_jar.replace("install", "universal")


def install_start_script(forge_server_jar):
    global is_os_windows, minecraft_dir

    if is_os_windows:
        with open(os.path.join(minecraft_dir, "settings.bat"), 'w') as settings_script:
            settings_script.write("REM Don\'t edit these values unless you know what you are doing.\n"
                                  f"set SERVER_JAR={forge_server_jar}\n\n"
                                  "REM You can edit these values if you wish.\n"
                                  "set MIN_RAM=1024M\n"
                                  "set MAX_RAM=4096M\n"
                                  "set JAVA_PARAMETERS=-XX:+UseG1GC -Dsun.rmi.dgc.server.gcInterval=2147483646 "
                                  "-XX:+UnlockExperimentalVMOptions -XX:G1NewSizePercent=20 -XX:G1ReservePercent=20 "
                                  "-XX:MaxGCPauseMillis=50 -XX:G1HeapRegionSize=32M -Dfml.readTimeout=180")

        with open(os.path.join(minecraft_dir, "ServerStart.bat"), 'w') as server_script:
            server_script.write("@echo off\n\n"
                                "call settings.bat\n\n"
                                ":start_server\n"
                                "echo Starting Minecraft Server...\n"
                                "java -server -Xms%MIN_RAM% -Xmx%MAX_RAM% %JAVA_PARAMETERS% -jar %SERVER_JAR% nogui\n"
                                "exit /B\n\n"
                                "goto start_server")

    else:
        with open(os.path.join(minecraft_dir, "settings.sh"), 'w') as settings_script:
            settings_script.write('# Don\'t edit these values unless you know what you are doing.\n'
                                  f'export SERVER_JAR="{forge_server_jar}"\n\n'
                                  '# You can edit these values if you wish.\n'
                                  'export MIN_RAM="1024M"\n'
                                  'export MAX_RAM="4096M"\n'
                                  'export JAVA_PARAMETERS="-XX:+UseG1GC -Dsun.rmi.dgc.server.gcInterval=2147483646 '
                                  '-XX:+UnlockExperimentalVMOptions -XX:G1NewSizePercent=20 -XX:G1ReservePercent=20 '
                                  '-XX:MaxGCPauseMillis=50 -XX:G1HeapRegionSize=32M -Dfml.readTimeout=180')

        with open(os.path.join(minecraft_dir, "ServerStart.sh"), 'w') as server_script:
            server_script.write('#!/bin/sh\n\n'
                                '# Read the settings.\n'
                                '. ./settings.sh\n\n'
                                '# Start the server.\n'
                                'start_server() {\n'
                                '    java -server -Xms${MIN_RAM} -Xmx${MAX_RAM} ${JAVA_PARAMETERS} -jar ${SERVER_JAR} nogui\n'
                                '}\n\n'
                                'echo "Starting SevTech Ages Server..."\n'
                                'start_server')

    safe_print("***************************************************************************"
               "    Please look at the settings file and change the values if you need!"
               "***************************************************************************")


def setup_server_instance(manifest):
    global minecraft_dir

    safe_print("Setting up server...")

    minecraft_version = manifest['minecraft']['version']
    forge_version = minecraft_version + "-" + manifest['minecraft']['modLoaders'][0]['id'].lstrip('forge-')

    forge_server_jar = install_forge_server(forge_version)

    script_ending = '.bat' if is_os_windows else '.sh'

    start_script = None
    for path in os.listdir(minecraft_dir):
        path_l = path.lower()

        if path_l.find('start'):
            if path_l.endswith(script_ending):
                if not start_script:
                    start_script = path
                else:
                    log("multiple start scripts found", logging.WARNING)

    if not start_script:
        if ask_permission("No start script found!\nInstall start script?"):
            install_start_script(forge_server_jar)

    safe_print("Successfully setup server")


def setup_server_from_zip(file):
    global is_os_windows, minecraft_dir

    safe_print("Setting up server...")

    if not minecraft_dir:
        safe_print("Filename is: " + file.split('/')[-1])
        server_name = input("Insert name of server instance: ")

        minecraft_dir = os.path.join(os.getcwd(), server_name)

    check_dir(minecraft_dir, "Server directory")

    with ZipFile(file) as zip_file:
        zip_file.extractall(minecraft_dir)

    files = {'start_script': None, 'install_script': None, 'forge_server_jar': None, 'forge_install_jar': None}

    script_ending = '.bat' if is_os_windows else '.sh'

    for path in os.listdir(minecraft_dir):
        path_l = path.lower()

        if path_l.find('install') >= 0:
            if path_l.endswith(script_ending):
                if not files['install_script']:
                    files['install_script'] = path
                else:
                    log("multiple install scripts found", logging.WARNING)

            elif path_l.endswith('.jar'):
                if not files['forge_install_jar']:
                    files['forge_install_jar'] = path
                else:
                    log("multiple install jars found", logging.WARNING)

        elif path_l.find('start') >= 0:
            if path_l.endswith(script_ending):
                if not files['start_script']:
                    files['start_script'] = path
                else:
                    log("multiple start scripts found", logging.WARNING)

        elif path_l.find('server') >= 0:
            if path_l.endswith('.jar'):
                if not files['forge_server_jar']:
                    files['forge_server_jar'] = path
                else:
                    log("multiple server jars found", logging.WARNING)

    if files['install_script'] and not files['forge_server_jar']:
        if ask_permission("Install forge with existing script?"):
            script = os.path.join(minecraft_dir, files['install_script'])

            old_wd = os.getcwd()
            os.chdir(minecraft_dir)

            os.chmod(script, 0o766)
            subprocess.run([script], shell=True)

            os.chdir(old_wd)

    elif files['forge_install_jar'] and not files['forge_server_jar']:
        if ask_permission("Install forge with forge install jar?"):
            forge_jar = os.path.join(minecraft_dir, files['forge_install_jar'])

            old_wd = os.getcwd()
            os.chdir(minecraft_dir)

            subprocess.run(["java", "-jar", forge_jar, "--installServer"])

            os.remove(forge_jar)
            os.remove(forge_jar + ".log")
            os.chdir(old_wd)

    elif not files['forge_server_jar']:
        if ask_permission("No forge server files found!\nInstall forge?"):
            files['forge_server_jar'] = install_forge_server(
                input("Which forge version is needed? (e.g. 1.12.2-14.23.4.2707): "))

    if not files['start_script']:
        if ask_permission("No start script found!\nInstall start script?"):
            install_start_script(files['forge_server_jar'])

    safe_print("Successfully setup server")


def main():
    global is_os_windows, cache_dir, modpack_cachedir, modpack_basedir, minecraft_dir, print_messages

    class ActionClearCache(argparse.Action):

        def __call__(self, parser, namespace, values, option_string=None):
            shutil.rmtree(cache_dir)
            exit_program(EXIT_NO_ERROR)

    for signum in [signal.SIGINT]:
        try:
            signal.signal(signum, signal_handler)
        except OSError:
            log("Skipping {}".format(signum), logging.WARNING)

    if is_os_windows:
        os_cache_dir = os.path.join(os.path.expanduser("~"), "AppData", "Local", "Temp")
    else:
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

    safe_print("Starting Curse server odyssey!")

    if not args.zip:
        file = download_modpack_file(args.file)
    else:
        file = args.file

    try:
        manifest = unzip_modpack(file)
    except KeyError as e:
        if args.server:
            if e.args[0] == "There is no item named 'manifest.json' in the archive":
                setup_server_from_zip(file)
                exit_program(EXIT_NO_ERROR)
            else:
                raise e
        else:
            exit_with_message("This is no modpack", EXIT_NO_MODPACK)

    if args.multimc:
        minecraft_dir = os.path.join(modpack_basedir, ".minecraft")
    else:
        minecraft_dir = modpack_basedir

    check_dir(modpack_basedir, "modpack base directory")
    check_dir(minecraft_dir, "minecraft directory")

    download_mods(manifest)

    copy_overrides(manifest)

    if args.server:
        setup_server_instance(manifest)

    elif args.multimc:
        setup_multimc_instance(manifest)

    exit_program(EXIT_NO_ERROR)


if __name__ == '__main__':
    main()
