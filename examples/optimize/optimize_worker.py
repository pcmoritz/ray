import sys
import argparse
import numpy as np

import optimization

import halo
import halo.services as services
import halo.worker as worker
import halo.arrays.remote as ra
import halo.arrays.distributed as da


parser = argparse.ArgumentParser(description='Parse addresses for the worker to connect to.')
parser.add_argument("--scheduler-address", default="127.0.0.1:10001", type=str, help="the scheduler's address")
parser.add_argument("--objstore-address", default="127.0.0.1:20001", type=str, help="the objstore's address")
parser.add_argument("--worker-address", default="127.0.0.1:40001", type=str, help="the worker's address")

if __name__ == '__main__':
  args = parser.parse_args()
  worker.connect(args.scheduler_address, args.objstore_address, args.worker_address)

  halo.register_module(halo.examples.optimization)
  halo.register_module(sys.modules[__name__])
  halo.register_module(ra)
  halo.register_module(ra.random)
  halo.register_module(ra.linalg)
  halo.register_module(da)
  halo.register_module(da.random)
  halo.register_module(da.linalg)

  worker.main_loop()
