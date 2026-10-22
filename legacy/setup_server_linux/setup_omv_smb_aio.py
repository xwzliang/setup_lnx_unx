#!/usr/bin/env python3
"""Prevent excessive Samba write-buffer memory use on an OMV SMB share.

QUICK START FROM YOUR LINUX CLIENT
    Show this help locally; no SSH, sudo, or OMV installation is needed:
        python3 /home/broliang/git/setup_lnx_unx/setup_server_linux/setup_omv_smb_aio.py --help

    Change to the repository for the shorter commands below:
        cd /home/broliang/git/setup_lnx_unx

    1. Preview the change on OMV (read-only; no backups or restarts):
        ssh omv 'sudo -n python3 - --share omv --dry-run' < setup_server_linux/setup_omv_smb_aio.py

    2. When SMB transfers are idle, apply the change:
        ssh omv 'sudo -n python3 - --share omv' < setup_server_linux/setup_omv_smb_aio.py

    These commands read the script from your client and execute it ON OMV.
    The dash after python3 means "read Python source from standard input".
    The script does not need to be installed or saved on the server.
    No confirmation prompt is shown when applying; deployment may restart SMB.

CHOOSING THE SERVER AND SHARE
    In "ssh omv", omv is your SSH host alias, not the share selector.
    Replace that SSH target with user@server-ip for a different server.
    In "--share omv", omv is the exact OMV shared-folder name used by SMB,
    not /mnt/omv, a server filesystem path, or a share UUID.
    The script selects one existing enabled SMB share; it does not create one.

    Example: configure the media share on the same server:
        ssh omv 'sudo -n python3 - --share media --dry-run' < setup_server_linux/setup_omv_smb_aio.py
        ssh omv 'sudo -n python3 - --share media' < setup_server_linux/setup_omv_smb_aio.py

    If --share is omitted, it defaults to omv. Names are case-sensitive.
    Quote names containing spaces, e.g. --share "Family Media" when running
    directly on OMV. Use the upload-and-run method below for simpler quoting.

IF SUDO REQUIRES A PASSWORD
    The streamed commands use sudo -n, which fails instead of prompting.
    Do not remove -n and try to share standard input with a password prompt.
    Instead upload the script, then log in interactively:
        scp setup_server_linux/setup_omv_smb_aio.py omv:~/setup_omv_smb_aio.py
        ssh -t omv

    In that OMV shell, run (sudo can now prompt for your password):
        sudo python3 ~/setup_omv_smb_aio.py --share omv --dry-run
        sudo python3 ~/setup_omv_smb_aio.py --share omv

RUNNING DIRECTLY ON OMV
    If the script is already on the server:
        sudo python3 /path/to/setup_omv_smb_aio.py --share omv --dry-run
        sudo python3 /path/to/setup_omv_smb_aio.py --share omv

    Requires Python 3, root privileges, and OMV's existing omv-confdbadm,
    omv-salt, testparm, and systemctl commands. No pip packages are required.
    Inspected and tested on OMV 7; compatibility with other versions is not
    guaranteed. Both dry-run and apply inspect root-owned OMV configuration.

VERIFYING THE RESULT
    From your client, query the generated share setting (expected output: 0):
        ssh omv 'sudo -n testparm -s --section-name=omv --parameter-name="aio write size"'
    Check that Samba is running (expected output: active):
        ssh omv 'systemctl is-active smbd'
    In OMV's web UI, the option should appear in the omv SMB share's
    Extra options field. Existing client mounts may reconnect after deployment.

    Successful apply prints "Verified: [omv] aio write size = 0".
    Repeating the script prints "Already configured persistently" and skips
    deployment when the saved and generated settings already match.
    This script verifies configuration and service health; it does not run
    a large-file copy benchmark automatically.

Problem observed on OMV 7 / Debian 12 / Samba 4.17.12:
    Copying a single ~60 GiB file via Linux CIFS caused an smbd worker to
    consume ~14.6 GiB RAM plus swap in a 16 GiB VM. Historical logs confirmed
    an smbd OOM kill. Both mergerfs and direct-ext4 SMB paths showed growth;
    multiple smaller files did not reproduce the same exhaustion.

Solution tested:
    Set "aio write size = 0" for the share to disable Samba asynchronous
    writes. This addresses the observed accumulation of pending write data;
    it is not a general cure for every OOM or a disk-durability setting.
    On the main mergerfs-backed share, the same 59.95 GiB cp completed at
    135.7 MiB/s including final fsync, with peak smbd RSS of 31.3 MiB.
    File size and beginning/middle/end samples matched (not a full hash).

Persistence and operational effects:
    Update OMV's configuration database, not just generated smb.conf.
    Preserve all other share properties and unrelated extra options.
    Back up config.xml, smb.conf and the original share JSON under /root.
    Deploy using omv-salt; this CAN RESTART SMB and disconnect clients.
    Run when transfers are idle. No shared data files are modified/deleted.
    Repeated runs do nothing when both saved and generated settings agree.
    Deployment errors leave backups and report failure; no automatic rollback
    overwrites potentially concurrent OMV changes. Avoid concurrent UI edits.

BACKUPS AND ROLLBACK
    Before any change, the script prints a unique server-side directory:
        /root/omv-smb-aio-YYYYMMDDTHHMMSS-<unique-suffix>
    It contains config.xml, smb.conf, and share.json. The directory is private
    to root. Backups are not created for dry runs or already-configured runs.

    To restore the selected share, log in to OMV and open a root shell:
        ssh -t omv
        sudo -i
    Substitute the actual printed backup path in this command:
        omv-confdbadm update conf.service.smb.share - < /root/omv-smb-aio-YYYYMMDDTHHMMSS-XXXX/share.json
        omv-salt deploy run samba
        exit

    The root shell is needed because shell input redirection must be able to
    read the root-only backup. Rollback restores the WHOLE saved share object,
    including any old extra options; review later share changes first.
    Deployment may restart SMB again. Restoring just smb.conf is not persistent
    because OMV regenerates it from its database. Full config.xml is retained
    for recovery, but normally use the narrower share.json rollback above.

TROUBLESHOOTING AND EXIT STATUS
    "sudo: a password is required": use the upload-and-run method above.
    "Could not resolve hostname": check your SSH alias or use user@server-ip.
    "Missing omv-confdbadm": you likely ran on the client; execute on OMV.
    "Expected exactly one SMB share": check the shared-folder name and that
    it is exported via SMB. Inspect on OMV with:
        sudo omv-confdbadm read --prettify conf.system.sharedfolder
        sudo omv-confdbadm read --prettify conf.service.smb.share
    "selected SMB share is disabled": enable the intended share in OMV first.
    "Share changed during inspection": finish other OMV edits and retry.
    Deployment/verification failure: keep the printed backup and inspect:
        sudo testparm -s
        sudo systemctl status smbd --no-pager
        sudo journalctl -u smbd -n 50 --no-pager
    The database may already contain the new option if deployment fails.
    After resolving the error, rerun this script to deploy, or use rollback.
    No automatic rollback is performed. No data files are removed.

    Exit 0: successful apply, already configured, dry-run, or --help.
    Exit 1: configuration, deployment, verification, or operating-system error.
    Exit 2: invalid arguments, missing tools, or insufficient privileges.
    SSH may report its own failure status (commonly 255) before Python runs.

References:
    https://lists.samba.org/archive/samba/2021-September/237297.html
    https://docs.openmediavault.org/en/7.x/administration/services/samba.html
"""

