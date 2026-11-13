from enum import StrEnum


class DatePrecision(StrEnum):
    EXACT = "exact"
    DAY = "day"
    RANGE = "range"
    INFERRED = "inferred"
    UNKNOWN = "unknown"
