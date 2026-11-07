
from pathlib import Path
import pyroorb

# 入力ファイル
input_file = Path.home() / "PyRoOrb/data/input/test_observations.txt"

if not input_file.exists():
    raise FileNotFoundError(f"Input file not found: {input_file}")

print("Reading:", input_file)

# MPC 80-column observations
obs = pyroorb.read_observations(
    input_file,
    format="obs80"
)

print("\n===== Read result =====")
print("Object type:", type(obs))
print("Representation:", repr(obs))

# 観測数
try:
    print("Number of observations:", len(obs))
except TypeError:
    print("Number of observations: not directly available")

# オブジェクトの属性
print("\n===== Available attributes =====")
print(dir(obs))

# 内部データ
if hasattr(obs, "__dict__"):
    print("\n===== Internal data =====")
    for key, value in vars(obs).items():
        print(f"{key}: {value!r}")

# メタデータ
if hasattr(obs, "meta"):
    print("\n===== Metadata =====")
    print(obs.meta)

print("\nReading completed.")
