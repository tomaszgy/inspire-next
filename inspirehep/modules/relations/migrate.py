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


import click
import csv
import os

from functools import partial
from itertools import islice
from uuid import uuid4

from inspirehep.modules.relations.proxies import current_db_session

from inspirehep.modules.relations import command_producers as produce_command
from inspirehep.modules.relations.model.indices import (
    INDICES_TO_CREATE
)
from inspirehep.modules.relations import builders
from inspirehep.modules.relations.graph_representation import (
    get_central_node,
    get_node_labels,
    get_node_properties,
    get_node_uid,
    get_node_type,
    get_outgoing_relations,
    get_relation_properties,
    get_relation_type,
    get_start_node,
    get_end_node,
    produce_model_from_node,
    should_create_end_node_if_not_exists
    )
from inspirehep.modules.relations.model.init_model import pregenerate_graph
from inspirehep.modules.relations.utils import prepare_directories
from inspirehep.modules.pidstore.providers import InspireRecordIdProvider

INDEX_TO_BUILDER = {
    'authors': builders.hepnames.hepnames,
    'journals': builders.journals.journals,
    'jobs': builders.jobs.jobs,
    'literature': builders.literature.literature,
    'experiments': builders.experiments.experiments,
    'conferences': builders.conferences.conferences,
    'institutions': builders.institutions.institutions
}

NODES_SUBDIRECTORY = 'nodes'
RELATIONS_SUBDIRECTORY = 'relations'
CHUNK_SIZE = 40000


def lazy_chunker(iterable, size=10):
    iterator = iter(iterable)
    for first in iterator:    # stops when iterator is depleted
        def chunk():          # construct generator for next chunk
            yield first       # yield element from for loop
            for more in islice(iterator, size - 1):
                yield more    # yield more elements from the iterator
        yield chunk()         # in outer generator, yield next chunk


def generate_file_name():
    return str(uuid4()) + '.csv'


def nested_setdefault(dictionary, keys, default=None):
    current_dict = dictionary
    for key in keys[:-1]:
        try:
            current_dict = current_dict.setdefault(key, dict())
        except AttributeError:
            raise TypeError(
                'Wrong internal structure. ' + '.'.join(
                    keys[:keys.index(key)]
                    ) + ' is already something else than dict.'
                )
    return current_dict.setdefault(keys[-1], default)


def make_labels_key(labels):
    return tuple(sorted(labels))


def make_properties_key(properties):
    return tuple(sorted(properties.keys()))


def move_central_node_to_proper_group(node, groups):
    labels_key = make_labels_key(get_node_labels(node))
    properties_key = make_properties_key(get_node_properties(node))

    try:
        proper_group = groups[labels_key][properties_key]
    except (TypeError, KeyError):
        proper_group = nested_setdefault(groups,
                                        [labels_key, properties_key],
                                        list())

    proper_group.append(node)


def move_relation_to_proper_group(relation, groups):
    relation_type = get_relation_type(relation)
    start_node_type = get_node_type(get_start_node(relation))
    end_node_type = get_node_type(get_end_node(relation))
    properties_key = make_properties_key(get_relation_properties(relation))

    try:
        proper_group = groups[relation_type][start_node_type][
            end_node_type][properties_key]
    except (TypeError, KeyError):
        proper_group = nested_setdefault(groups,
                                         [relation_type, start_node_type,
                                          end_node_type,properties_key],
                                         list())

    proper_group.append(relation)


def process_record_model(model, existing_uids,
                         nodes_to_create, relations_to_create):
    central_node = get_central_node(model)
    central_uid = get_node_uid(central_node)

    if central_uid not in existing_uids:
        existing_uids.add(central_uid)
        move_central_node_to_proper_group(central_node,
                                          nodes_to_create)

        outgoing_relations = get_outgoing_relations(model)

        for relation in outgoing_relations:
            move_relation_to_proper_group(relation,
                                          relations_to_create)

            if should_create_end_node_if_not_exists(relation):
                end_node_model = produce_model_from_node(
                    get_end_node(relation))
                process_record_model(end_node_model,
                                     existing_uids,
                                     nodes_to_create,
                                     relations_to_create)


