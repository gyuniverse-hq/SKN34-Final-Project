import { catalogMatches, makeupControls } from '@/lib/arMakeupControls';
import { intensityTarget, type ConfirmPaint, type ControlArgs, type ControlOperation } from '@/lib/arControl';
import { useMakeupStore } from '@/store/makeupStore';
import type { Product } from '@/types';

const template = (require('@/lib/devCatalog/oyCatalog.json') as {products:Product[]}).products.find(p => p.texture && p.shades.length)!;
const product = (id:string, zone:Product['makeupZone'], hex:string, texture:Product['texture']='matte'):Product => ({
  ...template,id,makeupZone:zone,name:id,nameKo:id,texture,shades:[{...template.shades[0],id:'01',name:id+' 01',hex}],
});
const a=product('rose','lip','#ed74a2'), b=product('pink','lip','#f387b3');
const oil=product('lip oil','lip','#ed74a2','glossy'), blush=product('blush','blush','#dc725d');
const base=product('base','foundation','#d6ba9d'), shadow=product('shadow','eyeshadow','#88796a');
const high=product('highlight','highlighter','#eadcca'), liner=product('liner','eyeliner','#45312c');
const catalog=[a,b,oil,blush,base,shadow,high,liner];
const swatch=(p:Product)=>({product:p,shade:p.shades[0]});
const wear=(p:Product)=>useMakeupStore.getState().applyShade(p,p.shades[0]);
const store=useMakeupStore.getState;
const frame:ConfirmPaint=async ()=>'rendered';
it('rounds half of the last applied change to hundredths and respects slider limits', () => {
  expect(intensityTarget(0.40, 'down', 0, undefined, 0.45 - 0.40)).toBe(0.37);
  expect(intensityTarget(0.37, 'down', 0, undefined, 0.01)).toBe(0.36);
  expect(intensityTarget(0.17, 'down', 0.15, undefined, 0.30)).toBe(0.15);
  expect(intensityTarget(0.99, 'up', 0, undefined, 0.10)).toBe(1);
});
function run(choice:string, opts:Partial<Parameters<typeof makeupControls>[1]>={}, args:ControlArgs={}, confirm=frame) {
  const choices=new Map<string,ControlOperation>();
  makeupControls(choices,{products:catalog,ready:true,tracking:true,swatchesOnly:false,display:[swatch(a),swatch(b)],center:0,faceShape:null,...opts});
  return choices.get(choice)!(args,confirm);
}
beforeEach(()=>store().reset());
it('finds catalog shade names across spaces and keeps duplicate identities', () => {
  const named = {...a,shades:[{...a.shades[0],name:'Fade Red'}]};
  const duplicate = {...named,id:'another-product'};
  expect(catalogMatches([named,duplicate],'fade red 발라줘').catalogNameMatches.map(m=>m.productId)).toEqual([a.id,duplicate.id]);
  expect(catalogMatches([named],'FADE RED 발라줘').catalogNameMatches[0].shadeId).toBe(named.shades[0].id);
  expect(catalogMatches([named],'차분한 레드로 발라줘').catalogNameMatches).toEqual([]);
});
it('grounds the product in its spoken title and finds a number within that product', () => {
  const tint = {...a, brand:'Aster', name:'[NEW] Aster Fixing Tint 4g', nameKo:'[기획] 애스터 픽싱 틴트 4g',
    shades:[{...a.shades[0],id:'07',name:'Soft Rose'}]};
  const nearby = {...tint, id:'nearby', name:'Aster Soft Fixing Tint 4g', nameKo:'애스터 소프트 픽싱 틴트 4g'};
  const result = catalogMatches([tint, nearby], '애스터 픽싱 틴트에 7호 발라봐.');
  expect(result.catalogProductMatches).toMatchObject([{productId:tint.id,reference:'애스터 픽싱 틴트'}]);
  expect(result.catalogNameMatches).toMatchObject([{productId:tint.id,shadeId:'07'}]);
  expect(catalogMatches([tint], '애스터 픽싱 틴트 17호').catalogNameMatches).toEqual([]);
});

