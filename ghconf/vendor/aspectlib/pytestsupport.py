import pytest
from . import weave


@pytest.fixture
def weave(request):
    def autocleaned_weave(*args, **kwargs):
        entanglement = weave(*args, **kwargs)
        request.addfinalizer(entanglement.rollback)
        return entanglement

    return autocleaned_weave
