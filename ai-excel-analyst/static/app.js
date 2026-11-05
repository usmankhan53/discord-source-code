'use strict';
const $ = id => document.getElementById(id);
const state = { uploaded: false, busy: false, uploading: false, controller: null };

function updateControls() {
  $('question').disabled = !state.uploaded || state.uploading;
  $('send').disabled = !state.uploaded || state.busy || state.uploading;
  $('file').disabled = state.busy || state.uploading;
  $('clearChat').disabled = state.busy;
  $('stop').hidden = !state.busy;
  $('send').hidden = state.busy;
  document.querySelectorAll('#suggestions button').forEach(button => {
    button.disabled = state.busy || state.uploading;
  });
}

function scrollChat() {
  const chat = $('chat');
  if (chat.scrollHeight - chat.scrollTop - chat.clientHeight < 160) {
    chat.scrollTop = chat.scrollHeight;
  }
}

function message(text, user = false) {
  $('welcome')?.remove();
  const element = document.createElement('div');
  element.className = `message ${user ? 'user' : 'assistant'}`;
  element.textContent = text;
  $('chat').append(element);
  $('chat').scrollTop = $('chat').scrollHeight;
  return element;
}

async function responseError(response) {
  const body = await response.json().catch(() => null);
  return typeof body?.detail === 'string' ? body.detail : `Request failed (${response.status}). Please try again.`;
}

function showPreview(data) {
  const head = document.createElement('thead');
  const header = document.createElement('tr');
  data.columns.forEach(column => {
    const cell = document.createElement('th');
    cell.textContent = column;
    cell.scope = 'col';
    header.append(cell);
  });
  head.append(header);
  const body = document.createElement('tbody');
  data.preview.forEach(row => {
    const tr = document.createElement('tr');
    data.columns.forEach(column => {
      const td = document.createElement('td');
      td.textContent = row[column] ?? '—';
      tr.append(td);
    });
    body.append(tr);
  });
  $('preview').replaceChildren(head, body);
  $('previewEmpty').hidden = true;
  $('columns').replaceChildren();
  data.columns.forEach(column => {
    const badge = document.createElement('span');
    badge.className = 'max-w-full truncate rounded-md border border-slate-200 bg-slate-50 px-2 py-1 text-xs text-slate-500';
    badge.textContent = column;
    badge.title = column;
    $('columns').append(badge);
  });
}

function suggestions(data) {
  const numeric = data.columns.find(column => data.preview.some(row => typeof row[column] === 'number'));
  const questions = ['How many rows are there?', ...(numeric ? [`What is the total ${numeric}?`, `Show the top 5 by ${numeric}`] : [`What are the unique values in ${data.columns[0]}?`])];
  $('suggestions').replaceChildren();
  questions.forEach(question => {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'rounded-full border border-slate-200 px-3 py-1.5 text-left text-xs text-slate-500 transition hover:border-emerald-300 hover:text-emerald-700 disabled:opacity-40';
    button.textContent = question;
    button.addEventListener('click', () => { $('question').value = question; $('question').focus(); });
    $('suggestions').append(button);
  });
}

async function uploadFile(file) {
  if (!file || state.busy || state.uploading) return;
  if (!file.name.toLowerCase().endsWith('.xlsx') || file.size > 5 * 1024 * 1024) {
    $('uploadStatus').textContent = 'Choose an .xlsx workbook smaller than 5 MB.';
    return;
  }
  state.uploading = true;
  updateControls();
  $('uploadStatus').textContent = 'Reading your spreadsheet…';
  const form = new FormData();
  form.append('file', file);
  try {
    const response = await fetch('/upload', { method: 'POST', body: form });
    if (!response.ok) throw new Error(await responseError(response));
    const data = await response.json();
    state.uploaded = true;
    $('fileInfo').classList.remove('hidden');
    $('fileName').textContent = file.name;
    $('rowCount').textContent = data.rows.toLocaleString();
    $('columnCount').textContent = data.columns.length;
    $('uploadStatus').textContent = '✓ Spreadsheet ready to explore';
    $('connection').textContent = 'Spreadsheet connected';
    $('question').placeholder = 'What would you like to know about your data?';
    $('chat').replaceChildren();
    message(`Your spreadsheet is ready. Explore ${data.rows.toLocaleString()} rows across ${data.columns.length} columns. What would you like to discover?`);
    showPreview(data);
    suggestions(data);
  } catch (error) {
    $('uploadStatus').textContent = error.message + (state.uploaded ? ' Your previous spreadsheet is still active.' : '');
  } finally {
    state.uploading = false;
    $('file').value = '';
    updateControls();
  }
}

function showResult(container, event) {
  const details = document.createElement('details');
  details.className = 'result';
  const summary = document.createElement('summary');
  summary.textContent = `Calculated result · ${event.operation.replaceAll('_', ' ')}`;
  const pre = document.createElement('pre');
  pre.textContent = JSON.stringify(event.answer, null, 2);
  details.append(summary, pre);
  details.open = true;
  container.append(details);
}

async function askAI(event) {
  event?.preventDefault();
  const question = $('question').value.trim();
  if (!question || !state.uploaded || state.busy || state.uploading) return;
  state.busy = true;
  state.controller = new AbortController();
  updateControls();
  message(question, true);
  $('question').value = '';
  const container = message('');
  const answer = document.createElement('div');
  answer.className = 'answer streaming';
  const status = document.createElement('p');
  status.className = 'message-status';
  status.setAttribute('role', 'status');
  status.textContent = 'Connecting…';
  container.append(answer, status);
  let reader;
  let done = false;
  try {
    const response = await fetch('/ask/stream', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ question }), signal: state.controller.signal,
    });
    if (!response.ok) throw new Error(await responseError(response));
    if (!response.body) throw new Error('Your browser does not support streaming responses.');
    reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    function handleLine(line) {
      if (!line.trim()) return;
      const item = JSON.parse(line);
      if (item.type === 'status') status.textContent = item.message;
      else if (item.type === 'result') showResult(container, item);
      else if (item.type === 'delta') { answer.textContent += item.text; status.textContent = 'Receiving answer…'; }
      else if (item.type === 'error') throw new Error(item.message);
      else if (item.type === 'done') { done = true; status.textContent = '✓ Analysis complete'; }
      scrollChat();
    }
    while (true) {
      const chunk = await reader.read();
      buffer += decoder.decode(chunk.value, { stream: !chunk.done });
      const lines = buffer.split('\n');
      buffer = lines.pop();
      lines.forEach(handleLine);
      if (chunk.done) break;
    }
    if (buffer.trim()) handleLine(buffer);
    if (!done) throw new Error('The connection ended before the answer was complete. Please try again.');
  } catch (error) {
    const stopped = error.name === 'AbortError';
    status.textContent = stopped ? 'Response stopped. You can ask another question.' : error.message;
    status.classList.toggle('error', !stopped);
  } finally {
    if (reader) { await reader.cancel().catch(() => {}); reader.releaseLock(); }
    answer.classList.remove('streaming');
    state.busy = false;
    state.controller = null;
    updateControls();
    $('question').focus();
  }
}

$('file').addEventListener('change', event => uploadFile(event.target.files[0]));
$('questionForm').addEventListener('submit', askAI);
$('question').addEventListener('keydown', event => {
  if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) { event.preventDefault(); askAI(); }
});
$('stop').addEventListener('click', () => state.controller?.abort());
$('clearChat').addEventListener('click', () => {
  if (state.busy) return;
  $('chat').replaceChildren();
  message(state.uploaded ? 'Ready for a fresh question. What would you like to explore?' : 'Upload a spreadsheet to start exploring your data.');
});
for (const type of ['dragenter', 'dragover']) {
  $('dropzone').addEventListener(type, event => { event.preventDefault(); $('dropzone').classList.add('dragging'); });
}
for (const type of ['dragleave', 'drop']) {
  $('dropzone').addEventListener(type, event => { event.preventDefault(); $('dropzone').classList.remove('dragging'); });
}
$('dropzone').addEventListener('drop', event => uploadFile(event.dataTransfer.files[0]));
updateControls();
