import sys
from unittest.mock import MagicMock

# Import google.auth and mock the default() method immediately
# This runs before pytest imports the agent application and telemetry setup.
import google.auth
google.auth.default = MagicMock(return_value=(MagicMock(), "dummy-project"))