it('chooses a shade within the requested product using visible makeup and returns its number', async () => {
  const requested = {...b, shades:[
    {...b.shades[0], id:'09', name:'Cool Pink', hex:'#f387b3'},
    {...b.shades[0], id:'11', name:'Muted Peach', hex:'#dc725d'},
  ]};
  wear(blush);
  const confirm = jest.fn(frame);
  const result = await run('apply_shade/product_pick', {products:[requested, a, blush]}, {productId:requested.id}, confirm);
  expect(result).toMatchObject({status:'APPLIED', featuredShade:{shade:'Muted Peach',shadeNumber:'11'}});
  expect(store().selections.lip).toEqual({productId:requested.id,shadeId:'11'});
  expect(store().selections.blush?.productId).toBe(blush.id);
  expect(confirm).toHaveBeenCalledTimes(1);
  expect(await run('apply_shade/product_pick', {products:[requested]}, {productId:'missing'})).toMatchObject({status:'REJECTED'});
  expect(store().selections.lip).toEqual({productId:requested.id,shadeId:'11'});
});
it('only applies a named shade when the full shade name identifies one swatch', async () => {
  const duplicate = {...b, id: 'other'};
  wear(a);
  expect(await run('apply_shade/lip/named', {}, { name: b.name })).toEqual({
    status: 'REJECTED', reason: 'no matching shade',
  });
  expect(await run('apply_shade/lip/named', { products: [...catalog, duplicate] }, { name: b.shades[0].name }))
    .toEqual({ status: 'REJECTED', reason: 'ambiguous shade' });
  expect(store().selections.lip).toEqual({productId: a.id, shadeId: a.shades[0].id});
  expect(await run('apply_shade/lip/named', {}, { name: b.shades[0].name.toUpperCase().replace(' ', '') }))
    .toMatchObject({ status: 'APPLIED' });
  expect(store().selections.lip).toEqual({productId: b.id, shadeId: b.shades[0].id});
});
it('replays the exact entry by zone or across zones and only counts committed changes', async () => {
  useMakeupStore.setState({tryOnHistory:[]});
  try {
    wear(a);
    wear(a);
    store().setIntensity('lip', 0.4);
    wear(blush);
    expect(await run('apply_shade/lip/named', {}, {name:b.shades[0].name}, async ()=>'failed')).toMatchObject({status:'FAILED'});
    expect(await run('reapply_try_on/lip', {}, {ordinal:2})).toMatchObject({status:'REJECTED'});
    wear(b);
    const history = store().tryOnHistory;
    expect(history?.map(entry => entry.productId)).toEqual([a.id, blush.id, b.id]);
    expect(await run('reapply_try_on/all', {}, {ordinal:2})).toMatchObject({status:'NO_CHANGE'});
    expect(await run('reapply_try_on/lip', {products:[b]}, {ordinal:1})).toMatchObject({status:'REJECTED'});
    expect(store().tryOnHistory).toBe(history);
    expect(await run('reapply_try_on/lip', {}, {ordinal:1})).toMatchObject({status:'APPLIED'});
    expect(store().tryOnHistory?.map(entry => entry.productId)).toEqual([a.id, blush.id, b.id, a.id]);
  } finally {
    useMakeupStore.setState({tryOnHistory:null});
  }
});
it('changes the recommended cheek shade when only the lip changes and ignores invisible layers', async () => {
  const cool = product('cool cheek','blush','#d096af'), warm = product('warm cheek','blush','#e09779');
  const options = {products:[warm,cool]};
  wear(product('plum','lip','#ae5c92'));
  expect(await run('apply_shade/blush/pick',options)).toMatchObject({featuredShade:{product:cool.name},matchedTo:[{zone:'lip'}]});
  wear(product('orange','lip','#e34517'));
  expect(await run('apply_shade/blush/pick',options)).toMatchObject({featuredShade:{product:warm.name},matchedTo:[{zone:'lip'}]});
  store().setIntensity('lip',0);
  expect(await run('apply_shade/blush/pick',options)).not.toHaveProperty('matchedTo');
});
it('matches a cheek recommendation to the worn lip even when another color is visible', async () => {
  const cool = product('cool cheek','blush','#d096af'), warm = product('warm cheek','blush','#e09779');
  wear(product('warm lip','lip','#e34517'));
  wear(product('cool shadow','eyeshadow','#5143af'));
  expect(await run('apply_shade/blush/pick',{products:[cool,warm]})).toMatchObject({
    featuredShade:{product:warm.name}, matchedTo:[{zone:'lip'}],
  });
});
it('previews one ranked pink, not the first catalog entry, and leaves the palette and other zones alone', async()=>{
  const exact = product('true pink','lip','#ef79ab');
  const unknown = product('missing color','lip','#ef79ab');
  unknown.shades[0].colorSource = 'placeholder';
  wear(blush);
  const beforeBlush = store().makeup.blush;
  const confirm = jest.fn<ReturnType<ConfirmPaint>,Parameters<ConfirmPaint>>(async () => 'rendered');
  const out = await run('apply_shade/lip/by_color',{products:[a,oil,unknown,exact]}, {family:'pink'},confirm);
  expect(confirm).toHaveBeenCalledTimes(1);
  expect(out).toMatchObject({status:'APPLIED',featuredShade:{product:exact.name,shade:exact.shades[0].name,family:'pink'}});
  expect(store().selections.lip?.productId).toBe(exact.id);
  expect(store().makeup.blush).toBe(beforeBlush);
  expect(await run('apply_shade/lip/by_color',{products:[oil,unknown]}, {family:'pink'},confirm)).toMatchObject({status:'OK',data:{applied:false}});
  expect(confirm).toHaveBeenCalledTimes(1);
  expect(await run('apply_shade/lip/by_color',{products:[a]}, {family:'pink'},async()=>'failed')).toMatchObject({status:'FAILED'});
  expect(store().selections.lip?.productId).toBe(exact.id);
});
it('combines independent color preferences and leaves the worn shade intact when no shade qualifies', async () => {
  const pink = product('muted pink','lip','#c57e9e');
  const nude = product('light nude','lip','#dfb1a8');
  const options = {products:[a,pink,nude]};
  expect(await run('find_shades/lip/by_color', options, {chroma:'muted'})).toMatchObject({data:{count:2}});
  expect(store().selections.lip).toBeUndefined();
  expect(await run('apply_shade/lip/by_color', options, {lightness:'light',chroma:'muted'}))
    .toMatchObject({featuredShade:{product:nude.name,family:'nude',lightness:'light',chroma:'muted'}});
  expect(await run('apply_shade/lip/by_color', options, {family:'pink',chroma:'muted'}))
    .toMatchObject({featuredShade:{product:pink.name,family:'pink',chroma:'muted'}});
  expect(await run('apply_shade/lip/by_color', options, {family:'pink',lightness:'deep',chroma:'muted'}))
    .toMatchObject({status:'OK',data:{count:0,applied:false}});
  expect(await run('apply_shade/lip/by_color', options)).toMatchObject({status:'REJECTED'});
  expect(store().selections.lip?.productId).toBe(pink.id);
});
it.each([[0.55,0.45,'APPLIED'],[0.15,0.15,'NO_CHANGE'],[0.20,0.15,'APPLIED']] as const)('reduces blush %s within the direct slider range',async(start,end,status)=>{
  wear(blush);store().setIntensity('blush',start);
  expect(await run('adjust_intensity/blush/down')).toMatchObject({status});
  expect(store().makeup.blush?.intensity).toBe(end);
  expect(store().selections.blush?.productId).toBe(blush.id);
});
it('does not exceed upper limit or apply a paletted product to fill an empty layer',async()=>{
  expect(await run('adjust_intensity/blush/down')).toMatchObject({status:'REJECTED'});
  expect(await run('set_intensity/foundation/half')).toMatchObject({status:'REJECTED'});
  wear(blush);store().setIntensity('blush',1);
  expect(await run('adjust_intensity/blush/up')).toMatchObject({status:'NO_CHANGE'});
  wear(base);store().setIntensity('foundation',0.8);
  expect(await run('set_intensity/foundation/half')).toMatchObject({status:'APPLIED',after:{intensity:0.4}});
  expect(await run('set_intensity/foundation/absolute',{}, {value:0.4})).toMatchObject({status:'NO_CHANGE'});
});
it('lists only real matching colors, distinguishing an empty catalog from a failed one',async()=>{
  wear(a);
  const before=store().makeup;
  expect(await run('find_shades/lip/pink')).toMatchObject({status:'OK',data:{count:2,shades:[{productId:a.id},{productId:b.id}]}});
  expect(await run('find_shades/lip/pink',{products:[]})).toMatchObject({status:'OK',data:{count:0,shades:[]}});
  expect(await run('find_shades/lip/pink',{ready:false})).toMatchObject({status:'REJECTED'});
  expect(store().makeup).toBe(before);
});
it('selects the center rather than the worn shade, preserving same, empty, and one-shade cases',async()=>{
  wear(a);
  expect(await run('apply_shade/palette_center',{center:1})).toMatchObject({status:'APPLIED',before:{product:{productId:a.id}},after:{product:{productId:b.id}}});
  expect(await run('apply_shade/palette_center',{center:1})).toMatchObject({status:'NO_CHANGE'});
  expect(await run('step_shade/next',{display:[swatch(b)]})).toMatchObject({status:'NO_CHANGE'});
  for(const op of ['apply_shade/palette_center','step_shade/next'])
    expect(await run(op,{display:[]})).toMatchObject({status:'REJECTED'});
  expect(store().selections.lip?.productId).toBe(b.id);
});
it('removes only lip care, and repeated removal has no effect',async()=>{
  wear(a);wear(oil);
  expect(await run('clear_layer/lipCare')).toMatchObject({status:'APPLIED',after:{lipCare:null,product:{productId:a.id}}});
  expect(await run('clear_layer/lipCare')).toMatchObject({status:'NO_CHANGE'});
  expect(store().makeup.lipCare).toBeNull();
});
it('leaves the highlighter preset when switching to a region already in the face layout', async () => {
  wear(high);
  store().patchGeometry('highlighter', { hlStyle: 'nose_tip' });
  expect(await run('set_style/highlighter/nose_bridge_on')).toMatchObject({ status: 'APPLIED' });
  expect(store().makeup.highlighter?.geometry?.hlStyle).toBeUndefined();
  expect(store().makeup.highlighter?.geometry?.areas).toContain('nose_bridge');
  expect(await run('set_style/highlighter/nose_bridge_on')).toMatchObject({ status: 'NO_CHANGE' });
});

