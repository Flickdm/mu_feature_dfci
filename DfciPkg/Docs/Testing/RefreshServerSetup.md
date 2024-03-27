# Refresh Server

## Description

The Refresh From Network feature is part of the Device Firmware Configuration Interface (DFCI) within the Unified Extensible Firmware Interface (UEFI).

**Purpose and Context:**

* DFCI enhances PC configuration management by allowing secure programmatic configuration of hardware settings typically adjusted through a BIOS menu.
* Refresh From Network specifically addresses the need to update or refresh configuration settings remotely.

**How It Works:**

* When a device is configured with DFCI, it can receive updated configuration settings from a central server over the network.
* This process ensures that the device adheres to the latest policies and configurations without manual intervention.

**Use Cases:**

* **Zero-Touch Configuration:** Organizations can remotely update settings without physically accessing each device.
* **Policy Enforcement:** For example, disabling cameras, microphones, or radios across a fleet of devices.
* **Kiosk and Single-Purpose Devices:** Prevent booting from USB or network (PXE) for security reasons.
* **Implementation:** In Surface devices, you can find the Refresh From Network option in the Surface UEFI settings under Management > Configure.
Choosing Opt Out for Refresh From Network ensures that the device doesn’t automatically fetch updated configurations from the network

A `Refresh From Network` server is required to run the Refresh From Network portion of the DFCI E2E tests.

## Setup

### Host System

#### Requirements

1. Windows x86-64
2. No other application may be using ports 80 or 443, as this is required for the RefreshServer.
    * If necessary, check if any other application is using ports 80 or 443.
    You can use the following command in Command Prompt to check:

   ```shell
   netstat -ano | findstr :80
   netstat -ano | findstr :443
   ```

   If any processes are listed, note down their Process ID (PID) and use Task Manager to identify the corresponding application.
3. Python x86-64 (the version tested), available here [Python 3.11.0](https://www.python.org/ftp/python/3.11.0/python-3.11.0-amd64.exe).
4. The current Windows SDK, available here [Windows SDK](https://developer.microsoft.com/en-us/windows/downloads/windows-10-sdk).
5. Install Git for Windows, available here  [Git for Windows](https://gitforwindows.org/).
    * Open the Start menu and search for "Environment Variables".
    * Click on "Edit the system environment variables".
    * In the System Properties window, click on the "Environment Variables" button.
    * Under "System variables", scroll down and find the "Path" variable.
    * Click on "Edit" and add the path to the Git installation directory (e.g., C:\Program Files\Git\bin)
        to the list of paths.
    * Click on "Edit" and add the path to the Git installation directory (e.g., C:\Program Files\Git\usr\bin)
        to the list of paths.
6. Install Windows Subsystem for Linux. Install instructions here [WSL2](https://learn.microsoft.com/en-us/windows/wsl/install).
7. Install Docker Desktop, available here [Docker Desktop](https://docs.docker.com/desktop/install/windows-install/).
    * This will require a reboot

#### Installation

1. If not performed already, clone the [mu_feature_dfci]<https://github.com/microsoft/mu_feature_dfci> repository

2. Install the required python packages by running using the pip-requirements.txt file in the DfciPkg\UnitTests\DfciTests directory:

    * It's recommended to setup and use a python virtual environment if not already done so.

        ```powershell
            python -m venv venv
            ./venv/Scripts/Activate
        ```

    Install the pip packages

   ```shell
   pip install --upgrade -r pip-requirements.txt
   ```

### Initialize the Refresh Server

> These steps assume you're on the host machine that will run the DFCI RefreshServer, if this is incorrect modify the steps to work accordingly

1. Locate the DfciTests.Template file (e.g. mu_feature_dfci\DfciPkg\UnitTests\DfciTests)
2. Copy DfciTests.Template and rename it DfciTests.ini
3. Edit DfciTests.ini and set the value of server_host_name to either a host name or an IP address of the host machine running the refresh server.
    * The server_host_name field will be used to populate the Subject Alternative Names list in the DFCI_HTTPS SSL certificates.

    Example:

    ```ini
    [DfciConfig]
    version = 1

    [DfciTest]
    server_host_name = 172.168.1.20
    ```

4. Locate `MakeHTTPSCerts.py` (e.g. mu_feature_dfci\DfciPkg\UnitTests\DfciTests\Certs)
5. Change directory to the same location as `MakeHTTPSCerts.py`
6. Execute MakeHTTPSCerts.py

    ```powershell
    python MakeHTTPSCerts.py
    ```

    This will generate two SSL certificates. One is for the RefreshServer, and the other is used by the RefreshServer testcase.

7. Locate `MakeCerts.py` (e.g. mu_feature_dfci\DfciPkg\UnitTests\DfciTests\Certs)
8. Change directory to the same location as `MakeCerts.py`
9. Execute MakeCerts.py

    ```powershell
    python MakeCerts.py
    ```

    This will generate two SSL certificates. One is for the RefreshServer, and the other is used by the RefreshServer testcase.

10. Locate `CreateDockerContainer.bat` (e.g. DfciPkg\UnitTests\DfciTests\RefreshServer)
11. Change directory to the same location as `CreateDockerContainer.bat`

12. In the same directory run `CreateDockerContainer.bat`.
    * After the container is created, the script will prompt you about starting the container.
    * It is recommended to use option 2 (Start in a command Window) initially, however other options are available.

13. At this point the RefreshServer should be Running! :fireworks:
