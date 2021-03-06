import unittest
import ray
import numpy as np
import time
import subprocess32 as subprocess
import os
import sys
from numpy.testing import assert_equal

import test_functions
import ray.array.remote as ra
import ray.array.distributed as da

RAY_TEST_OBJECTS = [[1, "hello", 3.0], 42, 43L, "hello world", 42.0, 1L << 62,
                    (1.0, "hi"), None, (None, None), ("hello", None),
                    True, False, (True, False), u"\u262F",
                    {True: "hello", False: "world"},
                    {"hello" : "world", 1: 42, 1.0: 45}, {},
                    np.int8(3), np.int32(4), np.int64(5),
                    np.uint8(3), np.uint32(4), np.uint64(5),
                    np.float32(1.0), np.float64(1.0)]

class UserDefinedType(object):
  def __init__(self):
    pass

  @staticmethod
  def deserialize(primitives):
    return "user defined type"

  def serialize(self):
    return "user defined type"

class SerializationTest(unittest.TestCase):

  def roundTripTest(self, data):
    serialized, _ = ray.serialization.serialize(ray.worker.global_worker.handle, data)
    result = ray.serialization.deserialize(ray.worker.global_worker.handle, serialized)
    assert_equal(data, result)

  def numpyTypeTest(self, typ):
    self.roundTripTest(np.random.randint(0, 10, size=(100, 100)).astype(typ))
    self.roundTripTest(np.array(0).astype(typ))
    self.roundTripTest(np.empty((0,)).astype(typ))

  def testSerialize(self):
    ray.init(start_ray_local=True, num_workers=0)

    for val in RAY_TEST_OBJECTS:
      self.roundTripTest(val)

    self.roundTripTest(np.zeros((100, 100)))

    self.numpyTypeTest("int8")
    self.numpyTypeTest("uint8")
    self.numpyTypeTest("int16")
    self.numpyTypeTest("uint16")
    self.numpyTypeTest("int32")
    self.numpyTypeTest("uint32")
    self.numpyTypeTest("float32")
    self.numpyTypeTest("float64")

    ref0 = ray.put(0)
    ref1 = ray.put(0)
    ref2 = ray.put(0)
    ref3 = ray.put(0)

    a = np.array([[ref0, ref1], [ref2, ref3]])
    capsule, _ = ray.serialization.serialize(ray.worker.global_worker.handle, a)
    result = ray.serialization.deserialize(ray.worker.global_worker.handle, capsule)
    self.assertTrue((a == result).all())

    self.roundTripTest(ref0)
    self.roundTripTest([ref0, ref1, ref2, ref3])
    self.roundTripTest({"0": ref0, "1": ref1, "2": ref2, "3": ref3})
    self.roundTripTest((ref0, 1))

    ray.worker.cleanup()

