#!/usr/bin/env python3

"""Run the signed DFCI Refresh From Network flow on QemuQ35."""

import argparse
import configparser
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request


TEST_ROOT = Path(__file__).resolve().parent
CERTS_DIR = TEST_ROOT / "Certs"
SERVER_DIR = TEST_ROOT / "RefreshServer"
SERVER_SRC_DIR = SERVER_DIR / "Src"
BUILD_RESPONSES_DIR = SERVER_DIR / "BuildResponses"
ENROLL_DIR = TEST_ROOT / "TestCases" / "DFCI_InTuneEnroll"
STARTUP_NSH = SERVER_DIR / "QemuRecoveryStartup.nsh"

PACKET_FILES = (
    "OwnerEnroll_Provision_apply.bin",
    "OwnerPermissions_Permission_apply.bin",
    "OwnerSettings_Settings_apply.bin",
    "UserEnroll_Provision_apply.bin",
    "UserPermissions_Permission_apply.bin",
    "UserSettings_Settings_apply.bin",
)
WINDOWS_PATH_PREFIX = None


def run(command, *, cwd=None, env=None, check=True):
    print("+", subprocess.list2cmdline([str(item) for item in command]))
    return subprocess.run(command, cwd=cwd, env=env, check=check)


def windows_path(path):
    result = subprocess.run(
        ["wslpath", "-w", str(path.resolve())],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def run_windows(command, cwd):
    temp_result = subprocess.run(
        ["cmd.exe", "/d", "/c", "echo", "%TEMP%"],
        check=True,
        capture_output=True,
        text=True,
    )
    temp_dir_result = subprocess.run(
        ["wslpath", "-u", temp_result.stdout.strip()],
        check=True,
        capture_output=True,
        text=True,
    )
    temp_dir = Path(temp_dir_result.stdout.strip())
    path_command = ""
    if WINDOWS_PATH_PREFIX is not None:
        path_command = f'set "PATH={WINDOWS_PATH_PREFIX};%PATH%"\n'
    script = (
        "@echo off\n"
        f'pushd "{windows_path(cwd)}" || exit /b 1\n'
        f"{path_command}"
        f"{command}\n"
        "set command_status=%ERRORLEVEL%\n"
        "popd\n"
        "exit /b %command_status%\n"
    )
    script_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".cmd",
            dir=temp_dir,
            delete=False,
            newline="\r\n",
        ) as script_file:
            script_file.write(script)
            script_path = Path(script_file.name)
        run(["cmd.exe", "/d", "/c", windows_path(script_path)])
    finally:
        if script_path is not None:
            script_path.unlink(missing_ok=True)


def write_test_config(host_name):
    config = configparser.ConfigParser()
    config["DfciConfig"] = {"version": "1"}
    config["DfciTest"] = {"server_host_name": host_name}
    config_path = TEST_ROOT / "DfciTests.ini"
    with config_path.open("w", newline="\n") as config_file:
        config.write(config_file)
    return config_path


def ensure_clean_generated_state():
    generated_paths = [
        TEST_ROOT / "DfciTests.ini",
        ENROLL_DIR / "DfciSettingsQemu.xml",
        ENROLL_DIR / "DfciSettingsQemuPattern.xml",
        SERVER_SRC_DIR / "Requests",
        SERVER_SRC_DIR / "Responses",
    ]
    generated_paths.extend(CERTS_DIR.glob("DFCI_HTTPS*"))
    generated_paths.extend(ENROLL_DIR / packet_name for packet_name in PACKET_FILES)
    conflicts = [path for path in generated_paths if path.exists()]
    if conflicts:
        formatted = "\n".join(f"  {path}" for path in conflicts)
        raise RuntimeError(
            "Generated test paths already exist. Move or remove them before running:\n"
            f"{formatted}"
        )


def generate_https_certificates():
    run_windows("python.exe MakeHTTPSCert.py -v", CERTS_DIR)


