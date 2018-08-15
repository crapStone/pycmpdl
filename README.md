# pycmpdl
A Curse Modpack downloader.

This program was inspired by Vazkiis [CMPDL](https://github.com/Vazkii/CMPDL).

### Usage

If you want to download a modpack just go to the curse website and copy the link of the project or of a specific file and use the downloader like this:

```python pycmpdl.py <link_to_modpack>```

Or if you want a MultiMC instance:

```python pycmpdl.py -m <link_to_modpack>```

For server instances please use the link to a server zip file (can be found on the curse website: "Files" > klick on the desired version > "Additional Files") and specify the "-s" option:

```python pycmpdl.py -s <link_to_server_zip>```

If no server files are provided try the following command (with the link to the modpack like above) and delete clientside mods manually:

```python pycmpdl.py -s <link_to_modpack>```

---

Help message:

```
 # pyhon pycmpdl.py -h                                                                       
usage: pycmpdl.py [-h] [--clear-cache] [-m] [-s] [-v] [-z] [-q | -d] file

Curse Modpack Downloader

positional arguments:
  file           URL to Modpack file

optional arguments:
  -h, --help     show this help message and exit
  --clear-cache  clear cache directory
  -m, --multimc  setup a multimc instance
  -s, --server   install server specific files
  -v, --version  show version and exit
  -z, --zip      use a zip file instead of URL
  -q, --quiet    write nothing to output
  -d, --debug    write debug messages to output

Report Bugs to https://github.com/crapStone/pycmpdl/issues
```

### Future plans

Add an option to ignore unwanted mods.

Maybe make a GUI.