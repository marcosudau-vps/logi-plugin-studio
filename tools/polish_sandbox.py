"""AP-POLISH-001: Clean-Windows checks of BOTH editions in Windows Sandbox.

    python tools/polish_sandbox.py setup    --out <dir>   # Setup lifecycle, no prerequisites
    python tools/polish_sandbox.py portable --out <dir>   # Portable + move, with .NET/Logitech files (read-only)

The sandbox has no Python. Plugin-runtime independence is checked with
``relocation-check.pyz`` executed by the runner INSIDE a built plugin package
(after the Studio folder was moved away): it starts the package's embedded
host bundle with that same runner and performs the signed handshake.
Each run writes ``progress.txt``, JSON reports and ``done.txt`` into ``--out``.
"""
from __future__ import annotations

import argparse
import io
import json
import shutil
import subprocess
import sys
import time
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))
from studio.version import VERSION  # noqa: E402

RC = ROOT / "work" / "polish" / "AP-POLISH-001" / "outputs" / "release_candidate"
SETUP = RC / f"LogiPluginStudio-Setup-{VERSION}.exe"
PORTABLE = RC / f"LogiPluginStudio-Portable-{VERSION}.zip"

CHECK_MAIN = r'''
import json, os, subprocess, sys, time, zipfile
from pathlib import Path
from runtime.wire import ConnectionSettings, LocalClient

def main():
    package, report = Path(sys.argv[1]), Path(sys.argv[2])
    record = json.loads((package / "bin" / "studio.host-runtime.json").read_text(encoding="utf-8"))
    runner = Path(sys.executable).resolve()
    row = {"runner": str(runner), "record_directory": record["directory"], "package": str(package)}
    row["runner_inside_package"] = str(runner).lower().startswith(str(package.resolve()).lower())
    dll = next(p for p in (package / "bin").glob("*Plugin.dll"))
    data = dll.read_bytes()
    name = "native-host.pyz" if b"native-host.pyz" in data else "shared-folder-host.pyz"
    bundle = Path(os.environ.get("TEMP", ".")) / ("check-" + name)
    # The bundle is embedded as a .NET resource; the build output beside the package has the same bytes.
    source = package.parent / name
    bundle.write_bytes(source.read_bytes())
    connection = package / "bin" / "studio.connection.json"
    env = dict(os.environ, LOGI_HOST_STDIN_LIFETIME="1")
    log = open(Path(os.environ.get("TEMP", ".")) / "check-host.log", "wb")
    process = subprocess.Popen([str(runner), "-I", "-B", str(bundle), str(connection)], stdin=subprocess.PIPE,
                               stdout=log, stderr=subprocess.STDOUT, cwd=str(connection.parent), env=env)
    deadline = time.monotonic() + 40
    handshake = None
    while time.monotonic() < deadline and handshake is None:
        try:
            handshake = LocalClient(ConnectionSettings.load(connection)).handshake()
        except Exception as exc:
            row["last_error"] = type(exc).__name__
            time.sleep(0.4)
    row["handshake"] = sorted(handshake) if handshake else None
    process.stdin.close()
    try:
        row["host_exit"] = process.wait(timeout=15)
    except subprocess.TimeoutExpired:
        process.kill(); row["host_exit"] = "killed"
    log.close()
    row["ok"] = bool(handshake) and row["runner_inside_package"]
    report.write_text(json.dumps(row, indent=2), encoding="utf-8")
    return 0 if row["ok"] else 1

raise SystemExit(main())
'''


def check_pyz(target: Path) -> None:
    files = {"__main__.py": CHECK_MAIN.encode("utf-8")}
    for package in ("runtime", "core"):
        for file in (SRC / package).glob("*.py"):
            files[f"{package}/{file.name}"] = file.read_bytes()
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in sorted(files.items()):
            archive.writestr(name, data)
    target.write_bytes(buffer.getvalue())


