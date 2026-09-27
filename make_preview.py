"""Create an offline clickable preview. No provider keys are included."""
import argparse
import json
from pathlib import Path

from runner import Application, mechanical_demo


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", default="run-data")
    parser.add_argument("--output", default="THESIS-Preview.html")
    args = parser.parse_args()
    snapshot = Application(args.data).snapshot()
    snapshot["events"] = snapshot["events"][:4]
    snapshot["running"], snapshot["busy"] = False, False
    snapshot["status"] = "Saved observation snapshot; this preview does not run an AI model"
    boot = {"snapshot": snapshot, "demo": mechanical_demo()}
    source = Path(__file__).with_name("interface.html").read_text()
    data = json.dumps(boot, ensure_ascii=False, allow_nan=False).replace("<", "\\u003c")
    output = source.replace("__THESIS_CSRF__", "preview").replace("/*BOOT*/null", data)
    Path(args.output).write_text(output)
    print("Created offline preview:", args.output)


if __name__ == "__main__":
    main()
