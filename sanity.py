import json, glob, os
from shapely.geometry import Polygon
from shapely.validation import make_valid, explain_validity

for f in sorted(glob.glob('examples/*.json')):
    d = json.load(open(f, encoding='utf-8'))
    pts = [tuple(p) for p in d['boundary']]
    closed = pts[0] == pts[-1]
    raw = Polygon(pts)
    fixed = make_valid(raw)
    print(f"{os.path.basename(f)}: n={len(pts)} closed={closed} "
          f"valid={raw.is_valid} area={fixed.area/1e6:.3f}m2 type={fixed.geom_type}")
    if not raw.is_valid:
        print(f"    -> {explain_validity(raw)}")
