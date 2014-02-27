#!/usr/bin/env python
from __future__ import print_function
import re
import os
import sys
import csv
import codecs
import urllib.request
import zipfile
import argparse
import collections

import us

class TabDelimited(csv.Dialect):
    delimiter = '\t'
    quoting = csv.QUOTE_NONE
    lineterminator = '\n\r'
    skipinitialspace = True


def get_exception_set():
    csvfile = csv.reader(open('identifiers/country-us/exceptions.csv'))
    return set(x[0] for x in csvfile)

BASE_URL = 'http://www2.census.gov/geo/gazetteer/2013_Gazetteer/'

TYPES = {
    'county': {
        'zip': '2013_Gaz_counties_national.zip',
        'funcstat': lambda row: 'F' if row['USPS'] == 'DC' else 'A',
        'type_mapping': {
            ' County': 'county',
            ' Parish': 'parish',
            ' Borough': 'borough',
            ' Municipality': 'borough',
            ' Census Area': 'census_area',
        },
        'overrides': {
            'Wrangell City and Borough': ('Wrangell', 'borough'),
            'Sitka City and Borough': ('Sitka', 'borough'),
            'Juneau City and Borough': ('Juneau', 'borough'),
            'Yakutat City and Borough': ('Yakutat', 'borough'),
        },
        'id_overrides': { }
    },
    #'county': {
    #    'zip': '2013_Gaz_counties_national.zip',
    #    'funcstat': lambda row: 'F' if row['USPS'] == 'DC' else 'A',
    #    'type_mapping': {
    #        ' County': 'county',
    #        ' Parish': 'parish',
    #        ' Borough': 'borough',
    #        ' Municipality': 'borough',
    #        ' Census Area': 'census_area',
    #    },
    #    'overrides': {
    #        'Wrangell City and Borough': ('Wrangell', 'borough'),
    #        'Sitka City and Borough': ('Sitka', 'borough'),
    #        'Juneau City and Borough': ('Juneau', 'borough'),
    #        'Yakutat City and Borough': ('Yakutat', 'borough'),
    #    },
    #    'id_overrides': { }
    #},
    'place': {
        'zip': '2013_Gaz_place_national.zip',
        'funcstat': lambda row: row['FUNCSTAT'],
        'type_mapping': {
            ' municipality': 'place',
            ' borough': 'place',
            ' city': 'place',
            ' town': 'place',
            ' village': 'place',
        },
        'overrides': {
            'Wrangell city and borough': ('Wrangell', 'place'),
            'Sitka city and borough': ('Sitka', 'place'),
            'Juneau city and borough': ('Juneau', 'place'),
            'Lexington-Fayette urban county': ('Lexington', 'place'),
            'Lynchburg, Moore County metropolitan government': ('Lynchburg', 'place'),
            'Cusseta-Chattahoochee County unified government': ('Cusseta', 'place'),
            'Georgetown-Quitman County unified government': ('Georgetown', 'place'),
            'Anaconda-Deer Lodge County': ('Anaconda', 'place'),
            'Hartsville/Trousdale County': ('Hartsville', 'place'),
            'Webster County unified government': ('Webster County ', 'place'),
            'Ranson corporation': ('Ranson', 'place'),
            'Carson City': ('Carson City', 'place'),
            'Princeton': ('Princeton', 'place'),
        },
        'id_overrides': {
            '2756680': ('St. Anthony (Hennepin/Ramsey Counties)', 'place'),
            '2756698': ('St. Anthony (Stearns County)', 'place'),
            '4861592': ('Reno (Lamar County)', 'place'),
            '4861604': ('Reno (Parker County)', 'place'),
            '4840738': ('Lakeside (San Patricio County)', 'place'),
            '4840744': ('Lakeside (Tarrant County)', 'place'),
            '4853154': ('Oak Ridge (Cooke County)', 'place'),
            '4853160': ('Oak Ridge (Kaufman County)', 'place'),
            '4253336': ('Newburg borough (Clearfield County)', 'place'),
            '4253344': ('Newburg borough (Cumberland County)', 'place'),
            '4214584': ('Coaldale borough (Bedford County)', 'place'),
            '4214600': ('Coaldale borough (Schuylkill County)', 'place'),
            '4243064': ('Liberty borough (Allegheny County)', 'place'),
            '4243128': ('Liberty borough (Tioga County)', 'place'),
            '4261496': ('Pleasantville borough (Bedford County)', 'place'),
            '4261512': ('Pleasantville borough (Venango County)', 'place'),
            '4237880': ('Jefferson borough (Greene County)', 'place'),
            '4237944': ('Jefferson borough (York County)', 'place'),
            '4212184': ('Centerville borough (Crawford County)', 'place'),
            '4212224': ('Centerville borough (Washington County)', 'place'),
        }
    },
    'subdiv': {
        'zip': '2013_Gaz_cousubs_national.zip',
        'funcstat': lambda row: row['FUNCSTAT'],
        'type_mapping': {
            ' town': 'place',
            ' village': 'place',
            ' township': 'place',
            ' plantation': 'place',
        },
        'overrides': {
            'Township 1': ('Township 1', 'place'),
            'Township 2': ('Township 2', 'place'),
            'Township 3': ('Township 3', 'place'),
            'Township 4': ('Township 4', 'place'),
            'Township 5': ('Township 5', 'place'),
            'Township 6': ('Township 6', 'place'),
            'Township 7': ('Township 7', 'place'),
            'Township 8': ('Township 8', 'place'),
            'Township 9': ('Township 9', 'place'),
            'Township 10': ('Township 10', 'place'),
            'Township 11': ('Township 11', 'place'),
            'Township 12': ('Township 12', 'place'),
        },
        'id_overrides': { }
    }
}

