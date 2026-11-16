// Runs inside the comparison WebView. Only its microphone track is added to the peer.
export const VOICE_SESSION_HTML = `<!doctype html><meta charset="utf-8"><script>
'use strict';
const post = (type, data = {}) => window.ReactNativeWebView.postMessage(JSON.stringify({type, ...data}));
let pc, channel, mic, ctx, input, output, lastVoice, firstAudio, applied, ready = false;
let timer, deadline, toolCall, running = false;
const seen = new Set();
function close() {
  running = false;
  clearInterval(timer); clearTimeout(deadline);
  mic?.getTracks().forEach(t => t.stop()); pc?.close(); ctx?.close().catch(() => {});
}
function fail() { if (running) { close(); post('failed'); } }
function meter(stream, play) {
  const source = ctx.createMediaStreamSource(stream), analyser = ctx.createAnalyser();
  analyser.fftSize = 512; source.connect(analyser);
  if (play) {
    const silent = ctx.createGain(); silent.gain.value = 0;
    analyser.connect(silent); silent.connect(ctx.destination);
  }
  const samples = new Float32Array(analyser.fftSize);
  return () => {
    analyser.getFloatTimeDomainData(samples);
    let power = 0;
    for (const s of samples) power += s*s;
    return power / samples.length > 0.0001;
  };
}
function report() {
  if (lastVoice != null && applied != null && firstAudio != null)
    post('metrics', {screenMs: Math.round(applied-lastVoice), speechMs: Math.round(firstAudio-lastVoice)});
}
window.startVoice = async () => {
  running = true;
  try {
    deadline = setTimeout(() => {
      if (firstAudio != null) { close(); post('ended'); } else fail();
    }, 60000);
    mic = await navigator.mediaDevices.getUserMedia({video:false, audio:{echoCancellation:true}});
    if (!running) { close(); return; }
    ctx = new AudioContext(); await ctx.resume(); input = meter(mic, false);
    pc = new RTCPeerConnection();
    pc.ontrack = e => {
      const remote = e.streams[0] || new MediaStream([e.track]);
      const player = document.createElement('audio');
      player.autoplay = true; player.srcObject = remote; document.body.append(player);
      player.play().catch(fail);
      output = meter(remote, true);
    };
    const track = mic.getAudioTracks()[0]; track.enabled = false;
    pc.addTrack(track, mic);
    pc.onconnectionstatechange = () => { if (pc.connectionState === 'failed') fail(); };
    channel = pc.createDataChannel('oai-events');
    channel.onclose = fail;
    channel.onmessage = ({data}) => {
      try {
        const envelope = JSON.parse(data);
        if (envelope.type === 'error' || envelope.type === 'session.closed') return fail();
        if (!ready && ['session.created', 'session.started'].includes(envelope.type)) {
          ready = true; track.enabled = true; post('ready');
        }
        const live = envelope.type === 'response.event';
        const event = live ? envelope.event : envelope;
        const item = event.type === 'response.output_item.done' ? event.item : null;
        if (!item || item.type !== 'function_call' || item.name !== 'ar_control' || seen.has(item.call_id)) return;
        seen.add(item.call_id);
        if (toolCall) { fail(); return; }
        track.enabled = false;
        toolCall = {live, id:item.call_id};
        post('tool', {args:JSON.parse(item.arguments)});
      } catch { fail(); }
    };
    timer = setInterval(() => {
      const now = performance.now();
      if (ready && !toolCall && input() && firstAudio == null) lastVoice = now;
      if (lastVoice != null && firstAudio == null && output?.()) { firstAudio = now; post('speaking'); report(); }
    }, 20);
    await pc.setLocalDescription(await pc.createOffer());
    if (pc.iceGatheringState !== 'complete') await new Promise(resolve => {
      const done = () => { clearTimeout(timeout); pc.removeEventListener('icegatheringstatechange', check); resolve(); };
      const check = () => { if (pc.iceGatheringState === 'complete') done(); };
      const timeout = setTimeout(done, 3000); pc.addEventListener('icegatheringstatechange', check);
    });
    if (running) post('offer', {sdp:pc.localDescription.sdp});
  } catch { fail(); }
};
window.setAnswer = sdp => pc.setRemoteDescription({type:'answer',sdp}).catch(fail);
window.toolResult = result => {
  if (!running || !toolCall) return;
  if (result.status === 'APPLIED') { applied = performance.now(); report(); }
  const item = {type:'function_call_output', call_id:toolCall.id, output:JSON.stringify(result)};
  channel.send(JSON.stringify({type:toolCall.live?'response.item.create':'conversation.item.create', item}));
  channel.send(JSON.stringify({type:'response.create'}));
};
window.addEventListener('pagehide',close);
post('loaded');
</script>`;
