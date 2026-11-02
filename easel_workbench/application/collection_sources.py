"""Collection composition; domain queue and source assets remain separate."""
from easel_workbench.runtime.project_paths import ROOT
from easel_workbench.features.collection.registry import SourceRegistry as Registry
from easel_workbench.integrations.collection.assets import SourceAssets

class SourceRegistry(Registry):
    def __init__(self,store,root):
        super().__init__(store,root,assets=SourceAssets(root))

from easel_workbench.features.collection.queue import CollectionQueue

class CollectionService(CollectionQueue):
    def __init__(self,store,root=ROOT,clock=None):
        super().__init__(store,root,clock,registry=SourceRegistry(store,root))
