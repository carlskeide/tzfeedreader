#!/usr/bin/env python2.7

import sys
import os.path
import logging
import sqlite3
import unicodedata
import re
from datetime import datetime

import yaml
import requests
import feedparser
import click
import click_logging

click_logging.basicConfig(logging.INFO)
logger = click_logging.getLogger('main')

DEFAULT_CONFIG_FILE = "~/.tzfeedreader.yaml"
DEFAULT_HISTORY_FILE = "~/.tzfeedreader.db"
HISTORY_SCHEMA = """
    CREATE TABLE IF NOT EXISTS history (
        date DATETIME,
        feed TEXT,
        url TEXT,
        title TEXT
    )
"""

HEADERS = {"User-agent": "TzFeedReader"}


def sanitize_filename(value):
    value = unicodedata.normalize('NFKD', value).encode('ascii', 'ignore')
    value = unicode(re.sub('[^\w\s-]', '', value).strip())
    value = unicode(re.sub('[\s]+', ' ', value))
    return value


class PushBullet(object):
    def __init__(self, token, device=None):
        self.token = token
        self.device = device

    def send(self, feed, title):
        payload = {
            "type": "note",
            "title": "New item from {}".format(feed),
            "body": title
        }

        if self.device:
            payload["device_iden"] = self.device

        try:
            response = requests.post(
                "https://api.pushbullet.com/v2/pushes",
                headers={"Access-Token": self.token},
                json=payload
            )
            response.raise_for_status()

        except Exception as e:
            logger.warning("Pushbullet notification failed: %s", e.message)


class History(object):
    def __init__(self, file_path):
        file_name = os.path.expanduser(DEFAULT_HISTORY_FILE)
        self.connection = sqlite3.connect(file_name)

        self.cursor.execute(HISTORY_SCHEMA)
        self.connection.commit()

    @property
    def cursor(self):
        return self.connection.cursor()

    def store(self, feed, url, title):
        logger.debug("Adding %s to history", title)
        self.cursor.execute(
            """INSERT INTO history
                (date, feed, url, title)
            VALUES (?, ?, ?, ?)""",
            (datetime.now(), feed, url, title)
        )
        self.connection.commit()

    def get(self, feed, title):
        res = self.cursor.execute(
            "SELECT date FROM history WHERE feed = ? AND title = ?",
            (feed, title)
        ).fetchone()

        return res if res else False

    def close(self):
        self.connection.close()


class Feed(object):
    request_args = {}
    whitelist = []

    def __init__(self, name, history, url, output, auth=None, whitelist=None):
        self.name = name
        self.history = history
        self.feed_url = url
        self.downloads = 0

        self.output = os.path.expanduser(output)
        logger.debug("Using output folder: %s", self.output)

        if isinstance(auth, str):
            self.request_args["auth"] = ":".split(auth)
            logger.debug("Using basic auth")

        elif isinstance(auth, dict):
            self.request_args["params"] = auth
            logger.debug("Using auth params: %s", auth.keys())

        if whitelist is not None:
            self.whitelist = [re.compile(pattern) for pattern in whitelist]
            logger.debug("Loaded %d whitelist patterns", len(whitelist))

        self.items = self.get_index()
        logger.debug("Found %d items", len(self.items))

    def get_index(self):
        logger.debug('Fetching feed index')
        feed_xml = requests.get(self.feed_url, headers=HEADERS,
                                **self.request_args)
        feed_xml.raise_for_status()

        logger.debug('Parsing feed')
        xml = feedparser.parse(feed_xml.text)
        return xml.entries

    def get_all(self):
        # Get oldest items first.
        for item in reversed(self.items):
            clean_title = sanitize_filename(item.title)
            logger.debug("Parsing item: %s", clean_title)

            if self.whitelist:
                if not any([p.match(item.title) for p in self.whitelist]):
                    logger.debug("Skipping item, no whitelist matches")
                    continue

            item_history = self.history.get(self.name, item.title)
            if item_history:
                logger.debug("Skipping item, downloaded at %s", item_history[0])
                continue

            for link in item.links:
                if link.rel == "enclosure" and link.href:
                    logger.debug("Found URL: %s", link.href)
                    item_link = link
                    break

            else:
                logger.warning("Skipping item: %s, no valid urls", clean_title)
                continue

            file_type = item_link.type.split("/")[-1]
            file_name = "{}.{}".format(clean_title, file_type)
            file_path = os.path.join(self.output, file_name)

            if os.path.exists(file_path):
                logger.debug("Skipping item, output path exists")
                continue

            logger.info("Downloading item %s", clean_title)
            try:
                self.download_item(link.href, file_path)
                yield clean_title

            except Exception as e:
                logger.warning("Skipping item: %s, download failed", e.message)
                continue

            self.history.store(self.name, link.href, item.title)

    def download_item(self, item_url, output_path):
        data = requests.get(item_url, headers=HEADERS, stream=True,
                            **self.request_args)
        data.raise_for_status()

        data_len = int(data.headers.get('content-length'))
        with click.progressbar(length=data_len) as bar:
            with open(output_path, 'wb') as output:
                for chunk in data.iter_content(chunk_size=1024 * 10):
                    bar.update(len(chunk))
                    output.write(chunk)

        self.downloads += 1


@click.command()
@click.option("-v", "--verbose", is_flag=True)
@click.option("-c", "--config", "config_file",
              type=click.Path(readable=True), default=DEFAULT_CONFIG_FILE)
@click.option("-h", "--history", "history_path",
              type=click.Path(writable=True), default=DEFAULT_HISTORY_FILE)
def run(verbose, config_file, history_path):
    if verbose:
        logger.setLevel(logging.DEBUG)

    logger.info("Start %s", datetime.now())
    logger.debug("Reading config file")
    try:
        with open(os.path.expanduser(config_file)) as fh:
            config = yaml.load(fh)

    except Exception:
        logger.error("Unable to parse config file: %s", config_file)
        sys.exit(1)

    logger.debug("Initializing notifers")
    notifiers = []
    for notifier in config.get("notifiers", []):
        if notifier == "pushbullet":
            logger.debug("Adding pushbullet notifier")
            pushbullet = PushBullet(**config["notifiers"]["pushbullet"])
            notifiers.append(pushbullet)

    logger.debug("Intializing feed history")
    try:
        history = History(history_path)

    except Exception:
        logger.error("Unable to intialize feed history")
        sys.exit(1)

    for feed_name, feed_cfg in config["feeds"].iteritems():
        logger.info("Processing %s", feed_name)
        try:
            feed = Feed(feed_name, history=history, **feed_cfg)

        except Exception as e:
            logger.error("Unable to load feed: %s", e.message)
            continue

        for title in feed.get_all():
            logger.debug("Updating notifers")
            for notifier in notifiers:
                notifier.send(feed_name, title)

        logger.info("Downloaded %d items", feed.downloads)

    logger.info("End %s", datetime.now())

if __name__ == '__main__':
    run()
