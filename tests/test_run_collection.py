'''
##############################################################################
# Copyright 2023 IBM Corp.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
##############################################################################

Tests for the unified, thread-safe SensorCollector.run_collection entry
point. All data is built locally from the tests/test_data topology file and
in-memory query results, no real pmcollector cluster is required.
'''

import json
import os
import threading
from contextlib import contextmanager
from unittest import mock

from source.bridgeLogger import configureLogging
from source.collector import (CollectionResult, CollectionStatus,
                              QueryPolicy, SensorCollector)
from source.messages import MSG
from source.queryHandler.QueryHandler import ColumnInfo, Key, Row
from source.queryHandler.Topo import Topo

SENSOR = 'GPFSFilesystem'
PERIOD = 300
VALID_FILTERS = {'node': 'scale-16', 'gpfs_fs_name': 'afmCacheFS'}

# populated once by setUpModule, shared read-only by the tests
path = None
topo = None
logger = None


def setUpModule():
    global path, topo, logger
    path = os.getcwd()
    topoStrFile = os.path.join(path, "tests", "test_data", 'topoStr.json')
    with open(topoStrFile) as f:
        topoStr = json.load(f)
    topo = Topo(topoStr)
    logger = configureLogging(path, None)


class FakeQueryResult(object):
    """Minimal stand-in for queryHandler.QueryHandler.QueryResult."""

    def __init__(self, column_infos, rows):
        self.columnInfos = column_infos
        self.rows = rows

    def remove_rows_with_no_data(self):
        self.rows = [row for row in self.rows if not row.is_empty()]


def make_column_info(metric, node, fs_name,
                     cluster='scale-cluster-1.vmlocal'):
    key_str = '|'.join((node, SENSOR, cluster, fs_name, metric))
    key = Key._from_string(key_str, '')
    return ColumnInfo(name=metric, semType=2, keys=(key,), column=0)


def make_query_result(metric='gpfs_fs_bytes_read', node='scale-16',
                      fs_name='afmCacheFS', values=None):
    values = [1.0, 2.0] if values is None else values
    column_info = make_column_info(metric, node, fs_name)
    rows = [Row(tstamp=1700000000 + index * PERIOD,
                values=[value], nsamples=[1])
            for index, value in enumerate(values)]
    return FakeQueryResult([column_info], rows)


def make_empty_query_result(metric='gpfs_fs_bytes_read'):
    column_info = make_column_info(metric, 'scale-16', 'afmCacheFS')
    return FakeQueryResult([column_info], [])


_UNSET = object()


@contextmanager
def collector_context(filters=None, grouptags=None, query_side_effect=None,
                      query_result=_UNSET):
    """Yield a SensorCollector wired to local topology and a fake qh.

    The ``md`` class properties are only shadowed while the generated
    patches are active, so the context must stay open while
    ``run_collection`` reads ``collector.md``.
    """

    attrs = {'sensor': SENSOR, 'period': PERIOD, 'nsamples': 1,
             'rawData': False}
    if filters:
        attrs['filters'] = filters
    if grouptags:
        attrs['grouptags'] = grouptags

    with mock.patch('source.collector.QueryPolicy.md'), \
            mock.patch('source.collector.SensorTimeSeries.md'), \
            mock.patch('source.collector.SensorCollector.md') as md:
        md_instance = md.return_value
        md_instance.includeDiskData = False
        md_instance.metaData = topo
        md_instance.metricsDesc = {}

        request = QueryPolicy(**attrs)
        collector = SensorCollector(SENSOR, PERIOD, logger, request)
        collector.md = md_instance
        collector.labels = collector._get_sensor_labels()
        collector.filtersMap = collector._get_all_filters()

        qh = mock.Mock()
        if query_side_effect is not None:
            qh.runQuery.side_effect = query_side_effect
        elif query_result is not _UNSET:
            qh.runQuery.return_value = query_result
        else:
            qh.runQuery.return_value = make_query_result()
        md_instance.qh = qh

        yield collector, qh


def test_run_collection_success_returns_metrics():
    with collector_context(filters=VALID_FILTERS) as (collector, qh):
        original_metrics = collector.metrics

        result = collector.run_collection()

        assert isinstance(result, CollectionResult)
        assert result.status == CollectionStatus.SUCCESS
        assert result.ok is True
        assert result.error is None
        assert result.exception is None
        assert 'gpfs_fs_bytes_read' in result.metrics
        metric_ts = result.metrics['gpfs_fs_bytes_read']
        assert len(metric_ts.timeseries) == 1
        assert metric_ts.timeseries[0].dps == {1700000000: 1.0,
                                               1700000300: 2.0}
        assert metric_ts.timeseries[0].tags['node'] == 'scale-16'
        assert metric_ts.timeseries[0].tags['gpfs_fs_name'] == 'afmCacheFS'
        # the query really went through the query handler
        assert qh.runQuery.call_count == 1
        # the shared collector state must not be mutated by run_collection
        assert collector.metrics is original_metrics
        assert all(mts.timeseries == []
                   for mts in collector.metrics.values())