def wsb(out: Path, mapped: list[tuple[Path, str, bool]]) -> Path:
    folders = "".join(f"<MappedFolder><HostFolder>{host}</HostFolder><SandboxFolder>{guest}</SandboxFolder>"
                      f"<ReadOnly>{'true' if ro else 'false'}</ReadOnly></MappedFolder>" for host, guest, ro in mapped)
    text = (f"<Configuration><vGPU>Disable</vGPU><Networking>Disable</Networking><MappedFolders>{folders}"
            "</MappedFolders><LogonCommand><Command>C:\\out\\run.cmd</Command></LogonCommand></Configuration>")
    path = out / "sandbox.wsb"
    path.write_text(text, encoding="utf-8")
    return path


SETUP_RUN = r"""@echo off
set PATH=C:\Windows\System32;C:\Windows;C:\Windows\System32\WindowsPowerShell\v1.0
set OUT=C:\out
set RC=C:\RC
echo started %DATE% %TIME% > %OUT%\progress.txt
where python >> %OUT%\progress.txt 2>&1
echo python_found=%ERRORLEVEL% (1 = not found) >> %OUT%\progress.txt
powershell -NoProfile -ExecutionPolicy Bypass -File C:\out\setup-lifecycle.ps1 >> %OUT%\progress.txt 2>&1
echo lifecycle_exit=%ERRORLEVEL% >> %OUT%\progress.txt
echo done > %OUT%\done.txt
if /I "%USERNAME%"=="WDAGUtilityAccount" shutdown.exe /s /t 0
"""

