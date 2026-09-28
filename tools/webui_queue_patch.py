"""Pinned-build repair: serialize send-now with cancellation and queue callbacks.

Only this function in 0.11.4's JS is replaced in memory when served. Fail closed
on a different build rather than silently applying a partial patch.
"""
OLD = 'ji=async w=>{const C=K()[g()]??[],q=C.find(Q=>Q.id===w);!q||(q.files??[]).some(Q=>["uploading","error"].includes(Q.status))||(Fn.update(Q=>({...Q,[g()]:C.filter(Ee=>Ee.id!==w)})),await zn(!1),await jt(),await Nn(q.prompt,q.files))}'

NEW = '''ji=async w=>{
 const target=g(),queue=K()[target]??[],item=queue.find(x=>x.id===w);
 if(!item||wi.has(target)||(item.files??[]).some(x=>["uploading","error"].includes(x.status)))return;
 wi.add(target);
 const notify=(state)=>window.dispatchEvent(new CustomEvent('local-studio-queue',{detail:{chatId:target,state}}));
 const previousId=r(je).currentId;
 let removed=false;
 try{
  notify('stopping');
  await zn(false);await jt();
  if(g()!==target){notify('retained');return;}
  const check=await fetch('/api/tasks/chat/'+encodeURIComponent(target),{headers:{Authorization:'Bearer '+localStorage.token}});
  if(!check.ok)throw new Error('停止状態を確認できません。追加指示は待機欄に保持しています。');
  if((await check.json()).task_ids?.length)throw new Error('処理の停止を待っています。追加指示は待機欄に保持しています。');
  if(g()!==target){notify('retained');return;}
  Fn.update(x=>({...x,[target]:(x[target]??[]).filter(m=>m.id!==w)}));removed=true;
  notify('sending');
  await Nn(item.prompt,item.files);
  notify('sent');
 }catch(error){
  if(removed&&g()===target&&r(je).currentId===previousId)Fn.update(x=>({...x,[target]:[item,...(x[target]??[])]}));
  notify('error');_t.error(String(error));
 }finally{wi.delete(target);}
}'''

# stopResponse's captured object must never overwrite the current message after
# an awaited cancellation event has advanced the history to a different branch.
STALE = 'C&&Vr(je,r(je).messages[r(je).currentId]=C),Ls()&&ts()'
SAFE = 'Ls()&&ts()'


def patch_bundle(source):
    if source.count(OLD) != 1 or source.count(STALE) != 1:
        raise RuntimeError('Unsupported Open WebUI queue bundle; the compatibility patch was not applied.')
    return source.replace(OLD, NEW).replace(STALE, SAFE)
