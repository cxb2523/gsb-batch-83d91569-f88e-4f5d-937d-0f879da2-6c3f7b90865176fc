'''
##############################################################################
# Copyright 2026 IBM Corp.
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

Created on Aug 1ß, 2026

@author: HWASSMAN
'''

from collections import defaultdict
from typing import Any, Dict, List, Optional, Set


class Schema:
    """Example:
    {
        "sensor_metric": {
            "Network": {
            "netdev_bytes_r": {
                "semantic": "counter",
                "data_type": "uint_64"
            },
            "netdev_bytes_s": {
                "semantic": "counter",
                "data_type": "uint_64"
            },
            ...
            }
        },
        "sensor_key_names": {
            "Network": ["node", "netdev_name"], ...
        },
        "sensor_key_values": {
            "Network": [
            ["nnode-11", "ens224"],
            ["nnode-11", "ens256"],
            ...
            ]
        }
    }
    """

    METRICS = "sensor_metric"
    KEYS = "sensor_key_names"
    VALUES = "sensor_key_values"

    def __init__(self, schema: Dict[str, Any], logger) -> None:
        self.logger = logger
        self.schema = schema or {}

        if not self.schema:
            self.logger.warning("SCHEMA initialized with empty schema dictionary")

        # some derived values and aliases
        self.metrics = self.schema.get(Schema.METRICS, {})
        self.keys = self.schema.get(Schema.KEYS, {})
        self.values = self.schema.get(Schema.VALUES, {})
        self.sensors = list(self.keys.keys())
        # ?? store transposed sensor_metric Map
        # self.metric_sensor = {m: sensor for sensor, metrics in self.metrics.items() for m in metrics}
        self.logger.debug("SCHEMA initialized with %d sensors", len(self.sensors))
        if not (len(self.values) == len(self.keys) == len(self.metrics)):
            self.logger.warning(
                "SCHEMA: Sensors, keys and values are not of the same length - values:%d, keys:%d, metrics:%d",
                len(self.values),
                len(self.keys),
                len(self.metrics),
            )
            missing_in_values = set(self.keys.keys()) - set(self.values.keys())
            missing_in_keys = set(self.metrics.keys()) - set(self.keys.keys())
            if missing_in_values:
                self.logger.warning("SCHEMA: Sensors missing in values: %s", missing_in_values)
            if missing_in_keys:
                self.logger.warning("SCHEMA: Sensors missing in keys: %s", missing_in_keys)

    def get_filters(self) -> Dict[str, List[Dict[str, str]]]:
        """combine keynames and values to get a dict of potential filters
        filters["CPU"] = [{'node': 'nnode-11'}, {'node': 'nnode-12'}, {'node': 'nnode-13'} ]
        """
        filters = {}
        for sensor, keys in self.keys.items():
            filters[sensor] = [dict(zip(keys, value)) for value in self.values[sensor]]
        return filters

    @property
    def allFiltersMaps(self) -> Dict[str, List[Dict[str, str]]]:
        """
        Returns a Dict with a list of all filters maps returned from zimon meta data.
        Each filters map is a list of component name, component as dict entries.
        representing a single entity have been monitored by zimon.
        e.g. allFiltersMaps['Network'] => [{'node': 'nnode-11', 'netdev_name': 'ens224'}, {'node': 'nnode-11', 'netdev_name': 'ens256'}, ....]
        """
        return self.get_filters()

    @property
    def allAvailableComponents(self) -> Dict[str, Set[str]]:
        """
        Dictionary contains a component name and all found values for this
        component(tag) in the meta data returned by zimon.
        e.g. 'gpfs_fs_name': {'(free disk)', 'gpfs0', 'cesSharedRoot'}, 'gpfs_disk_name': {'disk06', 'disk07'}, ...
        """
        comps = defaultdict(set)
        for sensor in self.sensors:
            for value in self.values[sensor]:
                for pos, elem in enumerate(value):
                    comps[self.keys[sensor][pos]].add(elem)
        return comps

    @property
    def allParents(self) -> List[str]:
        """
        All 'parents' of zimon entries => all node names + cluster name
        e.g. ['node-11', 'node-12', 'node-13', 'node-14', 'node-15', 'scale-cluster-1.vmlocal']
        """
        return list({val[0] for sensor in self.sensors for val in self.values[sensor]})

    @property
    def sensorsLevels(self) -> Dict[str, Dict[int, str]]:
        """
        Component level priority dictionary, per sensor
        e.g. levels["Network"] => {1: 'node', 2: 'netdev_name'}
        """
        return {sensor: dict(enumerate(keys, 1)) for sensor, keys in self.keys.items()}

    @property
    def sensorsSpec(self) -> Dict[str, List[str]]:
        """
        Returns the specification of all defined sensors as dictionary of Lists
        Sensor dictionary consists of for the sensor supported filter tags and metric names
        e.g. sensorsSpec['Network'] => ['node', 'netdev_name', 'netdev_bytes_r', 'netdev_carrier', ...'netdev_packets_s']
        """
        spec = {}
        for sensor, metric in self.metrics.items():
            spec[sensor] = self.keys.get(sensor, []) + list(metric.keys())
        return spec

    @property
    def metricsType(self) -> Dict[str, str]:
        """
        Returns a dictionary of (metric_name : metric_type) items.
        Metric type can be one of 'counter', 'quantity', 'deltaCounter'
        """
        return {k: v["semantic"] for metrics in self.metrics.values() for k, v in metrics.items()}

    @property
    def getAllEnabledMetricsNames(self) -> List[str]:
        """Returns list of all found metrics names"""
        return [metric_name for metrics in self.metrics.values() for metric_name in metrics]

    @property
    def getAllAvailableTagNames(self):
        return list(self.allAvailableComponents.keys())

    @property
    def getAllAvailableTagValues(self):
        tagvlist = []
        for key, values in self.allAvailableComponents.items():
            if not key == 'sensor':
                tagvlist.extend(values)
        return list(set(tagvlist))

    def getSensorForMetric(self, searchMetric: str) -> Optional[str]:
        """
        Return Sensor name for a given metric name or None if it was not found
        """
        if searchMetric.find("(") >= 0:
            searchMetric = searchMetric[searchMetric.find("(") + 1: -1]

        result = next((sensor for sensor, metrics in self.schema[Schema.METRICS].items() if searchMetric in metrics), None)
        if result is None:
            self.logger.debug("SCHEMA: Metric '%s' not found in any sensor", searchMetric)
        return result

    def getSensorLabels(self, searchSensor: str) -> list:
        labelsDict = self.sensorsLevels.get(searchSensor, None)
        if labelsDict:
            labelsList = []
            for level, name in labelsDict.items():
                labelsList.insert(int(level) - 1, name)
            return labelsList
        return []

    def getSensorMetricNames(self, searchSensor: str) -> list:
        metrics = self.metrics.get(searchSensor, None)
        if metrics:
            return metrics.keys()
        return []

    def getSensorMetricTypes(self, searchSensor: str) -> Dict[str, str]:
        sensorMetricsTypes = {}
        metrics = self.metrics.get(searchSensor, None)
        if metrics:
            sensorMetricsTypes = {k: v["semantic"] for k, v in metrics.items()}
        return sensorMetricsTypes

    def getSensorsForMeasurementMetrics(self, searchMetrics: List[str]) -> List[str]:
        """
        Return List of Sensor names for given list of metric names
        """
        sensors = {sensor for metric in searchMetrics if (sensor := self.getSensorForMetric(metric)) is not None}
        return list(sensors)

    def getAllValuesForTagName(self, searchTag: str) -> Set[str]:
        """
        Return set of possible tag (aka field) values for a given tag
        e.g. getAllValuesForTagName('netdev_name') => {'ens256', 'ens224', 'eth1', 'eth2', 'lo', 'ens192', 'ens161', 'eth0'}
        """
        return self.allAvailableComponents.get(searchTag, set())

    def getAllKeysForTagValue(self, searchValue: str) -> List[str]:
        """
        Return matching field/tag names for a given value
        e.g. getAllKeysForTagValue('gpfs0') => ['gpfs_fs_name']
        """
        tags = {key for key, values in self.allAvailableComponents.items() if searchValue in values}
        return list(tags)

    def getAllFilterMapsForSensor(self, searchSensor: str) -> List[Dict[str, str]]:
        """
        This function returns a list of filters maps found for the specified sensor name (searchSensor)
        """
        filtersMaps = []  # return copy of items as users modify it
        if searchSensor in self.allFiltersMaps:
            filtersMaps.extend(self.allFiltersMaps[searchSensor])
        return filtersMaps

    def getAllFilterMapsForMetric(self, searchMetric: str) -> List[Dict[str, str]]:
        """
        This function returns a list of filters maps found for the specified metric name (searchMetric)
        e.g. getAllFilterMapsForMetric("gpfs_fs_write_ops") =>
            [{'node': 'node-11', 'gpfs_cluster_name': 'scale-cluster-1.vmlocal', 'gpfs_fs_name': 'cesSharedRoot'},
             {'node': 'node-11', 'gpfs_cluster_name': 'scale-cluster-1.vmlocal', 'gpfs_fs_name': 'gpfs0'}, ... ]
        """
        searchSensor = self.getSensorForMetric(searchMetric)
        if searchSensor:
            return self.getAllFilterMapsForSensor(searchSensor)
        return []

    def getAllFilterMapsForMeasurementMetrics(self, searchMetrics: List[str]) -> List[Dict[str, str]]:
        """
        return a list of filters maps given a list of metrics
        """
        filtersMaps = []
        sensors = self.getSensorsForMeasurementMetrics(searchMetrics)
        for sensor in sensors:
            if sensor:
                filtersMaps.extend(self.getAllFilterMapsForSensor(sensor))
        return filtersMaps

    def getKeyGranularitylistForMetric(self, searchMetric: str) -> Optional[Dict[int, str]]:
        """
        Return dict with levels of the zimon key and tag/field name of that level or None if the metric was not found
        e.g. getKeyGranularitylistForMetric('gpfs_nsdpool_bytes_read') => {1: 'node', 2: 'gpfs_fs_name', 3: 'gpfs_diskpool_name'}
        """
        searchSensor = self.getSensorForMetric(searchMetric)
        if not searchSensor:
            return None
        return self.sensorsLevels[searchSensor]

    def getAllFilterKeysForMetric(self, searchMetric: str) -> List[str]:
        """
        Return potential field names the metric can be filtered for.
        e.g. getAllFilterKeysForMetric('netdev_fifo_s') => ['node', 'netdev_name']
        """
        return self.schema[Schema.KEYS].get(self.getSensorForMetric(searchMetric), [])

    def getAllFilterKeysForMeasurementsMetrics(self, searchMetrics: List[str]) -> List[str]:
        """
        Return potential field names the given list of metrics can be filtered for.
        e.g. getAllFilterKeysForMeasurementsMetrics(['netdev_fifo_s']) => ['netdev_name', 'node']
        """
        sensors = self.getSensorsForMeasurementMetrics(searchMetrics)
        return list({key_name for sensor in sensors for key_name in self.keys[sensor]})

    def getIdentifiersMapForQueryAttr(self, type_, metricsStr, filterBy):
        if type_ == 'metric':
            filtersMap = self.getAllFilterMapsForMetric(metricsStr)
        elif type_ == 'measurement':
            filtersMap = self.getAllFilterMapsForMeasurementMetrics(metricsStr.split(","))
        else:
            raise Exception("SCHEMA ERROR: The query type %s not supported" % type_)

        if not filtersMap or not filterBy or len(filterBy) == 0:
            return filtersMap

        if len(filterBy) > 0:
            groupFilter = {}
            conditionalFilter = {}
            singleFilter = {}
            for key, value in filterBy.items():
                if str(key).find('*') != -1:
                    foundKeys = self.getAllKeysForTagValue(value)
                    for foundKey in foundKeys:
                        singleFilter[foundKey] = value
                elif str(value).find('*') != -1:
                    groupFilter[key] = self.getAllValuesForTagName(key)
                elif str(value).find('|') != -1:
                    conditionalFilter[key] = value.split('|')
                else:
                    singleFilter[key] = value

            iteritems = lambda d: (getattr(d, 'iteritems', None) or d.items)()
            if singleFilter:
                for filtersDict in reversed(filtersMap):
                    if not all((k in filtersDict and filtersDict[k] == v) for k, v in iteritems(singleFilter)):
                        filtersMap.remove(filtersDict)
            if conditionalFilter:
                for filtersDict in reversed(filtersMap):
                    if not all((k in filtersDict and filtersDict[k] in v) for k, v in iteritems(conditionalFilter)):
                        filtersMap.remove(filtersDict)
            if groupFilter:
                for filtersDict in reversed(filtersMap):
                    if not all((k in filtersDict and filtersDict[k] in v) for k, v in iteritems(groupFilter)):
                        filtersMap.remove(filtersDict)

        return filtersMap

    # calculateQueryPriority- if needed copy 1:1 from topo
