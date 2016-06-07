import orchpy as op
import orchpy.services as services
import os
import time
import numpy as np

import halo.arrays.remote as ra

import optimization

test_dir = os.path.dirname(os.path.abspath(__file__))
test_path = os.path.join(test_dir, "optimize_worker.py")
services.start_singlenode_cluster(return_drivers=False, num_workers_per_objstore=3, worker_path=test_path)

dim = 10
num_data_per_batch = 100
num_batches = 13

w_ground_truth = ra.random.normal([dim])
x_batches = [ra.random.normal([num_data_per_batch, dim]) for _ in range(num_batches)]
y_batches = [ra.add(ra.dot(x_batches[i], w_ground_truth), ra.random.normal([num_data_per_batch])) for i in range(num_batches)]

w_current = ra.random.normal([dim])
for t in range(100):
  grad = optimization.sum(*[optimization.grad(w_current, x_batches[i], y_batches[i]) for i in range(num_batches)])
  w_current = ra.subtract(w_current, grad)

services.cleanup()
