# BOINC Discord RPC

Real-time Discord Rich Presence (RPC) integration for **BOINC** distributed computing projects.
Automatically cycles through your active BOINC projects in your Discord status, displaying live task progress, elapsed computation time, total completed tasks count, animated artwork, and project links.

[![Python 3.8+](https://img.shields.io/badge/python-3.8+-blue.svg)](https://www.python.org/downloads/)
[![Discord Rich Presence](https://img.shields.io/badge/Discord-Rich%20Presence-5865F2.svg)](https://discord.com/)
[![BOINC](https://img.shields.io/badge/BOINC-Multi--Project-005086.svg)](https://boinc.berkeley.edu/)
[![Platform](https://img.shields.io/badge/platform-Windows-0078D6.svg)](https://www.microsoft.com/windows)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

## Supported Projects

| Preview | Project | Discord Status | Project URL |
| :---: | :--- | :--- | :--- |
| <img src="docs/odlk1_preview.gif?v=2" width="76" alt="latinsquares"> | **latinsquares** | `Playing latinsquares`<br>`Searching 10x10 Latin Squares` | [https://boinc.multi-pool.info/latinsquares/](https://boinc.multi-pool.info/latinsquares/) |
| <img src="docs/milkyway_preview.gif?v=2" width="76" alt="MilkyWay@home"> | **MilkyWay@home** | `Playing MilkyWay@home`<br>`N-Body Galaxy Simulation` | [https://milkyway.cs.rpi.edu/milkyway/](https://milkyway.cs.rpi.edu/milkyway/) |
| <img src="docs/wcg_preview_v2.gif" width="76" alt="World Community Grid"> | **World Community Grid** | `Playing World Community Grid`<br>`Medical & Humanitarian Research` | [https://www.worldcommunitygrid.org/](https://www.worldcommunitygrid.org/) |
| <img src="docs/asteroids_preview_v2.gif" width="76" alt="Asteroids@home"> | **Asteroids@home** | `Playing Asteroids@home`<br>`3D Asteroid Shape Modeling` | [https://asteroidsathome.net/boinc/](https://asteroidsathome.net/boinc/) |
| <img src="docs/einstein_preview.gif" width="76" alt="Einstein@Home"> | **Einstein@Home** | `Playing Einstein@Home`<br>`Pulsar & Gravity Wave Search` | [https://einstein.phys.uwm.edu/](https://einstein.phys.uwm.edu/) |
| <img src="docs/primegrid_preview_v2.gif" width="76" alt="PrimeGrid"> | **PrimeGrid** | `Playing PrimeGrid`<br>`Record Prime Number Search` | [https://www.primegrid.com/](https://www.primegrid.com/) |
| <img src="docs/rosetta_preview.gif" width="76" alt="Rosetta@home"> | **Rosetta@home** | `Playing Rosetta@home`<br>`3D Protein Folding & Design` | [https://boinc.bakerlab.org/](https://boinc.bakerlab.org/) |

## Quick start

Requirements: **Windows**, **Python 3.8+**, running tasks in BOINC, and the Discord desktop app. No extra pip packages required.

1. Download `boinc-discord.zip` from [Releases](../../releases/latest) and extract it.
2. Run `start_discord.bat`.
3. A BOINC icon appears in your Windows system tray, and your Discord profile automatically updates and cycles across your active BOINC projects.

> If BOINC is installed as a Windows service, run `start_discord.bat` as administrator so `boinccmd` CLI can query task status.

## How it works

```
boinccmd --get_tasks -------------+
                                   |
job_log_*.txt (per project) ------+--> discord_rpc.py --Named Pipe (\\.\pipe\discord-ipc-*)--> Discord Desktop
                                   |
Standalone System Tray (tray.py) -+
```

- **Zero Dependencies**: `discord_rpc.py` communicates directly with the local Discord desktop client via Windows Named Pipes (`\\.\pipe\discord-ipc-0..9`), requiring zero third-party packages (`pypresence` not needed).
- **Cyclic Project Rotation**: Polls `boinccmd --get_tasks` for active (`EXECUTING`) projects. When multiple supported projects are running simultaneously, the status automatically rotates between them every **18 seconds** while refreshing live percentage progress every **4.5 seconds**.
- **Per-Project Sticky Workunit Tracking**: For each active project, automatically targets the workunit with the lowest progress and tracks it continuously through to 100% completion before switching to the next workunit.
- **Standalone System Tray**: Right-click the tray icon to switch between `Cyclic Rotation`, pinning a specific project via the `Pin Project` menu, or pausing/resuming Discord status.

## Options

```bash
# Silent background execution with system tray (default via start_discord.bat)
pythonw app.py

# Run in console with stdout logging
python app.py --console

# Custom progress update interval (seconds) and project rotation interval (seconds)
python app.py --interval 4.5 --rotate-interval 18.0

# Custom BOINC paths
python app.py --boinc-data "C:\Other\data.BOINC" --boinccmd "C:\Other\BOINC\boinccmd.exe"

# Headless mode (no system tray icon)
python app.py --no-tray
```

`boinccmd.exe` and the BOINC data directory are detected automatically.
For custom installations, use `--boinccmd <path>` and `--boinc-data <path>`.

## Safety

The service strictly uses standard read queries (`boinccmd --get_tasks` and reading `job_log_*.txt`) with zero memory writes or injections. All Discord communications take place locally via standard Win32 named pipes without external network requests. This project is independent and not affiliated with BOINC or Discord.

## License

Distributed under the MIT License. See [LICENSE](LICENSE) for details.
