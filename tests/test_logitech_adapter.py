"""AP-LOGI-001 tests: Logitech adapter validation gate, naming, generation, safety.

Scope: generator behaviour only. The real ``dotnet build`` against the installed
``PluginApi.dll`` is executed separately as run evidence (see
``work/runs/RUN-AP-LOGI-001-01/03_tests_und_evidenz.md``); these tests never
install anything and never touch the Logi Plugin Service.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from adapters.logitech import (  # noqa: E402
    BuildError,
    GenerationError,
    NamingError,
    OutputPathError,
    SelectionError,
    ValidationGateError,
    capability_report,
    generate,
    load_project_selection,
    plan_generation,
)
from adapters.logitech.build import assert_no_install_target, build_project  # noqa: E402
from adapters.logitech.codegen import (  # noqa: E402
    DEFAULT_SDK_DLL,
    MARKER_FILE,
    MANIFEST_FILE,
    check_output_dir,
    write_tree,
)
from adapters.logitech.naming import (  # noqa: E402
    IDENTIFIER_MAX_LENGTH,
    csharp_literal,
    identifier,
    namespace_for,
    plugin_class_name,
    sdk_action_name,
    validate_assembly_name,
    yaml_double_quoted,
)

FIXTURES = ROOT / "tests" / "fixtures" / "logitech"
SINGLE = FIXTURES / "project_single_action.json"
FOUR = FIXTURES / "project_four_actions.json"
SDK_AVAILABLE = DEFAULT_SDK_DLL.is_file()

_SIMPLE_UNESCAPE = {"\\": "\\", '"': '"', "r": "\r", "n": "\n", "t": "\t", "0": "\0"}


def first_csharp_literal(line: str, start: int = 0) -> str:
    """Extract one complete C# string literal (used to prove escaping is correct)."""
    begin = line.index('"', start)
    out = ['"']
    index = begin + 1
    while index < len(line):
        char = line[index]
        if char == "\\":
            out.append(line[index : index + 2])
            index += 2
            continue
        out.append(char)
        index += 1
        if char == '"':
            break
    return "".join(out)


def csharp_unescape(literal: str) -> str:
    """Minimal inverse of :func:`csharp_literal`, used to prove escaping is lossless."""
    assert literal.startswith('"') and literal.endswith('"'), literal
    body = literal[1:-1]
    out: list[str] = []
    index = 0
    while index < len(body):
        char = body[index]
        if char != "\\":
            out.append(char)
            index += 1
            continue
        escape = body[index + 1]
        if escape == "u":
            out.append(chr(int(body[index + 2 : index + 6], 16)))
            index += 6
            continue
        out.append(_SIMPLE_UNESCAPE[escape])
        index += 2
    return "".join(out)


def write_project(payload: dict, directory: Path, name: str = "project.json") -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def project_payload(components: list[dict], *, project_id: str = "test.project") -> dict:
    return {
        "schema_version": "0.1-draft",
        "project": {"id": project_id, "display_name": "Testprojekt"},
        "dependencies": [{"type": "core.command_action", "version": "1.0.0"}],
        "components": components,
        "states": [],
        "bindings": [],
        "presentations": [],
        "assets": [],
        "views": [],
    }


def command_action(component_id: str, display_name: str) -> dict:
    return {
        "id": component_id,
        "type": "core.command_action",
        "version": "1.0.0",
        "config": {"display_name": display_name},
    }


class TempDirTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="logi-adapter-test-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)


