#!/usr/bin/env python3
# coding: utf-8
#
# Check if local WordPress installations need to be updated
# The check is performed both for the core WordPress and the plugins
#

from datetime import datetime
import os
import re
import sys
from typing import Optional, Tuple, Union

import chardet
from bs4 import BeautifulSoup
import dateutil.parser as dateparser
from packaging import version
import requests


PackageVersion = Union[version.Version, version.LegacyVersion]


def read_file(file_name: str) -> str:
    """
    Read a text file, handling different encoding.
    """
    with open(file_name, "rb") as f:
        rawdata = f.read()
    try:
        return rawdata.decode("utf-8")
    except UnicodeDecodeError:
        detected = chardet.detect(rawdata)
        return rawdata.decode(detected["encoding"])


class WordPressOnline:
    """
    Parses online WordPress data.
    """

    def __init__(self):
        self.wp_cache = {}  # Most recent WP version per branch ---> release date
        self.plugin_cache = {}  # Plugin slug ---> last version

    def get_wp_branch_last_version_release_date(
        self, wp_version: str
    ) -> Optional[datetime]:
        """
        Returns the release date of the given version, but only if it is the
        last version of its branch. Returns None otherwise.
        """
        if not self.wp_cache:
            req = requests.get("https://wordpress.org/download/releases/")
            soup = BeautifulSoup(req.text, "html.parser")
            for table in soup.find_all("table"):
                tr = table.find("tr")
                tds = tr.find_all("td")
                version = tds[0].text
                date = dateparser.parse(tds[1].text)
                self.wp_cache[version] = date
        return self.wp_cache.get(wp_version)

    def get_plugin_last_version(
        self, plugin_slug: str
    ) -> Tuple[Optional[PackageVersion], Optional[bool]]:
        """
        Returns a tuple with the last version of the plugin and a boolean indicating
        whether or not the plugin has been closed.
        """
        if plugin_slug in self.plugin_cache:
            return self.plugin_cache[plugin_slug]
        # Sometimes the JSON API returns inconsistent results (e.g. duplicate-page)
        req = requests.get(f"https://wordpress.org/plugins/{plugin_slug}")
        if req.ok:
            soup = BeautifulSoup(req.text, "html.parser")
            closed = req.text.find("This plugin has been closed") != -1
            entry_meta = soup.find(class_="entry-meta")
            if entry_meta:
                versions = re.findall(r"Version:\s*([0-9\.]+)", entry_meta.text)
                if versions:
                    plugin_version = version.parse(versions[0])
                    self.plugin_cache[plugin_slug] = [plugin_version, closed]
                    return plugin_version, closed
        return None, None


def is_wordpress(directory: str) -> bool:
    """
    Naive on-disk WordPress detection.
    """
    return os.path.exists(os.path.join(directory, "wp-content")) and os.path.exists(
        os.path.join(directory, "wp-includes")
    )


def check_plugin(wp: WordPressOnline, plugins_dir: str, plugin_slug: str):
    """
    Checks whether the specified plugin is out-of-date or closed.
    """
    plugin_dir = os.path.join(plugins_dir, plugin_slug)
    plugin_name = None
    plugin_version_str = None

    for php_file in os.listdir(plugin_dir):
        php_file = os.path.join(plugin_dir, php_file)
        if not os.path.isfile(php_file) or not php_file.endswith(".php"):
            continue
        php_code = read_file(php_file)
        matches = re.findall(r"Plugin Name:\s*(.+?)$", php_code, re.MULTILINE)
        if not matches:
            continue
        plugin_name = matches[0]
        matches = re.findall(r"Version:\s*(.+?)$", php_code, re.MULTILINE)
        if not matches:
            continue
        plugin_version_str = matches[0]
    if not plugin_name or not plugin_version_str:
        return
    last_version, closed = wp.get_plugin_last_version(plugin_slug)
    plugin_version = version.parse(plugin_version_str)
    if closed:
        print(f"   {plugin_slug}: CLOSED")
    elif last_version and plugin_version < last_version:
        print(
            f"   {plugin_slug}: updated required from {plugin_version} to {last_version}"
        )


def check_wordpress_plugins(wp: WordPressOnline, wp_dir: str):
    """
    Checks if the plugins of the specified WordPress installation are
    out-of-date or closed.
    """
    plugins_dir = os.path.join(wp_dir, "wp-content", "plugins")
    if not os.path.exists(plugins_dir):
        return
    print(f"Plugins: {plugins_dir}")
    for plugin_slug in os.listdir(plugins_dir):
        plugin_dir = os.path.join(plugins_dir, plugin_slug)
        if not os.path.isdir(plugin_dir):
            continue
        check_plugin(wp, plugins_dir, plugin_slug)


def get_wp_version(wp_dir: str) -> Optional[str]:
    """
    Extract the WP version from an on-disk installation.
    """
    version_php = os.path.join(wp_dir, "wp-includes", "version.php")
    if not os.path.exists(version_php):
        return None
    php_code = read_file(version_php)
    versions = re.findall(r"\$wp_version\s*=\s*'([^']+)'", php_code, re.MULTILINE)
    if not versions:
        return None
    return versions[0]


def check_wordpress(rootdir: str):
    """
    Checks if WordPress and its plugins are updated.
    """
    wp = WordPressOnline()
    for wp_dir, dirs, files in os.walk(rootdir):
        if is_wordpress(wp_dir):
            print("-" * 40)
            print(f"WordPress: {wp_dir}")
            wp_version = get_wp_version(wp_dir)
            if not wp_version:
                print("   wp-includes/version.php not found, skipping.")
                continue
            print(f"   Version: {wp_version}")
            release_date = wp.get_wp_branch_last_version_release_date(wp_version)
            if not release_date:
                print("   This WordPress version is OUT-OF-DATE")
            elif (datetime.now() - release_date).days > 180:
                print("   This WordPress version is probabily outdated")
            check_wordpress_plugins(wp, wp_dir)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: wp-check <DIRECTORY>\n")
        print("Check for out-of-date WordPress core and plugin installations.")
        print("The check is performed recursively within the specified directory.")
        sys.exit(0)
    check_wordpress(sys.argv[1])
