"""One-time, explicitly selected deployment capability for the Hyclinics client."""
import argparse
import json
import os
import tempfile
from pathlib import Path
from dotenv import dotenv_values


def enable(env_file):
    values = dotenv_values(env_file)
    configured = values.get("REACHLY_GENERATION_CONFIG")
    if not configured or not Path(configured).is_absolute():
        raise ValueError("An absolute generation configuration path is required")
    path = Path(configured).resolve(strict=True)
    data = json.loads(path.read_text())
    client = data.get("clients", {}).get("hyclinics")
    if not isinstance(client, dict) or not values.get(client.get("token_env", "")):
        raise ValueError("The Hyclinics service client and credential must already be configured")
    if client.get("provider") not in data.get("providers", {}):
        raise ValueError("The Hyclinics generation provider must already be configured")
    if client.get("organisation_provisioning") is True:
        return False
    previous = path.read_bytes()
    stat = path.stat()
    # Private backup; no values are emitted to deployment logs.
    with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".before-org-onboarding-", delete=False) as backup:
        backup.write(previous)
        backup.flush()
        os.fsync(backup.fileno())
    client["organisation_provisioning"] = True
    with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, prefix=".org-onboarding-", delete=False) as output:
        temporary = Path(output.name)
        try:
            json.dump(data, output, indent=2)
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
            os.chmod(temporary, stat.st_mode & 0o777)
            if os.geteuid() == 0:
                os.chown(temporary, stat.st_uid, stat.st_gid)
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)
    return True


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", required=True)
    args = parser.parse_args()
    enable(args.env_file)
    print("Hyclinics organisation provisioning is enabled.")
