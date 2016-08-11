import pandas as pd
import ray
import ray.dataframe as df

ray.init(start_ray_local=True)
a = pd.DataFrame({"x":range(1000)})
b = df.DataFrameChunk(a)
c = ray.put(b)
d = df.chunk_getitem.remote(c, "x")
ray.get(d)