class ObjStoreTest(unittest.TestCase):

  # Test setting up object stores, transfering data between them and retrieving data to a client
  def testObjStore(self):
    scheduler_address, objstore_addresses = ray.services.start_ray_local(num_objstores=2, num_workers=0, worker_path=None)
    w1 = ray.worker.Worker()
    w2 = ray.worker.Worker()
    node_ip_address = "127.0.0.1"
    ray.connect(node_ip_address, scheduler_address, objstore_addresses[0], is_driver=True, mode=ray.SCRIPT_MODE, worker=w1)
    ray.reusables._cached_reusables = [] # This is a hack to make the test run.
    ray.connect(node_ip_address, scheduler_address, objstore_addresses[1], is_driver=True, mode=ray.SCRIPT_MODE, worker=w2)

    # putting and getting an object shouldn't change it
    for data in ["h", "h" * 10000, 0, 0.0]:
      objectid = ray.put(data, w1)
      result = ray.get(objectid, w1)
      self.assertEqual(result, data)

    # putting an object, shipping it to another worker, and getting it shouldn't change it
    for data in ["h", "h" * 10000, 0, 0.0, [1, 2, 3, "a", (1, 2)], ("a", ("b", 3))]:
      objectid = ray.put(data, w1)
      result = ray.get(objectid, w2)
      self.assertEqual(result, data)

    # putting an array, shipping it to another worker, and getting it shouldn't change it
    for data in [np.zeros([10, 20]), np.random.normal(size=[45, 25])]:
      objectid = ray.put(data, w1)
      result = ray.get(objectid, w2)
      assert_equal(result, data)

    # This test fails. See https://github.com/amplab/ray/issues/159.
    # getting multiple times shouldn't matter
    # for data in [np.zeros([10, 20]), np.random.normal(size=[45, 25]), np.zeros([10, 20], dtype=np.dtype("float64")), np.zeros([10, 20], dtype=np.dtype("float32")), np.zeros([10, 20], dtype=np.dtype("int64")), np.zeros([10, 20], dtype=np.dtype("int32"))]:
    #   objectid = worker.put(data, w1)
    #   result = worker.get(objectid, w2)
    #   result = worker.get(objectid, w2)
    #   result = worker.get(objectid, w2)
    #   assert_equal(result, data)

    # shipping a numpy array inside something else should be fine
    data = ("a", np.random.normal(size=[10, 10]))
    objectid = ray.put(data, w1)
    result = ray.get(objectid, w2)
    self.assertEqual(data[0], result[0])
    assert_equal(data[1], result[1])

    # shipping a numpy array inside something else should be fine
    data = ["a", np.random.normal(size=[10, 10])]
    objectid = ray.put(data, w1)
    result = ray.get(objectid, w2)
    self.assertEqual(data[0], result[0])
    assert_equal(data[1], result[1])

    # Getting a buffer after modifying it before it finishes should return updated buffer
    objectid = ray.libraylib.get_objectid(w1.handle)
    buf = ray.libraylib.allocate_buffer(w1.handle, objectid, 100)
    buf[0][0] = 1
    ray.libraylib.finish_buffer(w1.handle, objectid, buf[1], 0)
    completedbuffer = ray.libraylib.get_buffer(w1.handle, objectid)
    self.assertEqual(completedbuffer[0][0], 1)

    # We started multiple drivers manually, so we will disconnect them manually.
    ray.disconnect(worker=w1)
    ray.disconnect(worker=w2)
    ray.worker.cleanup()

class WorkerTest(unittest.TestCase):

  def testPutGet(self):
    ray.init(start_ray_local=True, num_workers=0)

    for i in range(100):
      value_before = i * 10 ** 6
      objectid = ray.put(value_before)
      value_after = ray.get(objectid)
      self.assertEqual(value_before, value_after)

    for i in range(100):
      value_before = i * 10 ** 6 * 1.0
      objectid = ray.put(value_before)
      value_after = ray.get(objectid)
      self.assertEqual(value_before, value_after)

    for i in range(100):
      value_before = "h" * i
      objectid = ray.put(value_before)
      value_after = ray.get(objectid)
      self.assertEqual(value_before, value_after)

    for i in range(100):
      value_before = [1] * i
      objectid = ray.put(value_before)
      value_after = ray.get(objectid)
      self.assertEqual(value_before, value_after)

    ray.worker.cleanup()

