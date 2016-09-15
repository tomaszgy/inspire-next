# -*- coding: utf-8 -*-
#
# This file is part of INSPIRE.
# Copyright (C) 2016 CERN.
#
# INSPIRE is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# INSPIRE is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with INSPIRE. If not, see <http://www.gnu.org/licenses/>.
#
# In applying this licence, CERN does not waive the privileges and immunities
# granted to it by virtue of its status as an Intergovernmental Organization
# or submit itself to any jurisdiction.

import pytest


@pytest.yield_fixture(scope='session')
def relations_tester(app):
    from inspirehep.modules.relations import command_producers
    class NeoTester:

        def __init__(self, session):
            self._session = session

        def _get_all_results(self, cypher_query):
            results = self._session.run(cypher_query)
            return [r for r in results]

        def node_exists(self, uid, labels=None,
                        properties=None, is_exactly_same=False):
            """
            Checks whether node with given set of labels and properties exists
            and is the only one matching.
            If is_exactly_same is set, it makes sure that the found node
            doesn't have any extra labels and properties.
            """
            if not properties: properties = {}
            properties['uid'] = uid
            query = 'MATCH ' + command_producers.produce_node_block(
                    labels=labels, properties=properties, variable_name='node'
                    ) + ' RETURN node'

            results = self._get_all_results(query)

            if len(results) == 1:
                if is_exactly_same:
                    node = results[0]['node']
                    are_same_labels = set(labels) == set(node.labels)

                    return node.properties == properties and are_same_labels
                else:
                    return True
            else:
                return False

        def relation_exists(self, start_uid, relation, end_uid,
                            relation_properties=None):
            """
            Checks whether relation of certain type between two nodes exists
            and is the only one matching.

            start_inneoid -- InspireNeoID of the start node
            end_inneoid -- InspireNeoID of the end node
            relation -- type of relation
            """
            relation_string = command_producers.produce_relation_block(
                relation_type=relation, properties=relation_properties,
                variable_name='r',
                arrow_right=True)

            query = (
                'MATCH ({{uid: "{start}"}}) {relation} ({{uid: "{end}"}})'
                'RETURN count(r) AS count'
            ).format(
                start=start_uid, end=end_uid, relation=relation_string
            )
            results = self._get_all_results(query)
            return results[0]['count'] == 1


        def nodes_exist(self, uids):
            """
            Given list of nodes' InspireNeoIDs makes sure that the nodes exist.
            """

            node_blocks = [command_producers.produce_node_block(
                properties={'uid': uid}) for uid in uids]

            query = 'MATCH {} RETURN count(*) > 0 AS do_they_exist'.format(
                ', '.join(node_blocks)
            )
            results = self._get_all_results(query)
            return results[0]['do_they_exist']

    with app.app_context():
        from inspirehep.modules.relations import current_db_session
        yield NeoTester(current_db_session)


def test_fake_test(relations_tester):
    that = relations_tester
    assert that.node_exists('Record|^|1196797')