it('changes only the requested geometry and restores an original layer exactly',async()=>{
  expect(await run('set_style/eyeshadow/matte')).toMatchObject({status:'REJECTED'});
  wear(shadow);wear(high);wear(liner);
  store().patchGeometry('eyeshadow',{shadowFinish:'shimmer'});
  useMakeupStore.setState({lookOrigin:{makeup:store().makeup,selections:store().selections}});
  expect(await run('set_style/eyeshadow/matte')).toMatchObject({status:'APPLIED',after:{geometry:{shadowFinish:'matte'}}});
  expect(await run('set_style/eyeshadow/matte')).toMatchObject({status:'NO_CHANGE'});
  expect(await run('set_style/eyeliner/cat_wing')).toMatchObject({status:'APPLIED',after:{geometry:{angle:15}}});
  expect(await run('set_style/highlighter/nose_bridge_off')).toMatchObject({status:'APPLIED',after:{geometry:{areas:['forehead','under_eye','philtrum','chin']}}});
  const unchanged=store().makeup.eyeliner;
  store().setIntensity('eyeshadow',0.22);
  expect(await run('restore_makeup/eyeshadow')).toMatchObject({status:'APPLIED'});
  expect(store().makeup.eyeshadow).toEqual(store().lookOrigin!.makeup.eyeshadow);
  expect(store().makeup.eyeliner).toBe(unchanged);
  expect(await run('restore_makeup/eyeshadow')).toMatchObject({status:'NO_CHANGE'});
});
it.each([['unknown','UNKNOWN'],['failed','FAILED'],['stale','REJECTED']] as const)('never commits a %s frame',async(outcome,status)=>{
  wear(a);
  expect(await run('apply_shade/product_shade',{}, {productId:b.id,shadeId:'01'},async()=>outcome)).toMatchObject({status});
  expect(store().selections.lip?.productId).toBe(a.id);
});
it('retains a manual edit made between submission and renderer acknowledgement',async()=>{
  wear(a);
  expect(await run('adjust_intensity/lip/down',{}, {},async()=>{store().setIntensity('lip',0.9);return 'rendered';})).toMatchObject({status:'REJECTED'});
  expect(store().makeup.lip?.intensity).toBe(0.9);
});