def locate_windows_openssl():
    openssl = shutil.which("openssl.exe")
    if openssl is not None:
        return Path(openssl)

    candidates = (
        Path("/mnt/c/Program Files/Git/usr/bin/openssl.exe"),
        Path("/mnt/c/Program Files/Git/mingw64/bin/openssl.exe"),
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate

    raise RuntimeError(
        "Windows openssl.exe was not found on PATH or in the standard Git for "
        "Windows installation"
    )


def generate_server_responses():
    (SERVER_SRC_DIR / "Requests").mkdir(parents=True, exist_ok=True)
    (SERVER_SRC_DIR / "Responses").mkdir(parents=True, exist_ok=True)
    run_windows("call GenResponses.bat", BUILD_RESPONSES_DIR)


def generate_enrollment_packets(host_name, http_port, https_port):
    pattern_path = ENROLL_DIR / "DfciSettingsPattern.xml"
    qemu_pattern_path = ENROLL_DIR / "DfciSettingsQemuPattern.xml"
    qemu_settings_path = ENROLL_DIR / "DfciSettingsQemu.xml"

    pattern = pattern_path.read_text()
    pattern = pattern.replace(
        "http://host.docker.internal.com",
        f"http://{host_name}:{http_port}",
    )
    pattern = pattern.replace(
        "https://host.docker.internal.com",
        f"https://{host_name}:{https_port}",
    )
    qemu_pattern_path.write_text(pattern)

    run_windows(
        "python.exe ..\\..\\Support\\Python\\InsertCertIntoXML.py "
        "--BinFilePath ..\\..\\Certs\\DFCI_HTTPS.cer "
        "--OutputFilePath DfciSettingsQemu.xml "
        "--PatternFilePath DfciSettingsQemuPattern.xml",
        ENROLL_DIR,
    )

    commands = (
        "python.exe ..\\..\\Support\\Python\\GenerateCertProvisionData.py "
        "--CertFilePath ..\\..\\Certs\\DDS_CA.cer "
        "--Step2AEnable --Signing2APfxFile ..\\..\\Certs\\DDS_Leaf.pfx "
        "--Step2BEnable --Step2Enable --SigningPfxFile ..\\..\\Certs\\ZTD_Leaf.pfx "
        "--Step3Enable --FinalizeResultFile OwnerEnroll_Provision_apply.bin "
        '--Step1Enable --Identity 1 --HdrVersion 2 --SMBIOSMfg "" --SMBIOSProd "" --SMBIOSSerial ""',
        "python.exe ..\\..\\Support\\Python\\GeneratePermissionPacketData.py "
        "--Step2Enable --SigningPfxFile ..\\..\\Certs\\DDS_Leaf.pfx "
        "--Step3Enable --FinalizeResultFile OwnerPermissions_Permission_apply.bin "
        "--Step1Enable --XmlFilePath DfciPermission.xml --HdrVersion 2 "
        '--SMBIOSMfg "" --SMBIOSProd "" --SMBIOSSerial ""',
        "python.exe ..\\..\\Support\\Python\\GenerateSettingsPacketData.py "
        "--Step2Enable --SigningPfxFile ..\\..\\Certs\\DDS_Leaf.pfx "
        "--Step3Enable --FinalizeResultFile OwnerSettings_Settings_apply.bin "
        "--Step1Enable --XmlFilePath DfciSettingsQemu.xml --HdrVersion 2 "
        '--SMBIOSMfg "" --SMBIOSProd "" --SMBIOSSerial ""',
        "python.exe ..\\..\\Support\\Python\\GenerateCertProvisionData.py "
        "--CertFilePath ..\\..\\Certs\\MDM_CA.cer "
        "--Step2AEnable --Signing2APfxFile ..\\..\\Certs\\MDM_Leaf.pfx "
        "--Step2BEnable --Step2Enable --SigningPfxFile ..\\..\\Certs\\DDS_Leaf.pfx "
        "--Step3Enable --FinalizeResultFile UserEnroll_Provision_apply.bin "
        '--Step1Enable --Identity 2 --HdrVersion 2 --SMBIOSMfg "" --SMBIOSProd "" --SMBIOSSerial ""',
        "python.exe ..\\..\\Support\\Python\\GeneratePermissionPacketData.py "
        "--Step2Enable --SigningPfxFile ..\\..\\Certs\\MDM_Leaf.pfx "
        "--Step3Enable --FinalizeResultFile UserPermissions_Permission_apply.bin "
        "--Step1Enable --XmlFilePath DfciPermission2.xml --HdrVersion 2 "
        '--SMBIOSMfg "" --SMBIOSProd "" --SMBIOSSerial ""',
        "python.exe ..\\..\\Support\\Python\\GenerateSettingsPacketData.py "
        "--Step2Enable --SigningPfxFile ..\\..\\Certs\\MDM_Leaf.pfx "
        "--Step3Enable --FinalizeResultFile UserSettings_Settings_apply.bin "
        "--Step1Enable --XmlFilePath DfciSettings2.xml --HdrVersion 2 "
        '--SMBIOSMfg "" --SMBIOSProd "" --SMBIOSSerial ""',
    )

    for command in commands:
        run_windows(command, ENROLL_DIR)


def write_onecrypto_override(platform_root, onecrypto_zip):
    override_path = (
        platform_root
        / "Platforms"
        / "QemuQ35Pkg"
        / "OneCrypto-Accelerated_override_ext_dep.json"
    )
    previous_contents = override_path.read_bytes() if override_path.exists() else None
    sha256 = hashlib.sha256(onecrypto_zip.read_bytes()).hexdigest()
    manifest = {
        "scope": "global",
        "type": "web",
        "id": "onecrypto-bin-local-override",
        "name": "onecrypto-bin-local-override",
        "override_id": "onecrypto-bin",
        "source": onecrypto_zip.resolve().as_uri(),
        "version": f"1.0.0-dfci-recovery-{sha256[:12]}",
        "sha256": sha256,
        "compression_type": "zip",
        "internal_path": "/",
        "flags": ["set_build_var"],
        "var_name": "BLD_*_ONE_CRYPTO_PATH",
    }
    override_path.write_text(json.dumps(manifest, indent=2) + "\n")
    return override_path, previous_contents


def restore_onecrypto_override(override_path, previous_contents):
    if previous_contents is None:
        override_path.unlink(missing_ok=True)
    else:
        override_path.write_bytes(previous_contents)


def start_server(config_path, http_port, https_port):
    server_env = os.environ.copy()
    server_env.update(
        {
            "DFCI_REFRESH_DATA_DIR": str(SERVER_SRC_DIR),
            "DFCI_TEST_CONFIG": str(config_path),
            "DFCI_SSL_DIR": str(CERTS_DIR),
            "DFCI_HTTP_PORT": str(http_port),
            "DFCI_HTTPS_PORT": str(https_port),
        }
    )
    process = subprocess.Popen(
        [sys.executable, "server.py"],
        cwd=SERVER_SRC_DIR,
        env=server_env,
    )

    for _ in range(30):
        if process.poll() is not None:
            raise RuntimeError(f"Refresh Server exited with code {process.returncode}")
        try:
            with urllib.request.urlopen(
                f"http://127.0.0.1:{http_port}/",
                timeout=1,
            ) as response:
                if response.status == 200:
                    return process
        except OSError:
            time.sleep(1)

    process.terminate()
    process.wait(timeout=10)
    raise RuntimeError("Refresh Server did not become ready")


def build_and_run(platform_root, stuart_venv):
    platform_build = "Platforms/QemuQ35Pkg/PlatformBuild.py"
    common_args = [
        "TARGET=DEBUG",
        "TOOL_CHAIN_TAG=GCC",
        "BLD_*_DFCI_NETWORK_RECOVERY_TEST=TRUE",
        "BLD_*_GUI_FRONT_PAGE=TRUE",
        "BLD_*_QEMU_CORE_NUM=2",
    ]
    stuart_update = stuart_venv / "bin" / "stuart_update"
    stuart_build = stuart_venv / "bin" / "stuart_build"

    run([stuart_update, "-c", platform_build], cwd=platform_root)
    run([stuart_build, "-c", platform_build, *common_args], cwd=platform_root)

    output_dir = platform_root / "Build" / "QemuQ35PkgX64" / "DEBUG_GCC" / "X64"
    for packet_name in PACKET_FILES:
        shutil.copy2(ENROLL_DIR / packet_name, output_dir / packet_name)

    run(
        [
            stuart_build,
            "-c",
            platform_build,
            *common_args,
            "ENABLE_NETWORK=TRUE",
            "BOOT_TO_FRONT_PAGE=FALSE",
            "EMPTY_DRIVE=TRUE",
            "SHUTDOWN_AFTER_RUN=TRUE",
            f"STARTUP_NSH={STARTUP_NSH}",
            "FILE_REGEX=DfciApply.efi,DfciSARecovery.efi,*_apply.bin",
            "--FlashRom",
        ],
        cwd=platform_root,
    )


def preserve_evidence(platform_root, output_dir):
    output_dir.mkdir(parents=True, exist_ok=True)
    evidence = {
        platform_root / "Build" / "BUILDLOG_QemuQ35Pkg_Run.txt": "QemuRecovery.log",
        SERVER_SRC_DIR / "Requests" / "Bootstrap_Request.json": "Bootstrap_Request.json",
        SERVER_SRC_DIR / "Requests" / "Recovery_Request.json": "Recovery_Request.json",
    }
    for source, name in evidence.items():
        if not source.exists():
            raise RuntimeError(f"Expected evidence was not produced: {source}")
        shutil.copy2(source, output_dir / name)

    log_text = (output_dir / "QemuRecovery.log").read_text(errors="replace")
    required_markers = (
        "OwnerEnabled=1, UserEnabled=1",
        "OwnerEnabled=0, UserEnabled=0",
        "PROGRESS - Success",
    )
    missing = [marker for marker in required_markers if marker not in log_text]
    if missing:
        raise RuntimeError(f"Firmware log is missing success markers: {missing}")


def cleanup_generated(config_path):
    config_path.unlink(missing_ok=True)
    for certificate in CERTS_DIR.glob("DFCI_HTTPS*"):
        certificate.unlink()
    for packet_name in PACKET_FILES:
        (ENROLL_DIR / packet_name).unlink(missing_ok=True)
    (ENROLL_DIR / "DfciSettingsQemu.xml").unlink(missing_ok=True)
    (ENROLL_DIR / "DfciSettingsQemuPattern.xml").unlink(missing_ok=True)
    shutil.rmtree(SERVER_SRC_DIR / "Requests", ignore_errors=True)
    shutil.rmtree(SERVER_SRC_DIR / "Responses", ignore_errors=True)


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--platform-root", required=True, type=Path)
    parser.add_argument(
        "--onecrypto-zip",
        type=Path,
        help="Optional local OneCrypto ZIP that overrides the platform dependency",
    )
    parser.add_argument("--stuart-venv", type=Path, default=Path("/opt/venv"))
    parser.add_argument("--host-name", default="10.0.2.2")
    parser.add_argument("--http-port", type=int, default=8080)
    parser.add_argument("--https-port", type=int, default=8443)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=TEST_ROOT / "Artifacts" / "QemuRecovery",
    )
    parser.add_argument("--keep-generated", action="store_true")
    return parser.parse_args()


