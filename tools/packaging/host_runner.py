"""LogiPluginStudioHost.exe – stdlib-only runner for Studio host bundles (.pyz).

Accepts the CPython-compatible call used by generated Shared plugins
(``<runner> -I -B <bundle.pyz> <connection.json>``) and the Studio's native
host bundles. It contains NO Studio/project modules: all plugin code comes from
the bundle, so a runner never mixes Studio and plugin versions. A zipped copy
of the pure-Python standard library (``stdlib.zip``) is appended to
``sys.path`` so trusted handlers can use the normal standard library.
"""
import sys
import os

# AP-POLISH-001: ``asyncio`` MUST be imported before the ``_asyncio`` C extension.
# Importing ``_asyncio`` first initialises it while ``asyncio.tasks`` is only
# half imported; tasks.py then falls back to its pure-Python current_task while
# Task stays the C class, so ``asyncio.current_task()`` is None inside every task
# and ``asyncio.wait_for``/``timeout`` raise "Timeout should be used inside a
# task" (the Shared peer runtime could never connect under the frozen runner).
import asyncio  # noqa: F401,E401  (keep first)
# C-extension and core modules must be imported here so PyInstaller bundles them.
import _socket, select, _ssl, _hashlib, _asyncio, _ctypes, unicodedata, pyexpat, _queue, _overlapped  # noqa: F401,E401
import _bz2, _lzma, _decimal, _elementtree, _multiprocessing, _uuid, _wmi, zoneinfo  # noqa: F401,E401
import asyncio, base64, binascii, collections, contextlib, copy, dataclasses, datetime, enum  # noqa: F401,E401
import functools, hashlib, hmac, http.client, http.server, importlib, importlib.util, io  # noqa: F401,E401
import ipaddress, itertools, json, logging, math, pathlib, queue, random, re, runpy, secrets  # noqa: F401,E401
import selectors, shutil, socket, socketserver, string, struct, tempfile, threading, time  # noqa: F401,E401
import traceback, typing, urllib.parse, uuid, zipfile, zlib, msvcrt, winreg, atexit, argparse  # noqa: F401,E401
import fnmatch, inspect, numbers, operator, textwrap, weakref, decimal, fractions, html, ssl  # noqa: F401,E401
import subprocess, signal, platform, locale, codecs, encodings.idna, encodings.utf_8  # noqa: F401,E401
import xml.etree.ElementTree, email.utils, concurrent.futures, csv, glob, heapq, bisect, statistics  # noqa: F401,E401

FLAGS = {"-I", "-B", "-u", "-E", "-s", "-S"}


def main() -> int:
    base = os.path.dirname(os.path.abspath(sys.executable))
    for candidate in (os.path.join(base, "_internal", "stdlib.zip"), os.path.join(base, "stdlib.zip")):
        if os.path.isfile(candidate):
            sys.path.append(candidate)
            break
    args = list(sys.argv[1:])
    while args and args[0] in FLAGS:
        args.pop(0)
    if args and args[0] == "--version":
        print("LogiPluginStudioHost", sys.version.split()[0])
        return 0
    if not args or not args[0].lower().endswith(".pyz") or not os.path.isfile(args[0]):
        print("usage: LogiPluginStudioHost.exe [-I] [-B] <bundle.pyz> <connection.json>", file=sys.stderr)
        return 2
    sys.argv = args
    runpy.run_path(args[0], run_name="__main__")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