class APITest(unittest.TestCase):

  def testObjectIDAliasing(self):
    reload(test_functions)
    ray.init(start_ray_local=True, num_workers=3, driver_mode=ray.SILENT_MODE)

    ref = test_functions.test_alias_f.remote()
    assert_equal(ray.get(ref), np.ones([3, 4, 5]))
    ref = test_functions.test_alias_g.remote()
    assert_equal(ray.get(ref), np.ones([3, 4, 5]))
    ref = test_functions.test_alias_h.remote()
    assert_equal(ray.get(ref), np.ones([3, 4, 5]))

    ray.worker.cleanup()

  def testKeywordArgs(self):
    reload(test_functions)
    ray.init(start_ray_local=True, num_workers=1)

    x = test_functions.keyword_fct1.remote(1)
    self.assertEqual(ray.get(x), "1 hello")
    x = test_functions.keyword_fct1.remote(1, "hi")
    self.assertEqual(ray.get(x), "1 hi")
    x = test_functions.keyword_fct1.remote(1, b="world")
    self.assertEqual(ray.get(x), "1 world")

    x = test_functions.keyword_fct2.remote(a="w", b="hi")
    self.assertEqual(ray.get(x), "w hi")
    x = test_functions.keyword_fct2.remote(b="hi", a="w")
    self.assertEqual(ray.get(x), "w hi")
    x = test_functions.keyword_fct2.remote(a="w")
    self.assertEqual(ray.get(x), "w world")
    x = test_functions.keyword_fct2.remote(b="hi")
    self.assertEqual(ray.get(x), "hello hi")
    x = test_functions.keyword_fct2.remote("w")
    self.assertEqual(ray.get(x), "w world")
    x = test_functions.keyword_fct2.remote("w", "hi")
    self.assertEqual(ray.get(x), "w hi")

    x = test_functions.keyword_fct3.remote(0, 1, c="w", d="hi")
    self.assertEqual(ray.get(x), "0 1 w hi")
    x = test_functions.keyword_fct3.remote(0, 1, d="hi", c="w")
    self.assertEqual(ray.get(x), "0 1 w hi")
    x = test_functions.keyword_fct3.remote(0, 1, c="w")
    self.assertEqual(ray.get(x), "0 1 w world")
    x = test_functions.keyword_fct3.remote(0, 1, d="hi")
    self.assertEqual(ray.get(x), "0 1 hello hi")
    x = test_functions.keyword_fct3.remote(0, 1)
    self.assertEqual(ray.get(x), "0 1 hello world")

    ray.worker.cleanup()

  def testVariableNumberOfArgs(self):
    reload(test_functions)
    ray.init(start_ray_local=True, num_workers=1)

    x = test_functions.varargs_fct1.remote(0, 1, 2)
    self.assertEqual(ray.get(x), "0 1 2")
    x = test_functions.varargs_fct2.remote(0, 1, 2)
    self.assertEqual(ray.get(x), "1 2")

    self.assertTrue(test_functions.kwargs_exception_thrown)
    self.assertTrue(test_functions.varargs_and_kwargs_exception_thrown)

    ray.worker.cleanup()

  def testNoArgs(self):
    reload(test_functions)
    ray.init(start_ray_local=True, num_workers=1, driver_mode=ray.SILENT_MODE)

    test_functions.no_op.remote()
    time.sleep(0.2)
    task_info = ray.task_info()
    self.assertEqual(len(task_info["failed_tasks"]), 0)
    self.assertEqual(len(task_info["running_tasks"]), 0)

    test_functions.no_op_fail.remote()
    time.sleep(0.2)
    task_info = ray.task_info()
    self.assertEqual(len(task_info["failed_tasks"]), 1)
    self.assertEqual(len(task_info["running_tasks"]), 0)
    self.assertTrue("The @remote decorator for function test_functions.no_op_fail has 0 return values, but test_functions.no_op_fail returned more than 0 values." in task_info["failed_tasks"][0].get("error_message"))

    ray.worker.cleanup()

  def testTypeChecking(self):
    reload(test_functions)
    ray.init(start_ray_local=True, num_workers=1, driver_mode=ray.SILENT_MODE)

    # Make sure that these functions throw exceptions because there return
    # values do not type check.
    test_functions.test_return1.remote()
    test_functions.test_return2.remote()
    time.sleep(0.2)
    task_info = ray.task_info()
    self.assertEqual(len(task_info["failed_tasks"]), 2)
    self.assertEqual(len(task_info["running_tasks"]), 0)

    ray.worker.cleanup()

  def testDefiningRemoteFunctions(self):
    ray.init(start_ray_local=True, num_workers=2)

    # Test that we can define a remote function in the shell.
    @ray.remote([int], [int])
    def f(x):
      return x + 1
    self.assertEqual(ray.get(f.remote(0)), 1)

    # Test that we can redefine the remote function.
    @ray.remote([int], [int])
    def f(x):
      return x + 10
    self.assertEqual(ray.get(f.remote(0)), 10)

    # Test that we can close over plain old data.
    data = [np.zeros([3, 5]), (1, 2, "a"), [0.0, 1.0, 2L], 2L, {"a": np.zeros(3)}]
    @ray.remote([], [list])
    def g():
      return data
    ray.get(g.remote())

    # Test that we can close over modules.
    @ray.remote([], [np.ndarray])
    def h():
      return np.zeros([3, 5])
    assert_equal(ray.get(h.remote()), np.zeros([3, 5]))
    @ray.remote([], [float])
    def j():
      return time.time()
    ray.get(j.remote())

    # Test that we can define remote functions that call other remote functions.
    @ray.remote([int], [int])
    def k(x):
      return x + 1
    @ray.remote([int], [int])
    def l(x):
      return k.remote(x)
    @ray.remote([int], [int])
    def m(x):
      return ray.get(l.remote(x))
    self.assertEqual(ray.get(k.remote(1)), 2)
    self.assertEqual(ray.get(l.remote(1)), 2)
    self.assertEqual(ray.get(m.remote(1)), 2)

    ray.worker.cleanup()

  def testCachingReusables(self):
    # Test that we can define reusable variables before the driver is connected.
    def foo_initializer():
      return 1
    def bar_initializer():
      return []
    def bar_reinitializer(bar):
      return []
    ray.reusables.foo = ray.Reusable(foo_initializer)
    ray.reusables.bar = ray.Reusable(bar_initializer, bar_reinitializer)

    @ray.remote([], [int])
    def use_foo():
      return ray.reusables.foo
    @ray.remote([], [list])
    def use_bar():
      ray.reusables.bar.append(1)
      return ray.reusables.bar

    ray.init(start_ray_local=True, num_workers=2)

    self.assertEqual(ray.get(use_foo.remote()), 1)
    self.assertEqual(ray.get(use_foo.remote()), 1)
    self.assertEqual(ray.get(use_bar.remote()), [1])
    self.assertEqual(ray.get(use_bar.remote()), [1])

    ray.worker.cleanup()

