#!/usr/bin/python
# -* encoding: utf-8 *-

import os
import re
import sys

from distutils.core import setup
from setuptools import find_packages


_HERE = os.path.abspath(os.path.dirname(__file__))


with open("ghconf/__init__.py", "rt", encoding="utf-8") as vf:
    lines = vf.readlines()

_version = "0.0.0+local"
for l in lines:
    m = re.match("version = \"(.*?)\"", l)
    if m:
        _version = m.group(1)

_packages = find_packages(exclude=["*.tests", "*.tests.*", "tests.*", "tests"])

_requirements = [
    'colorama==0.4.1',
    'wrapt==1.10.1',
    'pygithub==1.43.5',
    'aspectlib==1.4.2',
    'tqdm==4.31.1',
]

try:
    long_description = open(os.path.join(_HERE, 'README.rst')).read()
except IOError:
    long_description = None

setup(
    name='optile-ghconf',
    version=_version,
    packages=_packages,
    entry_points={
        "console_scripts": [
            "ghconf = ghconf.main:app",
        ]
    },
    install_requires=_requirements,
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: Developers",
        "Intended Audience :: System Administrators",
        "Environment :: Console",
        "Programming Language :: Python :: 3 :: Only",
        "Operating System :: POSIX",
    ],
    author="Jonas Maurus (@jdelic)",
    author_email="jonas.maurus@optile.net",
    license="MIT",
    description="Apply common Github configuration to a whole organization via the Github API",
    long_description=long_description,
)
