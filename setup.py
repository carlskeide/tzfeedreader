from setuptools import setup

__version__ = "2.0.0"

setup(name="tzfeedreader",
      version=__version__,
      description="Basic podcatcher with regex whitelists",
      author="Carl Skeide",
      py_modules=["tzfeedreader"],
      entry_points={
        "console_scripts": ["tzfeedreader=tzfeedreader:run"]
      },
      install_requires=[
        "pyyaml",
        "requests",
        "feedparser",
        "click",
      ],
      dependency_links=[
         "git+https://github.com/carlskeide/click-logging#egg=click-logging"
      ])
