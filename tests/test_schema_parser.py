import os
import json
import logging
from source.queryHandler.Schema import Schema
from nose2.tools.decorators import with_setup


def my_setup():
    global path, schemaStrFile, schemaData, schema, metrics, metrics1
    path = os.getcwd()
    schemaStrFile = os.path.join(path, "tests", "test_data", 'schemaStr.json')
    with open(schemaStrFile) as f:
        schemaData = json.load(f)
    schema = Schema(schemaData, logging.getLogger('test'))
    metrics = ['cpu_user']
    metrics1 = ['gpfs_nsdfs_bytes_read']


# ---------------------------------------------------------------------------
# getSensorLabels
# ---------------------------------------------------------------------------

@with_setup(my_setup)
def test_case01():
    '''getSensorLabels returns correct key order for a single-key sensor'''
    sensorLabels = schema.getSensorLabels('CPU')
    assert sensorLabels == ['node']


@with_setup(my_setup)
def test_case02():
    '''getSensorLabels returns correct key order for a multi-key sensor'''
    sensorLabels = schema.getSensorLabels('GPFSDiskCap')
    assert len(sensorLabels) > 0
    assert 'gpfs_disk_name' in sensorLabels
    assert sensorLabels.index('gpfs_fs_name') < sensorLabels.index('gpfs_disk_name')


# ---------------------------------------------------------------------------
# getSensorMetricTypes
# ---------------------------------------------------------------------------

@with_setup(my_setup)
def test_case03():
    '''getSensorMetricTypes for GPFSDiskCap contains only quantity metrics'''
    typesDict = schema.getSensorMetricTypes('GPFSDiskCap')
    assert len(typesDict) > 0
    assert 'counter' not in typesDict.values()
    assert 'gpfs_disk_disksize' in typesDict
    assert typesDict['gpfs_disk_disksize'] == 'quantity'


@with_setup(my_setup)
def test_case04():
    '''getSensorMetricTypes for GPFSNSDFS contains only counter metrics'''
    typesDict = schema.getSensorMetricTypes('GPFSNSDFS')
    assert len(typesDict) > 0
    assert 'counter' in typesDict.values()
    assert 'quantity' not in typesDict.values()


# ---------------------------------------------------------------------------
# getSensorForMetric
# ---------------------------------------------------------------------------

@with_setup(my_setup)
def test_case05():
    '''getSensorForMetric returns the correct sensor name'''
    assert schema.getSensorForMetric('cpu_user') == 'CPU'
    assert schema.getSensorForMetric('gpfs_disk_disksize') == 'GPFSDiskCap'
    assert schema.getSensorForMetric('gpfs_nsdfs_bytes_read') == 'GPFSNSDFS'


@with_setup(my_setup)
def test_case06():
    '''getSensorForMetric returns None for an unknown metric'''
    assert schema.getSensorForMetric('nonexistent_metric') is None


# ---------------------------------------------------------------------------
# metricsType
# ---------------------------------------------------------------------------

@with_setup(my_setup)
def test_case07():
    '''metricsType property returns a flat metric→semantic dict across all sensors'''
    mt = schema.metricsType
    assert isinstance(mt, dict)
    assert mt.get('cpu_user') == 'quantity'
    assert mt.get('cpu_contexts') == 'counter'
    assert mt.get('gpfs_nsdfs_bytes_read') == 'counter'
    assert mt.get('gpfs_disk_disksize') == 'quantity'


# ---------------------------------------------------------------------------
# getAllEnabledMetricsNames
# ---------------------------------------------------------------------------

@with_setup(my_setup)
def test_case08():
    '''getAllEnabledMetricsNames lists every metric name across all sensors'''
    names = schema.getAllEnabledMetricsNames
    assert 'cpu_user' in names
    assert 'gpfs_disk_disksize' in names
    assert 'gpfs_nsdfs_bytes_read' in names


# ---------------------------------------------------------------------------
# allParents
# ---------------------------------------------------------------------------

@with_setup(my_setup)
def test_case09():
    '''allParents contains the first key-value element of every row'''
    parents = schema.allParents
    assert 'scale-11' in parents
    assert 'scale-12' in parents
    assert 'scale-cluster-1.vmlocal' in parents


# ---------------------------------------------------------------------------
# getAllFilterMapsForSensor / getAllFilterMapsForMetric
# ---------------------------------------------------------------------------

@with_setup(my_setup)
def test_case10():
    '''getAllFilterMapsForSensor returns one dict per key-value row'''
    filterMaps = schema.getAllFilterMapsForSensor('CPU')
    assert len(filterMaps) == 2
    assert {'node': 'scale-11'} in filterMaps
    assert {'node': 'scale-12'} in filterMaps


@with_setup(my_setup)
def test_case11():
    '''getAllFilterMapsForMetric resolves via getSensorForMetric'''
    filterMaps = schema.getAllFilterMapsForMetric('gpfs_nsdfs_bytes_read')
    assert len(filterMaps) > 0
    assert all('node' in fm and 'gpfs_fs_name' in fm for fm in filterMaps)


# ---------------------------------------------------------------------------
# getAllValuesForTagName / getAllKeysForTagValue
# ---------------------------------------------------------------------------

@with_setup(my_setup)
def test_case12():
    '''getAllValuesForTagName returns all observed values for a tag'''
    values = schema.getAllValuesForTagName('node')
    assert 'scale-11' in values
    assert 'scale-12' in values
    assert 'scale-cluster-1.vmlocal' in values


@with_setup(my_setup)
def test_case13():
    '''getAllKeysForTagValue returns the tag name that owns a given value'''
    keys = schema.getAllKeysForTagValue('cesSharedRoot')
    assert 'gpfs_fs_name' in keys


# ---------------------------------------------------------------------------
# getKeyGranularitylistForMetric
# ---------------------------------------------------------------------------

@with_setup(my_setup)
def test_case14():
    '''getKeyGranularitylistForMetric returns level→key dict for a known metric'''
    granularity = schema.getKeyGranularitylistForMetric('gpfs_disk_disksize')
    assert granularity is not None
    assert 1 in granularity
    assert granularity[1] == 'node'
    assert 'gpfs_disk_name' in granularity.values()


@with_setup(my_setup)
def test_case15():
    '''getKeyGranularitylistForMetric returns None for an unknown metric'''
    assert schema.getKeyGranularitylistForMetric('unknown_metric') is None