def main():
    global WINDOWS_PATH_PREFIX

    args = parse_args()
    platform_root = args.platform_root.resolve()
    onecrypto_zip = args.onecrypto_zip.resolve() if args.onecrypto_zip else None
    output_dir = args.output_dir.resolve()

    if os.name == "nt":
        raise RuntimeError("Run this script from WSL, not Windows Python")
    if onecrypto_zip is not None and not onecrypto_zip.is_file():
        raise FileNotFoundError(onecrypto_zip)
    if not (platform_root / "Platforms" / "QemuQ35Pkg").is_dir():
        raise RuntimeError(f"Not a mu_tiano_platforms checkout: {platform_root}")
    for executable in ("cmd.exe", "python.exe"):
        if shutil.which(executable) is None:
            raise RuntimeError(f"Required Windows executable is not on PATH: {executable}")

    WINDOWS_PATH_PREFIX = windows_path(locate_windows_openssl().parent)
    ensure_clean_generated_state()
    config_path = write_test_config(args.host_name)
    override_path = None
    previous_override = None
    server = None
    try:
        generate_https_certificates()
        generate_server_responses()
        generate_enrollment_packets(args.host_name, args.http_port, args.https_port)
        if onecrypto_zip is not None:
            override_path, previous_override = write_onecrypto_override(
                platform_root,
                onecrypto_zip,
            )
        server = start_server(config_path, args.http_port, args.https_port)
        build_and_run(platform_root, args.stuart_venv.resolve())
        preserve_evidence(platform_root, output_dir)
        print(f"DFCI QEMU recovery test passed. Evidence: {output_dir}")
    finally:
        if server is not None:
            server.terminate()
            server.wait(timeout=10)
        if override_path is not None:
            restore_onecrypto_override(override_path, previous_override)
            run(
                [
                    args.stuart_venv.resolve() / "bin" / "stuart_update",
                    "-c",
                    "Platforms/QemuQ35Pkg/PlatformBuild.py",
                ],
                cwd=platform_root,
                check=False,
            )
        if not args.keep_generated:
            cleanup_generated(config_path)


if __name__ == "__main__":
    main()
