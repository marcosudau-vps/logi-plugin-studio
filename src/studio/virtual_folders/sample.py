"""Qt-free A/B example shared by the lab and tests."""
from .model import Document, Reference


def demo_document(snapshot, project_id):
    plugin = snapshot['plugin']['id']
    d = Document.create(project_id, plugin, 'A')
    a = d.root_id
    d, a01 = d.create_folder('A_01', a)
    d, a0101 = d.create_folder('A_01_01', a01)
    d, leaf = d.create_folder('A_01_01_02', a0101)
    d, b = d.create_folder('B')
    d, _ = d.add_link(b, Reference(plugin, leaf))
    d, _ = d.add_link(b, Reference(plugin, leaf))
    d, _ = d.add_link(leaf, Reference(plugin, b))  # explicit cycle, never expanded
    action = Reference(plugin, snapshot['actions'][0]['id'])
    d, _ = d.add_action(leaf, action)
    d, _ = d.add_action(b, action)
    d = d.set_mode(b, 'manual')
    d, page = d.add_page(b, 'Weitere Actions')
    d, _ = d.add_action(b, action, page)
    d, _ = d.add_action(b, Reference('peer.offline', 'action.shared'), page)
    return d

