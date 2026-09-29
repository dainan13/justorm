# tests package marker.
#
# The presence of this file lets pytest treat ``tests`` as a package,
# which matters when test modules need to import shared helpers from
# one another (for example ``from tests.helpers import ...``) and when
# coverage is asked to report per-package.
#
# It is intentionally empty.
