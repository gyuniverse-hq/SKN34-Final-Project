import fs from 'fs';
const [, , src, outp] = process.argv;
const s = fs.readFileSync(src, 'utf8');
const a = s.indexOf('  const PRECISION = ['), b = s.indexOf('  function createGLRenderer()');
const { MESH_VERT, MESH_FRAG } = new Function('NL', s.slice(a, b) + '; return { MESH_VERT, MESH_FRAG };')('\n');
const html = [
  '<!doctype html><html><body><pre id="o"></pre><script>',
  'const VS=' + JSON.stringify(MESH_VERT) + ';',
  'const FS=' + JSON.stringify(MESH_FRAG) + ';',
  'const out=[];',
  'for (const kind of ["webgl","webgl2"]) {',
  '  const gl=document.createElement("canvas").getContext(kind);',
  '  if(!gl){out.push(kind+": NO CONTEXT");continue;}',
  '  out.push(kind+" units "+gl.getParameter(gl.MAX_TEXTURE_IMAGE_UNITS));',
  '  for (const variant of ["plain","XFADE"]) {',
  '    const fs = variant==="XFADE" ? "#define XFADE\\n"+FS : FS;',
  '    const sh=(t,src)=>{const x=gl.createShader(t);gl.shaderSource(x,src);gl.compileShader(x);return [x,gl.getShaderParameter(x,gl.COMPILE_STATUS),gl.getShaderInfoLog(x)];};',
  '    const v=sh(gl.VERTEX_SHADER,VS), f=sh(gl.FRAGMENT_SHADER,fs);',
  '    const p=gl.createProgram(); gl.attachShader(p,v[0]); gl.attachShader(p,f[0]); gl.linkProgram(p);',
  '    const loc=(n)=>gl.getUniformLocation(p,n)!==null;',
  '    out.push(kind+" "+variant+": vs="+v[1]+" fs="+f[1]+" link="+gl.getProgramParameter(p,gl.LINK_STATUS)+" prev="+loc("uMask2Prev")+" mix="+loc("uContourMix")+" "+(f[2]||"")+(gl.getProgramInfoLog(p)||""));',
  '  }',
  '}',
  'document.getElementById("o").textContent="RESULT "+out.join(" | ");',
  '</script></body></html>',
].join('\n');
fs.writeFileSync(outp, html);
console.log('ok');
