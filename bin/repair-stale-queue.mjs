import postgres from '../.runtime/node_modules/postgres/src/index.js';
import fs from 'node:fs';
const root=new URL('../',import.meta.url);
const state=JSON.parse(fs.readFileSync(new URL('data/gtp-pilot/90f07b1c-8ac3-4e19-88de-42d4755e4da7/state.json',root)));
if(state.state!=='waiting_for_merge'||!state.pr_url)throw Error('Successful pilot evidence required');
const sql=postgres('postgres://paperclip:paperclip@127.0.0.1:54329/paperclip',{max:1});
try {
await sql.begin(async tx=>{
 const agents=await tx`select status from agents where id='055fe2a7-f089-4a95-a6da-9b7f76b40143' for update`;
 if(agents[0]?.status!=='paused')throw Error('Pilot must remain paused');
 const active=await tx`select id from heartbeat_runs where agent_id='055fe2a7-f089-4a95-a6da-9b7f76b40143' and status in ('running','queued','scheduled_retry')`;
 if(active.length)throw Error('Active runs require inspection');
 const rows=await tx`select * from agent_wakeup_requests where agent_id='055fe2a7-f089-4a95-a6da-9b7f76b40143' and status='deferred_issue_execution' and payload->>'issueId'='90f07b1c-8ac3-4e19-88de-42d4755e4da7' and payload->>'mutation'='comment' for update`;
 if(!rows.length){console.log('No stale pilot queues remain.');return;}
 const evidence=new URL('data/queue-repair-'+Date.now()+'.json',root);
 fs.writeFileSync(evidence,JSON.stringify({reason:'Completed pilot; PR waiting for human merge; retire stale delivery without deleting comments',rows},null,2),{mode:0o600});
 const ids=rows.map(r=>r.id);
 const changed=await tx`update agent_wakeup_requests set status='skipped',finished_at=now(),updated_at=now(),error='Operator retired stale comment delivery: pilot completed; waiting for human merge; comments preserved' where id in ${tx(ids)} and status='deferred_issue_execution' returning id`;
 console.log('Preserved and retired stale requests:',changed.length);
});
} finally {await sql.end();}
