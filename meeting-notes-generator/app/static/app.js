const $ = (id) => document.getElementById(id);
const transcript = $('transcript');
let currentNotes = null;
const fileInput = $("fileInput");
const dropZone = $("dropZone");

const sample = `Maya: Thanks everyone. The beta onboarding completion rate is 62%, below our 70% target. Users most often leave at workspace setup.\nJon: We can reduce the setup form from eight fields to four. I can have the new flow ready by Friday, September 12.\nMaya: Approved. Let's ship it behind a feature flag to 20% of new accounts.\nPriya: I'll prepare the tracking dashboard and confirm the event names with Jon by Wednesday.\nJon: We also need updated help-center screenshots before the wider launch.\nMaya: Good call. Let's review beta results next Monday and decide whether to expand the rollout.`;

transcript.addEventListener('input', () => {
  const words = transcript.value.trim() ? transcript.value.trim().split(/\s+/).length : 0;
  $('wordCount').textContent = `${words} word${words === 1 ? '' : 's'}`;
});

$('sampleBtn').addEventListener('click', () => {
  $('meetingTitle').value = 'Product onboarding sync'; transcript.value = sample;
  transcript.dispatchEvent(new Event('input')); transcript.focus();
});

function showError(message) {
  $('error').textContent = message;
  $('error').classList.remove('hidden');
}

async function uploadFile(file) {
  if (!file) return;
  $('error').classList.add('hidden');
  $('uploadTitle').textContent = `Reading ${file.name}…`;
  $('uploadHint').textContent = 'Extracting transcript text';
  $('uploadCheck').classList.add('hidden');
  $('status').textContent = 'Uploading'; dropZone.disabled = true;
  const form = new FormData(); form.append('file', file);
  try {
    const res = await fetch('/api/upload', { method: 'POST', body: form });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || 'Unable to read this transcript.');
    transcript.value = data.transcript; transcript.dispatchEvent(new Event('input'));
    if (!$('meetingTitle').value.trim()) $('meetingTitle').value = data.title;
    $('uploadTitle').textContent = data.filename;
    $('uploadHint').textContent = `${data.characters.toLocaleString()} characters extracted · Ready to review`;
    $('uploadCheck').classList.remove('hidden'); $('status').textContent = 'Transcript ready'; transcript.focus();
  } catch (err) {
    $('uploadTitle').innerHTML = 'Drop a transcript here <span class="font-normal text-ink/50">or browse</span>';
    $('uploadHint').textContent = 'TXT, VTT, SRT, DOCX or PDF · up to 10 MB';
    $('status').textContent = 'Needs attention'; showError(err.message);
  } finally { dropZone.disabled = false; fileInput.value = ''; }
}

dropZone.addEventListener('click', () => fileInput.click());
fileInput.addEventListener('change', () => uploadFile(fileInput.files[0]));
['dragenter','dragover'].forEach(name => dropZone.addEventListener(name, event => { event.preventDefault(); dropZone.classList.add('border-pine','bg-sage/70'); }));
['dragleave','drop'].forEach(name => dropZone.addEventListener(name, event => { event.preventDefault(); dropZone.classList.remove('border-pine','bg-sage/70'); }));
dropZone.addEventListener('drop', event => uploadFile(event.dataTransfer.files[0]));
function list(items, accent=false) {
  if (!items.length) return '<li class="text-sm text-ink/40">None identified</li>';
  return items.map(x => `<li class="flex gap-3 text-sm leading-6 text-ink/70"><span class="mt-2 h-1.5 w-1.5 shrink-0 rounded-full ${accent?'bg-coral':'bg-pine'}"></span><span>${escapeHtml(x)}</span></li>`).join('');
}
function escapeHtml(value='') { const el=document.createElement('div'); el.textContent=value; return el.innerHTML; }

function render(data) {
  currentNotes=data; $('empty').classList.add('hidden'); $('results').classList.remove('hidden');
  $('resultTitle').textContent=data.title; $('overview').textContent=data.overview;
  $('keyPoints').innerHTML=list(data.key_points); $('decisions').innerHTML=list(data.decisions,true); $('followups').innerHTML=list(data.follow_ups);
  $('actions').innerHTML=data.action_items.length ? data.action_items.map(a=>`<div class="grid items-start gap-3 rounded-xl bg-cream p-4 sm:grid-cols-[minmax(0,1fr)_auto]"><p class="min-w-0 text-sm font-medium leading-6">${escapeHtml(a.task)}</p><div class="flex flex-wrap items-start justify-start gap-2 text-xs sm:max-w-64 sm:justify-end"><span class="whitespace-nowrap rounded-full bg-sage px-3 py-1.5 leading-none text-pine">${escapeHtml(a.owner)}</span><span class="whitespace-nowrap rounded-full bg-white px-3 py-1.5 leading-none text-ink/55">${escapeHtml(a.due_date)}</span></div></div>`).join('') : '<p class="text-sm text-ink/40">None identified</p>';
}

$('generateBtn').addEventListener('click', async () => {
  $('error').classList.add('hidden');
  if (transcript.value.trim().length < 20) { $('error').textContent='Please add a longer transcript before generating notes.'; $('error').classList.remove('hidden'); return; }
  const btn=$('generateBtn'); btn.disabled=true; btn.querySelector('span').textContent='Analyzing…'; $('status').textContent='Generating';
  try {
    const res=await fetch('/api/generate',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({transcript:transcript.value,meeting_title:$('meetingTitle').value||'Untitled meeting',tone:$('tone').value})});
    const data=await res.json(); if(!res.ok) throw new Error(data.detail||'Unable to generate notes.'); render(data); $('status').textContent='Notes ready';
  } catch(err) { $('error').textContent=err.message; $('error').classList.remove('hidden'); $('status').textContent='Needs attention'; }
  finally { btn.disabled=false; btn.querySelector('span').textContent='Generate notes'; }
});

$('copyBtn').addEventListener('click', async () => {
  if(!currentNotes) return;
  const n=currentNotes; const actions=n.action_items.map(a=>`- ${a.task} — ${a.owner} (${a.due_date})`).join('\n');
  const text=`# ${n.title}\n\n## Overview\n${n.overview}\n\n## Key points\n${n.key_points.map(x=>'- '+x).join('\n')}\n\n## Decisions\n${n.decisions.map(x=>'- '+x).join('\n')}\n\n## Action items\n${actions}\n\n## Follow-ups\n${n.follow_ups.map(x=>'- '+x).join('\n')}`;
  await navigator.clipboard.writeText(text); $('copyBtn').textContent='Copied'; setTimeout(()=>$('copyBtn').textContent='Copy notes',1400);
});
