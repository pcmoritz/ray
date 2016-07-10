# These three constants are used to define the mode that a worker is running in.
# Right now, this is only used for determining how to print information about
# task failures.
SCRIPT_MODE = 0
WORKER_MODE = 1
SHELL_MODE = 2
PYTHON_MODE = 3

import libraylib as lib
import serialization
from worker import scheduler_info, visualize_computation_graph, task_info, register_module, connect, disconnect, get, put, remote, kill_workers, restart_workers_local
from libraylib import ObjRef
import internal
