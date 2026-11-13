from __future__ import annotations

from typing import TYPE_CHECKING, Any, Iterator

import pycountry

if TYPE_CHECKING:
    from pydantic import GetCoreSchemaHandler
    from pydantic_core import CoreSchema


class _CountryMeta(type):
    """Metaclass enabling iteration over all ISO countries (excluding RANDOM)."""

    _iso_countries: list["Country"] | None = None

    def __iter__(cls) -> Iterator["Country"]:
        if cls._iso_countries is None:
            cls._iso_countries = [
                getattr(cls, c.alpha_2) for c in pycountry.countries
            ]
        yield from cls._iso_countries

    def __contains__(cls, item: object) -> bool:
        if isinstance(item, Country):
            return True
        if isinstance(item, str):
            return item == "RANDOM" or pycountry.countries.get(alpha_2=item) is not None
        return False


class Country(str, metaclass=_CountryMeta):
    """Country codes for geolocation. Supports all ISO 3166-1 alpha-2 codes plus RANDOM.

    All 249 ISO countries are available as class attributes (e.g., Country.US, Country.DE).
    RANDOM is a special value for random country selection.

    Iteration yields all ISO countries (RANDOM excluded):
        >>> [c.value for c in Country]  # All ISO codes, no RANDOM

    Usage:
        >>> Country.US  # Access by attribute
        >>> Country("DE")  # Create from string
        >>> Country.RANDOM  # Random selection
    """

    __slots__ = ()

    def __new__(cls, code: str) -> "Country":
        if code == "RANDOM":
            return str.__new__(cls, code)
        if pycountry.countries.get(alpha_2=code) is None:
            raise ValueError(f"Invalid ISO 3166-1 alpha-2 country code: {code}")
        return str.__new__(cls, code)

    @property
    def value(self) -> str:
        return str(self)

    def __repr__(self) -> str:
        return f"Country.{self}"

    @classmethod
    def __get_pydantic_core_schema__(
        cls, source_type: Any, handler: "GetCoreSchemaHandler"
    ) -> "CoreSchema":
        from pydantic_core import core_schema

        def validate_country(value: Any) -> "Country":
            if isinstance(value, Country):
                return value
            if isinstance(value, str):
                return cls(value)
            raise ValueError(f"Expected str or Country, got {type(value).__name__}")

        return core_schema.no_info_plain_validator_function(
            validate_country,
            serialization=core_schema.to_string_ser_schema(),
        )


# Generate all country attributes dynamically
for _c in pycountry.countries:
    setattr(Country, _c.alpha_2, Country(_c.alpha_2))
Country.RANDOM = Country("RANDOM")

# Clear iteration cache so it's built fresh with the new instances
Country._iso_countries = None


class CertainCountries:
    """Validator for endpoints that only support a subset of countries.

    This class is designed for future use where specific API endpoints
    may only support certain country codes.

    Args:
        valid_countries: Set of valid ISO 3166-1 alpha-2 codes for this endpoint.

    Usage:
        >>> validator = CertainCountries({"US", "CA", "GB"})
        >>> validator.validate("US")  # Returns Country.US
        >>> validator.validate("DE")  # Raises ValueError
    """

    def __init__(self, valid_countries: set[str]) -> None:
        for code in valid_countries:
            if pycountry.countries.get(alpha_2=code) is None:
                raise ValueError(f"Invalid ISO 3166-1 alpha-2 country code: {code}")
        self._valid_countries = frozenset(valid_countries)

    def validate(self, code: str) -> Country:
        """Validate and return a Country instance if the code is valid for this endpoint."""
        if code not in self._valid_countries:
            raise ValueError(
                f"Country code '{code}' is not supported. "
                f"Valid countries: {sorted(self._valid_countries)}"
            )
        return Country(code)

    @property
    def valid_codes(self) -> frozenset[str]:
        return self._valid_countries