SETUP_PS1 = r"""
$ErrorActionPreference = 'Continue'
$out = 'C:\out'; $rc = 'C:\RC'
$setup = Get-ChildItem $rc -Filter 'LogiPluginStudio-Setup-*.exe' | Where-Object { $_.Name -notlike '*updatetest*' } | Select-Object -First 1
$old = Get-ChildItem 'C:\in' -Filter '*updatetest*.exe' | Select-Object -First 1
$results = [ordered]@{}
function Step($name, $ok, $detail) { $results[$name] = [ordered]@{ ok = [bool]$ok; detail = $detail }; "STEP $name ok=$ok $detail" }
function UninstallKey { Get-ChildItem 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall' -ErrorAction SilentlyContinue |
    ForEach-Object { Get-ItemProperty $_.PSPath } | Where-Object { $_.DisplayName -like 'Logitech Plugin Studio*' } }
$default = Join-Path $env:LOCALAPPDATA 'Programs\LogiPluginStudio'
$data = Join-Path $env:LOCALAPPDATA 'LogiPluginStudio'
$plugins = Join-Path $env:LOCALAPPDATA 'Logi\LogiPluginService\Plugins'

# 1 Abort: start the interactive wizard and terminate it before installing.
$p = Start-Process $setup.FullName -PassThru
Start-Sleep 8
Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue
Get-Process | Where-Object { $_.Name -like 'LogiPluginStudio-Setup*' -or $_.Name -like 'is-*' } | Stop-Process -Force -ErrorAction SilentlyContinue
Start-Sleep 3
Step 'abort_leaves_nothing' (-not (Test-Path $default) -and -not (UninstallKey)) "app_exists=$(Test-Path $default)"

# 2 Old version (update test) installed first, with a stale file of that old version.
$args = '/VERYSILENT /SUPPRESSMSGBOXES /NORESTART /LOG="' + $out + '\install-old.log"'
$code = (Start-Process $old.FullName -ArgumentList $args -Wait -PassThru).ExitCode
Step 'install_old_version' ($code -eq 0 -and (Test-Path "$default\_internal\stale-from-old-version.txt")) "exit=$code version=$((UninstallKey).DisplayVersion)"

# User data that must survive update, repair and uninstall.
New-Item -ItemType Directory -Force "$data\SharedFolders\config", "$data\settings", "$env:USERPROFILE\Documents\Projekte\demo", "$plugins\FremdesPlugin", "$plugins\StudioTestPlugin\bin" | Out-Null
Set-Content "$data\SharedFolders\config\demo.plugin.json" '{"peers": {}}'
Set-Content "$data\settings\build_modes.json" '{"format":"studio-build-modes-1","projects":{}}'
Set-Content "$env:USERPROFILE\Documents\Projekte\demo\project.json" '{"schema_version":"logitech-native-1"}'
Set-Content "$plugins\FremdesPlugin\keep.txt" 'foreign'
Set-Content "$plugins\StudioTestPlugin\bin\installed.txt" 'installed plugin'
$before = Get-ChildItem $data, "$env:USERPROFILE\Documents\Projekte", $plugins -Recurse -File | Get-FileHash | Select-Object Path, Hash

# 3 Update to the release candidate.
$args = '/VERYSILENT /SUPPRESSMSGBOXES /NORESTART /LOG="' + $out + '\install-update.log"'
$code = (Start-Process $setup.FullName -ArgumentList $args -Wait -PassThru).ExitCode
$key = UninstallKey
Step 'update_over_existing' ($code -eq 0 -and $key.DisplayVersion -like '1.0.0*' -and -not (Test-Path "$default\_internal\stale-from-old-version.txt")) "exit=$code version=$($key.DisplayVersion) stale_removed=$(-not (Test-Path "$default\_internal\stale-from-old-version.txt"))"
Step 'edition_marker' (Test-Path "$default\studio-edition.json") ''
Get-ChildItem $default -Recurse -File | ForEach-Object { [pscustomobject]@{
    path = $_.FullName.Substring($default.Length + 1).Replace('\', '/');
    sha256 = (Get-FileHash $_.FullName -Algorithm SHA256).Hash.ToLower() } } |
  ConvertTo-Json -Compress | Set-Content "$out\installed-files.json" -Encoding UTF8
Step 'start_menu_entry' (Test-Path (Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs\Logitech Plugin Studio\Logitech Plugin Studio.lnk')) ''
Step 'uninstall_entry' ($key -and $key.UninstallString -like '*unins000.exe*') "$($key.UninstallString)"
Step 'no_admin_hklm_entry' (-not (Get-ChildItem 'HKLM:\Software\Microsoft\Windows\CurrentVersion\Uninstall' | ForEach-Object { Get-ItemProperty $_.PSPath } | Where-Object { $_.DisplayName -like 'Logitech Plugin Studio*' })) ''

# 4 Program start: diagnosis and the scripted self-test (GUI objects, project editing, builds refused without prerequisites).
$code = (Start-Process "$default\LogiPluginStudio.exe" -ArgumentList '--diagnose','--out',"$out\diagnose.txt" -Wait -PassThru).ExitCode
Step 'diagnose_runs' (Test-Path "$out\diagnose.txt") "exit=$code"
$code = (Start-Process "$default\LogiPluginStudio.exe" -ArgumentList '--selftest','--work',"$env:TEMP\st1",'--out',"$out\selftest-setup.json" -Wait -PassThru).ExitCode
$st = Get-Content "$out\selftest-setup.json" -Raw | ConvertFrom-Json
Step 'selftest_setup_edition' ($code -eq 0 -and $st.failed -eq 0) "passed=$($st.passed) refusals=$($st.expected_refusals) failed=$($st.failed)"

# 5 Repair: damage a program file, reinstall the same version.
Remove-Item "$default\hostruntime\LogiPluginStudioHost.exe" -Force
Set-Content "$default\_internal\python312.dll" 'damaged'
$args = '/VERYSILENT /SUPPRESSMSGBOXES /NORESTART /LOG="' + $out + '\install-repair.log"'
$code = (Start-Process $setup.FullName -ArgumentList $args -Wait -PassThru).ExitCode
$code2 = (Start-Process "$default\LogiPluginStudio.exe" -ArgumentList '--diagnose','--out',"$out\diagnose-after-repair.txt" -Wait -PassThru).ExitCode
$diag = Get-Content "$out\diagnose-after-repair.txt" -Raw
Step 'repair_same_version' ($code -eq 0 -and (Test-Path "$default\hostruntime\LogiPluginStudioHost.exe") -and $diag -notmatch 'STUDIO_HOST_RUNTIME') "exit=$code"

# 6 Alternative install path (second, independent install is not wanted: uninstall first, then custom dir).
$args = '/VERYSILENT /SUPPRESSMSGBOXES /NORESTART /LOG="' + $out + '\uninstall-1.log"'
$code = (Start-Process "$default\unins000.exe" -ArgumentList $args -Wait -PassThru).ExitCode
Start-Sleep 3
$after = Get-ChildItem $data, "$env:USERPROFILE\Documents\Projekte", $plugins -Recurse -File | Get-FileHash | Select-Object Path, Hash
$same = -not (Compare-Object $before $after -Property Path, Hash)
Step 'uninstall_removes_program' ($code -eq 0 -and -not (Test-Path "$default\LogiPluginStudio.exe") -and -not (UninstallKey)) "exit=$code"
Step 'user_data_and_plugins_preserved' $same "files=$($after.Count)"
$alt = 'C:\Alt Pfad\Mein Studio'
$args = '/VERYSILENT /SUPPRESSMSGBOXES /NORESTART /DIR="' + $alt + '" /LOG="' + $out + '\install-alt.log"'
$code = (Start-Process $setup.FullName -ArgumentList $args -Wait -PassThru).ExitCode
$code2 = (Start-Process "$alt\LogiPluginStudio.exe" -ArgumentList '--diagnose','--out',"$out\diagnose-alt.txt" -Wait -PassThru).ExitCode
$diagAlt = Get-Content "$out\diagnose-alt.txt" -Raw
Step 'alternative_path' ($code -eq 0 -and $diagAlt -match [regex]::Escape($alt)) "exit=$code"
$args = '/VERYSILENT /SUPPRESSMSGBOXES /NORESTART /LOG="' + $out + '\uninstall-2.log"'
$code = (Start-Process "$alt\unins000.exe" -ArgumentList $args -Wait -PassThru).ExitCode
Start-Sleep 3
Step 'uninstall_alternative_path' ($code -eq 0 -and -not (Test-Path "$alt\LogiPluginStudio.exe")) "exit=$code"
$after2 = Get-ChildItem $data, "$env:USERPROFILE\Documents\Projekte", $plugins -Recurse -File | Get-FileHash | Select-Object Path, Hash
Step 'user_data_preserved_after_second_uninstall' (-not (Compare-Object $before $after2 -Property Path, Hash)) ''
$results | ConvertTo-Json -Depth 5 | Set-Content "$out\setup-lifecycle.json" -Encoding UTF8
if ($results.Values | Where-Object { -not $_.ok }) { exit 1 } else { exit 0 }
"""