class TaskStatusTest(unittest.TestCase):
  def testFailedTask(self):
    reload(test_functions)
    ray.init(start_ray_local=True, num_workers=3, driver_mode=ray.SILENT_MODE)

    test_functions.test_alias_f.remote()
    test_functions.throw_exception_fct1.remote()
    test_functions.throw_exception_fct1.remote()
    time.sleep(1)
    result = ray.task_info()
    self.assertEqual(len(result["failed_tasks"]), 2)
    task_ids = set()
    for task in result["failed_tasks"]:
      self.assertTrue(task.has_key("worker_address"))
      self.assertTrue(task.has_key("operationid"))
      self.assertTrue("Test function 1 intentionally failed." in task.get("error_message"))
      self.assertTrue(task["operationid"] not in task_ids)
      task_ids.add(task["operationid"])

    x = test_functions.throw_exception_fct2.remote()
    try:
      ray.get(x)
    except Exception as e:
      self.assertTrue("Test function 2 intentionally failed."in str(e))
    else:
      self.assertTrue(False) # ray.get should throw an exception

    x, y, z = test_functions.throw_exception_fct3.remote(1.0)
    for ref in [x, y, z]:
      try:
        ray.get(ref)
      except Exception as e:
        self.assertTrue("Test function 3 intentionally failed."in str(e))
      else:
        self.assertTrue(False) # ray.get should throw an exception

    ray.worker.cleanup()

  def testFailImportingRemoteFunction(self):
    ray.init(start_ray_local=True, num_workers=2, driver_mode=ray.SILENT_MODE)

    # This example is somewhat contrived. It should be successfully pickled, and
    # then it should throw an exception when it is unpickled. This may depend a
    # bit on the specifics of our pickler.
    def reducer(*args):
      raise Exception("There is a problem here.")
    class Foo(object):
      def __init__(self):
        self.__name__ = "Foo_object"
        self.func_doc = ""
        self.__globals__ = {}
      def __reduce__(self):
        return reducer, ()
      def __call__(self):
        return
    ray.remote([], [])(Foo())
    time.sleep(0.1)
    self.assertTrue("There is a problem here." in ray.task_info()["failed_remote_function_imports"][0]["error_message"])

    ray.worker.cleanup()

  def testFailImportingReusableVariable(self):
    ray.init(start_ray_local=True, num_workers=2, driver_mode=ray.SILENT_MODE)

    # This will throw an exception when the reusable variable is imported on the
    # workers.
    def initializer():
      if ray.worker.global_worker.mode == ray.WORKER_MODE:
        raise Exception("The initializer failed.")
      return 0
    ray.reusables.foo = ray.Reusable(initializer)
    time.sleep(0.1)
    # Check that the error message is in the task info.
    self.assertTrue("The initializer failed." in ray.task_info()["failed_reusable_variable_imports"][0]["error_message"])

    ray.worker.cleanup()

  def testFailReinitializingVariable(self):
    ray.init(start_ray_local=True, num_workers=2, driver_mode=ray.SILENT_MODE)

    def initializer():
      return 0
    def reinitializer(foo):
      raise Exception("The reinitializer failed.")
    ray.reusables.foo = ray.Reusable(initializer, reinitializer)
    @ray.remote([], [])
    def use_foo():
      ray.reusables.foo
    use_foo.remote()
    time.sleep(0.1)
    # Check that the error message is in the task info.
    self.assertTrue("The reinitializer failed." in ray.task_info()["failed_reinitialize_reusable_variables"][0]["error_message"])

    ray.worker.cleanup()

