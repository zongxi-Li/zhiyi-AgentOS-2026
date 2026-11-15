import pytest
from support.acg.capabilities import CapabilityCatalog, PlanningCapabilityDescriptor


def test_disabled_workspace_optional_edge_does_not_leak_or_mutate_global_catalog():
    catalog = CapabilityCatalog([
        PlanningCapabilityDescriptor(capabilityId='verification', displayName='verification', optionalDependencies=['workspace_execution']),
        PlanningCapabilityDescriptor(capabilityId='workspace_execution', displayName='workspace execution'),
    ])
    scoped = catalog.scoped(['verification'])
    assert scoped.get('verification').optional_dependencies == []
    assert catalog.get('verification').optional_dependencies == ['workspace_execution']
    assert catalog.scoped(['verification','workspace_execution']).get('verification').optional_dependencies == ['workspace_execution']


def test_scoped_catalog_still_rejects_missing_required_dependencies():
    catalog = CapabilityCatalog([
        PlanningCapabilityDescriptor(capabilityId='verification', displayName='verification', dependsOn=['workspace_execution']),
        PlanningCapabilityDescriptor(capabilityId='workspace_execution', displayName='workspace execution'),
    ])
    with pytest.raises(ValueError, match='dangling dependency'):
        catalog.scoped(['verification'])
