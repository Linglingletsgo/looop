import concurrent.futures,os,pathlib,stat,sys,tempfile,threading,unittest
from unittest.mock import patch
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]/'bin'))
import process_owner
from jobs import Jobs,STATUSES,KINDS

class JobTable(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.root=pathlib.Path(self.tmp.name);self.jobs=Jobs(self.root)
  self.owner=process_owner.identity()
 def tearDown(self):self.tmp.cleanup()
 def create(self,**extra):
  return self.jobs.create(extra.pop('lane','demo'),extra.pop('kind','delivery'),extra.pop('title','Job'),**extra)

 def test_create_get_identifier_and_list_filters(self):
  one=self.create(title='First')
  two=self.create(lane='other',kind='planning',title='Second',status='todo',assignee='lane:role')
  self.assertEqual(one['identifier'],'DEMO-'+one['id'][:8]);self.assertTrue(one['id'].isalnum())
  self.assertEqual(two['identifier'],'OTHER-'+two['id'][:8])
  self.assertEqual(self.jobs.get(one['id'])['title'],'First');self.assertIsNone(self.jobs.get('missing'))
  self.assertEqual([j['id'] for j in self.jobs.list()],[one['id'],two['id']])
  self.assertEqual([j['id'] for j in self.jobs.list(lane='other')],[two['id']])
  self.assertEqual([j['id'] for j in self.jobs.list(status='todo')],[two['id']])
  self.assertEqual([j['id'] for j in self.jobs.list(status=['backlog','done'])],[one['id']])
  self.assertEqual([j['id'] for j in self.jobs.list(kind='planning')],[two['id']])
  self.assertEqual([j['id'] for j in self.jobs.list(assignee='lane:role')],[two['id']])
  self.assertEqual(self.jobs.list(status=[]),[])
  self.assertEqual(set(one),{'id','identifier','lane','kind','title','description','status','assignee','created','updated'})

 def test_create_is_idempotent_for_same_payload_and_rejects_conflicts(self):
  first=self.create(job_id='legacy-1')
  again=self.create(job_id='legacy-1')
  self.assertEqual(first,again)
  with self.assertRaises(ValueError):self.jobs.create('demo','planning','Job',job_id='legacy-1')
  with self.assertRaises(ValueError):self.jobs.create('other','delivery','Job',job_id='legacy-1')
  self.assertEqual(len(self.jobs.events('legacy-1')),1)

 def test_update_only_given_fields_and_explicit_assignee_clear(self):
  job=self.create(assignee='lane:role',description='old')
  updated=self.jobs.update(job['id'],status='in_progress',comment='note')
  self.assertEqual(updated['status'],'in_progress');self.assertEqual(updated['assignee'],'lane:role')
  self.assertEqual(updated['description'],'old');self.assertGreaterEqual(updated['updated'],job['updated'])
  cleared=self.jobs.update(job['id'],assignee=None)
  self.assertIsNone(cleared['assignee']);self.assertEqual(cleared['status'],'in_progress')
  self.assertEqual(self.jobs.update(job['id'],description='new')['description'],'new')
  with self.assertRaises(KeyError):self.jobs.update('missing',status='done')
  with self.assertRaises(KeyError):self.jobs.update('missing')
  self.assertEqual(self.jobs.get(job['id'])['description'],'new')

 def test_status_and_comment_events_are_bounded(self):
  job=self.create()
  self.jobs.update(job['id'],status='todo');self.jobs.update(job['id'],status='todo')
  events=self.jobs.events(job['id'])
  self.assertEqual([e['kind'] for e in events],['created','status'])
  self.assertEqual(events[-1]['body'],'backlog->todo')
  for index in range(55):self.jobs.update(job['id'],comment='c'+str(index))
  events=self.jobs.events(job['id'])
  self.assertEqual(len(events),50);self.assertEqual(events[-1]['body'],'c54');self.assertEqual(events[0]['body'],'c5')
  self.assertEqual([e['body'] for e in self.jobs.events(job['id'],limit=2)],['c53','c54'])
  self.jobs.update(job['id'],comment='x'*40000)
  self.assertEqual(len(self.jobs.events(job['id'],limit=1)[0]['body']),35000)
  with self.assertRaises(KeyError):self.jobs.events('missing')

 def test_invalid_values_rejected(self):
  for status in ('unknown','',None,'TODO'):
   with self.assertRaises(ValueError):self.jobs.create('demo','delivery','Job',status=status)
  with self.assertRaises(ValueError):self.jobs.create('demo','unknown','Job')
  for lane in ('Demo','1demo','','demo_'):
   with self.assertRaises(ValueError):self.jobs.create(lane,'delivery','Job')
  job=self.create()
  with self.assertRaises(ValueError):self.jobs.update(job['id'],status='nope')
  with self.assertRaises(ValueError):self.jobs.list(status='nope')
  with self.assertRaises(ValueError):self.jobs.list(status=['todo','nope'])
  with self.assertRaises(ValueError):self.jobs.list(kind='nope')
  with self.assertRaises(ValueError):self.jobs.list(lane='Bad Lane')
  self.assertEqual(STATUSES,('backlog','todo','in_progress','in_review','blocked','done','cancelled'))
  self.assertEqual(KINDS,('planning','delivery','status'))

 def test_non_string_fields_and_non_identity_owner_rejected(self):
  for extra in ({'title':5},{'description':5},{'assignee':7}):
   with self.assertRaises(TypeError):self.create(job_id='i',**extra)
  self.assertIsNone(self.jobs.get('i'))
  job=self.create()
  for owner in ('owner',None,['x']):
   with self.assertRaises(TypeError):self.jobs.claim(job['id'],owner,60)
  with self.jobs.connection() as c:
   c.execute("UPDATE jobs SET lease_owner='\"owner\"',lease_until=? WHERE id=?",(9e12,job['id']))
  self.assertIsNone(self.jobs.holder(job['id']))
  self.assertTrue(self.jobs.claim(job['id'],self.owner,60))

 def test_claim_renew_release_and_holder(self):
  job=self.create();other={**self.owner,'start_ticks':str(int(self.owner['start_ticks'])+1)}
  self.assertIsNone(self.jobs.holder(job['id']))
  self.assertTrue(self.jobs.claim(job['id'],self.owner,60));self.assertEqual(self.jobs.holder(job['id']),self.owner)
  self.assertTrue(self.jobs.claim(job['id'],self.owner,60))
  self.assertFalse(self.jobs.claim(job['id'],other,60));self.assertFalse(self.jobs.release(job['id'],other))
  self.assertEqual(self.jobs.holder(job['id']),self.owner)
  self.assertTrue(self.jobs.release(job['id'],self.owner));self.assertIsNone(self.jobs.holder(job['id']))
  self.assertFalse(self.jobs.release(job['id'],self.owner))
  with self.assertRaises(KeyError):self.jobs.claim('missing',self.owner,60)
  with self.assertRaises(KeyError):self.jobs.release('missing',self.owner)
  with self.assertRaises(KeyError):self.jobs.holder('missing')
  self.assertEqual(self.jobs.owner(),'owner')

 def test_expired_and_dead_leases_are_reclaimed(self):
  job=self.create()
  self.assertTrue(self.jobs.claim(job['id'],self.owner,-1))
  self.assertIsNone(self.jobs.holder(job['id']))
  self.assertTrue(self.jobs.claim(job['id'],self.owner,60))
  self.assertEqual(self.jobs.holder(job['id']),self.owner)
  self.assertTrue(self.jobs.release(job['id'],self.owner))
  dead={'pid':os.getpid(),'boot_id':'dead-boot','start_ticks':'1'}
  self.assertTrue(self.jobs.claim(job['id'],dead,60));self.assertIsNone(self.jobs.holder(job['id']))
  self.assertTrue(self.jobs.claim(job['id'],self.owner,60))
  zombie={'pid':999999999,'boot_id':self.owner['boot_id'],'start_ticks':'1'}
  self.jobs.release(job['id'],self.owner)
  self.assertTrue(self.jobs.claim(job['id'],zombie,60));self.assertIsNone(self.jobs.holder(job['id']))

 def test_unknown_liveness_counts_as_held(self):
  job=self.create();other={**self.owner,'start_ticks':str(int(self.owner['start_ticks'])+1)}
  with patch('jobs.process_owner.alive',return_value=True):
   self.assertTrue(self.jobs.claim(job['id'],self.owner,60))
  with patch('jobs.process_owner.alive',return_value=None):
   self.assertFalse(self.jobs.claim(job['id'],other,60));self.assertEqual(self.jobs.holder(job['id']),self.owner)
   self.assertFalse(self.jobs.release(job['id'],other))

 def test_concurrent_claims_have_one_winner(self):
  job=self.create();owners=[{**self.owner,'start_ticks':str(int(self.owner['start_ticks'])+n)} for n in (1,2)]
  barrier=threading.Barrier(2)
  def attempt(owner):
   barrier.wait()
   return self.jobs.claim(job['id'],owner,60)
  with patch('jobs.process_owner.alive',return_value=True):
   with concurrent.futures.ThreadPoolExecutor(2) as pool:results=list(pool.map(attempt,owners))
   self.assertEqual(sorted(results),[False,True])
   winner=owners[results.index(True)];loser=owners[results.index(False)]
   self.assertEqual(self.jobs.holder(job['id']),winner)
   self.assertFalse(self.jobs.release(job['id'],loser))
   self.assertTrue(self.jobs.release(job['id'],winner));self.assertIsNone(self.jobs.holder(job['id']))

 def test_database_permissions_and_wal(self):
  self.create()
  self.assertEqual(stat.S_IMODE(self.jobs.path.stat().st_mode),0o600)
  self.assertEqual(stat.S_IMODE(self.jobs.path.parent.stat().st_mode),0o700)
  with self.jobs.connection() as c:self.assertEqual(c.execute('PRAGMA journal_mode').fetchone()[0],'wal')
