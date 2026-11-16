"""Qt-free acceptance scenarios for containment, reference identity and paging."""
from dataclasses import replace
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from studio.virtual_folders import (Document, FolderError, Navigation,
                                    PagingCapability, Reference)
from studio.virtual_folders.sample import demo_document  # fixture also used by GUI
from studio.virtual_folders.providers import DisplayData, ReferenceHub


def native():
    return json.loads((ROOT / 'examples/project_logitech_native_v1.json').read_text(encoding='utf-8'))


class FolderModelTests(unittest.TestCase):
    def setUp(self):
        self.raw = native()
        self.d = demo_document(self.raw, 'project.test')
        self.plugin = self.d.plugin_id
        self.a = self.d.root_id
        self.b = next(f.id for f in self.d.folders if f.name == 'B')
        self.leaf = next(f.id for f in self.d.folders if f.name == 'A_01_01_02')
        self.link = next(p.id for p in self.d.entries(self.b) if p.kind == 'link')

    def test_required_a_hierarchy_b_link_back_follows_actual_path(self):
        leaf = self.d.folder(self.leaf)
        parent = self.d.folder(leaf.parent_id)
        self.assertEqual(parent.name, 'A_01_01')
        self.assertEqual(self.d.folder(parent.parent_id).name, 'A_01')
        n = Navigation(self.d, self.b)
        n.open(self.link)
        self.assertEqual(n.folder_id, self.leaf)
        self.assertEqual(n.stack[0].placement_id, self.link)
        self.assertTrue(n.back())
        self.assertEqual(n.folder_id, self.b)
        self.assertFalse(n.back())

    def test_two_links_share_rename_and_remove_does_not_delete_target(self):
        original = self.d
        updated = self.d.rename_folder(self.leaf, 'Gemeinsames Ziel')
        links = [p for p in updated.entries(self.b) if p.kind == 'link']
        self.assertEqual(len(links), 2)
        for p in links:
            self.assertEqual(updated.folder(p.target.resource_id).name, 'Gemeinsames Ziel')
        removed = updated.remove_placement(links[0].id)
        self.assertEqual(removed.folder(self.leaf).id, self.leaf)
        self.assertEqual(removed.placement(links[1].id).target.resource_id, self.leaf)
        self.assertEqual(original.folder(self.leaf).name, 'A_01_01_02')

    def test_copy_new_node_page_placement_ids_and_independent_true_subtree(self):
        a01 = next(f.id for f in self.d.folders if f.name == 'A_01')
        copied, copy_id = self.d.copy_folder(a01, self.b)
        descendants = []
        current = copy_id
        while True:
            descendants.append(current)
            child = next((f.id for f in copied.folders if f.parent_id == current), None)
            if child is None:
                break
            current = child
        self.assertEqual(len(descendants), 3)
        self.assertTrue(set(descendants).isdisjoint(f.id for f in self.d.folders))
        new_pages = {p.id for f in copied.folders if f.id in descendants for p in f.pages}
        self.assertTrue(new_pages.isdisjoint(p.id for f in self.d.folders for p in f.pages))
        for p in copied.placements:
            if p.folder_id in descendants:
                self.assertNotIn(p.id, {x.id for x in self.d.placements})
        cloned_leaf = copied.folder(current)
        copied = copied.rename_folder(cloned_leaf.id, 'Unabhängige Kopie')
        self.assertEqual(copied.folder(self.leaf).name, 'A_01_01_02')
        # Link in copied leaf still points to B; no external/link-target duplication.
        self.assertEqual(next(p.target.resource_id for p in copied.entries(current) if p.kind == 'link'), self.b)
        self.assertEqual(len(copied.folders), len(self.d.folders) + 3)

    def test_copy_links_inside_subtree_remain_explicit_original_targets(self):
        linked, _ = self.d.add_link(self.a, Reference(self.plugin, self.leaf))
        copied, copy_id = linked.copy_folder(self.a)
        p = next(p for p in copied.entries(copy_id) if p.kind == 'link')
        self.assertEqual(p.target.resource_id, self.leaf)

    def test_move_keeps_node_and_contains_placement_ids_and_all_links(self):
        incoming = next(p for p in self.d.placements if p.kind == 'contains' and p.target.resource_id == self.leaf)
        result = self.d.move_folder(self.leaf, self.b)
        self.assertEqual(result.folder(self.leaf).parent_id, self.b)
        self.assertEqual(result.placement(incoming.id).folder_id, self.b)
        self.assertEqual(result.placement(self.link).target.resource_id, self.leaf)

    def test_cycles_blocked_without_changing_snapshot(self):
        before = self.d
        for folder_id, parent in ((self.leaf, self.leaf), (self.d.folder(self.leaf).parent_id, self.leaf), (self.a, self.b)):
            with self.assertRaises(FolderError):
                self.d.move_folder(folder_id, parent)
        self.assertIs(before, self.d)

    def test_link_cycle_is_finite_path_and_back_unwinds_each_placement(self):
        n = Navigation(self.d, self.b)
        back_link = next(p.id for p in self.d.entries(self.leaf) if p.kind == 'link')
        for _ in range(20):
            n.open(self.link)
            n.open(back_link)
        self.assertEqual(len(n.stack), 40)
        for _ in range(40):
            self.assertTrue(n.back())
        self.assertEqual(n.folder_id, self.b)

    def test_action_repeated_across_folders_pages_no_definition_mutation(self):
        before = json.dumps(self.raw, sort_keys=True)
        ref = Reference(self.plugin, self.raw['actions'][0]['id'])
        placements = [p for p in self.d.placements if p.kind == 'action' and p.target == ref]
        self.assertGreaterEqual(len(placements), 3)
        result = self.d.remove_placement(placements[0].id)
        self.assertGreaterEqual(sum(p.target == ref for p in result.placements), 2)
        self.assertEqual(json.dumps(self.raw, sort_keys=True), before)

    def test_manual_page_identity_switch_preserves_stack_and_back_page(self):
        n = Navigation(self.d, self.b)
        pages = self.d.folder(self.b).pages
        n.page(pages[1].id)
        self.assertEqual(n.stack, [])
        d, link_id = self.d.add_link(self.b, Reference(self.plugin, self.leaf), pages[1].id)
        n.update(d)
        n.open(link_id)
        n.next_page()
        n.back()
        self.assertEqual((n.folder_id, n.page_id), (self.b, pages[1].id))

    def test_auto_requires_explicit_capability_without_invented_limit(self):
        with self.assertRaises(FolderError):
            self.d.set_mode(self.b, 'auto')
        for value in (0, -1, True, 2.5):
            with self.assertRaises(FolderError):
                PagingCapability(value, 'test')
        d = self.d.set_mode(self.b, 'auto', PagingCapability(2, 'Test capability'))
        f = d.folder(self.b)
        self.assertEqual(len(f.pages), 3)
        self.assertEqual([len(d.entries(self.b, p.id)) for p in f.pages], [2, 2, 1])
        wide = d.set_mode(self.b, 'auto', PagingCapability(1000, 'Explicit test capability'))
        self.assertEqual(len(wide.folder(self.b).pages), 1)

    def test_auto_surviving_page_ids_stable_on_growth_reorder_and_shrink(self):
        d = self.d.set_mode(self.b, 'auto', PagingCapability(2, 'test'))
        first = d.folder(self.b).pages[0].id
        d, extra = d.add_action(self.b, Reference(self.plugin, 'action.command'))
        last = d.entries(self.b)[-1]
        d = d.reorder_placement(last.id, 0)
        d = d.remove_placement(extra)
        self.assertEqual(d.folder(self.b).pages[0].id, first)
        d.validate()

    def test_single_flattens_entries_without_losing_placement_ids(self):
        ids = {p.id for p in self.d.entries(self.b)}
        d = self.d.set_mode(self.b, 'single')
        self.assertEqual(len(d.folder(self.b).pages), 1)
        self.assertEqual({p.id for p in d.entries(self.b)}, ids)
        with self.assertRaises(FolderError):
            d.add_page(self.b)

    def test_page_add_reorder_rename_delete_nonempty_defensive(self):
        d, page = self.d.add_page(self.b, 'Dritte')
        d = d.reorder_page(self.b, page, 0)
        self.assertEqual(d.folder(self.b).pages[0].id, page)
        d = d.rename_page(self.b, page, 'Neue Bezeichnung')
        self.assertEqual(d.folder(self.b).pages[0].name, 'Neue Bezeichnung')
        d = d.remove_page(self.b, page)
        with self.assertRaises(FolderError):
            d.remove_page(self.b, d.folder(self.b).pages[0].id)

    def test_placement_move_to_other_page_and_reorder(self):
        action = next(p for p in self.d.entries(self.b) if p.kind == 'action')
        target = self.d.folder(self.b).pages[1].id
        d = self.d.move_placement(action.id, self.b, target, 0)
        self.assertEqual(d.placement(action.id).page_id, target)
        d = d.reorder_placement(action.id, 1)
        self.assertEqual(d.placement(action.id).position, 1)

    def test_delete_is_defensive_for_children_links_and_root(self):
        for identity in (self.a, self.leaf, self.d.folder(self.leaf).parent_id):
            with self.assertRaises(FolderError):
                self.d.delete_folder(identity)
        d, empty = self.d.create_folder('Empty', self.a)
        d, _ = d.add_link(empty, Reference(self.plugin, self.leaf))
        d = d.delete_folder(empty)
        self.assertEqual(d.folder(self.leaf).id, self.leaf)

    def test_contains_cannot_be_removed_like_a_shortcut(self):
        p = next(p for p in self.d.placements if p.kind == 'contains')
        with self.assertRaises(FolderError):
            self.d.remove_placement(p.id)

    def test_missing_folder_target_duplicates_and_bad_positions_rejected(self):
        with self.assertRaises(FolderError):
            self.d.add_link(self.b, Reference(self.plugin, 'missing'))
        for bad in (-1, 10000, False, '0'):
            with self.assertRaises(FolderError):
                self.d.reorder_placement(self.link, bad)
        with self.assertRaises(FolderError):
            replace(self.d, placements=(*self.d.placements, self.d.placements[0])).validate()
        for changes in ({'position': 5}, {'page_id': 'missing'}, {'kind': 'unknown'}):
            with self.assertRaises(FolderError):
                replace(self.d, placements=(replace(self.d.placements[0], **changes), *self.d.placements[1:])).validate()

    def test_ids_are_validated_and_names_are_not_identities(self):
        for value in ('', 'UPPER', 'with space', '../bad', None):
            with self.assertRaises(FolderError):
                Reference(self.plugin, value)
        for value in ('bad', 'a::b::c', 'UPPER::valid'):
            with self.assertRaises(FolderError):
                Reference.parse(value)
        ref = Reference.parse('plugin.one::action.one')
        self.assertEqual(ref.key, 'plugin.one::action.one')
        d, identity = self.d.create_folder('A', self.a)
        self.assertNotEqual(identity, self.a)

    def test_detach_to_root_and_set_explicit_sdk_entry(self):
        d = self.d.move_folder(self.leaf, None)
        d = d.set_root(self.leaf)
        self.assertEqual(d.root_id, self.leaf)
        self.assertIsNone(d.folder(self.leaf).parent_id)
        with self.assertRaises(FolderError):
            self.d.set_root(self.leaf)

    def test_navigation_reconciles_removed_link_and_keeps_shared_target(self):
        n = Navigation(self.d, self.b)
        n.open(self.link)
        n.update(self.d.remove_placement(self.link))
        self.assertEqual(n.stack, [])
        self.assertEqual(n.folder_id, self.leaf)

    def test_open_wrong_page_action_or_external_fails_without_stack_change(self):
        n = Navigation(self.d, self.b)
        p = next(p for p in self.d.entries(self.b) if p.kind == 'action')
        for identity in (p.id, 'placement.missing'):
            with self.assertRaises(FolderError):
                n.open(identity)
        d, link = self.d.add_link(self.b, Reference('peer', 'folder.remote'))
        n.update(d)
        n.page(d.placement(link).page_id)
        with self.assertRaises(FolderError):
            n.open(link)
        self.assertEqual(n.stack, [])


