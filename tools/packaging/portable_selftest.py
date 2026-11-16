"""Scripted end-to-end check executed INSIDE the packaged Studio (``--selftest``).

Exercises the real GUI objects and the frozen code paths: create/open project,
edit an action, edit a virtual folder, SymbolDesigner/ICT, save, native and
Shared SDK builds, package validation, the stdlib host runner with the native
and the embedded Shared host bundle, the PLUGIN-LOCAL host runtime copied into
each package (started from the package, not from the Studio folder), and the
prerequisite diagnosis. Writes a JSON report; exit code 0 only if every check
passed. No installation and no Logitech service interaction happens here.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import traceback
from pathlib import Path


def run(work: Path, report: Path) -> int:
    work = Path(work).resolve()
    work.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("LOGI_STUDIO_DATA", str(work / "data"))
    os.environ.setdefault("LOGI_SHARED_HOME", str(work / "shared-home"))
    checks: list[dict] = []
    started = time.time()

    def check(name, fn):
        t0 = time.time()
        try:
            detail = fn()
            result = "PASS"
            if isinstance(detail, dict) and detail.get("expected_refusal"):
                result = "EXPECTED_REFUSAL"  # prerequisite missing and correctly diagnosed
            checks.append(dict(name=name, result=result, seconds=round(time.time() - t0, 2), detail=detail))
            return detail
        except Exception as exc:
            checks.append(dict(name=name, result="FAIL", seconds=round(time.time() - t0, 2),
                               error=f"{type(exc).__name__}: {exc}", trace=traceback.format_exc(limit=6)))
            return None

    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication(sys.argv[:1])
    from studio.native_shell import NativeStudioShell
    from studio.native_symbol_dialog import NativeSymbolDesignerDialog
    from studio.native_shell.ict_session import SessionIctCoordinator
    from studio.virtual_folders.model import Reference

    window = NativeStudioShell()
    window.show()
    app.processEvents()
    state: dict = {}

    check("gui_start", lambda: dict(platform=app.platformName(), frozen=bool(getattr(sys, "frozen", False)),
                                    tabs=[window.tabs.tabText(i) for i in range(window.tabs.count())]))

    def create():
        project = work / "projekt" / "portable.json"
        if project.exists():
            raise RuntimeError("selftest work directory must be fresh")
        assert window.create_project(project, "portable.selftest", "Portable Selbsttest")
        state["project"] = project
        return dict(project=str(project), plugin=window.coordinator.session.snapshot()["plugin"])
    check("create_and_open_project", create)

    def edit_action():
        c = window.coordinator
        c.rename_action("action.command", "Portabler Befehl", base_revision=c.session.revision)
        assert window.save_project()
        assert window.reload_project()
        names = [a.display_name for a in c.session.native_project().actions]
        assert "Portabler Befehl" in names, names
        return dict(actions=names)
    check("edit_action_save_reload", edit_action)

    def edit_folder():
        composer = window.composer
        document, placement = composer.document.add_action(
            composer.document.root_id, Reference("portable.selftest", "action.toggle"))
        composer._run(lambda: composer._commit(document))
        assert window.save_folders()
        document, external = composer.document.add_action(
            composer.document.root_id, Reference("portable.owner", "action.command"), action_parameter="first")
        composer._run(lambda: composer._commit(document))
        assert window.save_folders()
        return dict(local=placement, external=external)
    check("edit_virtual_folder_save", edit_folder)

    def symbol_designer():
        seen = {}

        def interact():
            dialog = QApplication.activeModalWidget()
            seen["type"] = type(dialog).__name__
            if isinstance(dialog, NativeSymbolDesignerDialog):
                dialog._confirm_unsaved = lambda *a, **k: True
                dialog.reject()
            elif dialog is not None:
                dialog.close()
        QTimer.singleShot(300, interact)
        assert window.open_symbol_designer("action.command")
        assert seen.get("type") == "NativeSymbolDesignerDialog", seen
        session = window.coordinator.session
        binding = SessionIctCoordinator(session, lambda: True)
        opened = binding.open_action("action.command")
        target = binding.save(opened, opened.template)
        assert Path(target).is_file()
        assert window.reload_project()
        return dict(dialog=seen["type"], ict=str(target))
    check("symbol_designer_and_ict", symbol_designer)

    def build(mode):
        controller = window.build_controller
        controller.set_folder_mode(mode)
        missing = controller.quick_prerequisites()
        if missing:
            assert not controller.start()
            assert "Voraussetzung fehlt" in (controller.last_error or ""), controller.last_error
            return dict(expected_refusal=True, missing=missing, message=controller.last_error)
        assert controller.start(), controller.last_error
        deadline = time.monotonic() + 300
        while controller.running and time.monotonic() < deadline:
            app.processEvents()
            time.sleep(0.03)
        app.processEvents()
        assert controller.last_error is None, controller.log.toPlainText()[-3000:]
        result = controller.last_result
        assert result and result["folder_mode"] == mode, result
        from adapters.logitech import workflow
        validated = workflow.validate(result["package"])
        state[mode] = result
        resources = sorted(p.relative_to(result["package"]).as_posix() for p in Path(result["package"]).rglob("*")
                           if p.is_file())
        return dict(output=result["output"], package_status=validated.status["package"], files=resources,
                    dotnet=result["build"]["dotnet_version"])
    check("native_plugin_build", lambda: build("native"))
    check("shared_plugin_build", lambda: build("shared"))

    def standalone_bundle(mode):
        """Bundle + connection without a C# build (runner check on machines without .NET)."""
        import secrets
        from adapters.logitech.gate import DEFAULT_MANIFEST_DIR
        from adapters.logitech.host_runtime import native_host_bundle
        from runtime.wire import ConnectionSettings, json_bytes, project_digest
        raw = window.coordinator.session.snapshot()
        out = work / ("standalone-" + mode)
        (out / "bin").mkdir(parents=True, exist_ok=True)
        connection = out / "bin" / "studio.connection.json"
        import socket
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        connection.write_bytes(json_bytes(ConnectionSettings(raw["plugin"]["id"], project_digest(raw), port,
                                                             secrets.token_hex(32)).as_dict()))
        if mode == "native":
            bundle = out / "native-host.pyz"
            bundle.write_bytes(native_host_bundle(raw, None, "native", DEFAULT_MANIFEST_DIR, None))
            return dict(output=str(out), host_bundle=str(bundle), connection=str(connection))
        from extensions.shared_folders.generation import python_bundle
        from extensions.shared_folders.runtime_projection import initial_layout
        (out / "development-package" / "bin").mkdir(parents=True, exist_ok=True)
        target = out / "development-package" / "bin" / "studio.connection.json"
        target.write_bytes(connection.read_bytes())
        (out / "shared-folder-host.pyz").write_bytes(python_bundle(raw, initial_layout(raw)[0], [],
                                                                   DEFAULT_MANIFEST_DIR, None))
        return dict(output=str(out), package=str(out / "development-package"))

    def native_host():
        from adapters.logitech.host_runtime import ManagedHost, resolve_shared_python
        from runtime.wire import ConnectionSettings, LocalClient
        result = state.get("native") or standalone_bundle("native")
        host = ManagedHost(result["host_bundle"], result["connection"], Path(result["output"]) / "native-host.log")
        host.start()
        try:
            deadline = time.monotonic() + 30
            while True:
                try:
                    handshake = LocalClient(ConnectionSettings.load(result["connection"])).handshake()
                    break
                except Exception:
                    if time.monotonic() > deadline or not host.running:
                        raise RuntimeError((Path(result["output"]) / "native-host.log").read_text(errors="replace")[-2000:])
                    time.sleep(0.3)
        finally:
            code = host.stop()
        return dict(runner=resolve_shared_python(), handshake=sorted(handshake), exit=code)
    check("native_host_via_runner", native_host)

    def shared_host():
        from adapters.logitech.host_runtime import host_command
        from runtime.wire import ConnectionSettings, LocalClient
        result = state.get("shared") or standalone_bundle("shared")
        package = Path(result["package"])
        bundle = work / "shared-host.pyz"
        bundle.write_bytes((Path(result["output"]) / "shared-folder-host.pyz").read_bytes())
        connection = package / "bin" / "studio.connection.json"
        log = (work / "shared-host.log").open("wb")
        process = subprocess.Popen(host_command(bundle, connection), stdin=subprocess.PIPE, stdout=log,
                                   stderr=subprocess.STDOUT, cwd=str(connection.parent),
                                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        try:
            deadline = time.monotonic() + 30
            while True:
                try:
                    handshake = LocalClient(ConnectionSettings.load(connection)).handshake()
                    break
                except Exception:
                    if time.monotonic() > deadline or process.poll() is not None:
                        log.flush()
                        raise RuntimeError((work / "shared-host.log").read_text(errors="replace")[-2000:])
                    time.sleep(0.3)
            record = package / "bin" / "studio.host-runtime.json"
            row = json.loads(record.read_text()) if record.exists() else None
            if getattr(sys, "frozen", False) and "shared" in state:
                assert row and row["format"] == "studio-host-runtime-2" and row["directory"], row
            return dict(handshake=sorted(handshake),
                        runtime_record={k: v for k, v in (row or {}).items() if k != "files"} or None)
        finally:
            process.stdin.close()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
            log.close()
    check("shared_host_via_runner", shared_host)

    def plugin_local_runtime():
        """The package's OWN runtime copy runs the embedded host (no Studio path involved)."""
        from adapters.logitech.host_runtime import installed_runtime_status, parse_record
        from runtime.wire import ConnectionSettings, LocalClient
        results = {}
        for mode in ("native", "shared"):
            result = state.get(mode)
            if result is None:
                results[mode] = "not built (prerequisite missing)"
                continue
            package = Path(result["package"])
            status = installed_runtime_status(package)
            assert status["status"] == "PLUGIN_LOCAL", status
            record = parse_record((package / "bin" / "studio.host-runtime.json").read_bytes())
            runner = package / "bin" / record["directory"] / record["executable"]
            assert str(Path(sys.executable).parent) not in record_text(package), "Studio path leaked into package"
            bundle = work / f"package-host-{mode}.pyz"
            bundle.write_bytes((Path(result["output"]) / ("native-host.pyz" if mode == "native"
                                                          else "shared-folder-host.pyz")).read_bytes())
            connection = package / "bin" / "studio.connection.json"
            log = (work / f"package-host-{mode}.log").open("wb")
            env = dict(os.environ, LOGI_HOST_STDIN_LIFETIME="1")
            process = subprocess.Popen([str(runner), "-I", "-B", str(bundle), str(connection)], stdin=subprocess.PIPE,
                                       stdout=log, stderr=subprocess.STDOUT, cwd=str(connection.parent), env=env,
                                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            try:
                deadline = time.monotonic() + 30
                while True:
                    try:
                        LocalClient(ConnectionSettings.load(connection)).handshake()
                        break
                    except Exception:
                        if time.monotonic() > deadline or process.poll() is not None:
                            log.flush()
                            raise RuntimeError((work / f"package-host-{mode}.log").read_text(errors="replace")[-2000:])
                        time.sleep(0.3)
            finally:
                process.stdin.close()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                log.close()
            results[mode] = dict(status=status["status"], directory=status["directory"], files=status["files"],
                                 exit=process.returncode)
        if not state.get("native") and not state.get("shared"):
            return dict(expected_refusal=True, reason="no SDK build possible on this machine", results=results)
        return results

    def runner_asyncio():
        """The Studio's host runtime keeps asyncio tasks functional (Shared peer runtime)."""
        import zipfile
        from adapters.logitech.host_runtime import studio_host_runner
        runner = studio_host_runner()
        if runner is None:
            if getattr(sys, "frozen", False):
                raise RuntimeError("frozen Studio without hostruntime")
            return dict(expected_refusal=True, reason="source checkout without host runtime")
        bundle = work / "asyncio-probe.pyz"
        with zipfile.ZipFile(bundle, "w") as archive:
            archive.writestr("__main__.py", "import asyncio\n"
                             "async def m():\n"
                             "    assert asyncio.current_task() is not None\n"
                             "    await asyncio.wait_for(asyncio.sleep(0.01), 2)\n"
                             "    return 'ASYNCIO_OK'\n"
                             "print(asyncio.run(m()))\n")
        result = subprocess.run([runner, "-I", "-B", str(bundle)], capture_output=True, text=True, timeout=60,
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        assert result.returncode == 0 and "ASYNCIO_OK" in result.stdout, (result.returncode, result.stderr[-1500:])
        return dict(runner=runner, output=result.stdout.strip())
    check("host_runtime_asyncio", runner_asyncio)

    def record_text(package):
        return (package / "bin" / "studio.host-runtime.json").read_text(encoding="utf-8")
    check("plugin_local_host_runtime", plugin_local_runtime)

    def prerequisites():
        from adapters.logitech.service import detect_prerequisites
        result = detect_prerequisites()
        return dict(issues=result.issues, plugin_api=result.plugin_api_dll, dotnet=result.dotnet_sdks,
                    host_runtime=result.python_for_shared)
    check("prerequisite_diagnosis", prerequisites)

    def project_unchanged_by_builds():
        project = state["project"]
        raw = json.loads(project.read_text(encoding="utf-8"))
        assert raw["schema_version"] == "logitech-native-1"
        return dict(bytes=project.stat().st_size)
    check("project_file_still_valid", project_unchanged_by_builds)

    window.close()
    app.processEvents()
    import platform
    summary = dict(format="portable-selftest-1", executable=sys.executable, frozen=bool(getattr(sys, "frozen", False)),
                   machine=platform.node(), windows=platform.platform(), user=os.environ.get("USERNAME"),
                   started=started, seconds=round(time.time() - started, 1), work=str(work),
                   passed=sum(c["result"] == "PASS" for c in checks),
                   expected_refusals=sum(c["result"] == "EXPECTED_REFUSAL" for c in checks),
                   failed=sum(c["result"] == "FAIL" for c in checks), total=len(checks), checks=checks)
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
    return 0 if summary["failed"] == 0 else 1
