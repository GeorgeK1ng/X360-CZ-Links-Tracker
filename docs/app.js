const PAGE_SIZE = 24;
const state = { games: [], cards: new Map(), searchIndex: new Map(), visibleLimit: PAGE_SIZE };

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
  pegi: document.querySelector('#pegi-filter'),
  sort: document.querySelector('#sort-filter'),
  reset: document.querySelector('#reset-filters'),
  total: document.querySelector('#total-count'),
  shown: document.querySelector('#shown-count'),
  missing: document.querySelector('#missing-count'),
  empty: document.querySelector('#empty'),
  error: document.querySelector('#load-error'),
  loadControls: document.querySelector('#load-controls'),
  loadCount: document.querySelector('#load-count'),
  loadMore: document.querySelector('#load-more'),
  show100: document.querySelector('#show-100'),
  showAll: document.querySelector('#show-all'),
  legalDialog: document.querySelector('#legal-dialog'),
  legalAccept: document.querySelector('#legal-accept'),
  legalDecline: document.querySelector('#legal-decline'),
  legalOpeners: document.querySelectorAll('.open-legal'),
  downloadDialog: document.querySelector('#download-dialog'),
  downloadDialogClose: document.querySelector('#download-dialog-close'),
  downloadGame: document.querySelector('#download-game'),
  downloadConfirm: document.querySelector('#download-confirm'),
  downloadContinue: document.querySelector('#download-continue'),
  dialog: document.querySelector('#package-dialog'),
  dialogTitle: document.querySelector('#package-dialog-title'),
  dialogContent: document.querySelector('#package-dialog-content'),
  dialogClose: document.querySelector('#package-dialog-close'),
};

const collator = new Intl.Collator('cs', { sensitivity: 'base', numeric: true });
let pendingDownloadUrl = '';

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

function matches(game, filters) {
  if (filters.query && !state.searchIndex.get(game.asset_id).includes(filters.query)) return false;
  if (filters.language === 'audio' && !game.audio_cs) return false;
  if (filters.language === 'subtitles' && !game.subtitles_cs) return false;
  if (filters.status !== 'all' && primaryStatus(game) !== filters.status) return false;
  if (filters.genre !== 'all' && !(game.categories || []).includes(filters.genre)) return false;
  if (filters.year !== 'all' && String(game.release_year) !== filters.year) return false;
  if (filters.format !== 'all' && game.format !== filters.format) return false;
  if (filters.rating && Number(game.rating || 0) < filters.rating) return false;
  if (filters.pegi !== 'all' && String(game.pegi) !== filters.pegi) return false;
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
  const pegiRatings = [...new Set(state.games.map(game => game.pegi).filter(value => value != null))].sort((a, b) => a - b);
  addOptions(elements.genre, genres);
  addOptions(elements.year, years);
  addOptions(elements.format, formats);
  for (const value of pegiRatings) {
    const option = document.createElement('option');
    option.value = value;
    option.textContent = `PEGI ${value}`;
    elements.pegi.append(option);
  }
}

function setupGallery(card, game) {
  const covers = game.covers || [];
  const image = card.querySelector('.cover-image');
  const fallback = card.querySelector('.cover-fallback');
  const controls = card.querySelector('.cover-controls');
  const count = card.querySelector('.cover-count');
  const kind = card.querySelector('.cover-kind');
  let index = 0;

  function showCover(nextIndex) {
    if (!covers.length) {
      image.hidden = true;
      fallback.hidden = false;
      kind.textContent = 'Obal není dostupný';
      return;
    }
    index = (nextIndex + covers.length) % covers.length;
    const cover = covers[index];
    image.hidden = false;
    fallback.hidden = true;
    image.src = cover.file;
    image.alt = `Obal hry ${game.title}, varianta ${index + 1} z ${covers.length}`;
    count.textContent = `${index + 1} / ${covers.length}`;
    kind.textContent = cover.official ? 'Oficiální obal' : 'Komunitní obal';
  }

  controls.hidden = covers.length < 2;
  card.querySelector('.cover-prev').addEventListener('click', () => showCover(index - 1));
  card.querySelector('.cover-next').addEventListener('click', () => showCover(index + 1));
  showCover(0);
}

