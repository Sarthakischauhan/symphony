"""Surface pytest diagnostics in check annotations as well as runner logs."""
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

report = Path(sys.argv[1])
if report.exists():
    for case in ET.parse(report).iter("testcase"):
        for failure in list(case.findall("failure")) + list(case.findall("error")):
            message = (failure.text or failure.get("message", ""))[:16000]
            escaped = message.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
            print(f"::error title={case.get('name', 'Test failed')}::{escaped}")