def test_run_collection_success_without_filters():
    with collector_context() as (collector, _):
        result = collector.run_collection()

        assert result.status == CollectionStatus.SUCCESS
        assert result.ok is True
        assert 'gpfs_fs_bytes_read' in result.metrics


def test_run_collection_invalid_filter_tag_name():
    bad_filters = {'node': 'scale-16',
                   'gpfs_filesystem_name': 'afmCacheFS'}
    with collector_context(filters=bad_filters) as (collector, qh):
        result = collector.run_collection()

        assert result.status == CollectionStatus.INVALID_FILTER
        assert result.ok is False
        assert result.metrics == {}
        # the explanation names the offending tag name, not just a generic 400
        assert 'gpfs_filesystem_name' in result.error
        assert 'tag name' in result.error
        assert SENSOR in result.error
        # validation happens before any query is executed
        assert qh.runQuery.called is False


def test_run_collection_invalid_filter_value():
    bad_filters = {'node': 'not-there-node'}
    with collector_context(filters=bad_filters) as (collector, qh):
        result = collector.run_collection()

        assert result.status == CollectionStatus.INVALID_FILTER
        assert 'not-there-node' in result.error
        assert 'node' in result.error
        assert 'value' in result.error
        assert qh.runQuery.called is False


def test_run_collection_pipe_separated_values_accepted_and_rejected():
    # the | conditional syntax must keep working for valid values
    with collector_context(filters={'node': 'scale-11|scale-12'}) \
            as (good_collector, _):
        good_result = good_collector.run_collection()
        assert good_result.status == CollectionStatus.SUCCESS

    # a pipe list that still contains a known value stays valid because the
    # remaining maps simply get filtered down (legacy validator behaviour)
    with collector_context(filters={'node': 'scale-11|bogus-node'}) \
            as (mixed_collector, _):
        mixed_result = mixed_collector.run_collection()
        assert mixed_result.status == CollectionStatus.SUCCESS

    # a pipe list of only unknown values has to be reported specifically
    with collector_context(
            filters={'node': 'bogus-node|another-bogus-node'}) \
            as (bad_collector, qh):
        bad_result = bad_collector.run_collection()

        assert bad_result.status == CollectionStatus.INVALID_FILTER
        assert 'bogus-node' in bad_result.error
        assert 'another-bogus-node' in bad_result.error
        assert 'node' in bad_result.error
        assert qh.runQuery.called is False


def test_run_collection_wildcard_value_accepted_and_rejected():
    # wildcard '*' values stay valid for a known tag
    with collector_context(filters={'gpfs_fs_name': '*'}) \
            as (good_collector, _):
        good_result = good_collector.run_collection()
        assert good_result.status == CollectionStatus.SUCCESS

    # wildcard on a tag with no known component values is invalid
    with collector_context(filters={'gpfs_filesystem_name': '*'}) \
            as (bad_collector, qh):
        bad_result = bad_collector.run_collection()

        assert bad_result.status == CollectionStatus.INVALID_FILTER
        assert 'gpfs_filesystem_name' in bad_result.error
        assert qh.runQuery.called is False


def test_run_collection_wildcard_tag_name_is_supported():
    # a '*' tag name is resolved from the value via the metadata, exactly
    # as validate_query_filters does; a known value must collect fine
    with collector_context(filters={'*': 'scale-16'}) \
            as (collector, qh):
        result = collector.run_collection()

        assert result.status == CollectionStatus.SUCCESS
        assert qh.runQuery.call_count == 1


def test_run_collection_invalid_group_tag():
    with collector_context(filters=VALID_FILTERS,
                           grouptags=['not_a_group_tag']) \
            as (collector, qh):
        result = collector.run_collection()

        assert result.status == CollectionStatus.INVALID_FILTER
        assert 'not_a_group_tag' in result.error
        assert 'groupBy' in result.error
        # supported tags are offered as part of the explanation
        assert 'node' in result.error
        assert 'gpfs_fs_name' in result.error
        assert qh.runQuery.called is False


