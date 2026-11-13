"""Unit tests for Country model in olostep.models.common."""

import pytest

from olostep.models.common import CertainCountries, Country


class TestCountry:
    """Test Country class functionality."""

    def test_dot_addressable_common_countries(self):
        """Test that common countries are accessible via dot notation."""
        assert Country.US == "US"
        assert Country.CA == "CA"
        assert Country.GB == "GB"
        assert Country.DE == "DE"
        assert Country.FR == "FR"
        assert Country.JP == "JP"
        assert Country.CN == "CN"
        assert Country.BR == "BR"
        assert Country.IN == "IN"
        assert Country.AU == "AU"

    def test_dot_addressable_new_countries(self):
        """Test that countries not in old enum are accessible."""
        # Countries that were NOT in the old 11-country enum
        assert Country.DE == "DE"  # Germany
        assert Country.FR == "FR"  # France
        assert Country.CN == "CN"  # China
        assert Country.BR == "BR"  # Brazil
        assert Country.ES == "ES"  # Spain
        assert Country.NL == "NL"  # Netherlands
        assert Country.SE == "SE"  # Sweden
        assert Country.NO == "NO"  # Norway
        assert Country.DK == "DK"  # Denmark
        assert Country.FI == "FI"  # Finland
        assert Country.PL == "PL"  # Poland
        assert Country.IT == "IT"  # Italy (was in old enum, but test it anyway)

    def test_random_special_value(self):
        """Test that RANDOM is accessible and works correctly."""
        assert Country.RANDOM == "RANDOM"
        assert Country.RANDOM.value == "RANDOM"
        assert repr(Country.RANDOM) == "Country.RANDOM"

    def test_country_creation_from_string(self):
        """Test creating Country instances from strings."""
        assert Country("US") == "US"
        assert Country("DE") == "DE"
        assert Country("RANDOM") == "RANDOM"
        assert Country("FR") == "FR"

    def test_invalid_country_codes_raise_error(self):
        """Test that invalid country codes raise ValueError."""
        invalid_codes = ["ZZ", "XX", "invalid", "123", "usa", "UK", "EN"]
        for code in invalid_codes:
            with pytest.raises(ValueError, match="Invalid ISO 3166-1 alpha-2 country code"):
                Country(code)

    def test_iteration_excludes_random(self):
        """Test that iteration over Country yields all ISO codes but excludes RANDOM."""
        all_countries = [c.value for c in Country]
        
        # Should have 249 ISO countries
        assert len(all_countries) == 249
        
        # RANDOM should NOT be in the iteration
        assert "RANDOM" not in all_countries
        
        # But valid ISO codes should be present
        assert "US" in all_countries
        assert "DE" in all_countries
        assert "FR" in all_countries
        assert "CN" in all_countries
        assert "BR" in all_countries

    def test_membership_check(self):
        """Test that membership checks work correctly."""
        # Valid ISO codes should be in Country
        assert "US" in Country
        assert "DE" in Country
        assert "FR" in Country
        assert "CN" in Country
        
        # RANDOM should be in Country
        assert "RANDOM" in Country
        
        # Invalid codes should not be in Country
        assert "ZZ" not in Country
        assert "XX" not in Country
        assert "invalid" not in Country
        
        # Country instances should be in Country
        assert Country.US in Country
        assert Country.DE in Country
        assert Country.RANDOM in Country

    def test_value_property(self):
        """Test that .value property returns the string code."""
        assert Country.US.value == "US"
        assert Country.DE.value == "DE"
        assert Country.RANDOM.value == "RANDOM"

    def test_repr(self):
        """Test that __repr__ returns expected format."""
        assert repr(Country.US) == "Country.US"
        assert repr(Country.DE) == "Country.DE"
        assert repr(Country.RANDOM) == "Country.RANDOM"

    def test_all_iso_countries_accessible(self):
        """Test that all 249 ISO countries are accessible via dot notation."""
        # Sample a diverse set of countries from different regions
        test_countries = [
            "US", "CA", "MX",  # North America
            "BR", "AR", "CL",  # South America
            "GB", "DE", "FR", "ES", "IT", "NL",  # Europe
            "CN", "JP", "IN", "KR", "ID", "TH",  # Asia
            "AU", "NZ",  # Oceania
            "ZA", "EG", "NG",  # Africa
            "AE", "SA", "IL",  # Middle East
        ]
        
        for code in test_countries:
            country_attr = getattr(Country, code)
            assert country_attr == code
            assert country_attr.value == code

    def test_pydantic_integration(self):
        """Test that Country works with Pydantic models."""
        from olostep.models.request import ScrapeUrlBodyParams
        
        # Test with Country instance
        body1 = ScrapeUrlBodyParams(
            url_to_scrape="https://example.com",
            country=Country.US
        )
        assert body1.country == Country.US
        assert body1.country.value == "US"
        
        # Test with string (should be converted to Country)
        body2 = ScrapeUrlBodyParams(
            url_to_scrape="https://example.com",
            country="DE"
        )
        assert isinstance(body2.country, Country)
        assert body2.country == "DE"
        
        # Test with RANDOM
        body3 = ScrapeUrlBodyParams(
            url_to_scrape="https://example.com",
            country=Country.RANDOM
        )
        assert body3.country == Country.RANDOM

    def test_pydantic_validation_rejects_invalid(self):
        """Test that Pydantic validation rejects invalid country codes."""
        from pydantic import ValidationError

        from olostep.models.request import ScrapeUrlBodyParams
        
        with pytest.raises(ValidationError):
            ScrapeUrlBodyParams(
                url_to_scrape="https://example.com",
                country="ZZ"
            )


class TestCertainCountries:
    """Test CertainCountries validator class."""

    def test_certain_countries_validation(self):
        """Test that CertainCountries validates against a restricted set."""
        validator = CertainCountries({"US", "CA", "GB"})
        
        # Valid countries should work
        assert validator.validate("US") == Country.US
        assert validator.validate("CA") == Country.CA
        assert validator.validate("GB") == Country.GB
        
        # Invalid countries should raise ValueError
        with pytest.raises(ValueError, match="not supported"):
            validator.validate("DE")
        
        with pytest.raises(ValueError, match="not supported"):
            validator.validate("FR")

    def test_certain_countries_invalid_iso_code(self):
        """Test that CertainCountries rejects invalid ISO codes in constructor."""
        with pytest.raises(ValueError, match="Invalid ISO 3166-1 alpha-2 country code"):
            CertainCountries({"US", "ZZ"})

    def test_certain_countries_valid_codes_property(self):
        """Test that valid_codes property returns the set of valid codes."""
        validator = CertainCountries({"US", "CA", "GB"})
        assert validator.valid_codes == frozenset({"US", "CA", "GB"})