PORTABLE_RUN = r"""@echo off
set PATH=C:\Windows\System32;C:\Windows;C:\Windows\System32\WindowsPowerShell\v1.0;C:\Program Files\dotnet
set DOTNET_CLI_TELEMETRY_OPTOUT=1
set DOTNET_NOLOGO=1
echo started %DATE% %TIME% > C:\out\progress.txt
where python >> C:\out\progress.txt 2>&1
echo python_found=%ERRORLEVEL% (1 = not found) >> C:\out\progress.txt
powershell -NoProfile -ExecutionPolicy Bypass -File C:\out\portable-move.ps1 >> C:\out\progress.txt 2>&1
echo portable_exit=%ERRORLEVEL% >> C:\out\progress.txt
echo done > C:\out\done.txt
if /I "%USERNAME%"=="WDAGUtilityAccount" shutdown.exe /s /t 0
"""

PORTABLE_PS1 = r"""
$ErrorActionPreference = 'Continue'
$out = 'C:\out'
$zip = Get-ChildItem 'C:\RC' -Filter 'LogiPluginStudio-Portable-*.zip' | Select-Object -First 1
$results = [ordered]@{}
function Step($name, $ok, $detail) { $results[$name] = [ordered]@{ ok = [bool]$ok; detail = $detail }; "STEP $name ok=$ok $detail" }
$loc1 = 'C:\Programme\LogiStudio'; $loc2 = 'C:\Tools verschoben\LogiStudio'
New-Item -ItemType Directory -Force 'C:\Programme', 'C:\Tools verschoben' | Out-Null
Expand-Archive $zip.FullName -DestinationPath 'C:\Programme\unpack' -Force
$top = Get-ChildItem 'C:\Programme\unpack' | Select-Object -First 1
Move-Item $top.FullName $loc1
Step 'unzip_fresh' (Test-Path "$loc1\LogiPluginStudio.exe") $loc1
# Read-only program folder: the Studio must not need to write there.
icacls $loc1 /deny "$($env:USERNAME):(OI)(CI)(WD,AD,WEA,WA,DC)" | Out-Null
$code = (Start-Process "$loc1\LogiPluginStudio.exe" -ArgumentList '--selftest','--work',"$env:TEMP\st-loc1",'--out',"$out\selftest-loc1.json" -Wait -PassThru).ExitCode
$st1 = Get-Content "$out\selftest-loc1.json" -Raw | ConvertFrom-Json
Step 'selftest_location_1_readonly_program_dir' ($code -eq 0 -and $st1.failed -eq 0) "passed=$($st1.passed) refusals=$($st1.expected_refusals) failed=$($st1.failed)"
$builds = Get-ChildItem "$env:TEMP\st-loc1\data\builds" -Directory
icacls $loc1 /remove:d "$($env:USERNAME)" | Out-Null
# Move the whole Studio folder.
Move-Item $loc1 $loc2
Step 'move_studio_folder' ((-not (Test-Path $loc1)) -and (Test-Path "$loc2\LogiPluginStudio.exe")) $loc2
# Plugins built at location 1 run with THEIR OWN runtime although the Studio moved away.
$i = 0
foreach ($b in $builds) {
  $package = Join-Path $b.FullName 'development-package'
  $record = Get-Content "$package\bin\studio.host-runtime.json" -Raw | ConvertFrom-Json
  $runner = Join-Path "$package\bin" (Join-Path $record.directory $record.executable)
  $code = (Start-Process $runner -ArgumentList '-I','-B','C:\in\relocation-check.pyz',"`"$package`"","$out\relocation-$i.json" -Wait -PassThru -NoNewWindow).ExitCode
  $r = Get-Content "$out\relocation-$i.json" -Raw | ConvertFrom-Json
  Step "plugin_runtime_after_move_$i" ($code -eq 0 -and $r.ok) "runner_inside_package=$($r.runner_inside_package) handshake=$($r.handshake -ne $null)"
  $i++
}
Step 'built_plugins_found' ($i -ge 2) "count=$i"
$code = (Start-Process "$loc2\LogiPluginStudio.exe" -ArgumentList '--diagnose','--out',"$out\diagnose-loc2.txt" -Wait -PassThru).ExitCode
$diag = Get-Content "$out\diagnose-loc2.txt" -Raw
Step 'studio_finds_itself_at_new_location' ($diag -match [regex]::Escape($loc2) -and $diag -match 'hostruntime') "exit=$code"
$code = (Start-Process "$loc2\LogiPluginStudio.exe" -ArgumentList '--selftest','--work',"$env:TEMP\st-loc2",'--out',"$out\selftest-loc2.json" -Wait -PassThru).ExitCode
$st2 = Get-Content "$out\selftest-loc2.json" -Raw | ConvertFrom-Json
Step 'selftest_location_2' ($code -eq 0 -and $st2.failed -eq 0) "passed=$($st2.passed) refusals=$($st2.expected_refusals) failed=$($st2.failed)"
# Studio folder removed entirely: plugin runtimes still work.
Remove-Item $loc2 -Recurse -Force
$r0 = $null
$b = $builds | Select-Object -First 1
$package = Join-Path $b.FullName 'development-package'
$record = Get-Content "$package\bin\studio.host-runtime.json" -Raw | ConvertFrom-Json
$runner = Join-Path "$package\bin" (Join-Path $record.directory $record.executable)
$code = (Start-Process $runner -ArgumentList '-I','-B','C:\in\relocation-check.pyz',"`"$package`"","$out\relocation-studio-deleted.json" -Wait -PassThru -NoNewWindow).ExitCode
$r0 = Get-Content "$out\relocation-studio-deleted.json" -Raw | ConvertFrom-Json
Step 'plugin_runtime_with_studio_deleted' ($code -eq 0 -and $r0.ok) ''
$results | ConvertTo-Json -Depth 5 | Set-Content "$out\portable-move.json" -Encoding UTF8
if ($results.Values | Where-Object { -not $_.ok }) { exit 1 } else { exit 0 }
"""