def test_run_collection_query_exception_is_retained():
    boom = RuntimeError('pmcollector connection reset')
    with collector_context(filters=VALID_FILTERS,
                           query_side_effect=boom) as (collector, _):
        result = collector.run_collection()

        assert result.status == CollectionStatus.QUERY_FAILED
        assert result.ok is False
        assert result.metrics == {}
        # the displayable explanation and the original exception are retained
        assert 'pmcollector connection reset' in result.error
        assert result.exception is boom
        assert isinstance(result.exception, RuntimeError)


def test_run_collection_none_response_is_no_data():
    with collector_context(filters=VALID_FILTERS, query_result=None) \
            as (collector, _):
        result = collector.run_collection()

        assert result.status == CollectionStatus.NO_DATA
        assert result.ok is False
        assert result.metrics == {}
        assert result.error == MSG['NoData']
        assert result.exception is None


def test_run_collection_empty_rows_is_no_data():
    with collector_context(filters=VALID_FILTERS,
                           query_result=make_empty_query_result()) \
            as (collector, _):
        result = collector.run_collection()

        assert result.status == CollectionStatus.NO_DATA
        assert result.error == MSG['NoData']
        assert result.metrics == {}


def test_legacy_validate_methods_still_raise_http_error():
    import cherrypy

    with collector_context(filters={'gpfs_filesystem_name': 'afmCacheFS'}) \
            as (bad_name_collector, _):
        try:
            bad_name_collector.validate_query_filters()
            raised = None
        except cherrypy.HTTPError as exc:
            raised = exc
        assert raised is not None
        assert raised.status == 400

    with collector_context(filters=VALID_FILTERS,
                           grouptags=['not_a_group_tag']) \
            as (bad_group_collector, _):
        try:
            bad_group_collector.validate_group_tags()
            raised = None
        except cherrypy.HTTPError as exc:
            raised = exc
        assert raised is not None
        assert raised.status == 400


def test_run_collection_concurrent_on_shared_collector():
    # One collector instance is shared by many threads calling the unified
    # entry point concurrently; every thread must get its own isolated,
    # successful result.
    with collector_context(filters=VALID_FILTERS) as (collector, qh):
        thread_count = 12
        barrier = threading.Barrier(thread_count)
        results = [None] * thread_count
        errors = []

        def worker(index):
            try:
                barrier.wait()
                results[index] = collector.run_collection()
            except Exception as exc:  # pragma: no cover - failure path
                errors.append(exc)

        threads = [threading.Thread(target=worker, args=(i,))
                   for i in range(thread_count)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        assert errors == []
        assert qh.runQuery.call_count == thread_count
        for result in results:
            assert result is not None
            assert result.status == CollectionStatus.SUCCESS
            assert result.ok is True
            assert 'gpfs_fs_bytes_read' in result.metrics
            assert result.error is None
        # result objects are independent per call
        assert len({id(result) for result in results}) == thread_count
        # shared collector state stays untouched
        assert all(mts.timeseries == []
                   for mts in collector.metrics.values())


def test_run_collection_concurrent_mixed_outcomes():
    # A failing filter in one collector thread must not poison the
    # successful collections running at the same time.
    with collector_context(filters=VALID_FILTERS) as (success_collector,
                                                      success_qh), \
            collector_context(filters={'node': 'bogus-node'}) \
            as (invalid_collector, invalid_qh), \
            collector_context(filters=VALID_FILTERS,
                              query_side_effect=RuntimeError('boom')) \
            as (failing_collector, _), \
            collector_context(filters=VALID_FILTERS, query_result=None) \
            as (empty_collector, _):

        participants = 4
        barrier = threading.Barrier(participants)
        outcome = {}

        def run(name, col):
            barrier.wait()
            outcome[name] = col.run_collection()

        threads = [
            threading.Thread(target=run,
                             args=('success', success_collector)),
            threading.Thread(target=run,
                             args=('invalid', invalid_collector)),
            threading.Thread(target=run,
                             args=('failed', failing_collector)),
            threading.Thread(target=run,
                             args=('empty', empty_collector)),
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        assert outcome['success'].status == CollectionStatus.SUCCESS
        assert 'gpfs_fs_bytes_read' in outcome['success'].metrics

        assert outcome['invalid'].status == CollectionStatus.INVALID_FILTER
        assert 'bogus-node' in outcome['invalid'].error
        assert invalid_qh.runQuery.called is False

        assert outcome['failed'].status == CollectionStatus.QUERY_FAILED
        assert isinstance(outcome['failed'].exception, RuntimeError)

        assert outcome['empty'].status == CollectionStatus.NO_DATA

        # the invalid collector never reached the query layer and the healthy
        # collector's query was still executed exactly once
        assert success_qh.runQuery.call_count == 1
