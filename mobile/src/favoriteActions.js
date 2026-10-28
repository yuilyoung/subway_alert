const {saveFavorite}=require('./domain');

// Capture the form before awaiting storage; edits always use the latest saved record.
async function saveFavoriteDraft({readState,writeState,createId},draft,editingId=null){
 const captured={...draft,schedule:{...draft?.schedule,
  days:Array.isArray(draft?.schedule?.days)?[...draft.schedule.days]:draft?.schedule?.days}};
 const current=await readState();
 if(editingId===null)captured.id=createId();
 const next={...current,favorites:saveFavorite(current.favorites||[],captured,editingId)};
 await writeState(next);
 return next;
}
module.exports={saveFavoriteDraft};