# list of rules for how to handle subdivs
#   prefix - these are strictly within counties and need to be id'd as such
#   town - these are the equivalent of places
SUBDIV_RULES = {
    'ct': 'town',
    'il': 'prefix',
    'in': 'prefix',
    'ks': 'prefix',
    'ma': 'town',
    'me': 'town',
    'mi': 'prefix',
    'mn': 'prefix',
    'mo': 'prefix',
    'nd': 'prefix',
    'ne': 'prefix',
    'nh': 'town',
    'nj': 'prefix',
    'ny': 'prefix',
    'oh': 'prefix',
    'pa': 'prefix',
    'ri': 'town',
    'sd': 'prefix',
    'vt': 'town',
    'wi': 'prefix',
}



def make_id(parent=None, **kwargs):
    if len(kwargs) > 1:
        raise ValueError('only one kwarg is allowed for make_id')
    type, type_id = list(kwargs.items())[0]
    if not re.match('^[a-z_]+$', type):
        raise ValueError('type must match [a-z]+ [%s]' % type)
    type_id = type_id.lower()
    type_id = re.sub('\.? ', '_', type_id)
    type_id = re.sub('[^\w0-9~_.-]', '~', type_id, re.UNICODE)
    if parent:
        return '{parent}/{type}:{type_id}'.format(parent=parent, type=type, type_id=type_id)
    else:
        return 'ocd-division/country:us/{type}:{type_id}'.format(type=type, type_id=type_id)


# http://www.census.gov/geo/reference/gtc/gtc_area_attr.html#status


