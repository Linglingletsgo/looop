"""Opt-in PM skill packs shared by the research loader and the Magpie export."""
import json

NONCOMMERCIAL_PACK='noncommercial'
BASES=('looop:research-core','looop:investigation')

def noncommercial_enabled(root):
 """True only for {"pm_skills":{"noncommercial":true}} in ROOT/data/local-settings.json."""
 try:settings=json.loads((root/'data/local-settings.json').read_text())
 except (OSError,ValueError):return False
 pack=settings.get('pm_skills') if isinstance(settings,dict) else None
 return isinstance(pack,dict) and pack.get('noncommercial') is True

def base_skill(enabled):
 return BASES[1] if enabled else BASES[0]

def with_base(selected,known,defaults,project,base):
 """Keep an explicit base, else add the configured one; never two bases."""
 selected=list(selected);bases=[p for p in selected if p in BASES]
 if len(bases)>1:raise ValueError('Research must select at most one base method')
 if not bases and defaults and base in known:selected.insert(0,base)
 if not selected and not project and base in known:selected=[base]
 return selected