function setupPackageDetails(card, game) {
  card.querySelector('.format').textContent = game.format || '—';
  const update = Number(game.title_update || 0);
  card.querySelector('.title-update').textContent = update > 0 ? `TU ${update}` : '0';

  const dlc = String(game.dlc || '')
    .split(/\r?\n|\s*;\s*/)
    .map(value => value.trim())
    .filter(value => value && value !== '-');
  const dlcRow = card.querySelector('.dlc-row');
  if (dlc.length) {
    dlcRow.hidden = false;
    card.querySelector('.dlc-count').textContent = dlc.length.toLocaleString('cs-CZ');
    dlcRow.addEventListener('click', () => openPackageDialog(`${game.title} — DLC`, dlc));
  }

  const note = String(game.note || '').trim();
  const noteRow = card.querySelector('.note-row');
  if (note) {
    noteRow.hidden = false;
    noteRow.addEventListener('click', () => openPackageDialog(`${game.title} — poznámka`, note));
  }
}

function openPackageDialog(title, content) {
  elements.dialogTitle.textContent = title;
  elements.dialogContent.replaceChildren();
  if (Array.isArray(content)) {
    const list = document.createElement('ul');
    for (const value of content) {
      const item = document.createElement('li');
      item.textContent = value;
      list.append(item);
    }
    elements.dialogContent.append(list);
  } else {
    const paragraph = document.createElement('p');
    paragraph.textContent = content;
    elements.dialogContent.append(paragraph);
  }
  elements.dialog.showModal();
}

function createGameCard(game) {
    const card = elements.template.content.firstElementChild.cloneNode(true);
    card.querySelector('.game-id').textContent = game.title_id;
    card.querySelector('.game-title').textContent = game.title;
    card.querySelector('.description').textContent = game.description_cs || 'Popis zatím není k dispozici.';
    card.querySelector('.year').textContent = game.release_year || '—';
    card.querySelector('.rating').textContent = game.rating != null ? `${game.rating}/100 · ${game.rating} %` : '—';
    card.querySelector('.pegi').textContent = game.pegi != null ? `PEGI ${game.pegi}` : '—';
    card.querySelector('.developer').textContent = game.developer || '—';
    card.querySelector('.language').textContent = languageText(game);
    card.querySelector('.size').textContent = game.archive_size_gib != null ? `${game.archive_size_gib.toLocaleString('cs-CZ')} GiB` : '—';
    setupGallery(card, game);
    setupPackageDetails(card, game);
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
      const link = document.createElement('button');
      link.className = 'download-link';
      link.type = 'button';
      link.textContent = `Stáhnout z ${name}`;
      link.setAttribute('aria-label', `Stáhnout ${game.title} z ${name}`);
      link.addEventListener('click', event => {
        event.preventDefault();
        pendingDownloadUrl = url;
        elements.downloadGame.textContent = game.title;
        elements.downloadConfirm.checked = false;
        elements.downloadContinue.disabled = true;
        elements.downloadDialog.showModal();
      });
      downloads.append(link);
    }
    return card;
}

function cardFor(game) {
  if (!state.cards.has(game.asset_id)) state.cards.set(game.asset_id, createGameCard(game));
  return state.cards.get(game.asset_id);
}

function render() {
  const filters = {
    query: normalized(elements.search.value.trim()),
    language: elements.language.value,
    status: elements.status.value,
    genre: elements.genre.value,
    year: elements.year.value,
    format: elements.format.value,
    rating: Number(elements.rating.value),
    pegi: elements.pegi.value,
  };
  const matchesAll = sortGames(state.games.filter(game => matches(game, filters)));
  const visibleGames = matchesAll.slice(0, state.visibleLimit);
  const fragment = document.createDocumentFragment();
  for (const game of visibleGames) fragment.append(cardFor(game));
  elements.games.replaceChildren(fragment);
  elements.total.textContent = state.games.length;
  elements.shown.textContent = matchesAll.length;
  elements.missing.textContent = state.games.filter(game => game.providers?.webshare === 'missing').length;
  elements.empty.hidden = matchesAll.length !== 0;
  const hasMore = visibleGames.length < matchesAll.length;
  elements.loadControls.hidden = !hasMore;
  elements.loadCount.textContent = `Zobrazeno ${visibleGames.length.toLocaleString('cs-CZ')} z ${matchesAll.length.toLocaleString('cs-CZ')}`;
  elements.loadMore.textContent = `Zobrazit dalších ${Math.min(PAGE_SIZE, matchesAll.length - visibleGames.length).toLocaleString('cs-CZ')}`;
  elements.show100.hidden = visibleGames.length >= 100 || matchesAll.length <= 100;
  elements.showAll.textContent = `Zobrazit vše · ${matchesAll.length.toLocaleString('cs-CZ')}`;
}

