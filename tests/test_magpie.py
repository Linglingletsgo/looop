import json,pathlib,sys,tempfile,unittest
from unittest.mock import patch
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]/'bin'))
import magpie_provider as magpie,sandbox,execution_settings as settings

class Magpie(unittest.TestCase):
 def test_only_existing_local_gateway_and_private_token(self):
  with tempfile.TemporaryDirectory() as d:
   p=pathlib.Path(d)/'config.toml'
   def config(base):p.write_text('model_provider="local"\nmodel="gpt-test"\n[model_providers.local]\nbase_url="'+base+'"\nexperimental_bearer_token="private-fixture"\n')
   config('http://127.0.0.1:3425/v1');self.assertEqual(magpie.connection(p),('http://127.0.0.1:3425/v1','private-fixture','gpt-test'))
   for base in ('https://paid.example/v1','http://127.0.0.1:8317/v1','http://127.0.0.1:3425/v1?key=bad'):
    config(base)
    with self.assertRaises(ValueError):magpie.connection(p)
 def test_explicit_subscription_namespaces_prevent_provider_fallback(self):
  with patch.object(magpie,'connection',return_value=('http://127.0.0.1:3425/v1','private-fixture','gpt-test')):
   self.assertEqual(magpie.selected('magpie_chatgpt')[2],'codex/gpt-test')
   self.assertEqual(magpie.selected('magpie_deepseek','other')[2],'workbuddy/deepseek-v4.1-flash')
   self.assertEqual(magpie.selected('magpie_commandcode','other')[2],'commandcode/deepseek/deepseek-v4.1-flash')
   self.assertEqual(magpie.selected('magpie_flash_pool','other')[2],'group/auto-deepseek-v4-1-flash')
   with self.assertRaises(ValueError):magpie.selected('magpie_chatgpt','workbuddy/auto')
 def test_all_native_harnesses_use_selected_gateway_without_keys_in_argv(self):
  with tempfile.TemporaryDirectory() as d,patch.object(sandbox.shutil,'which',return_value='/cli'),patch.object(magpie,'connection',return_value=('http://127.0.0.1:3425/v1','private-fixture','gpt-test')):
   for provider in magpie.PLANS:
    for harness in sandbox.HARNESS_IDS:
     scratch=pathlib.Path(d)/(provider+harness);scratch.mkdir()
     argv,env,model=sandbox.invocation(pathlib.Path(d),scratch,{'harness':harness,'provider':provider})
     self.assertEqual(argv[0],harness);self.assertNotIn('private-fixture',' '.join(argv))
     if harness=='claude':
      self.assertEqual(env['ANTHROPIC_BASE_URL'],'http://127.0.0.1:3425');self.assertEqual(env['CLAUDE_CODE_SUBAGENT_MODEL'],model)
     else:self.assertEqual(env['LOOOP_PROVIDER_KEY'],'private-fixture')
 def test_dashboard_and_revision_checked_selection(self):
  with tempfile.TemporaryDirectory() as d,patch.object(settings,'magpie_configured',return_value=True):
   command={'harness':'codex','routes':{s:'magpie_chatgpt' if s=='planning' else 'magpie_deepseek' for s in settings.STAGES},'stage_harnesses':{'build':'claude','review':'claude'},'codex_model':'gpt-test'}
   settings.save(d,command,0,'magpie');public=settings.public(d)
   self.assertTrue(all(p['id'] in public['plan_labels'] for p in public['plans']));self.assertTrue(all(p['configured'] for p in public['plans'] if p['id'] in magpie.PLANS));self.assertEqual(settings.route(settings.read(d),'planning')['model'],'gpt-test');self.assertEqual(settings.route(settings.read(d),'build')['provider'],'magpie_deepseek')
   with patch.object(settings,'magpie_configured',return_value=False):
    with self.assertRaises(ValueError):settings.save(d,command,1,'missing')

 def test_shared_pool_setting_is_explicit_and_not_blocked_by_member_cooldown(self):
  from provider_state import pause
  from autonomy import slots
  with tempfile.TemporaryDirectory() as d,patch.object(settings,'magpie_configured',return_value=True):
   root=pathlib.Path(d)
   value={'harness':'claude','routes':{s:'magpie_flash_pool' for s in settings.STAGES},'stage_harnesses':{},'codex_model':None}
   settings.save(root,value,0,'shared-pool')
   pause(root,'magpie_deepseek',429,'3600')
   self.assertIsNone(slots(root,'demo',{}))
   self.assertEqual(settings.route(settings.read(root),'planning')['provider'],'magpie_flash_pool')
   public=settings.public(root)
   self.assertIn('magpie_flash_pool',public['compatibility']['claude'])
   self.assertIn('magpie_flash_pool',public['plan_labels'])
