# -*- coding: utf-8 -*-
#
# This file is part of INSPIRE.
# Copyright (C) 2016 CERN.
#
# INSPIRE is free software; you can redistribute it
# and/or modify it under the terms of the GNU General Public License as
# published by the Free Software Foundation; either version 2 of the
# License, or (at your option) any later version.
#
# INSPIRE is distributed in the hope that it will be
# useful, but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
# General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with INSPIRE; if not, write to the
# Free Software Foundation, Inc., 59 Temple Place, Suite 330, Boston,
# MA 02111-1307, USA.
#
# In applying this license, CERN does not
# waive the privileges and immunities granted to it by virtue of its status
# as an Intergovernmental Organization or submit itself to any jurisdiction.

import os
import shutil

from invenio_records.models import RecordMetadata


def clear_string(string):
    return string.replace("\\\"", "")


def pick_one_citation_type(labels):
    """
    Used for citation summary, should be replaced with something smarter.
    """
    obvious_types = set(['Literature', 'Record'])
    non_obvious = set(labels) - obvious_types
    if non_obvious:
        return non_obvious.pop()
    else:
        return 'Paper'


def pick_one_field_category(categories):
    """
    Used for citation summary, should be replaced with something smarter.
    """
    return categories[0]


def extract_element(record, field=None, musts=None):
    """A generator that yields all elements matching pattern
    in the specified field inside json.

    Field can be nested e.g. 'authors.affiliations'.
    Musts specify the pattern.
    For element to be yielded it must contain all keys specified in 'musts'.

    If neither field nor musts are specified, the record itself is returned.

    E.g.
    json = {'title': 'Short title',
           'authors': [{'recid': 1},
                       {'name': 'John'},
                       {'recid': 2, 'name': 'Jean', 'year': 2016}]

    extract_elements(json, field='authors', musts=['recid', 'name'])

                    will yield only one element:

    {'recid': 2, 'name': 'Jean', 'year': 2016}
    """
    if not musts: musts = []

    def contains_keys(element, keys=[]):
        if not keys:
            return True
        else:
            if not isinstance(element, dict):
                return False
            else:
                return set(element.keys()) >= set(keys)

    if field:
        subjson = record
        for field_part in field.split('.'):
            subjson = subjson.get(field_part)
            if not subjson:
                break
        if subjson:
            if isinstance(subjson, list):
                for element in subjson:
                    if contains_keys(element, musts):
                        yield element
            else:
                if contains_keys(subjson, musts):
                    yield subjson
    else:
        if contains_keys(record, musts):
            yield record


def prepare_directories(*args):
    for directory in args:
        if os.path.exists(directory):
            shutil.rmtree(directory)
        os.makedirs(directory)


def get_all_records_in_db():
    """Retrieve all records and their count from relational db."""
    return (
        RecordMetadata().query.yield_per(1000),
        RecordMetadata().query.count()
        )
