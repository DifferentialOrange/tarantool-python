#!/usr/bin/env python

import codecs
import os
import re

try:
    from setuptools import setup, find_packages
except ImportError:
    from distutils.core import setup, find_packages

# Extra commands for documentation management
cmdclass = {}
command_options = {}

# Build Sphinx documentation (html)
# python setup.py build_sphinx
# generates files into build/sphinx/html
try:
    from sphinx.setup_command import BuildDoc
    cmdclass["build_sphinx"] = BuildDoc
except ImportError:
    pass


# Upload Sphinx documentation to PyPI (using Sphinx-PyPI-upload)
# python setup.py build_sphinx
# updates documentation at http://packages.python.org/tarantool/
try:
    from sphinx_pypi_upload import UploadDoc
    cmdclass["upload_sphinx"] = UploadDoc
    command_options["upload_sphinx"] = {
        'upload_dir': ('setup.py', os.path.join("build", "sphinx", "html"))
    }
except ImportError:
    pass


# Test runner
# python setup.py test
try:
    from test.setup_command import test
    cmdclass["test"] = test
except ImportError:
    pass


def read(*parts):
    filename = os.path.join(os.path.dirname(__file__), *parts)
    with codecs.open(filename, encoding='utf-8') as fp:
        return fp.read()

def get_dependencies(file):
    root = os.path.dirname(os.path.realpath(__file__))
    requirements = os.path.join(root, file)
    result = []
    if os.path.isfile(requirements):
        with open(requirements) as f:
            return f.read().splitlines()
    raise RuntimeError("Unable to get dependencies from file " + file)

def find_version(*file_paths):
    version_file = read(*file_paths)
    version_match = re.search(r"""^__version__\s*=\s*(['"])(.+)\1""",
                              version_file, re.M)
    if version_match:
        return version_match.group(2)
    raise RuntimeError("Unable to find version string.")

packages = [item for item in find_packages('.') if item.startswith('tarantool')]

setup(
    name="tarantool",
    packages=packages,
    package_dir={"tarantool": "tarantool"},
    include_package_data=True,
    version=find_version('tarantool', '__init__.py'),
    platforms=["all"],
    author="tarantool-python AUTHORS",
    author_email="admin@tarantool.org",
    url="https://github.com/tarantool/tarantool-python",
    license="BSD",
    description="Python client library for Tarantool 1.6 Database",
    long_description=read('README.rst'),
    long_description_content_type='text/x-rst',
    classifiers=[
        "Intended Audience :: Developers",
        "License :: OSI Approved :: BSD License",
        "Operating System :: OS Independent",
        "Programming Language :: Python",
        "Topic :: Database :: Front-Ends"
    ],
    cmdclass=cmdclass,
    command_options=command_options,
    install_requires=get_dependencies('requirements.txt'),
    python_requires='>=3',
)
