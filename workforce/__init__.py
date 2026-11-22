"""HERMES WORKFORGE - observability for autonomous AI work.

One event stream, one source of truth, many interfaces.
"""

from .models import SCHEMA_VERSION, Evidence, TaskSpec, WorkerEvent

__version__ = "0.1.0"
__all__ = ["SCHEMA_VERSION", "Evidence", "TaskSpec", "WorkerEvent", "__version__"]
