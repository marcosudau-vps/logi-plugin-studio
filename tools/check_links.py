from __future__ import annotations
import re
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[1]
# Frozen build artifacts of the closed and accepted AP-RELEASE-FINAL-001 run
# (0.9.0-rc1). They are evidence and are not rewritten; their documentation
# source was corrected in AP-POLISH-001 and the new release candidate is checked.
# Findings inside them are listed separately and do not fail the check.
HISTORICAL = tuple(Path(p) for p in (
    "work/release-final/AP-RELEASE-FINAL-001/outputs/portable-final-build",
    "work/release-final/AP-RELEASE-FINAL-001/outputs/portable-first-rebuild",
    "work/release-final/AP-RELEASE-FINAL-001/outputs/pyinstaller",
    "work/release-final/AP-RELEASE-FINAL-001/outputs/release_candidate",
))
scan = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else root
errors, historical = [], []
checked = 0
for doc in sorted(scan.rglob('*.md')):
    # Historical source documents are not actively maintained and may refer to
    # an older internal directory structure.
    if 'references' in doc.relative_to(scan).parts:
        continue
    for match in re.finditer(r'(?<!!)\[[^\]\n]+\]\(([^)]+)\)', doc.read_text(encoding='utf-8')):
        target = match.group(1).split(' ')[0].split('#')[0]
        if not target or '://' in target or target.startswith(('mailto:', '#')):
            continue
        checked += 1
        if not (doc.parent / target).exists():
            relative = doc.relative_to(scan) if scan != root else doc.relative_to(root)
            frozen = scan == root and any(relative.is_relative_to(h) for h in HISTORICAL)
            (historical if frozen else errors).append(f'{relative}: {target}')
print(f'Gepruefte lokale Markdown-Links: {checked}; fehlende Ziele: {len(errors)}; '
      f'in historischen Build-Artefakten (nicht veraendert): {len(historical)}')
for item in errors:
    print('FEHLT:', item)
for item in historical:
    print('HISTORISCH:', item)
raise SystemExit(bool(errors))
