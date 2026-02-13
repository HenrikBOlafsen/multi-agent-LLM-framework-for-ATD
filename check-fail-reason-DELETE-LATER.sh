python - <<'PY'
import xml.etree.ElementTree as ET
from collections import Counter

path = "results/omegaconf/master/code_quality_checks/pytest.xml"  # adjust if needed
root = ET.parse(path).getroot()

c = Counter()
for tc in root.iter("testcase"):
    sk = tc.find("skipped")
    if sk is not None:
        msg = (sk.get("message") or "").strip()
        text = (sk.text or "").strip()
        key = msg or text or "skipped"
        c[key[:160]] += 1

for k,v in c.most_common(50):
    print(f"{v:4d}  {k}")
PY
