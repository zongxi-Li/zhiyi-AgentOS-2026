"""Build the Core-owned Native capability catalog."""

from core.planning.capabilities import CapabilityCatalog
from core.planning.native_capabilities import register_native_capabilities


def build_default_capability_catalog() -> CapabilityCatalog:
    catalog = CapabilityCatalog()
    register_native_capabilities(catalog)
    catalog.validate()
    return catalog


__all__ = ["build_default_capability_catalog"]