import argparse
import datetime
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile


MODEL = "conf.service.smb.share"
OPTION = "aio write size = 0"
OPTION_LINE = re.compile(r"^\s*aio\s+write\s+size\s*=", re.IGNORECASE)


def run(*args, **kwargs):
    return subprocess.run(args, check=True, text=True, **kwargs)


def read_model(model):
    return json.loads(run("omv-confdbadm", "read", model,
                          stdout=subprocess.PIPE).stdout)


def effective_value(share_name):
    return run("testparm", "-s", "--section-name=" + share_name,
               "--parameter-name=aio write size",
               stdout=subprocess.PIPE, stderr=subprocess.PIPE).stdout.strip()


def updated_options(options):
    lines = [line for line in options.splitlines() if not OPTION_LINE.match(line)]
    lines.append(OPTION)
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--share", default="omv", help="OMV shared-folder name (default: omv)")
    parser.add_argument("--dry-run", action="store_true", help="inspect and preview only")
    args = parser.parse_args()
    if os.geteuid() != 0:
        parser.error("Run as root on the OMV server (use sudo).")
    for command in ("omv-confdbadm", "omv-salt", "testparm", "systemctl"):
        if shutil.which(command) is None:
            parser.error(f"Missing {command}; run this script on OMV, not the SMB client.")

    folders = read_model("conf.system.sharedfolder")
    refs = {folder["uuid"] for folder in folders if folder["name"] == args.share}
    matches = [share for share in read_model(MODEL) if share["sharedfolderref"] in refs]
    if len(matches) != 1:
        raise RuntimeError(f"Expected exactly one SMB share for {args.share!r}; found {len(matches)}.")
    original = matches[0]
    if not original.get("enable"):
        raise RuntimeError("The selected SMB share is disabled; refusing to change it.")
    updated = dict(original)
    updated["extraoptions"] = updated_options(original.get("extraoptions", ""))
    current = effective_value(args.share)
    print(f"Share: {args.share}; UUID: {original['uuid']}; generated aio write size: {current}")
    if original == updated and current == "0":
        print("Already configured persistently. No deployment or restart needed.")
        return
    if args.dry_run:
        print("Would back up configuration, save the following extra options, and deploy Samba:")
        print(updated["extraoptions"])
        print("Deployment may restart SMB. No changes made.")
        return

    stamp = datetime.datetime.now().strftime("%Y%m%dT%H%M%S")
    backup = Path(tempfile.mkdtemp(prefix=f"omv-smb-aio-{stamp}-", dir="/root"))
    for source in ("/etc/openmediavault/config.xml", "/etc/samba/smb.conf"):
        target = backup / Path(source).name
        shutil.copy2(source, target)
        target.chmod(0o600)
    (backup / "share.json").write_text(json.dumps(original, indent=2) + "\n")
    (backup / "share.json").chmod(0o600)
    print(f"Backup: {backup}", flush=True)

    # Catch edits made since inspection, before writing our saved share object.
    latest = next((s for s in read_model(MODEL) if s["uuid"] == original["uuid"]), None)
    if latest != original:
        raise RuntimeError("Share changed during inspection; rerun after other OMV edits finish.")
    if original != updated:
        run("omv-confdbadm", "update", MODEL, "-", input=json.dumps(updated))
    saved = next((s for s in read_model(MODEL) if s["uuid"] == original["uuid"]), None)
    if saved != updated:
        raise RuntimeError(f"Saved share did not match requested configuration. Backup: {backup}")
    print("Deploying Samba; clients may briefly disconnect.", flush=True)
    run("omv-salt", "deploy", "run", "samba")
    if effective_value(args.share) != "0":
        raise RuntimeError(f"Deployed value is not 0. Inspect configuration; backup: {backup}")
    run("systemctl", "is-active", "--quiet", "smbd")
    print(f"Verified: [{args.share}] {OPTION}; smbd is active. Backup: {backup}")


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, KeyError, RuntimeError, subprocess.CalledProcessError) as error:
        print(f"ERROR: {error}\nNo automatic rollback performed; retain the printed backup.", file=sys.stderr)
        sys.exit(1)
