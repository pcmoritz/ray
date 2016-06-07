import halo
import numpy as np

@halo.remote([np.ndarray, np.ndarray, np.ndarray], [float])
def loss(w, xs, ys):
  return 0.5 * np.linalg.norm(np.dot(xs, w) - ys) ** 2

@halo.remote([np.ndarray, np.ndarray, np.ndarray], [np.ndarray, int])
def grad(w, xs, ys):
  return np.dot(xs.T, np.dot(xs, w)) - np.dot(xs.T, ys), xs.shape[0]

@halo.remote([np.ndarray], [np.ndarray])
def sum(*grads):
  return sum(grads)
