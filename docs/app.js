const state = { games: [] };

const elements = {
  games: document.querySelector('#games'),
  template: document.querySelector('#game-template'),
  search: document.querySelector('#search'),
  language: document.querySelector('#language-filter'),
  status: document.querySelector('#status-filter'),
  genre: document.querySelector('#genre-filter'),
  year: document.querySelector('#year-filter'),
  format: document.querySelector('#format-filter'),
  rating: document.querySelector('#rating-filter'),
  sort: document.querySelector('#sort-filter'),
  reset: document.querySelector('#reset-filters'),
  total: document.querySelector('#total-count'),
  shown: document.querySelector('#shown-count'),
  missing: document.querySelector('#missing-count'),
  empty: document.querySelector('#empty'),
  error: document.querySelector('#load-error'),
};

const collator = new Intl.Collator('cs', { sensitivity: 'base', numeric: true });

function normalized(value) {
  return String(value || '').normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLocaleLowerCase('cs');
}

function searchable(game) {
  return [game.title, game.folder_name, game.title_id, game.developer, game.publisher, ...(game.categories || [])]
    .filter(Boolean).join(' ');
}

function languageText(game) {
  if (game.audio_cs) return 'dabing + titulky';
  if (game.subtitles_cs) return 'titulky';
  return 'bez češtiny';
}

function statusLabel(value) {
  return ({ healthy: 'nalezeno', missing: 'chybí', ambiguous: 'nejasné', unknown: 'nezjištěno' })[value] || value;
}

function primaryStatus(game) {
  return game.providers?.webshare || Object.values(game.providers || {})[0] || game.local_status || 'unknown';
}

function matches(game) {
  const query = normalized(elements.search.value.trim());
  if (query && !normalized(searchable(game)).includes(query)) return false;
  if (elements.language.value === 'audio' && !game.audio_cs) return false;
  if (elements.language.value === 'subtitles' && !game.subtitles_cs) return false;
  if (elements.status.value !== 'all' && primaryStatus(game) !== elements.status.value) return false;
  if (elements.genre.value !== 'all' && !(game.categories || []).includes(elements.genre.value)) return false;
  if (elements.year.value !== 'all' && String(game.release_year) !== elements.year.value) return false;
  if (elements.format.value !== 'all' && game.format !== elements.format.value) return false;
  if (Number(elements.rating.value) && Number(game.rating || 0) < Number(elements.rating.value)) return false;
  return true;
}

function sortGames(games) {
  const [field, direction] = elements.sort.value.split('-');
  const multiplier = direction === 'desc' ? -1 : 1;
  return games.sort((a, b) => {
    if (field === 'title') return collator.compare(a.title, b.title) * multiplier;
    const property = field === 'year' ? 'release_year' : field;
    const left = Number(a[property] ?? -1);
    const right = Number(b[property] ?? -1);
    return ((left - right) * multiplier) || collator.compare(a.title, b.title);
  });
}

function addOptions(select, values) {
  for (const value of values) {
    const option = document.createElement('option');
    option.value = value;
    option.textContent = value;
    select.append(option);
  }
}

function populateFilters() {
  const genres = [...new Set(state.games.flatMap(game => game.categories || []))].sort(collator.compare);
  const years = [...new Set(state.games.map(game => game.release_year).filter(Boolean))].sort((a, b) => b - a);
  const formats = [...new Set(state.games.map(game => game.format).filter(Boolean))].sort(collator.compare);
  addOptions(elements.genre, genres);
  addOptions(elements.year, years);
  addOptions(elements.format, formats);
}

function render() {
  const games = sortGames(state.games.filter(matches));
  elements.games.replaceChildren();
  const fragment = document.createDocumentFragment();
  for (const game of games) {
    const card = elements.template.content.cloneNode(true);
    card.querySelector('.game-id').textContent = game.title_id;
    card.querySelector('.game-title').textContent = game.title;
    card.querySelector('.description').textContent = game.description_cs || 'Popis zatím není k dispozici.';
    card.querySelector('.year').textContent = game.release_year || '—';
    card.querySelector('.rating').textContent = game.rating != null ? `${game.rating}/100` : '—';
    card.querySelector('.developer').textContent = game.developer || '—';
    card.querySelector('.language').textContent = languageText(game);
    const status = card.querySelector('.status');
    const mainStatus = primaryStatus(game);
    status.textContent = statusLabel(mainStatus);
    status.classList.add(mainStatus);
    const tags = card.querySelector('.tags');
    for (const category of (game.categories || []).slice(0, 5)) {
      const tag = document.createElement('span');
      tag.className = 'tag'; tag.textContent = category; tags.append(tag);
    }
    const providers = card.querySelector('.providers');
    for (const [name, providerStatus] of Object.entries(game.providers || {})) {
      const badge = document.createElement('span');
      badge.className = `provider ${providerStatus}`;
      badge.textContent = `${name}: ${statusLabel(providerStatus)}`;
      providers.append(badge);
    }
    const downloads = card.querySelector('.downloads');
    for (const [name, url] of Object.entries(game.download_urls || {})) {
      const link = document.createElement('a');
      link.className = 'download-link';
      link.href = url;
      link.target = '_blank';
      link.rel = 'noopener noreferrer';
      link.textContent = `Stáhnout z ${name}`;
      link.setAttribute('aria-label', `Stáhnout ${game.title} z ${name}`);
      downloads.append(link);
    }
    fragment.append(card);
  }
  elements.games.append(fragment);
  elements.total.textContent = state.games.length;
  elements.shown.textContent = games.length;
  elements.missing.textContent = state.games.filter(game => game.providers?.webshare === 'missing').length;
  elements.empty.hidden = games.length !== 0;
}

for (const control of [elements.search, elements.language, elements.status, elements.genre,
  elements.year, elements.format, elements.rating, elements.sort]) {
  control.addEventListener('input', render);
}

elements.reset.addEventListener('click', () => {
  elements.search.value = '';
  for (const control of [elements.language, elements.status, elements.genre, elements.year, elements.format]) {
    control.value = 'all';
  }
  elements.rating.value = '0';
  elements.sort.value = 'title-asc';
  elements.search.focus();
  render();
});

fetch('data/games.json')
  .then(response => {
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    return response.json();
  })
  .then(data => { state.games = data.games || []; populateFilters(); render(); })
  .catch(error => {
    elements.error.hidden = false;
    elements.error.textContent = `Katalog se nepodařilo načíst: ${error.message}`;
  });