def save_nodes_to_csv(file_name, nodes, labels, properties):
    with open(file_name, 'w') as csv_file:
        csv_writer = csv.writer(csv_file, delimiter=',')
        properties_header = ['uid'] + properties
        csv_writer.writerow(properties_header)

        for node in nodes:
            node_properties = get_node_properties(node)
            node_data = [get_node_uid(node)] + map(
                lambda p: node_properties.get(p), properties)

            try:
                csv_writer.writerow(node_data)
            except UnicodeEncodeError:
                """ This is a workaround for titles
                containing non-ASCII characters.
                """
                encoded_data = map(lambda x: x.encode('utf-8')
                                   if isinstance(x, unicode)
                                   else x, node_data)
                csv_writer.writerow(encoded_data)


def produce_csvs_and_commands_for_nodes(nodes_to_create, directory):
    commands = []
    for labels_set, nodes_subset in nodes_to_create.items():
        for properties_set, nodes in nodes_subset.items():

            node_properties = list(properties_set)
            csv_file = os.path.join(directory, generate_file_name())

            save_nodes_to_csv(csv_file, nodes, labels_set, node_properties)
            commands.append(
                produce_command.create_node_from_csv(csv_file, labels_set,
                                                     node_properties,
                                                     add_uid=True)
            )

    return commands


def traverse_relations_tree(relations_to_create):
    for r_type, rs_of_rel_type in relations_to_create.items():
        for start_n_type, rs_with_start_n_type in rs_of_rel_type.items():
            for end_n_type, rs_with_end_n_type in rs_with_start_n_type.items():
                for prop_set, rs_with_p_set in rs_with_end_n_type.items():
                    yield (start_n_type, r_type, end_n_type,
                           prop_set, rs_with_p_set)


def save_relations_to_csv(file_name, relations, relation_type,
                     start_node_labels, end_node_labels,
                     properties_set):
    with open(file_name, 'w') as csv_file:
        csv_writer = csv.writer(csv_file, delimiter=',')
        csv_writer.writerow(
            ['start_node_uid', 'end_node_uid'] + properties_set
        )

        for relation in relations:
            start_uid = get_node_uid(get_start_node(relation))
            end_uid = get_node_uid(get_end_node(relation))
            relation_properties = get_relation_properties(relation)

            data = [start_uid, end_uid] + map(
                lambda p: relation_properties.get(p), properties_set)

            csv_writer.writerow(data)


def start_and_end_node_exist(relation, existing_uids):
    start_node_uid = get_node_uid(get_start_node(relation))
    end_node_uid = get_node_uid(get_end_node(relation))

    return start_node_uid in existing_uids and end_node_uid in existing_uids


def produce_csvs_and_commands_for_relations(relations_to_create, directory):
    #                                        existing_uids):
    # checking if both ends exists has to be disabled
    # because we do migration in chunks
    #
    # both_edge_nodes_exist = partial(start_and_end_node_exist,
    #                                 existing_uids=existing_uids)

    commands = []
    for (start_node_type, relation_type,
         end_node_type, properties_set,
         relations) in traverse_relations_tree(relations_to_create):
             relation_properties = list(properties_set)
             csv_file = os.path.join(directory, generate_file_name())
             save_relations_to_csv(csv_file,
                                   #filter(both_edge_nodes_exist, relations),
                                   relations,
                                   relation_type, start_node_type,
                                   end_node_type, relation_properties)

             commands.append(
                 produce_command.create_relations_from_csv(
                     csv_file, relation_type, start_node_type.default_labels,
                     end_node_type.default_labels, relation_properties)
                 )

    return commands


def generate_init_commands(indices_to_create):
    init_commands = [produce_command.delete_all()]
    for index in indices_to_create:
        init_commands.append(
            produce_command.create_index(index['label'], index['property'])
            )
    return init_commands