elements.search.addEventListener('input', () => {
  state.visibleLimit = PAGE_SIZE;
  render();
});
for (const control of [elements.language, elements.status, elements.genre,
  elements.year, elements.format, elements.rating, elements.pegi, elements.sort]) {
  control.addEventListener('change', () => {
    state.visibleLimit = PAGE_SIZE;
    render();
  });
}

elements.loadMore.addEventListener('click', () => {
  state.visibleLimit += PAGE_SIZE;
  render();
});

elements.show100.addEventListener('click', () => {
  state.visibleLimit = 100;
  render();
});

elements.showAll.addEventListener('click', () => {
  state.visibleLimit = Number.POSITIVE_INFINITY;
  render();
});

const LEGAL_ACCEPTANCE_KEY = 'x360cz-legal-accepted-v1';
let legalAccepted = false;
try {
  legalAccepted = localStorage.getItem(LEGAL_ACCEPTANCE_KEY) === 'yes';
} catch (_) {
  // Soukromý režim může zablokovat úložiště; dialog pak zobrazíme znovu.
}

function openLegalDialog() {
  if (!elements.legalDialog.open) elements.legalDialog.showModal();
}

for (const opener of elements.legalOpeners) opener.addEventListener('click', openLegalDialog);

elements.legalAccept.addEventListener('click', () => {
  legalAccepted = true;
  try {
    localStorage.setItem(LEGAL_ACCEPTANCE_KEY, 'yes');
  } catch (_) {
    // Souhlas platí alespoň po dobu aktuální návštěvy.
  }
  elements.legalDialog.close();
});

elements.legalDecline.addEventListener('click', () => {
  if (history.length > 1) history.back();
  else location.href = 'https://github.com/GeorgeK1ng/X360-CZ-Links-Tracker';
});

elements.legalDialog.addEventListener('cancel', event => {
  if (!legalAccepted) event.preventDefault();
});

if (!legalAccepted) openLegalDialog();

elements.downloadConfirm.addEventListener('change', () => {
  elements.downloadContinue.disabled = !elements.downloadConfirm.checked;
});

function closeDownloadDialog() {
  pendingDownloadUrl = '';
  elements.downloadConfirm.checked = false;
  elements.downloadContinue.disabled = true;
  elements.downloadDialog.close();
}

elements.downloadDialogClose.addEventListener('click', closeDownloadDialog);
elements.downloadDialog.addEventListener('click', event => {
  if (event.target === elements.downloadDialog) closeDownloadDialog();
});
elements.downloadContinue.addEventListener('click', () => {
  if (!elements.downloadConfirm.checked || !pendingDownloadUrl) return;
  const target = pendingDownloadUrl;
  closeDownloadDialog();
  window.open(target, '_blank', 'noopener,noreferrer');
});

elements.dialogClose.addEventListener('click', () => elements.dialog.close());
elements.dialog.addEventListener('click', event => {
  if (event.target === elements.dialog) elements.dialog.close();
});

elements.reset.addEventListener('click', () => {
  elements.search.value = '';
  for (const control of [elements.language, elements.status, elements.genre, elements.year, elements.format, elements.pegi]) {
    control.value = 'all';
  }
  elements.rating.value = '0';
  elements.sort.value = 'title-asc';
  state.visibleLimit = PAGE_SIZE;
  render();
});

fetch('data/games.json', { cache: 'no-store' })
  .then(response => {
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    return response.json();
  })
  .then(data => {
    state.games = data.games || [];
    state.searchIndex = new Map(state.games.map(game => [game.asset_id, normalized(searchable(game))]));
    populateFilters();
    render();
  })
  .catch(error => {
    elements.error.hidden = false;
    elements.error.textContent = `Katalog se nepodařilo načíst: ${error.message}`;
  });
