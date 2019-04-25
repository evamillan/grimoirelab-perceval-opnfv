# -*- coding: utf-8 -*-
#
# Copyright (C) 2015-2017 Bitergia
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program. If not, see <http://www.gnu.org/licenses/>.
#
# Authors:
#     Santiago Dueñas <sduenas@bitergia.com>
#

import json
import logging

from grimoirelab_toolkit.datetime import (datetime_utcnow,
                                          datetime_to_utc,
                                          str_to_datetime)
from grimoirelab_toolkit.uris import urijoin

from ...backend import (Backend,
                        BackendCommand,
                        BackendCommandArgumentParser)
from ...client import HttpClient
from ...utils import DEFAULT_DATETIME

CATEGORY_FUNCTEST = "functest"

logger = logging.getLogger(__name__)


class Functest(Backend):
    """Functest backend for Perceval.

    This class retrieves data from tests stored in a functest
    server. To initialize this class the URL must be provided.
    The `url` will be set as the origin of the data.

    :param url: Functest URL
    :param tag: label used to mark the data
    :param archive: archive to store/retrieve items
    """
    version = '0.4.2'

    CATEGORIES = [CATEGORY_FUNCTEST]

    def __init__(self, url, tag=None, archive=None):
        origin = url

        super().__init__(origin, tag=tag, archive=archive)
        self.url = url
        self.client = None

    def fetch(self, category=CATEGORY_FUNCTEST, from_date=DEFAULT_DATETIME, to_date=None):
        """Fetch tests data from the server.

        This method fetches tests data from a server that were
        updated since the given date.

        :param category: the category of items to fetch
        :param from_date: obtain data updated since this date
        :param to_date: obtain data updated before this date

        :returns: a generator of items
        """
        from_date = datetime_to_utc(from_date) if from_date else DEFAULT_DATETIME
        to_date = datetime_to_utc(to_date) if to_date else datetime_utcnow()

        kwargs = {"from_date": from_date, "to_date": to_date}
        items = super().fetch(category, **kwargs)

        return items

    def fetch_items(self, category, **kwargs):
        """Fetch tests data

        :param category: the category of items to fetch
        :param kwargs: backend arguments

        :returns: a generator of items
        """
        from_date = kwargs['from_date']
        to_date = kwargs['to_date']

        logger.info("Fetching tests data of '%s' group from %s to %s",
                    self.url, str(from_date),
                    str(to_date) if to_date else '--')

        pages = self.client.results(from_date=from_date,
                                    to_date=to_date)
        ndata = 0

        for raw_page in pages:
            parsed_data = self.parse_json(raw_page)

            for test_data in parsed_data:
                yield test_data
                ndata += 1

        logger.info("Fetch process completed: %s tests data fetched", ndata)

    @classmethod
    def has_archiving(cls):
        """Returns whether it supports archiving items on the fetch process.

        :returns: this backend supports items archive
        """
        return True

    @classmethod
    def has_resuming(cls):
        """Returns whether it supports to resume the fetch process.

        :returns: this backend does not support items resuming
        """
        return False

    @staticmethod
    def metadata_id(item):
        """Extracts the identifier from a Functest item."""

        return str(item['_id'])

    @staticmethod
    def metadata_updated_on(item):
        """Extracts and coverts the update time from a Functest item.

        The timestamp is extracted from 'start_date' field as the item
        does not have any info about when it was updated for the last
        time. This time is converted to a UNIX timestamp.

        :param item: item generated by the backend

        :returns: a UNIX timestamp
        """
        ts = item['start_date']
        ts = str_to_datetime(ts)

        return ts.timestamp()

    @staticmethod
    def metadata_category(item):
        """Extracts the category from a Functest item.

        This backend only generates one type of item which is
        'functest'.
        """
        return CATEGORY_FUNCTEST

    @staticmethod
    def parse_json(raw_json):
        """Parse a Functest JSON stream.

        The method parses a JSON stream and returns a
        dict with the parsed data.

        :param raw_json: JSON string to parse

        :returns: a dict with the parsed data
        """
        result = json.loads(raw_json)
        return result['results']

    def _init_client(self, from_archive=False):
        """Init client"""

        return FunctestClient(self.url, self.archive, from_archive)


class FunctestClient(HttpClient):
    """Functest REST API client.

    This class implements a simple client to retrieve data
    from a Functest site using its REST API v1.

    :param base_url: URL of the Functest server
    :param archive: an archive to store/read fetched data
    :param from_archive: it tells whether to write/read the archive
    """
    FUNCTEST_API_PATH = "/api/v1/"

    # API resources
    RRESULTS = 'results'

    # API parameters
    PFROM_DATE = 'from'
    PTO_DATE = 'to'
    PPAGE = 'page'

    # Maximum retries per request
    MAX_RETRIES = 3

    def __init__(self, base_url, archive=None, from_archive=False):
        super().__init__(base_url, max_retries=FunctestClient.MAX_RETRIES,
                         archive=archive, from_archive=from_archive)

    def results(self, from_date, to_date=None):
        """Get test cases results."""

        fdt = from_date.strftime("%Y-%m-%d %H:%M:%S")
        params = {
            self.PFROM_DATE: fdt,
            self.PPAGE: 1
        }

        if to_date:
            tdt = to_date.strftime("%Y-%m-%d %H:%M:%S")
            params[self.PTO_DATE] = tdt

        while True:
            url = urijoin(self.base_url, self.FUNCTEST_API_PATH, self.RRESULTS)
            response = self.fetch(url, payload=params)
            content = response.text
            yield content

            j = json.loads(content)
            page = j['pagination']['current_page']
            total_pages = j['pagination']['total_pages']

            if page >= total_pages:
                break

            params[self.PPAGE] = page + 1


class FunctestCommand(BackendCommand):
    """Class to run Functest backend from the command line."""

    BACKEND = Functest

    @classmethod
    def setup_cmd_parser(cls):
        """Returns the Functest argument parser."""

        parser = BackendCommandArgumentParser(cls.BACKEND.CATEGORIES,
                                              from_date=True,
                                              to_date=True,
                                              archive=True)

        # Required arguments
        parser.parser.add_argument('url',
                                   help="URL of the Functest server")

        return parser
