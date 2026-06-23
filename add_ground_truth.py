import os
import pandas as pd

root_dir = "/path/to/your/results"  # 改成你的实际路径

for folder in os.listdir(root_dir):
    folder_path = os.path.join(root_dir, folder)
    csv_path = os.path.join(folder_path, "rrc_decomposition_summary.csv")
    
    if not os.path.isfile(csv_path):
        continue
    
    df = pd.read_csv(csv_path)
    
    residual_abs_sum = df["residual_abs"].sum()
    trend_residual_sum = df["trend_residual"].sum()
    
    new_name = f"rrc_decomposition_summary_residual{residual_abs_sum:.1f}_trend{trend_residual_sum:.1f}.csv"
    new_path = os.path.join(folder_path, new_name)
    
    os.rename(csv_path, new_path)
    print(f"{folder}: {new_name}")