# --------------------------------------------------------------------------- #
# 1. Validation gate (reuses the core model, no second validator)
# --------------------------------------------------------------------------- #
class TestValidationGate(TempDirTestCase):
    def test_single_action_fixture_is_selected(self):
        selection = load_project_selection(SINGLE)
        self.assertEqual(selection.project_id, "fixture.single_action")
        self.assertEqual(selection.action_count, 1)
        self.assertEqual(selection.actions[0].component_id, "action.primary")
        self.assertEqual(selection.actions[0].display_name, "Einzige Aktion")

    def test_four_action_fixture_keeps_project_order_and_names(self):
        selection = load_project_selection(FOUR)
        self.assertEqual(
            [action.component_id for action in selection.actions],
            [
                "action.datei_oeffnen",
                "action.konsole_starten",
                "action.pfad_anzeigen",
                "action.umbenannt_lang",
            ],
        )
        self.assertIn("„zuletzt verwendet“", selection.actions[0].display_name)

    def test_valid_fixture_has_no_error_warnings_blocking(self):
        selection = load_project_selection(FOUR)
        self.assertEqual([issue for issue in selection.warnings if issue["severity"] == "ERROR"], [])

    def test_views_are_recorded_as_not_generated(self):
        selection = load_project_selection(FOUR)
        self.assertEqual(len(selection.not_generated["views"]), 1)
        self.assertEqual(selection.not_generated["views"][0]["view_id"], "view.main")
        self.assertEqual(len(selection.not_generated["views"][0]["placements"]), 2)

    def test_duplicate_component_id_is_rejected(self):
        payload = project_payload(
            [command_action("action.same", "A"), command_action("action.same", "B")]
        )
        path = write_project(payload, self.tmp)
        with self.assertRaises(ValidationGateError) as ctx:
            load_project_selection(path)
        self.assertEqual(ctx.exception.code, "PROJECT_INVALID")
        self.assertIn("ID_DUPLICATE", {issue["code"] for issue in ctx.exception.issues})

    def test_unknown_component_type_is_rejected_before_generation(self):
        component = command_action("action.x", "X")
        component["type"] = "core.unknown_type"
        path = write_project(project_payload([component]), self.tmp)
        with self.assertRaises(ValidationGateError) as ctx:
            load_project_selection(path)
        self.assertIn("TYPE_MISSING", {issue["code"] for issue in ctx.exception.issues})

    def test_missing_config_is_rejected(self):
        component = command_action("action.x", "X")
        del component["config"]
        path = write_project(project_payload([component]), self.tmp)
        with self.assertRaises(ValidationGateError) as ctx:
            load_project_selection(path)
        self.assertIn("FIELD_REQUIRED", {issue["code"] for issue in ctx.exception.issues})

    def test_missing_display_name_is_rejected(self):
        component = command_action("action.x", "X")
        component["config"] = {}
        path = write_project(project_payload([component]), self.tmp)
        with self.assertRaises(ValidationGateError) as ctx:
            load_project_selection(path)
        self.assertIn("CONFIG_INVALID", {issue["code"] for issue in ctx.exception.issues})

    def test_invalid_project_id_is_rejected(self):
        payload = project_payload([command_action("action.x", "X")], project_id="Not Valid")
        path = write_project(payload, self.tmp)
        with self.assertRaises(ValidationGateError) as ctx:
            load_project_selection(path)
        self.assertIn("ID_INVALID", {issue["code"] for issue in ctx.exception.issues})

    def test_project_without_command_action_is_rejected(self):
        payload = project_payload([])
        payload["components"] = [
            {
                "id": "handler.only",
                "type": "core.host_handler",
                "version": "1.0.0",
                "config": {"callback_id": "cb"},
            }
        ]
        path = write_project(payload, self.tmp)
        with self.assertRaises(SelectionError) as ctx:
            load_project_selection(path)
        self.assertEqual(ctx.exception.code, "CAPABILITY_UNSUPPORTED")

    def test_supported_non_action_component_is_recorded(self):
        payload = project_payload([command_action("action.x", "X")])
        payload["components"].append(
            {
                "id": "handler.aux",
                "type": "core.host_handler",
                "version": "1.0.0",
                "config": {"callback_id": "cb"},
            }
        )
        selection = load_project_selection(write_project(payload, self.tmp))
        self.assertEqual(selection.action_count, 1)
        self.assertEqual(selection.unsupported_components[0]["component_id"], "handler.aux")
        self.assertIn("no generator", selection.unsupported_components[0]["reason"])

    def test_unreadable_project_yields_gate_error(self):
        path = self.tmp / "broken.json"
        path.write_text("{not json", encoding="utf-8")
        with self.assertRaises(ValidationGateError) as ctx:
            load_project_selection(path)
        self.assertEqual(ctx.exception.issues[0]["code"], "PROJECT_UNREADABLE")

    def test_gate_error_is_serialisable(self):
        path = write_project(project_payload([]), self.tmp)
        with self.assertRaises(SelectionError) as ctx:
            load_project_selection(path)
        self.assertEqual(set(ctx.exception.as_dict()), {"code", "message"})