def check_get_deallocated(data):
  x = ray.put(data)
  ray.get(x)
  return x.id

def check_get_not_deallocated(data):
  x = ray.put(data)
  y = ray.get(x)
  return y, x.id

class ReferenceCountingTest(unittest.TestCase):

  def testDeallocation(self):
    reload(test_functions)
    for module in [ra.core, ra.random, ra.linalg, da.core, da.random, da.linalg]:
      reload(module)
    ray.init(start_ray_local=True, num_workers=1)

    x = test_functions.test_alias_f.remote()
    ray.get(x)
    time.sleep(0.1)
    objectid_val = x.id
    self.assertEqual(ray.scheduler_info()["reference_counts"][objectid_val], 1)

    del x
    self.assertEqual(ray.scheduler_info()["reference_counts"][objectid_val], -1) # -1 indicates deallocated

    y = test_functions.test_alias_h.remote()
    ray.get(y)
    time.sleep(0.1)
    objectid_val = y.id
    self.assertEqual(ray.scheduler_info()["reference_counts"][objectid_val:(objectid_val + 3)], [1, 0, 0])

    del y
    self.assertEqual(ray.scheduler_info()["reference_counts"][objectid_val:(objectid_val + 3)], [-1, -1, -1])

    z = da.zeros.remote([da.BLOCK_SIZE, 2 * da.BLOCK_SIZE])
    time.sleep(0.1)
    objectid_val = z.id
    self.assertEqual(ray.scheduler_info()["reference_counts"][objectid_val:(objectid_val + 3)], [1, 1, 1])

    del z
    time.sleep(0.1)
    self.assertEqual(ray.scheduler_info()["reference_counts"][objectid_val:(objectid_val + 3)], [-1, -1, -1])

    x = ra.zeros.remote([10, 10])
    y = ra.zeros.remote([10, 10])
    z = ra.dot.remote(x, y)
    objectid_val = x.id
    time.sleep(0.1)
    self.assertEqual(ray.scheduler_info()["reference_counts"][objectid_val:(objectid_val + 3)], [1, 1, 1])

    del x
    time.sleep(0.1)
    self.assertEqual(ray.scheduler_info()["reference_counts"][objectid_val:(objectid_val + 3)], [-1, 1, 1])
    del y
    time.sleep(0.1)
    self.assertEqual(ray.scheduler_info()["reference_counts"][objectid_val:(objectid_val + 3)], [-1, -1, 1])
    del z
    time.sleep(0.1)
    self.assertEqual(ray.scheduler_info()["reference_counts"][objectid_val:(objectid_val + 3)], [-1, -1, -1])

    ray.worker.cleanup()

  def testGet(self):
    ray.init(start_ray_local=True, num_workers=3)

    for val in RAY_TEST_OBJECTS + [np.zeros((2, 2)), UserDefinedType()]:
      objectid_val = check_get_deallocated(val)
      self.assertEqual(ray.scheduler_info()["reference_counts"][objectid_val], -1)

      if not isinstance(val, bool) and not isinstance(val, np.generic) and val is not None:
        x, objectid_val = check_get_not_deallocated(val)
        self.assertEqual(ray.scheduler_info()["reference_counts"][objectid_val], 1)

    # The following currently segfaults: The second "result = " closes the
    # memory segment as soon as the assignment is done (and the first result
    # goes out of scope).
    # data = np.zeros([10, 20])
    # objectid = ray.put(data)
    # result = worker.get(objectid)
    # result = worker.get(objectid)
    # assert_equal(result, data)

    ray.worker.cleanup()

  # @unittest.expectedFailure
  # def testGetFailing(self):
  #   ray.init(start_ray_local=True, num_workers=3)

  #   # This is failing, because for bool and None, we cannot track python
  #   # refcounts and therefore cannot keep the refcount up
  #   # (see 5281bd414f6b404f61e1fe25ec5f6651defee206).
  #   # The resulting behavior is still correct however because True, False and
  #   # None are returned by get "by value" and therefore can be reclaimed from
  #   # the object store safely.
  # for val in [True, False, None]:
  #    x, objectid_val = check_get_not_deallocated(val)
  #   self.assertEqual(ray.scheduler_info()["reference_counts"][objectid_val], 1)

  # ray.worker.cleanup()