class ProviderTests(unittest.TestCase):
    def test_folder_metadata_snapshot_and_invalid_push_are_atomic(self):
        hub = ReferenceHub(native())
        ref = Reference('peer', 'folder.remote')
        updates = []
        release = hub.subscribe({ref}, updates.append)
        hub.push((DisplayData(ref, 'folder', 'Remote folder', True),))
        self.assertEqual(updates[-1][0].kind, 'folder')
        before = hub.snapshot()
        with self.assertRaises(FolderError):
            hub.push((DisplayData(ref, 'folder', 'Changed', True), DisplayData('bad', 'action', 'Invalid', True)))
        self.assertEqual(hub.snapshot(), before)
        release()

    def test_native_snapshot_metadata_and_missing_action_unavailable(self):
        raw = native()
        hub = ReferenceHub(raw)
        ref = Reference(raw['plugin']['id'], 'action.command')
        self.assertTrue(hub.resolve(ref).available)
        updated = json.loads(json.dumps(raw))
        updated['folders'] = []
        updated['actions'] = updated['actions'][1:]
        hub.update_native(updated)
        self.assertFalse(hub.resolve(ref).available)
        self.assertEqual(len(raw['actions']), 4)

    def test_push_subscription_initial_snapshot_offline_rejoin_and_release(self):
        hub = ReferenceHub(native())
        ref = Reference('peer', 'action.remote')
        updates = []
        release = hub.subscribe({ref}, updates.append)
        self.assertFalse(updates[-1][0].available)
        hub.push((DisplayData(ref, 'action', 'Remote', True),))
        self.assertTrue(updates[-1][0].available)
        hub.offline('peer')
        self.assertFalse(updates[-1][0].available)
        self.assertEqual(updates[-1][0].name, 'Remote')
        hub.push((DisplayData(ref, 'action', 'Remote neu', True),))
        self.assertEqual(updates[-1][0].name, 'Remote neu')
        release()
        count = len(updates)
        hub.offline('peer')
        self.assertEqual(len(updates), count)


if __name__ == '__main__':
    unittest.main()