def process_types(types):
    funcstat_count = collections.Counter()
    type_count = collections.Counter()
    # map geoid to id
    counties = {}
    # list of rows that produced an id
    duplicates = collections.defaultdict(list)
    # load exceptions from file
    exceptions = get_exception_set()

    for entity_type in types:
        ids = {}
        csvfile = csv.writer(open('identifiers/country-us/us_census_{}.csv'.format(entity_type),
                                  'w'))
        geocsv = csv.writer(open('mappings/us-census-{}-geoids.csv'.format(entity_type), 'w'))

        url = BASE_URL + TYPES[entity_type]['zip']
        print('fetching zipfile', url)
        zf, _ = urllib.request.urlretrieve(url)
        zf = zipfile.ZipFile(zf)
        localfile = zf.extract(zf.filelist[0], '/tmp/')
        data = codecs.open(localfile, encoding='latin1')
        rows = csv.DictReader(data, dialect=TabDelimited)
        # function to extract funcstat value
        funcstat_func = TYPES[entity_type]['funcstat']
        overrides = TYPES[entity_type]['overrides']
        id_overrides = TYPES[entity_type]['id_overrides']

        for row in rows:
            state = row['USPS'].lower()

            # FIXME: just need classifiers for PR
            if state == 'pr':
                continue

            subdiv_rule = SUBDIV_RULES.get(state)
            parent_id = make_id(state=state)

            row['_FUNCSTAT'] = funcstat = funcstat_func(row)
            funcstat_count[funcstat] += 1

            # active government
            if funcstat in ('A', 'B', 'I'):
                if entity_type == 'subdiv' and not subdiv_rule:
                    raise Exception('unexpected subdiv in {0}: {1}'.format(state, row))

                name = row['NAME']

                if name in overrides:
                    name, subtype = overrides[name]
                elif row['GEOID'] in id_overrides:
                    name, subtype = id_overrides[row['GEOID']]
                else:
                    for ending, subtype in TYPES[entity_type]['type_mapping'].items():
                        if name.endswith(ending):
                            name = name.replace(ending, '')
                            break
                    else:
                        # skip independent cities indicated at county level
                        if (entity_type == 'county' and (name.endswith(' city') or
                                                         name == 'Carson City')):
                            continue
                        else:
                            raise ValueError('unknown ending: {} for {}'.format(name, row))

                type_count[subtype] += 1

                if entity_type == 'subdiv' and subdiv_rule == 'prefix':
                    # find county id
                    for geoid, countyid in counties.items():
                        if row['GEOID'].startswith(geoid):
                            id = make_id(parent=countyid, **{subtype: name})
                            break
                    else:
                        raise Exception('{0} had no parent county'.format(row))
                elif entity_type != 'subdiv' or subdiv_rule == 'town':
                    id = make_id(parent=parent_id, **{subtype: name})

                # check for duplicates
                if id in ids:
                    id1 = make_id(parent=parent_id, **{subtype: row['NAME']})
                    row2 = ids.pop(id)
                    id2 = make_id(parent=parent_id, **{subtype: row2['NAME']})
                    if id1 != id2:
                        ids[id1] = row
                        ids[id2] = row2
                    else:
                        duplicates[id].append(row)
                        duplicates[id].append(row2)
                elif id in duplicates:
                    duplicates[id].append(row)
                else:
                    ids[id] = row
                    if entity_type == 'county':
                        counties[row['GEOID']] = id

            elif funcstat not in ('F', 'N', 'S', 'C', 'G'):
                # inactive/fictitious/nonfunctioning/statistical/consolidated
                # unhandled FUNCSTAT type
                raise Exception(row)


        # write ids out
        for id, row in sorted(ids.items()):
            if id not in exceptions:
                csvfile.writerow((id, row['NAME']))
                if geocsv:
                    geocsv.writerow((id, row['GEOID']))

    print(' | '.join('{0}: {1}'.format(k,v) for k,v in funcstat_count.most_common()))
    print(' | '.join('{0}: {1}'.format(k,v) for k,v in type_count.most_common()))

    for id, sources in duplicates.items():
        error = '{0} duplicate {1}\n'.format(state, id)
        for source in sources:
            error += '    {NAME} {_FUNCSTAT} {GEOID}'.format(**source)
        raise Exception(error)


def _ordinal(value):
    if value == 0:
        return 'At-Large'

    if (value % 100) // 10 != 1:
        if value % 10 == 1:
            ordval = 'st'
        elif value % 10 == 2:
            ordval = 'nd'
        elif value % 10 == 3:
            ordval = 'rd'
        else:
            ordval = 'th'
    else:
        ordval = 'th'

    return '{0}{1}'.format(value, ordval)


if __name__ == '__main__':
    process_types(('county', 'place', 'subdiv'))