class PythonModeTest(unittest.TestCase):

  def testPythonMode(self):
    reload(test_functions)
    ray.init(start_ray_local=True, driver_mode=ray.PYTHON_MODE)

    xref = test_functions.test_alias_h.remote()
    assert_equal(xref, np.ones([3, 4, 5])) # remote functions should return by value
    assert_equal(xref, ray.get(xref)) # ray.get should be the identity
    y = np.random.normal(size=[11, 12])
    assert_equal(y, ray.put(y)) # ray.put should be the identity

    # make sure objects are immutable, this example is why we need to copy
    # arguments before passing them into remote functions in python mode
    aref = test_functions.python_mode_f.remote()
    assert_equal(aref, np.array([0, 0]))
    bref = test_functions.python_mode_g.remote(aref)
    assert_equal(aref, np.array([0, 0])) # python_mode_g should not mutate aref
    assert_equal(bref, np.array([1, 0]))

    ray.worker.cleanup()

class PythonCExtensionTest(unittest.TestCase):

  def testReferenceCountNone(self):
    ray.init(start_ray_local=True, num_workers=1)

    # Make sure that we aren't accidentally messing up Python's reference counts.
    for obj in [None, True, False]:
      @ray.remote([], [int])
      def f():
        return sys.getrefcount(obj)
      first_count = ray.get(f.remote())
      second_count = ray.get(f.remote())
      self.assertEqual(first_count, second_count)

    ray.worker.cleanup()