def get_commands_from_the_script(script_file):
    commands = []
    with open(script_file, 'r') as script:
        commands = map(lambda command: command.replace('\n', ' ').strip() + ';',
                      ''.join([line for line in script]).split(';'))
    return commands[:-1]


def run_cypher_commands(commands):
    click.echo("Running {} CYPHER commands".format(len(commands)))
    with click.progressbar(commands) as cmds:
        for command in cmds:
            # TODO: Remove printing commands.
            click.echo(command)
            response = current_db_session.run(command)
            for info in response:
                click.echo(info)


def run_loading_script(csv_directory):
    loader = os.path.join(csv_directory, 'loader.cypher')
    if os.path.isfile(loader):
        commands = get_commands_from_the_script(loader)
        run_cypher_commands(commands)
    else:
        click.echo('The CYPHER script {} does not exist. ' + \
                   'Please generate it.'.format(loader))


def generate_csvs_and_commands(records, records_count, csv_storage):
    """
    Generate graph model of records in CSV format,
    return commands to load the files.
    """
    existing_uids = set()
    nodes_directory = os.path.join(csv_storage, NODES_SUBDIRECTORY)
    relations_directory = os.path.join(csv_storage, RELATIONS_SUBDIRECTORY)

    prepare_directories(csv_storage, nodes_directory, relations_directory)

    init_commands = generate_init_commands(INDICES_TO_CREATE)
    nodes_commands = []
    relations_commands = []

    number_of_parts = (records_count / CHUNK_SIZE) + 1
    chunk_number = 1

    for records_chunk in lazy_chunker(records, size=CHUNK_SIZE):
        click.echo(
            'Processing part {chunk_no}/{number_of_parts} of records.'.format(
                chunk_no=chunk_number, number_of_parts=number_of_parts)
            )

        (uids_of_the_chunk,
         nodes_to_create,
         relations_to_create) = build_graph_representation(records_chunk,
                                                           CHUNK_SIZE,
                                                           csv_storage,
                                                           existing_uids)

        click.echo("Generating CSV files of the chunk for nodes")
        chunk_nodes_commands = produce_csvs_and_commands_for_nodes(
            nodes_to_create, nodes_directory)

        click.echo("Generating CSV files of the chunk for relations")
        chunk_relations_commands = produce_csvs_and_commands_for_relations(
            relations_to_create, relations_directory)

        nodes_commands += chunk_nodes_commands
        relations_commands += chunk_relations_commands
        existing_uids.update(uids_of_the_chunk)
        chunk_number += 1

    loader_commands = init_commands + nodes_commands + relations_commands
    return loader_commands


def generate_loader(directory, commands):
    with open(os.path.join(directory, 'loader.cypher'), 'w') as loader_file:
        for command in commands:
            loader_file.write(command)


def records_to_models(records):
    """
    Build graph models of records.
    """
    for record_object in records:
        record = record_object.json

        index = InspireRecordIdProvider.schema_to_pid_type(record['$schema'])
        builder = INDEX_TO_BUILDER[index]

        yield builder.build(record)


def build_graph_representation(records, records_count, csv_storage,
                               existing_uids):

    nodes_to_create = {}
    relations_to_create = {}

    click.echo("\nBuilding basic graph elements (countries etc.)")
    for model in pregenerate_graph():
        process_record_model(model, existing_uids, nodes_to_create,
                             relations_to_create)

    click.echo("Building records graph models")
    with click.progressbar(records_to_models(records),
                           length=records_count) as models:
        for model in models:
            process_record_model(model, existing_uids, nodes_to_create,
                                 relations_to_create)

    return existing_uids, nodes_to_create, relations_to_create


def migrate(records, records_count, csv_storage):
    click.echo('\nMigration started.\n')
    loader_commands = generate_csvs_and_commands(records, records_count,
                                                csv_storage)

    click.echo('Generating CYPHER loader.')
    generate_loader(csv_storage, loader_commands)

    run_cypher_commands(loader_commands)
    #run_loading_scripts(csv_storage)
    click.echo('\nMigration completed\n')
