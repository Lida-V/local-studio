// Exercise the real replacement function with delayed cancellation events.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, '../tools/webui_queue_patch.py'), 'utf8');
const patched = source.match(/NEW = '''([\s\S]*?)'''/)[1];
async function fixture({fail = false, navigate = false, double = false} = {}) {
  let selected = 'chat-a';
  const queue = {'chat-a': [{id:'one',prompt:'追加指示',files:[]}, {id:'two',prompt:'後続指示',files:[]}]};
  const guard = new Set(), submitted = [], states = [], errors = [];
  const history = {currentId:'original'};
  const context = {g:()=>selected, K:()=>queue, wi:guard, r:v=>v, je:history, jt:async()=>{},
    localStorage:{token:'fixture'}, encodeURIComponent, CustomEvent: class {constructor(_,p){this.detail=p.detail;}},
    window:{dispatchEvent:e=>states.push(e.detail.state)}, _t:{error:e=>errors.push(e)},
    Fn:{update:f=>Object.assign(queue,f(queue))},
    fetch:async()=>({ok:!fail,json:async()=>({task_ids:[]})}),
    zn:async()=>{
      await new Promise(resolve=>setTimeout(resolve,5));
      // The cancel socket callback tries to process the queued messages here.
      if (!guard.has('chat-a')) submitted.push('UNEXPECTED automatic queue submission');
      if(navigate) selected='chat-b';
    },
    Nn:async(prompt)=>{submitted.push(prompt);history.currentId='new-response';}
  };
  vm.createContext(context);
  vm.runInContext(patched,context);
  if(double) await Promise.all([context.ji('one'),context.ji('one')]);
  else await context.ji('one');
  assert.equal(guard.size,0);
  if(fail||navigate){assert.equal(submitted.length,0);assert.equal(queue['chat-a'].length,2);}
  else{assert.deepEqual(submitted,['追加指示']);assert.equal(queue['chat-a'][0].id,'two');assert.equal(states.at(-1),'sent');}
  if(fail)assert.equal(errors.length,1);
}
(async()=>{await fixture();await fixture({double:true});await fixture({fail:true});await fixture({navigate:true});console.log('Queue insertion: 4 regression cases passed');})().catch(e=>{console.error(e);process.exitCode=1;});