# --------------------------------------------------------------------------- #
# 2. Deterministic, collision-free naming and escaping
# --------------------------------------------------------------------------- #
class TestNaming(unittest.TestCase):
    def test_identifier_is_ascii_and_stable(self):
        first = identifier("Action", "action.datei_oeffnen")
        second = identifier("Action", "action.datei_oeffnen")
        self.assertEqual(first, second)
        self.assertTrue(first.startswith("Action_ActionDateiOeffnen_"))
        self.assertTrue(first.isascii())
        self.assertTrue(first[0].isalpha())

    def test_identifier_resolves_collisions_of_similar_ids(self):
        names = {
            identifier("Action", "action.a-b"),
            identifier("Action", "action.a_b"),
            identifier("Action", "action.a.b"),
            identifier("Action", "action.ab"),
        }
        self.assertEqual(len(names), 4)

    def test_identifier_length_is_bounded_for_long_ids(self):
        long_id = "action." + "x" * 400
        name = identifier("Action", long_id)
        self.assertLessEqual(len(name), IDENTIFIER_MAX_LENGTH)
        self.assertNotEqual(name, identifier("Action", "action." + "x" * 399))

    def test_identifier_neutralises_injection_characters(self):
        name = identifier("Action", 'action."); System.IO.File.Delete("C:\\\\x"); //')
        self.assertTrue(all(char.isalnum() or char == "_" for char in name))
        self.assertNotIn('"', name)
        self.assertNotIn(";", name)
        self.assertTrue(name.isascii())

    def test_identifier_rejects_unsafe_prefix(self):
        with self.assertRaises(NamingError):
            identifier("Action-", "action.x")
        with self.assertRaises(NamingError):
            identifier("", "action.x")

    def test_unicode_folding_produces_ascii(self):
        name = identifier("Action", "aktion.übergröße")
        self.assertTrue(name.isascii())
        self.assertIn("Aktion", name)
        self.assertIn("Ubergroe", name)

    def test_namespace_is_stable_and_ascii(self):
        namespace = namespace_for("studio.sample")
        self.assertEqual(namespace, namespace_for("studio.sample"))
        self.assertTrue(namespace.startswith("PluginStudio.Generated."))
        self.assertTrue(namespace.isascii())

    def test_namespace_handles_unicode_and_long_plugin_ids(self):
        self.assertTrue(namespace_for("plugin.ü").isascii())
        self.assertLessEqual(len(namespace_for("plugin." + "a" * 200)), 80)

    def test_plugin_class_name_ends_with_plugin(self):
        self.assertTrue(plugin_class_name("StudioSample").endswith("Plugin"))
        self.assertTrue(plugin_class_name("SamplePlugin").endswith("Plugin"))
        self.assertNotIn("PluginPlugin", plugin_class_name("SamplePlugin"))

    def test_sdk_action_name_is_logical_and_stable(self):
        self.assertEqual(sdk_action_name("studio.sample", "action.x"), "studio.sample:action.x")

    def test_assembly_name_validation_accepts_normal_names(self):
        for name in ("StudioSample", "Studio.Sample", "Plugin_1"):
            self.assertEqual(validate_assembly_name(name), name)

    def test_assembly_name_validation_rejects_unsafe_values(self):
        for name in ("", "1Sample", "Sample.-Bad", "Sample DLL", "Sample.dll", "CON", "a" * 101):
            with self.assertRaises(NamingError, msg=name):
                validate_assembly_name(name)


class TestCSharpLiteral(unittest.TestCase):
    def test_quotes_and_backslashes_are_escaped(self):
        literal = csharp_literal('a"b\\c')
        self.assertEqual(literal, '"a\\"b\\\\c"')
        self.assertEqual(csharp_unescape(literal), 'a"b\\c')

    def test_control_characters_are_escaped(self):
        literal = csharp_literal("line1\nline2\r\t\u0007")
        self.assertNotIn("\n", literal)
        self.assertNotIn("\r", literal)
        self.assertIn("\\u0007", literal)
        self.assertEqual(csharp_unescape(literal), "line1\nline2\r\t\u0007")

    def test_unicode_is_kept_but_line_separator_is_escaped(self):
        self.assertIn("ö", csharp_literal("ö"))
        self.assertIn("\\u2028", csharp_literal("a\u2028b"))

    def test_lone_surrogate_is_escaped(self):
        literal = csharp_literal("a\ud800b")
        self.assertIn("\\uD800", literal)
        literal.encode("utf-8")  # must stay encodable

    def test_round_trip_of_nasty_payload(self):
        payload = '"); System.IO.File.Delete("C:\\Temp\\x"); //\nnext'
        self.assertEqual(csharp_unescape(csharp_literal(payload)), payload)

    def test_non_string_is_rejected(self):
        with self.assertRaises(NamingError):
            csharp_literal(42)  # type: ignore[arg-type]

    def test_yaml_quoting_escapes_quotes_and_breaks(self):
        value = yaml_double_quoted('a"b\\c\nd')
        self.assertTrue(value.startswith('"') and value.endswith('"'))
        self.assertNotIn("\n", value)
        self.assertIn('\\"', value)