def old_setup(out: Path) -> Path:
    """An OLDER-versioned installer from the same payload plus one stale file (update test only)."""
    sys.path.insert(0, str(ROOT / "tools" / "packaging"))
    import build_release
    payload = ROOT / "work" / "polish" / "AP-POLISH-001" / "outputs" / "payload" / f"LogiPluginStudio-{VERSION}"
    stage = out / "old-payload" / "LogiPluginStudio"
    if stage.exists():
        shutil.rmtree(stage)
    shutil.copytree(payload, stage)
    (stage / "_internal" / "stale-from-old-version.txt").write_text("from 0.99.0-updatetest", encoding="utf-8")
    compiler = build_release.inno_compiler()
    command = [str(compiler), "/Q", "/DAppVersion=0.99.0-updatetest", "/DAppVersionNumeric=0.99.0.0",
               f"/DPayload={stage}", f"/DOutputDir={out / 'in'}", "/DOutputBaseFilename=LogiPluginStudio-Setup-0.99.0-updatetest",
               str(ROOT / "tools" / "packaging" / "LogiPluginStudio.iss")]
    subprocess.run(command, cwd=ROOT / "tools" / "packaging", check=True)
    shutil.rmtree(out / "old-payload")
    return out / "in" / "LogiPluginStudio-Setup-0.99.0-updatetest.exe"