class ReusablesTest(unittest.TestCase):

  def testReusables(self):
    ray.init(start_ray_local=True, num_workers=1)

    # Test that we can add a variable to the key-value store.

    def foo_initializer():
      return 1
    def foo_reinitializer(foo):
      return foo

    ray.reusables.foo = ray.Reusable(foo_initializer, foo_reinitializer)
    self.assertEqual(ray.reusables.foo, 1)

    @ray.remote([], [int])
    def use_foo():
      return ray.reusables.foo
    self.assertEqual(ray.get(use_foo.remote()), 1)
    self.assertEqual(ray.get(use_foo.remote()), 1)
    self.assertEqual(ray.get(use_foo.remote()), 1)

    # Test that we can add a variable to the key-value store, mutate it, and reset it.

    def bar_initializer():
      return [1, 2, 3]

    ray.reusables.bar = ray.Reusable(bar_initializer)

    @ray.remote([], [list])
    def use_bar():
      ray.reusables.bar.append(4)
      return ray.reusables.bar
    self.assertEqual(ray.get(use_bar.remote()), [1, 2, 3, 4])
    self.assertEqual(ray.get(use_bar.remote()), [1, 2, 3, 4])
    self.assertEqual(ray.get(use_bar.remote()), [1, 2, 3, 4])

    # Test that we can use the reinitializer.

    def baz_initializer():
      return np.zeros([4])
    def baz_reinitializer(baz):
      for i in range(len(baz)):
        baz[i] = 0
      return baz

    ray.reusables.baz = ray.Reusable(baz_initializer, baz_reinitializer)

    @ray.remote([int], [np.ndarray])
    def use_baz(i):
      baz = ray.reusables.baz
      baz[i] = 1
      return baz
    assert_equal(ray.get(use_baz.remote(0)), np.array([1, 0, 0, 0]))
    assert_equal(ray.get(use_baz.remote(1)), np.array([0, 1, 0, 0]))
    assert_equal(ray.get(use_baz.remote(2)), np.array([0, 0, 1, 0]))
    assert_equal(ray.get(use_baz.remote(3)), np.array([0, 0, 0, 1]))

    # Make sure the reinitializer is actually getting called. Note that this is
    # not the correct usage of a reinitializer because it does not reset qux to
    # its original state. This is just for testing.

    def qux_initializer():
      return 0
    def qux_reinitializer(x):
      return x + 1

    ray.reusables.qux = ray.Reusable(qux_initializer, qux_reinitializer)

    @ray.remote([], [int])
    def use_qux():
      return ray.reusables.qux
    self.assertEqual(ray.get(use_qux.remote()), 0)
    self.assertEqual(ray.get(use_qux.remote()), 1)
    self.assertEqual(ray.get(use_qux.remote()), 2)

    ray.worker.cleanup()

class ClusterAttachingTest(unittest.TestCase):

  def testAttachingToCluster(self):
    node_ip_address = "127.0.0.1"
    scheduler_port = np.random.randint(40000, 50000)
    scheduler_address = "{}:{}".format(node_ip_address, scheduler_port)
    ray.services.start_scheduler(scheduler_address, cleanup=True)
    ray.services.start_node(scheduler_address, node_ip_address, num_workers=1, cleanup=True)

    ray.init(node_ip_address=node_ip_address, scheduler_address=scheduler_address)

    @ray.remote([int], [int])
    def f(x):
      return x + 1
    self.assertEqual(ray.get(f.remote(0)), 1)

    ray.worker.cleanup()

  def testAttachingToClusterWithMultipleObjectStores(self):
    node_ip_address = "127.0.0.1"
    scheduler_port = np.random.randint(40000, 50000)
    scheduler_address = "{}:{}".format(node_ip_address, scheduler_port)
    ray.services.start_scheduler(scheduler_address, cleanup=True)
    ray.services.start_node(scheduler_address, node_ip_address, num_workers=5, cleanup=True)
    ray.services.start_node(scheduler_address, node_ip_address, num_workers=5, cleanup=True)
    ray.services.start_node(scheduler_address, node_ip_address, num_workers=5, cleanup=True)

    ray.init(node_ip_address=node_ip_address, scheduler_address=scheduler_address)

    @ray.remote([int], [int])
    def f(x):
      return x + 1
    self.assertEqual(ray.get(f.remote(0)), 1)

    ray.worker.cleanup()

if __name__ == "__main__":
    unittest.main()