# --------------------------------------------------------------------------- #
# 3. Generation: escaping, determinism, variable counts
# --------------------------------------------------------------------------- #
class TestGeneration(TempDirTestCase):
    def plan(self, fixture: Path = SINGLE, *, plugin_id: str = "studio.sample", assembly: str = "StudioSample"):
        selection = load_project_selection(fixture)
        return plan_generation(
            selection, plugin_id=plugin_id, assembly_name=assembly, sdk_dll=DEFAULT_SDK_DLL
        )

    def test_plan_exposes_all_expected_files(self):
        plan = self.plan()
        expected = {
            "nuget.config",
            "StudioSample.csproj",
            "src/Plugin.cs",
            "src/Application.cs",
            "src/ActionDispatch.cs",
            "metadata/LoupedeckPackage.yaml",
            MANIFEST_FILE,
        }
        self.assertTrue(expected.issubset(set(plan.files)))
        for action in plan.actions:
            self.assertIn(action.source_path, plan.files)

    def test_single_action_project_generates_exactly_one_action_class(self):
        plan = self.plan()
        action_files = [name for name in plan.files if name.startswith("src/actions/")]
        self.assertEqual(len(action_files), 1)
        self.assertIn("class " + plan.actions[0].type_name, plan.files[action_files[0]])

    def test_four_action_project_generates_four_distinct_classes(self):
        plan = self.plan(FOUR, plugin_id="studio.multi", assembly="StudioMulti")
        action_files = [name for name in plan.files if name.startswith("src/actions/")]
        self.assertEqual(len(action_files), 4)
        type_names = {action.type_name for action in plan.actions}
        self.assertEqual(len(type_names), 4)

    def test_display_names_survive_into_sources_and_manifest(self):
        plan = self.plan(FOUR, plugin_id="studio.multi", assembly="StudioMulti")
        source = plan.files[plan.actions[1].source_path]
        self.assertIn(csharp_literal('Konsole "PowerShell" starten'), source)
        self.assertIn('Konsole \\"PowerShell\\" starten', source)
        manifest = json.loads(plan.files[MANIFEST_FILE])
        self.assertEqual(
            manifest["actions"][3]["display_name"], plan.actions[3].display_name
        )
        self.assertIn("vollständig im Manifest", manifest["actions"][3]["display_name"])

    def test_backslash_in_display_name_is_escaped(self):
        plan = self.plan(FOUR, plugin_id="studio.multi", assembly="StudioMulti")
        source = plan.files[plan.actions[2].source_path]
        self.assertIn("C:\\\\Temp\\\\prüfen", source)
        self.assertNotIn('"Pfad C:\\Temp', source)

    def test_source_code_injection_is_neutralised(self):
        payload = '"); System.IO.File.Delete("C:\\\\x"); //'
        path = write_project(project_payload([command_action("action.evil", payload)]), self.tmp)
        plan = plan_generation(
            load_project_selection(path),
            plugin_id="studio.evil",
            assembly_name="StudioEvil",
            sdk_dll=DEFAULT_SDK_DLL,
        )
        source = plan.files[plan.actions[0].source_path]
        self.assertEqual(source.count("class "), 1)
        self.assertEqual(source.count("namespace "), 1)
        base_line = next(line for line in source.splitlines() if ": base(" in line)
        literal = first_csharp_literal(base_line, base_line.index(": base("))
        self.assertEqual(csharp_unescape(literal), payload)
        self.assertNotIn("\n", literal)
        self.assertNotIn("\r", literal)

    def test_generation_is_byte_identical_for_the_same_input(self):
        first = self.plan(FOUR, plugin_id="studio.multi", assembly="StudioMulti")
        second = self.plan(FOUR, plugin_id="studio.multi", assembly="StudioMulti")
        self.assertEqual(first.files, second.files)
        self.assertEqual(sorted(first.files), list(second.files))

    def test_written_tree_is_identical_across_directories(self):
        out_a = self.tmp / "a"
        out_b = self.tmp / "b"
        generate(SINGLE, plugin_id="studio.sample", assembly_name="StudioSample", output_dir=out_a)
        generate(SINGLE, plugin_id="studio.sample", assembly_name="StudioSample", output_dir=out_b)
        files_a = sorted(p.relative_to(out_a).as_posix() for p in out_a.rglob("*") if p.is_file())
        files_b = sorted(p.relative_to(out_b).as_posix() for p in out_b.rglob("*") if p.is_file())
        self.assertEqual(files_a, files_b)
        for relative in files_a:
            self.assertEqual((out_a / relative).read_bytes(), (out_b / relative).read_bytes())

    def test_generated_csharp_uses_sdk_namespace_and_reference(self):
        plan = self.plan()
        plugin_source = plan.files["src/Plugin.cs"]
        self.assertIn("using Loupedeck;", plugin_source)
        self.assertIn(": Plugin", plugin_source)
        self.assertIn("public override Boolean HasNoApplication => true;", plugin_source)
        self.assertIn("public override void Load()", plugin_source)
        self.assertIn("public override void Unload()", plugin_source)
        action_source = plan.files[plan.actions[0].source_path]
        self.assertIn(": PluginDynamicCommand", action_source)
        self.assertIn("protected override void RunCommand(String actionParameter)", action_source)
        self.assertIn("ActionDispatcher.Dispatch(SdkActionName, ComponentId);", action_source)

    def test_generated_callback_is_explicitly_pending(self):
        plan = self.plan()
        dispatcher = plan.files["src/ActionDispatch.cs"]
        self.assertIn("BUILD_ONLY / CALLBACK_PENDING", dispatcher)
        self.assertIn("interface IActionDispatch", dispatcher)
        self.assertNotIn("HttpClient", dispatcher)
        self.assertNotIn("Socket", dispatcher)
        self.assertNotIn("Process.Start", dispatcher)

    def test_package_metadata_matches_assembly(self):
        plan = self.plan()
        yaml = plan.files["metadata/LoupedeckPackage.yaml"]
        self.assertIn('pluginFileName: "StudioSample.dll"', yaml)
        self.assertIn("NOT installed by this adapter", yaml)
        self.assertIn('name: "StudioSample"', yaml)
        self.assertNotIn('name: "studio.sample"', yaml)
        application = plan.files["src/Application.cs"]
        self.assertIn("class StudioSampleApplication : ClientApplication", application)
        self.assertIn("ClientApplicationStatus.Unknown", application)

    def test_manifest_records_sdk_reference_and_status(self):
        manifest = json.loads(self.plan().files[MANIFEST_FILE])
        self.assertEqual(manifest["sdk"]["reference"], "PluginApi.dll")
        self.assertEqual(manifest["sdk"]["sha256"], manifest["sdk"]["sha256"].lower())
        self.assertEqual(len(manifest["sdk"]["sha256"]), 64)
        self.assertEqual(manifest["capabilities"]["runtime_status"], "BUILD_ONLY")
        self.assertEqual(manifest["capabilities"]["callback_status"], "CALLBACK_PENDING")
        self.assertEqual(manifest["actions"][0]["component_id"], "action.primary")

    def test_manifest_lists_views_without_claiming_support(self):
        plan = self.plan(FOUR, plugin_id="studio.multi", assembly="StudioMulti")
        manifest = json.loads(plan.files[MANIFEST_FILE])
        self.assertEqual(manifest["not_generated"]["views"][0]["view_id"], "view.main")
        self.assertIn("core.command_action", manifest["not_generated"]["reason"])
        self.assertTrue(any("PluginDynamicFolder" in item for item in manifest["capabilities"]["not_yet_supported"]))

    def test_capability_report_never_claims_folder_or_hardware(self):
        report = capability_report()
        self.assertIn("action.plugin_dynamic_command.static", report["capabilities"])
        self.assertEqual(
            report["capabilities"]["action.plugin_dynamic_command.static"]["status"], "BUILD_PROVEN"
        )
        self.assertEqual(
            report["capabilities"]["deployment.install_development_plugin"]["status"],
            "NOT_YET_SUPPORTED",
        )
        self.assertTrue(any("HARDWARE_PENDING" in item or "Hardware" in item for item in report["not_yet_supported"]))

    def test_sdk_reference_must_be_the_real_dll(self):
        selection = load_project_selection(SINGLE)
        with self.assertRaises(GenerationError):
            plan_generation(
                selection, plugin_id="studio.sample", assembly_name="A", sdk_dll=self.tmp / "PluginApi.dll"
            )
        with self.assertRaises(GenerationError):
            plan_generation(
                selection, plugin_id="studio.sample", assembly_name="A", sdk_dll=DEFAULT_SDK_DLL.parent / "Other.dll"
            )


