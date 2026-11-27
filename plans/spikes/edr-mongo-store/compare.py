import sys, numpy as np
ref = np.load(sys.argv[1]); bad = 0
for other in sys.argv[2:]:
    o = np.load(other)
    for k in ref.files:
        a, b = ref[k], o[k]
        same = a.shape == b.shape and a.dtype == b.dtype and np.array_equal(a, b, equal_nan=True)
        if not same: bad += 1
        print(f"{other:18s} {k:18s} shape {a.shape} finite {int(np.isfinite(a).sum()):7d} -> {'EQUAL' if same else 'DIFFERENT'}")
print('DIFFERENCES:', bad); sys.exit(1 if bad else 0)
