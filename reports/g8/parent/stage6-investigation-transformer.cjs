// Diagnostic source edits exist only in the compiled investigation bundle.
const upstream = require('@expo/metro-config/babel-transformer');
const fs = require('node:fs');
const path = require('node:path');
const root = path.resolve(__dirname, '../../..');
const helper = `
function __g8Phase(phase, meta = {}) {
  if (typeof window === 'undefined') return;
  const event = {at: new Date().toISOString(), phase, ...meta};
  (globalThis.__g8ProbeEvents ??= []).push(event);
  fetch('http://localhost:19833/__g8_probe', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(event)}).catch(()=>{});
}
function __g8Next() { return globalThis.__g8ProbeSeq = (globalThis.__g8ProbeSeq ?? 0) + 1; }
function __g8Route(p) { return /\\/conversations\\/[^/]+\\/requests\\//.test(p) ? 'request-status' : /\\/conversations\\/[^/]+/.test(p) ? 'detail' : p.split('?')[0].endsWith('/conversations') ? 'list' : 'other'; }
`;
function replace(src, before, after) {
  if (!src.includes(before)) throw new Error('Investigation source anchor changed: '+before.slice(0,80));
  return src.replace(before, after);
}
module.exports = { ...upstream, getCacheKey: () => 'g8-investigation-transform-v2',
  transform(args) {
    const file = path.relative(root,args.filename).replaceAll('\\','/');
    let src=args.src.replaceAll('\r\n','\n');
    if (file==='lib/api.ts') {
      src=replace(src,'async function arCredentials(): Promise<OwnedCredentials> {','async function arCredentials(__g8Parent?: number): Promise<OwnedCredentials> {\n const __g8Auth=__g8Next(); __g8Phase("auth.start",{span:__g8Auth,parent:__g8Parent});');
      src=replace(src,'const first = client ? await client.auth.getSession() : null;','__g8Phase("auth.session.before",{span:__g8Auth}); const first = client ? await client.auth.getSession() : null; __g8Phase("auth.session.after",{span:__g8Auth});');
      src=replace(src,'const verified = await client.auth.getClaims(token);','__g8Phase("auth.claims.before",{span:__g8Auth}); const verified = await client.auth.getClaims(token); __g8Phase("auth.claims.after",{span:__g8Auth});');
      src=replace(src,'const latest = await client.auth.getSession();','__g8Phase("auth.recheck.before",{span:__g8Auth}); const latest = await client.auth.getSession(); __g8Phase("auth.recheck.after",{span:__g8Auth});');
      const offset=src.indexOf('export async function apiChatUserRequest');
      let tail=src.slice(offset);
      tail=replace(tail,'const client = getSupabase();','const __g8Request=__g8Next(); __g8Phase("api.start",{span:__g8Request,route:__g8Route(path),method}); const client = getSupabase();');
      tail=replace(tail,'const credentials = await arCredentials();','const credentials = await arCredentials(__g8Request); __g8Phase("api.credentials.ready",{span:__g8Request});');
      tail=replace(tail,'const data = response.status === 204 ? undefined : await response.json();','__g8Phase("api.response",{span:__g8Request,status:response.status}); const data = response.status === 204 ? undefined : await response.json(); __g8Phase("api.body",{span:__g8Request});');
      tail=replace(tail,'const latest = await arCredentials();','__g8Phase("api.recheck.before",{span:__g8Request}); const latest = await arCredentials(__g8Request); __g8Phase("api.recheck.after",{span:__g8Request});');
      tail=replace(tail,'subscription?.unsubscribe();','__g8Phase("api.finally",{span:__g8Request}); subscription?.unsubscribe();');
      src=src.slice(0,offset)+tail;
    } else if (file==='hooks/useChatConversations.ts') {
      src=replace(src,'const updateStatus = (patch: Partial<typeof emptyStatus>) => {','const updateStatus = (patch: Partial<typeof emptyStatus>) => {\n __g8Phase("hook.status",patch);');
      src=replace(src,"const open = async (id: string, mode: 'select' | 'reload' | 'refresh' = 'select', stillSelected?: () => boolean) => {","const open = async (id: string, mode: 'select' | 'reload' | 'refresh' = 'select', stillSelected?: () => boolean) => {\n const __g8Open=__g8Next(); __g8Phase('open.start',{span:__g8Open,mode,reading:reading.current,current:current()});");
      src=replace(src,'const detail = await apiChatUserRequest<ServerConversationDetail>(\n        `/api/chat/conversations/${room.serverId}`',"__g8Phase('open.detail.before',{span:__g8Open}); const detail = await apiChatUserRequest<ServerConversationDetail>(\n        `/api/chat/conversations/${room.serverId}`");
      src=replace(src,'if (!current() || (stillSelected && !stillSelected()) || detail.conversationId !== room.serverId) return;',"__g8Phase('open.detail.after',{span:__g8Open,current:current(),selected:!stillSelected||stillSelected()}); if (!current() || (stillSelected && !stillSelected()) || detail.conversationId !== room.serverId) return;");
      src=replace(src,"if (mode !== 'reload' && opened) await recover(opened, undefined, stillSelected);","__g8Phase('open.restore',{span:__g8Open,opened:!!opened}); if (mode !== 'reload' && opened) { __g8Phase('open.recover.before',{span:__g8Open}); await recover(opened, undefined, stillSelected); __g8Phase('open.recover.after',{span:__g8Open}); }");
      src=replace(src,"if (mode === 'refresh') refreshes.delete(room.serverId);","__g8Phase('open.finally',{span:__g8Open,mode,current:current()}); if (mode === 'refresh') refreshes.delete(room.serverId);");
    } else if (file==='app/chat.tsx') {
      src=replace(src,"if (state === 'active') refreshFromServer();","__g8Phase('screen.appstate',{state}); if (state === 'active') refreshFromServer();");
      src=replace(src,'if (openingRoom.current) return;',"__g8Phase('screen.select',{alreadyOpening:!!openingRoom.current}); if (openingRoom.current) return;");
      src=replace(src,"void savedRooms.open(id, 'select', stillSelected).then((opened) => {","void savedRooms.open(id, 'select', stillSelected).then((opened) => { __g8Phase('screen.open.result',{opened:!!opened,selected:stillSelected()});");
      src=replace(src,'const send = async (textToSend = input, retryId?: string, retryCategory?: Category, automatic = false) => {',"const send = async (textToSend = input, retryId?: string, retryCategory?: Category, automatic = false) => { __g8Phase('screen.send',{automatic,retry:!!retryId});");
    } else return upstream.transform(args);
    src=helper+src;
    fs.appendFileSync(path.join(__dirname,'stage6-investigation-transformations.jsonl'),JSON.stringify({file,sourceSha256:require('node:crypto').createHash('sha256').update(args.src).digest('hex'),at:new Date().toISOString()})+'\n');
    return upstream.transform({...args,src});
  }
};