# --------------------------------------------------------------------------- #
# 4. Output path safety and isolated writes
# --------------------------------------------------------------------------- #
class TestOutputPathSafety(TempDirTestCase):
    def test_relative_output_path_is_resolved(self):
        resolved = check_output_dir("work/tmp/adapter-check")
        self.assertTrue(resolved.is_absolute())

    def test_drive_root_is_rejected(self):
        with self.assertRaises(OutputPathError):
            check_output_dir(Path("C:/"))

    def test_project_root_and_source_tree_are_rejected(self):
        for candidate in (ROOT, ROOT / "src", ROOT / "tests", ROOT / "component_types", ROOT / "docs"):
            with self.assertRaises(OutputPathError, msg=str(candidate)):
                check_output_dir(candidate)

    def test_logi_plugin_service_folder_is_rejected(self):
        with self.assertRaises(OutputPathError):
            check_output_dir(self.tmp / "LogiPluginService" / "Plugins")

    def test_localappdata_logi_is_rejected(self):
        base = os.environ.get("LOCALAPPDATA")
        if not base:
            self.skipTest("LOCALAPPDATA not set")
        with self.assertRaises(OutputPathError):
            check_output_dir(Path(base) / "Logi" / "LogiPluginService" / "Plugins" / "Generated")

    def test_existing_non_empty_directory_without_marker_is_rejected(self):
        target = self.tmp / "occupied"
        target.mkdir()
        (target / "foreign.txt").write_text("x", encoding="utf-8")
        with self.assertRaises(OutputPathError):
            generate(SINGLE, plugin_id="studio.sample", assembly_name="StudioSample", output_dir=target)
        self.assertTrue((target / "foreign.txt").is_file())

    def test_rerun_with_same_plugin_id_is_allowed_and_cleans_stale_actions(self):
        target = self.tmp / "generated"
        generate(FOUR, plugin_id="studio.multi", assembly_name="StudioMulti", output_dir=target)
        self.assertEqual(len(list((target / "src" / "actions").glob("*.cs"))), 4)
        generate(SINGLE, plugin_id="studio.multi", assembly_name="StudioMulti", output_dir=target)
        self.assertEqual(len(list((target / "src" / "actions").glob("*.cs"))), 1)
        self.assertTrue((target / MARKER_FILE).is_file())

    def test_rerun_with_other_plugin_id_is_rejected(self):
        target = self.tmp / "generated"
        generate(SINGLE, plugin_id="studio.sample", assembly_name="StudioSample", output_dir=target)
        with self.assertRaises(OutputPathError):
            generate(SINGLE, plugin_id="studio.other", assembly_name="StudioSample", output_dir=target)

    def test_output_path_that_is_a_file_is_rejected(self):
        target = self.tmp / "file.txt"
        target.write_text("x", encoding="utf-8")
        with self.assertRaises(OutputPathError):
            check_output_dir(target)

    def test_nothing_is_written_outside_the_target_directory(self):
        parent = self.tmp / "parent"
        parent.mkdir()
        before = sorted(p.name for p in parent.iterdir())
        generate(SINGLE, plugin_id="studio.sample", assembly_name="StudioSample", output_dir=parent / "out")
        after = sorted(p.name for p in parent.iterdir())
        self.assertEqual(before, [])
        self.assertEqual(after, ["out"])

    def test_all_written_paths_stay_inside_the_target(self):
        target = self.tmp / "generated"
        plan = generate(
            SINGLE, plugin_id="studio.sample", assembly_name="StudioSample", output_dir=target
        )
        for relative in plan.files:
            self.assertNotIn("..", relative)
            self.assertNotIn("\\", relative)
            self.assertTrue((target / relative).resolve().is_relative_to(target.resolve()))

    def test_write_tree_rejects_unsafe_relative_paths(self):
        target = self.tmp / "generated"
        plan = generate(SINGLE, plugin_id="studio.sample", assembly_name="StudioSample", output_dir=target)
        tampered = type(plan)(
            **{**plan.__dict__, "files": {**plan.files, "../escape.cs": "// nope\n"}}
        )
        with self.assertRaises(OutputPathError):
            write_tree(tampered, target)


