from pathlib import Path
import pyroorb
import warnings

# PyRoOrbのプロジェクトディレクトリ
BASE_DIR = Path(__file__).resolve().parent.parent

# MPC80観測ファイル
input_file = BASE_DIR / "data" / "input" / "test_observations.txt"

# 観測読み込み
obs = pyroorb.read_observations(input_file)

print(f"読み込んだ観測数: {len(obs)}")

# クラスター全体を1天体として軌道決定
designation = "TEST_CLUSTER_001"

with warnings.catch_warnings(record=True) as caught:
    warnings.simplefilter("always")

    fit = pyroorb.fit_orbit(
        obs,
        designation=designation,
        mpc_seed=False,
        nongrav="none"
    )

# 結果表示
print("\n--- 軌道決定結果 ---")
print(f"Designation: {designation}")
print(f"Determined: {fit.is_determined}")
print(f"Determinacy: {fit.determinacy()}")

print("\n--- 警告 ---")
for warning in caught:
    print(warning.message)

print("\n--- 軌道要素 ---")
print(fit.elements())

print("\n--- RMS残差 ---")
print(fit.rms_residual(), "arcsec")

print("\n--- 観測の採用状況 ---")
print(f"入力観測数: {len(obs)}")
print(f"軌道決定に使用された観測数: {fit.n_observations()}")
print(f"除外された観測数: {fit.n_excluded()}")

print("\n--- 軌道要素の1σ誤差 ---")
print(fit.element_sigmas())

print("\n--- MPC Uパラメータ ---")
print(fit.uncertainty_parameter())

print("\n--- モンテカルロ不確実性 ---")
mc = fit.monte_carlo_uncertainty(n=1000)
print(mc)

print("\n--- Statistical Ranging ---")
sr = fit.sr_uncertainty(max_orbits=100)
print(sr)