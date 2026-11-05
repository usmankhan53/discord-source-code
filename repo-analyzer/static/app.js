const form = document.querySelector('#analyze-form');
const input = document.querySelector('#repository-url');
const button = document.querySelector('#submit-button');
const error = document.querySelector('#form-error');
const results = document.querySelector('#results');
const emptyState = document.querySelector('#empty-state');

function showError(message) {
  error.textContent = message;
  error.classList.remove('hidden');
}

function setLoading(isLoading) {
  button.disabled = isLoading;
  button.textContent = isLoading ? 'Analyzing…' : 'Analyze repository';
}

function renderRepository(repo) {
  document.querySelector('#repo-card').innerHTML = `
    <div class="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
      <div><p class="text-sm font-medium text-sky">Repository</p><h2 class="mt-1 text-2xl font-bold tracking-tight">${escapeHtml(repo.name)}</h2><p class="mt-2 max-w-2xl text-slate-600">${escapeHtml(repo.description)}</p></div>
      <div class="flex gap-2 text-sm text-slate-600"><span class="rounded-full bg-slate-100 px-3 py-1">★ ${repo.stars}</span><span class="rounded-full bg-slate-100 px-3 py-1">${escapeHtml(repo.language)}</span><span class="rounded-full bg-slate-100 px-3 py-1">${repo.file_count} files</span></div>
    </div>`;
}

function escapeHtml(value) {
  return String(value).replace(/[&<>'"]/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[char]));
}

form.addEventListener('submit', async (event) => {
  event.preventDefault();
  error.classList.add('hidden');
  const repositoryUrl = input.value.trim();
  if (!/^https?:\/\/(www\.)?github\.com\/[\w.-]+\/[\w.-]+\/?$/i.test(repositoryUrl)) {
    showError('Please enter a public GitHub repository URL.');
    return;
  }
  setLoading(true);
  try {
    const response = await fetch('/api/analyze', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({repository_url: repositoryUrl})});
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || 'Something went wrong. Please try again.');
    renderRepository(data.repository);
    document.querySelector('#analysis').innerHTML = marked.parse(data.analysis);
    results.classList.remove('hidden');
    emptyState.classList.add('hidden');
    results.scrollIntoView({behavior: 'smooth', block: 'start'});
  } catch (err) {
    showError(err.message || 'Something went wrong. Please try again.');
  } finally {
    setLoading(false);
  }
});
