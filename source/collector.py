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

Created on Okt 27, 2023

@author: HWASSMAN
'''

import cherrypy
import copy
import analytics
from queryHandler.Query import Query
from messages import MSG
from collections import defaultdict
from typing import Optional, Any, List, Union
from threading import Thread, Lock
from metadata import MetadataHandler
from bridgeLogger import getBridgeLogger
from refresher import TopoRefreshManager
from utils import classattributes, cond_execution_time, get_runtime_statistics


local_cache = set()


class CollectionStatus(object):
    """Terminal states of a single collection run.

    The members are plain strings so that a ``CollectionResult`` can be
    inspected without importing any additional type and serializes cleanly
    when it is surfaced to an API response.
    """

    SUCCESS = 'success'
    NO_DATA = 'no_data'
    INVALID_FILTER = 'invalid_filter'
    QUERY_FAILED = 'query_failed'


class CollectionResult(object):
    """Structured outcome of one :meth:`SensorCollector.run_collection` call.

    Each call owns its own result instance, so collector threads running
    concurrently can never share or overwrite each others status or error
    description.

    Attributes:
        status: one of the constants defined in :class:`CollectionStatus`
        error: human readable, directly presentable explanation of what went
            wrong; ``None`` for successful collections
        metrics: mapping ``metric name -> MetricTimeSeries`` with the
            collected data on success, otherwise an empty dict
        exception: the original exception retained when the underlying query
            raised, otherwise ``None``
    """

    def __init__(self, status: str, error: Optional[str] = None,
                 metrics: Optional[dict] = None,
                 exception: Optional[BaseException] = None) -> None:
        self.status = status
        self.error = error
        self.metrics = metrics if metrics is not None else {}
        self.exception = exception

    @property
    def ok(self) -> bool:
        """True when the collection finished with data."""
        return self.status == CollectionStatus.SUCCESS

    def __repr__(self) -> str:
        return (f'CollectionResult(status={self.status!r}, error={self.error!r}, '
                f'metrics={list(self.metrics.keys())!r})')


class TimeSeries(object):

    def __init__(self, columnInfo, dps, filtersMap, defaultLabels):
        self.metricname = columnInfo.keys[0].metric
        self.columnInfo = columnInfo
        self.dps = dps
        self.tags = defaultdict(list)
        self.aggregatedTags = []

        self.parse_tags(filtersMap, defaultLabels)

    @cond_execution_time(detail_level=2)
    def parse_tags(self, filtersMap, defaultLabels):
        logger = getBridgeLogger()
        if not (filtersMap and defaultLabels):
            logger.trace(f'No labels, no filters in local cache for {self.columnInfo.keys[0].__str__()}')
            return
        tagsDict = defaultdict(set)
        for key in self.columnInfo.keys:
            ident = [key.parent]
            ident.extend(key.identifier)
            logger.trace(MSG['ReceivAttrValues'].format(
                'Single ts identifiers', '|'.join(ident)))
            found = False
            for filtersDict in filtersMap:
                if set(filtersDict.values()) == set(ident):
                    # logger.trace(MSG['ReceivAttrValues'].format(
                    #    'filtersKeys', ', '.join(filtersDict.keys())))
                    if len(self.columnInfo.keys) == 1:
                        self.tags = filtersDict
                    else:
                        for _key, _value in filtersDict.items():
                            tagsDict[_key].add(_value)
                    found = True
                    break
            # detected zimon key, do we need refresh local TOPO?
            if not found:
                topoRefresher = TopoRefreshManager()
                topoRefresher.update_local_cache(ident)

                constructedTags = dict(zip(defaultLabels, ident))
                if len(self.columnInfo.keys) == 1:
                    self.tags = constructedTags
                else:
                    for _key, _value in constructedTags.items():
                        tagsDict[_key].add(_value)

        for _key, _values in tagsDict.items():
            if len(_values) > 1:
                self.aggregatedTags.append(_key)
            else:
                self.tags[_key] = _values.pop()

    @get_runtime_statistics(enabled=analytics.runtime_profiling)
    def reduce_dps_to_first_not_none(self, reverse_order=False):
        """Reduce multiple data points(dps) of a single
           TimeSeries to the first non null value in a sorted order.
           Optionally the order of timestamps can be reversed.
        """
        if len(self.dps) > 1:
            logger = getBridgeLogger()
            timestamps = sorted(self.dps.keys(), reverse=reverse_order)
            self.dps = next((
                {timestmp: self.dps[timestmp]} for timestmp in timestamps if
                self.dps[timestmp] is not None), {})
            if len(self.dps) == 0:
                logger.debug(MSG['NullValues'].format(self.metricname, '|'.join(self.tags.values())))


class MetricTimeSeries(object):

    def __init__(self, name: str, desc: str, type: Optional[str] = None):
        self.mtype = type or 'gauge'
        self.mname = name
        self.desc = desc
        self.timeseries: list[TimeSeries] = []

    def __format__(self, spec):
        return f'{self.mname}_mTS'

    def str_descfmt(self) -> [str]:
        """Format MetricTimeSeries description rows
            Output format:
                '''# HELP {name} {desc}'''
                '''# TYPE {name} {mtype}'''
        """

        myset = []

        expfmt = '''# HELP {name} {desc}'''.format(
            name=self.mname,
            desc=self.desc,
        )
        myset.append(expfmt)
        expfmt1 = '''# TYPE {name} {mtype}'''.format(
            name=self.mname,
            mtype=self.mtype,
        )
        myset.append(expfmt1)

        return myset


class SensorTimeSeries(object):

    def __init__(self, sensor: str, period: str):
        self.sensor = sensor
        self.period = period
        self.metrics = {}
        self.internal_metrics: defaultdict[int, dict[str, Union[int, float]]] = defaultdict(dict)
        self.filtersMap = self._get_all_filters()
        self.labels = self._get_sensor_labels()

    @property
    def md(self):
        return MetadataHandler()

    def cleanup_metrics_values(self) -> None:
        for name in self.metrics.keys():
            self.metrics[name].timeseries = []

    def setup_static_metrics_data(self, include_metrics: Optional[list] = None,
                                  exclude_metrics: Optional[list] = None):

        include_metrics = include_metrics or []
        exclude_metrics = exclude_metrics or []

        metrics = self.md.metaData.getSensorMetricNames(self.sensor)
        if len(metrics) < 1:
            return                       # this should not happen

        for exclude_metric in exclude_metrics:
            metrics.remove(exclude_metric)

        if len(include_metrics) > 0 and (set(include_metrics).
                                         issubset(set(metrics))):
            self._setup_static_metrics_data(include_metrics)
        else:
            self._setup_static_metrics_data(metrics)

    def _setup_static_metrics_data(self, metric_names: List[str]):
        self.metrics = self._build_static_metrics_dict(metric_names)

    def _build_static_metrics_dict(self, metric_names: List[str]) -> dict:
        """Create a fresh metric name -> MetricTimeSeries mapping.

        Kept separate from :meth:`_setup_static_metrics_data` so the
        thread-safe collection entry point can build its own isolated
        mapping without touching the shared ``self.metrics`` state.
        """
        mDict = {}
        spec = self.md.metricsDesc
        metricsTypes = self.md.metaData.metricsType

        for name in metric_names:
            mtype = 'gauge'
            if self.sensor == 'GPFSWaiters':
                mtype = 'histogram'
            elif metricsTypes.get(name, None) == "counter":
                mtype = 'counter'
            ts = MetricTimeSeries(name,
                                  spec.get(name, "Desc not found"),
                                  mtype)
            mDict[name] = ts
        return mDict

    def _get_all_filters(self):
        return self.md.metaData.getAllFilterMapsForSensor(self.sensor)

    def _get_sensor_labels(self):
        return self.md.metaData.getSensorLabels(self.sensor)


@classattributes(dict(metricsaggr=None, filters=None, grouptags=None,
                      start='', end='', nsamples=0, duration=0,
                      dsBucketSize=0, dsOp='', rawData=False, skipNullValues=False, dpsArrays=False),
                 ['sensor', 'period'])
class QueryPolicy(object):

    def __init__(self, **kwargs):
        pass

    @property
    def md(self):
        return MetadataHandler()

    def get_zimon_query(self):
        '''Returns zimon query string '''
        query = Query(includeDiskData=self.md.includeDiskData)
        query.normalize_rates = False
        query.skipRangeData = True
        query.rawData = self.rawData
        query.skipNullValues = self.skipNullValues

        if not self.metricsaggr and not self.sensor:
            raise ValueError('Missing metric or sensor name')

        if self.metricsaggr:
            for key, value in self.metricsaggr.items():
                query.addMetric(key, value)
        else:
            query.addMetricsGroup(self.sensor)

        query.setTime(tstart=self.start, tend=self.end,
                      num_buckets=self.nsamples, duration=self.duration)

        if self.grouptags:
            for tag in self.grouptags:
                query.addGroupByMetric(tag)

        if self.filters:
            for key, value in self.filters.items():
                query.addFilter(key, value)

        query.setBucketSize(self._calc_zimon_query_bucketsize())

        return query

    def _calc_zimon_query_bucketsize(self):

        logger = getBridgeLogger()

        bucketSize = self.period

        if self.dsBucketSize and self.dsBucketSize > bucketSize:
            if not self.dsOp:
                bucketSize = self.dsBucketSize
                logger.trace(MSG['BucketsizeChange'].format(
                    self.dsBucketSize, bucketSize))
        else:
            logger.details(MSG['BucketsizeToPeriod'].format(bucketSize))

        return bucketSize


class SensorCollector(SensorTimeSeries):
    running = False
    thread = None

    def __init__(self, sensor: str, period: str, logger, request: QueryPolicy,
                 bundle_id: Optional[str] = None,
                 *args: Any, **kwargs: Any) -> None:
        super().__init__(sensor, period)
        self.__query = None
        self.__ds_interval = None
        self.__query_lock = Lock()
        self.__ds_interval_lock = Lock()
        self.request = request
        self.logger = logger
        self.bundle_id = bundle_id  # Store bundle_id as instance property
        self.removeNoData = False
        self.cache = False
        self.cached_metrics = {}

        self.prepare_static_metrics_data()

    def __format__(self, spec):
        return f'{self.sensor}_Collector'

    @property
    def md(self):
        return MetadataHandler()

    @property
    def query(self):
        # Lazily build the zimon query under a lock: several collector
        # threads may share one SensorCollector and must not race on the
        # private query cache.
        with self.__query_lock:
            if not self.__query:
                self.__query = self.request.get_zimon_query()
            return self.__query

    @property
    def dsInterval(self):
        with self.__ds_interval_lock:
            if self.__ds_interval is None:
                self.__ds_interval = self._calc_ds_interval()
            return self.__ds_interval

    def start_collect(self):
        """ Function to start collect in a thread"""
        self.running = True
        if not self.thread:
            thread_name = list(self.request.metricsaggr.keys())[0] if self.request.metricsaggr else self.sensor
            self.thread = Thread(name=thread_name, target=self.collect)
            self.thread.start()
            # self.thread.name += '_' + str(self.thread.ident)
            # self.logger.info(f"Started col thread with ident {self.thread.ident}")
            self.logger.trace(
                MSG['StartCustomThread'].format(self.thread.name))

    def collect(self) -> None:
        self._collect()
        if self.cache:
            self.cached_metrics = copy.deepcopy(self.metrics)
            self.cleanup_metrics_values()

    def stop_collect(self):
        """ Function to break collecting """
        try:
            self.running = False
            if self.thread:
                self.thread.join()
                cherrypy.engine.log(
                    MSG['StopCustomThread'].format(self.thread.name))
                self.logger.trace(
                    MSG['StopCustomThread'].format(self.thread.name))
                self.thread = None
        except KeyboardInterrupt:
            print(f"Received KeyboardInterrupt during \
            stopping the thread {self.thread.name}")

    def _calc_ds_interval(self) -> int:

        dsInterval = 0

        if self.query and self.request:
            if self.request.dsOp and self.request.dsBucketSize > int(
                    self.query.bucket_size):
                dsInterval = int(
                    self.request.dsBucketSize / int(self.query.bucket_size))
        return dsInterval

    def _collect(self):
        '''Executes zimon query and stores results in ``self.metrics``'''

        metrics, error, _ = self._run_query_and_collect()
        if error is None:
            self.metrics = metrics

    def _run_query_and_collect(self):
        '''Executes the zimon query and builds the metrics mapping.

        All state needed to assemble the result is kept in local variables
        so that concurrent invocations (also via :meth:`run_collection`)
        never share intermediate data. The method mirrors the behaviour of
        the legacy :meth:`_collect` flow, including the query failure and
        empty-result handling, but returns its outcome instead of only
        logging it.

        :return: tuple ``(metrics, error, exception)`` where ``metrics`` is
                 a fresh metric name -> MetricTimeSeries dict, ``error`` is
                 ``None`` on success and otherwise one of the
                 :class:`CollectionStatus` failure constants, and
                 ``exception`` retains the original exception when the
                 underlying query raised.
        '''

        try:
            res = self.md.qh.runQuery(self.query)
        except Exception as e:
            self.logger.error(MSG['QueryError'].format(e))
            return {}, CollectionStatus.QUERY_FAILED, e

        if res is None:
            self.logger.error(MSG['NoData'])
            return {}, CollectionStatus.NO_DATA, None
        self.logger.details("res.rows length: {}".format(len(res.rows)))
        if self.removeNoData:
            res.remove_rows_with_no_data()

        if len(res.rows) < 1:
            return {}, CollectionStatus.NO_DATA, None
        rows = res.rows
        if self.request.dsOp and self.dsInterval and len(res.rows) > 1:
            self.logger.trace(MSG['DownsampleAggregation'].format(
                str(self.request.dsOp) + '-' + str(self.dsInterval),
                list(self.request.metricsaggr.keys())[0]))
            rows = res.downsampleResults(self.dsInterval, self.request.dsOp)

        if self.request.dpsArrays:
            columnValues = defaultdict(list)
            for row in rows:
                for value, columnInfo in zip(row.values, res.columnInfos):
                    columnValues[columnInfo].append([row.tstamp, value])
        else:
            columnValues = defaultdict(dict)
            for row in rows:
                for value, columnInfo in zip(row.values, res.columnInfos):
                    columnValues[columnInfo][row.tstamp] = value

        # Fresh, locally owned metric containers: this mapping is never
        # stored on shared instance state, so parallel collection runs can
        # not interleave their TimeSeries objects.
        metrics = self._build_static_metrics_dict(list(self.metrics.keys()))
        for columnInfo, dps in columnValues.items():
            ts = TimeSeries(columnInfo, dps, self.filtersMap, self.labels)
            if metrics.get(columnInfo.keys[0].metric) is not None:
                self.logger.trace(MSG['MetricInResults'].format(
                    columnInfo.keys[0].metric))
                metrics[columnInfo.keys[0].metric].timeseries.append(ts)
            else:
                # metric not in Collector.metrcs
                self.logger.warning(MSG['MetricNotInResults'].format(
                    columnInfo.keys[0].metric))
                mt = MetricTimeSeries(columnInfo.keys[0].metric, '')
                mt.timeseries.append(ts)
                metrics[columnInfo.keys[0].metric] = mt
        return metrics, None, None

    def run_collection(self) -> CollectionResult:
        """Unified, thread-safe entry point for one collection cycle.

        The request filters and group tags are validated first (reusing the
        existing :meth:`validate_query_filters` and
        :meth:`validate_group_tags` semantics, including ``*`` wildcard and
        ``|`` separated multi-value handling), then the zimon query is
        executed. Everything that could fail is translated into a
        :class:`CollectionResult`:

        * :attr:`CollectionStatus.SUCCESS` - data was collected, available
          in ``result.metrics``
        * :attr:`CollectionStatus.NO_DATA` - the query returned no rows /
          ``None``
        * :attr:`CollectionStatus.INVALID_FILTER` - a filter or group tag is
          not supported by this sensor; ``result.error`` names the offending
          tag name or value
        * :attr:`CollectionStatus.QUERY_FAILED` - the query raised an
          exception, which is retained on ``result.exception``

        The method only reads shared collector state (request, topology
        metadata) and keeps all intermediate data in local variables, so
        concurrent threads calling it on the same instance cannot clobber
        each others validation findings or error messages, and one thread's
        invalid filter never affects another thread's successful run.
        """

        validation_error = self._validate_request()
        if validation_error is not None:
            status, error = validation_error
            return CollectionResult(status, error)

        metrics, error, exception = self._run_query_and_collect()
        if error == CollectionStatus.QUERY_FAILED:
            reason = str(exception) if exception is not None else 'unknown error'
            return CollectionResult(
                CollectionStatus.QUERY_FAILED,
                MSG['QueryError'].format(reason),
                exception=exception)
        if error == CollectionStatus.NO_DATA:
            return CollectionResult(CollectionStatus.NO_DATA, MSG['NoData'])

        return CollectionResult(CollectionStatus.SUCCESS, metrics=metrics)

    def _validate_request(self):
        """Validate filters and group tags, returning ``(status, error)``.

        Returns ``None`` when the request is valid. The original validation
        behaviour (raising ``cherrypy.HTTPError(400, ...)``) is preserved
        for the existing callers; this wrapper only translates the raised
        errors into structured, specific descriptions.
        """

        try:
            self.validate_query_filters()
        except cherrypy.HTTPError:
            return CollectionStatus.INVALID_FILTER, self._describe_filter_error()

        try:
            self.validate_group_tags()
        except cherrypy.HTTPError:
            return CollectionStatus.INVALID_FILTER, self._describe_group_tags_error()

        return None

    def _describe_filter_error(self) -> str:
        """Build a specific explanation of why the request filters fail.

        Distinguishes unsupported tag names from unsupported tag values and
        keeps the special treatment of ``*`` wildcards and ``|`` separated
        conditional values used by :meth:`validate_query_filters`.
        """

        if not self.request.filters:
            return MSG['AttrNotValid'].format('filter')

        if not self.filtersMap:
            return MSG['FilterByErr']

        supported_keys = set()
        for filtersDict in self.filtersMap:
            supported_keys.update(filtersDict.keys())

        problems = []
        for key, value in self.request.filters.items():
            str_key = str(key)
            str_value = str(value)

            # wildcard in the tag name: the tag is resolved from the
            # requested value, mirroring validate_query_filters. When no
            # tag matches, the legacy validator simply applies no filter
            # and stays valid, so it must not be reported as a problem here
            if '*' in str_key:
                found_keys = self.md.metaData.getAllKeysForTagValue(value)
                if found_keys and not any(key in supported_keys
                                          for key in found_keys):
                    problems.append(
                        f"filter tag name '{str_key}' (value '{str_value}') is not "
                        f"supported by sensor '{self.sensor}'")
                continue

            if str_key not in supported_keys:
                problems.append(
                    f"filter tag name '{str_key}' is not supported by sensor "
                    f"'{self.sensor}'")
                continue

            if '*' in str_value:
                # wildcard value matches everything of an existing tag name;
                # it only fails when the tag has no known values at all
                if not self.md.metaData.getAllValuesForTagName(str_key):
                    problems.append(
                        f"filter value '{str_value}' for tag '{str_key}' does not "
                        f"match any known component of sensor '{self.sensor}'")
                continue

            if '|' in str_value:
                # conditional filters keep every map whose value is one of
                # the pipe separated values; the filter only fails when none
                # of the requested values matches, mirroring
                # validate_query_filters
                candidates = str_value.split('|')
                known_values = {filtersDict[str_key] for filtersDict in
                                self.filtersMap if str_key in filtersDict}
                unknown = [candidate for candidate in candidates
                           if candidate not in known_values]
                if unknown and not any(candidate in known_values
                                       for candidate in candidates):
                    problems.append(
                        f"filter value(s) '{', '.join(unknown)}' for tag "
                        f"'{str_key}' are not supported by sensor '{self.sensor}'")
                continue

            known_values = {filtersDict[str_key] for filtersDict in
                            self.filtersMap if str_key in filtersDict}
            if str_value not in known_values:
                problems.append(
                    f"filter value '{str_value}' for tag '{str_key}' is not "
                    f"supported by sensor '{self.sensor}'")

        if problems:
            return '; '.join(problems)

        # Fallback for combinations that only fail when applied together
        return MSG['FilterByErr']

    def _describe_group_tags_error(self) -> str:
        """Build a specific explanation of why the group tags fail."""

        filter_keys = set()
        for filtersDict in self.filtersMap:
            filter_keys.update(filtersDict.keys())

        if not filter_keys:
            return MSG['GroupByErr']

        unsupported = [tag for tag in self.request.grouptags
                       if tag not in filter_keys]
        if unsupported:
            return (
                f"groupBy tag name(s) '{', '.join(unsupported)}' are not "
                f"supported by sensor '{self.sensor}'. Supported groupBy tags: "
                f"{', '.join(sorted(filter_keys))}")

        return MSG['AttrNotValid'].format('groupBy key')

    @cond_execution_time(detail_level=2)
    def prepare_static_metrics_data(self):
        incl_metrics = list(self.request.metricsaggr.keys()
                            ) if self.request.metricsaggr else None
        self.setup_static_metrics_data(incl_metrics)

    @cond_execution_time(detail_level=2)
    def validate_query_filters(self):
        # check filterBy settings
        if self.request.filters:

            if not self.filtersMap:
                self.logger.error(MSG['FilterByErr'])
                raise cherrypy.HTTPError(
                    400, MSG['AttrNotValid'].format('filter'))

            filtersMap = self.filtersMap[:]

            groupFilter = {}
            conditionalFilter = {}
            singleFilter = {}
            for key, value in self.request.filters.items():
                if str(key).find('*') != -1:
                    foundKeys = self.md.metaData.getAllKeysForTagValue(value)
                    for foundKey in foundKeys:
                        singleFilter[foundKey] = value
                elif str(value).find('*') != -1:
                    groupFilter[key] = self.md.metaData.getAllValuesForTagName(key)
                elif str(value).find('|') != -1:
                    conditionalFilter[key] = value.split('|')
                else:
                    singleFilter[key] = value

            iteritems = lambda d: (getattr(d, 'iteritems', None) or d.items)()
            if singleFilter:
                for filtersDict in reversed(filtersMap):
                    if not all((k in filtersDict and filtersDict[k] == v) for
                               k, v in iteritems(singleFilter)):
                        filtersMap.remove(filtersDict)
            if conditionalFilter:
                for filtersDict in reversed(filtersMap):
                    if not all((k in filtersDict and filtersDict[k] in v) for
                               k, v in iteritems(conditionalFilter)):
                        filtersMap.remove(filtersDict)
            if groupFilter:
                for filtersDict in reversed(filtersMap):
                    if not all((k in filtersDict and filtersDict[k] in v) for
                               k, v in iteritems(groupFilter)):
                        filtersMap.remove(filtersDict)

            if not filtersMap:
                self.logger.error(MSG['FilterByErr'])
                raise cherrypy.HTTPError(
                    400, MSG['AttrNotValid'].format('filter'))

    @cond_execution_time(detail_level=2)
    def validate_group_tags(self):
        # check groupBy settings
        if self.request.grouptags:
            filter_keys = set()
            for filter in self.filtersMap:
                filter_keys.update(filter.keys())
            if not filter_keys:
                self.logger.error(MSG['GroupByErr'])
                raise cherrypy.HTTPError(
                    400, MSG['AttrNotValid'].format('groupBy key'))
            if not (set(self.request.grouptags)).issubset(filter_keys):
                self.logger.error(MSG['AttrNotValid'].format('groupBy key'))
                self.logger.error(MSG['ReceivAttrValues'].format(
                    'groupBy keys', ", ".join(filter_keys)))
                raise cherrypy.HTTPError(
                    400, MSG['AttrNotValid'].format('groupBy key'))
