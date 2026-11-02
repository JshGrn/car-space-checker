const $ = id => document.getElementById(id);
let photo=null, imageData='', points=[], reference=[], rearRange=[], preferred=[], drawing='zone';
let detections=[], placement=[], imageRatio=null, generation=0, loading=0, checking=false;
const canvas=$('canvas'), ctx=canvas.getContext('2d');
const message=text=>{$('message').textContent=text;};
function invalidate(){generation++;detections=[];placement=[];$('result').hidden=true;$('detections').replaceChildren();}
function configuration(){return {camera_id:'floodlight',zone:points,reference,aspect_ratio:imageRatio,
  mode:$('method').value,reference_kind:$('reference-kind').value,clearance:Number($('clearance').value)/100,
  charging:rearRange.length?{rear_range:rearRange,preferred:preferred[0]||null}:null,
  live_enabled:$('live-enabled').checked};}
function update(){
  const enough=photo&&points.length>=3&&($('method').value!=='gap'||(points.length===4&&reference.length===2));
  $('analyze').disabled=!enough||checking;$('save').disabled=!enough;
  $('calibration').textContent=`Zone: ${points.length}/4 · Reference: ${reference.length}/2 · Rear limits: ${rearRange.length}/2`;
  $('clearance-label').textContent=`${$('clearance').value}%`;
  for(const mode of ['zone','reference','rear','preferred']) $('mark-'+mode).classList.toggle('selected',drawing===mode);
  $('mark-help').textContent={zone:'Mark four road-plane corners: far left → far right → near right → near left. The first edge follows the kerb.',reference:'Mark both ends of your parked car’s full length projected onto the road, or a gap you know fits.',rear:'Mark the leftmost and rightmost allowed REAR positions on the road. Start just right of the bin’s position along the kerb, then mark the furthest cable reach.',preferred:'Mark the ideal centre of the car on the road in front of the right-hand wall.'}[drawing];
  draw();
}
function draw(){
  if(!photo)return;
  ctx.drawImage(photo,0,0,canvas.width,canvas.height);
  const line=(coords,colour,close,label)=>{
    if(!coords.length)return;
    ctx.beginPath();ctx.strokeStyle=colour;ctx.lineWidth=Math.max(3,canvas.width/500);
    coords.forEach(([x,y],i)=>i?ctx.lineTo(x*canvas.width,y*canvas.height):ctx.moveTo(x*canvas.width,y*canvas.height));
    if(close&&coords.length>2){ctx.closePath();ctx.fillStyle=colour+'24';ctx.fill();}ctx.stroke();
    coords.forEach(([x,y],i)=>{ctx.beginPath();ctx.arc(x*canvas.width,y*canvas.height,6,0,Math.PI*2);ctx.fillStyle=colour;ctx.fill();ctx.font='bold 18px system-ui';ctx.fillText(label||String(i+1),x*canvas.width+10,y*canvas.height-8);});
  };
  for(const d of detections){ctx.strokeStyle='#ffd190';ctx.lineWidth=2;ctx.strokeRect(d.box[0]*canvas.width,d.box[1]*canvas.height,(d.box[2]-d.box[0])*canvas.width,(d.box[3]-d.box[1])*canvas.height);}
  line(points,'#a9edc1',true);line(reference,'#7abaff',false);line(rearRange,'#e4a2ff',false,'rear');line(preferred,'#ffffff',false,'ideal');line(placement,'#ffdd55',false,'candidate');
}
async function loadImage(blob,name){
  const loadId=++loading;invalidate();update();
  if(blob.size>10000000)throw new Error('Please use an image smaller than 10 MB.');
  const source=await new Promise((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(reader.result);reader.onerror=()=>reject(new Error('Could not read image.'));reader.readAsDataURL(blob);});
  const next=await new Promise((resolve,reject)=>{const im=new Image();im.onload=()=>resolve(im);im.onerror=()=>reject(new Error('Use a JPEG or PNG image.'));im.src=source;});
  if(loadId!==loading)return false;
  const ratio=next.naturalWidth/next.naturalHeight;
  if(imageRatio&&Math.abs(ratio/imageRatio-1)>.02&&points.length){message('Different image proportions: all marks cleared. Use the same uncropped floodlight view.');points=[];reference=[];rearRange=[];preferred=[];}
  invalidate();photo=next;imageData=source.split(',')[1];imageRatio=ratio;
  canvas.width=next.naturalWidth;canvas.height=next.naturalHeight;$('empty').hidden=true;$('image-name').textContent=name;update();return true;
}
async function api(url,payload){const response=await fetch(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});const result=await response.json();if(!response.ok)throw new Error(result.error||'Request failed.');return result;}
$('image-file').addEventListener('change',async e=>{if(e.target.files[0])try{message('');await loadImage(e.target.files[0],e.target.files[0].name);}catch(error){message(error.message);}});
canvas.addEventListener('pointerdown',event=>{
  if(!photo)return;
  const rect=canvas.getBoundingClientRect(), point=[Math.max(0,Math.min(1,(event.clientX-rect.left)/rect.width)),Math.max(0,Math.min(1,(event.clientY-rect.top)/rect.height))];
  if(drawing==='zone'){if(points.length>=4)return message('Four corners marked. Undo a point or clear the marks to redraw.');points.push(point);}
  else if(drawing==='reference'){if(reference.length>=2)reference=[];reference.push(point);}
  else if(drawing==='rear'){if(rearRange.length>=2)rearRange=[];rearRange.push(point);}
  else preferred=[point];
  invalidate();message('');update();
});
for(const mode of ['zone','reference','rear','preferred'])$('mark-'+mode).onclick=()=>{drawing=mode;update();};
$('undo').onclick=()=>{({zone:points,reference,rear:rearRange,preferred}[drawing]).pop();invalidate();update();};
$('clear').onclick=()=>{points=[];reference=[];rearRange=[];preferred=[];invalidate();update();};
$('method').onchange=()=>{invalidate();update();};$('clearance').oninput=()=>{invalidate();update();};
$('live-enabled').onchange=()=>{invalidate();update();};
$('reference-kind').onchange=()=>{$('clearance').value=$('reference-kind').value==='parked_car'?20:0;invalidate();update();};
$('analyze').onclick=async()=>{
  invalidate();const revision=generation;checking=true;update();$('analyze').textContent='Checking locally…';message('');
  try{
    const result=await api('api/preview',{image:imageData,settings:configuration()});
    if(revision!==generation)return;
    detections=result.detections;placement=result.placement_points||[];draw();$('result').hidden=false;
    $('result-title').textContent={clear:result.charging_checked?'Charging position appears available':'Space appears available',occupied:result.charging_checked?'No charging position fits':'Not enough clear space',uncertain:'Unable to confirm space'}[result.assessment];
    const estimate=result.gap_car_lengths==null?'':`Estimated gap: ${result.gap_car_lengths.toFixed(2)} × your reference; required: ${result.required_car_lengths.toFixed(2)} ×. `;
    const direction=result.placement?`Suggested direction: facing ${result.placement.facing}. `:'';
    $('result-detail').textContent=estimate+direction+result.reason+' Preview only — live sensor unchanged.';
    $('download').href=canvas.toDataURL('image/jpeg',.9);$('detections').replaceChildren();
  }catch(error){if(revision===generation)message(error.message);}finally{checking=false;$('analyze').textContent='Check this image';update();}
};
$('save').onclick=async()=>{const revision=generation;try{await api('api/settings',configuration());message(revision===generation?'Floodlight setup saved. Live confirmation has been reset.':'Earlier marks were saved. Save again to apply your latest changes.');await refreshStatus(false);}catch(error){message(error.message);}};
async function loadExample(key){try{
  const response=await fetch('api/example/'+key);if(!response.ok)throw new Error('Choose your own floodlight image.');const sample=await response.json();
  const imageResponse=await fetch(sample.image);if(!imageResponse.ok)throw new Error('Example image unavailable.');
  if(await loadImage(await imageResponse.blob(),sample.label)){
    applySettings(sample.settings);drawing='reference';update();message('Draft marks use your car for size and your labelled charging positions for reach. Green: zone. Blue: car length. Purple: rear limits. White: preferred centre. Review before enabling live observations.');}
}catch(error){message(error.message);}}
$('load-sample').onclick=()=>loadExample('empty-day');
$('example').onchange=()=>{if($('example').value)loadExample($('example').value);};
function applySettings(settings){if(!settings)return;invalidate();points=settings.zone;reference=settings.reference||[];rearRange=settings.charging?.rear_range||[];preferred=settings.charging?.preferred?[settings.charging.preferred]:[];imageRatio=settings.aspect_ratio;$('method').value=settings.mode;$('reference-kind').value=settings.reference_kind||'known_fit';$('clearance').value=(settings.clearance||0)*100;$('live-enabled').checked=settings.live_enabled;update();}
async function refreshStatus(loadSettings=false){const revision=generation;try{const response=await fetch('api/status'),status=await response.json();$('model-status').textContent=status.model_ready?'● Local model ready':'Model download required';$('live-state').textContent={unknown:'Awaiting fresh footage',unavailable:'Footage expired',available:'Space available',occupied:'Space occupied'}[status.state]||status.state;$('capture-status').textContent=(status.capture?.message||'Ring capture is configured in the HAOS add-on settings.')+(status.capture?.captured_at?' Last frame: '+new Date(status.capture.captured_at*1000).toLocaleString()+'.':'');$('load-recording').disabled=!status.capture?.frame_available;$('live-detail').textContent=status.mqtt_connected?'Connected to Home Assistant MQTT':'MQTT not connected · preview available';if(loadSettings&&revision===generation)applySettings(status.settings);}catch(error){$('live-state').textContent='Service unavailable';}}
refreshStatus(true);setInterval(()=>refreshStatus(false),5000);update();

$('load-recording').onclick=async()=>{try{const response=await fetch('api/source/frame');if(!response.ok)throw new Error('No recording frame has arrived yet.');await loadImage(await response.blob(),'Latest received recording frame — preview only; see capture time above');message('Check that this is the same uncropped floodlight view used for calibration. Loading it does not publish availability.');}catch(error){message(error.message);}};
