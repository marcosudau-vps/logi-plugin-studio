"""Bind NF-16 to the shell's one native JSON writer."""
from __future__ import annotations

import codecs
import json
import os
import stat
import tempfile
from pathlib import Path
from uuid import uuid4

from adapters.logitech.native import parse_native_project
from studio.native_ict_binding import NativeIctBindingError, NativeIctCoordinator, _read_ict
from studio.native_session import NativeProjectSession, _invalid_constant, _unique_object


class StudioProjectSession(NativeProjectSession):
    def saved_project(self):
        """Read the saved baseline from the current writer, never reopen a second session."""
        return parse_native_project(json.loads(self._saved_content))

    def save_ict_reference(self, action_id, relative_target, *, base_revision):
        """Persist a link using the normal session writer, restoring history on failure."""
        proposed = self.snapshot()
        record = next((a for a in proposed["actions"] if a["id"] == action_id), None)
        if record is None:
            raise NativeIctBindingError("Aktion existiert nicht mehr im Projekt.")
        record["icon_template"] = relative_target
        # replace() changes memory/history; save() is atomic on disk. Keep the
        # exact old revision and both stacks if save fails before publishing.
        before = (self._raw, self._project, self._content, self._revision,
                  self._undo.copy(), self._redo.copy())
        self.replace(proposed, base_revision=base_revision)
        try:
            self.save()
        except Exception:
            (self._raw, self._project, self._content, self._revision,
             self._undo, self._redo) = before
            raise


class SessionIctCoordinator(NativeIctCoordinator):
    """Reads live project snapshots. Only the session can publish a JSON link."""

    # SDK package resource limit (adapters.logitech.product.read_native_resource).
    asset_limit = 1_048_576

    def __init__(self, session: StudioProjectSession, is_current):
        self.session = session
        self.is_current = is_current
        self.project_path = session.path
        self.project_root = self.project_path.parent
        self._read()

    def _read(self):
        self.project = self.session.native_project()
        # The inherited binding field holds the source-version token. Here it is
        # an opaque session revision, not a hash of a second project snapshot.
        self.project_sha256 = self.session.revision

    def _force_fork(self, action_id, source):
        if not self.session.dirty:
            return False
        baseline = self.session.saved_project()
        saved = next((a for a in baseline.actions if a.id == action_id), None)
        # A direct write is independent of JSON only if the same private link
        # already exists on disk. Preserve files that an earlier snapshot owns.
        return (not saved or not saved.icon_template or self._safe(saved.icon_template) != source
                or self._is_shared(baseline, action_id, source))

    def _alternate_target(self, action_id, target):
        # Undo deliberately retains linked assets for redo. A new edit can
        # branch without reusing or overwriting any retained/foreign file.
        return f"icontemplates/{action_id}__{uuid4().hex}.ict"

    def decode_template(self, data):
        try:
            json.loads(data.decode("utf-8-sig"), object_pairs_hook=_unique_object,
                       parse_constant=_invalid_constant)
        except (ValueError, RecursionError) as exc:
            raise NativeIctBindingError("Ungültige ICT-Datei: " + str(exc)) from exc
        return super().decode_template(data)

    def _guard(self, binding):
        if not self.is_current() or self.session.revision != binding.project_sha256:
            raise NativeIctBindingError("Projekt oder Revision gewechselt; ICT erneut öffnen.")
        self.session._check_disk()
        self.check_assets(binding)
        if not binding.forked and not binding.target.stat().st_mode & stat.S_IWRITE:
            raise NativeIctBindingError("ICT-Ziel ist schreibgeschützt: " + str(binding.target))

    def save(self, binding, template):
        # The existing SDK generator accepts UTF-8 JSON without BOM. Keep the
        # designer's other formatting and every ICT field intact.
        data = self.encode_template(template).removeprefix(codecs.BOM_UTF8)
        self._guard(binding)
        target = binding.target
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(dir=target.parent, prefix=".studio-ict-",
                                             suffix=".tmp", delete=False) as stream:
                temporary = Path(stream.name)
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            self._guard(binding)
            if binding.forked:
                # Same-directory exclusive publish. A competing creator never
                # loses bytes, even in the gap after the conflict checks.
                os.link(temporary, target)
                try:
                    self.session.save_ict_reference(binding.action_id, binding.relative_target,
                                                    base_revision=binding.project_sha256)
                except Exception as exc:
                    try:
                        if target.exists():
                            if not target.samefile(temporary) or _read_ict(target, self.asset_limit) != data:
                                raise NativeIctBindingError("Ziel wurde zwischenzeitlich extern verändert.")
                            target.unlink()
                    except (ValueError, OSError) as rollback:
                        raise NativeIctBindingError(
                            f"Projekt nicht gespeichert: {exc}. Neue ICT konnte nicht sicher "
                            f"zurückgenommen werden ({rollback}). Datei prüfen: {target}") from exc
                    raise
            else:
                os.replace(temporary, target)
                temporary = None
        finally:
            if temporary is not None:
                try:
                    temporary.unlink(missing_ok=True)
                except OSError:
                    # The staging name is never referenced by a project.
                    pass
        self._read()
        return target
