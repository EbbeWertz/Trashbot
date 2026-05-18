import numpy as np

data = dict(np.load("stereo_params_v1.npz"))
# Multiply the Translation vector by your scale correction
data['T'] = data['T'] * 0.9466 
np.savez("stereo_params_v2.npz", **data)
print("Baseline corrected. Try the validation script again with this file.")