# --------------------------------------------------------------------------- #
# 5. No installation target, no vendor side effects
# --------------------------------------------------------------------------- #
class TestNoInstallation(unittest.TestCase):
    def csproj(self) -> str:
        selection = load_project_selection(SINGLE)
        plan = plan_generation(
            selection, plugin_id="studio.sample", assembly_name="StudioSample", sdk_dll=DEFAULT_SDK_DLL
        )
        return plan.files[plan.csproj_relative_path]

    def test_generated_csproj_has_no_install_machinery(self):
        text = self.csproj()
        for marker in (
            "InstallDevelopmentPlugin",
            ".link",
            "LocalAppData",
            "WriteLinesToFile",
            "$(PluginDir)",
            "<PluginDir>",
            "LogiPluginService\\\\Plugins",
        ):
            self.assertNotIn(marker.lower(), text.lower())
        self.assertIsNone(re.search(r"<target(?:\s|>)", text, re.IGNORECASE))

    def test_generated_csproj_references_only_the_real_sdk(self):
        text = self.csproj()
        self.assertIn('<Reference Include="PluginApi">', text)
        self.assertIn("$(PluginApiDir)PluginApi.dll", text)
        self.assertIn("<Private>false</Private>", text)
        self.assertNotIn("PackageReference", text)
        self.assertIn("<TargetFramework>net10.0</TargetFramework>", text)

    def test_assert_no_install_target_accepts_generated_project(self):
        assert_no_install_target(self.csproj())

    def test_assert_no_install_target_rejects_lab_machinery(self):
        snippets = [
            '<Target Name="InstallDevelopmentPlugin" AfterTargets="Build"></Target>',
            '<WriteLinesToFile File="$(PluginDir)X.link" Lines="x" />',
            "<PluginDir>$(LocalAppData)\\Logi\\LogiPluginService\\Plugins\\</PluginDir>",
        ]
        for snippet in snippets:
            with self.assertRaises(BuildError, msg=snippet):
                assert_no_install_target(snippet)

    def test_build_runner_refuses_project_with_install_target(self):
        directory = Path(tempfile.mkdtemp(prefix="logi-adapter-refuse-"))
        self.addCleanup(shutil.rmtree, directory, ignore_errors=True)
        (directory / "Bad.csproj").write_text(
            '<Project Sdk="Microsoft.NET.Sdk"><Target Name="InstallDevelopmentPlugin" '
            'AfterTargets="Build"></Target></Project>',
            encoding="utf-8",
        )
        with self.assertRaises(BuildError) as ctx:
            build_project(directory)
        self.assertIn("installation marker", ctx.exception.message)

    def test_build_runner_requires_exactly_one_csproj(self):
        directory = Path(tempfile.mkdtemp(prefix="logi-adapter-empty-"))
        self.addCleanup(shutil.rmtree, directory, ignore_errors=True)
        with self.assertRaises(BuildError):
            build_project(directory)

    def test_generated_project_has_no_deployment_machinery(self):
        selection = load_project_selection(FOUR)
        plan = plan_generation(
            selection, plugin_id="studio.multi", assembly_name="StudioMulti", sdk_dll=DEFAULT_SDK_DLL
        )
        build_inputs = {
            relative: content
            for relative, content in plan.files.items()
            if relative.endswith((".csproj", ".config", ".cs"))
        }
        self.assertGreaterEqual(len(build_inputs), 7)
        for relative, content in build_inputs.items():
            lowered = content.lower()
            for marker in (
                "installdevelopmentplugin",
                ".link",
                "writelinestofile",
                "localappdata",
                "logipluginservice\\plugins",
                "$(plugindir)",
            ):
                self.assertNotIn(marker, lowered, msg=relative)
            self.assertFalse(relative.startswith(("bin/", "obj/")), msg=relative)


if __name__ == "__main__":
    unittest.main()