def launch(out: Path, timeout: int) -> dict:
    sandbox = Path(r"C:\Windows\System32\WindowsSandbox.exe")
    started = time.time()
    subprocess.Popen([str(sandbox), str(out / "sandbox.wsb")])
    deadline = time.time() + timeout
    while time.time() < deadline and not (out / "done.txt").exists():
        time.sleep(10)
    return {"finished": (out / "done.txt").exists(), "seconds": round(time.time() - started)}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("kind", choices=("setup", "portable"))
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--timeout", type=int, default=3600)
    args = parser.parse_args(argv)
    out = args.out.resolve()
    if out.exists():
        raise SystemExit("output directory must be fresh")
    (out / "in").mkdir(parents=True)
    check_pyz(out / "in" / "relocation-check.pyz")
    mapped = [(RC, r"C:\RC", True), (out, r"C:\out", False), (out / "in", r"C:\in", True)]
    if args.kind == "setup":
        old_setup(out)
        (out / "run.cmd").write_text(SETUP_RUN, encoding="ascii")
        (out / "setup-lifecycle.ps1").write_text(SETUP_PS1, encoding="utf-8-sig")
    else:
        mapped += [(Path(r"C:\Program Files\dotnet"), r"C:\Program Files\dotnet", True),
                   (Path(r"C:\Program Files\Logi\LogiPluginService"), r"C:\Program Files\Logi\LogiPluginService", True)]
        (out / "run.cmd").write_text(PORTABLE_RUN, encoding="ascii")
        (out / "portable-move.ps1").write_text(PORTABLE_PS1, encoding="utf-8-sig")
    wsb(out, mapped)
    result = launch(out, args.timeout)
    print(json.dumps(result))
    return 0 if result["finished"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
