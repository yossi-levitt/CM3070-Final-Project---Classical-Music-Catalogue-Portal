const apiBase = "/api";

const byId = function (id)
{
    return document.getElementById(id);
};

const statsEl = byId("stats");
const searchInput = byId("search-input");
const composerFilter = byId("composer-filter");
const genreFilter = byId("genre-filter");
const instrumentFilter = byId("instrument-filter");
const meiUpload = byId("mei-upload");
const uploadStatus = byId("upload-status");
const worksBody = byId("works-body");
const resultCount = byId("result-count");
const paginationEl = byId("pagination");
const browseView = byId("browse-view");
const workDetail = byId("work-detail");
const detailBody = byId("detail-body");
const detailClose = byId("detail-close");

let searchDebounce = null;
const pageSize = 50;
let currentPage = 1;

function escapeHtml(value)
{
    if (value === null || value === undefined)
    {
        return "";
    }
    const map = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };
    return String(value).replace(/[&<>"']/g, function (char)
    {
        return map[char];
    });
}

function dashIfEmpty(value)
{
    if (value === null || value === undefined || value === "")
    {
        return "-";
    }
    return escapeHtml(value);
}

async function fetchJson(url)
{
    const res = await fetch(url);
    if (!res.ok)
    {
        throw new Error(`${url} -> ${res.status}`);
    }
    return res.json();
}

async function loadStats()
{
    try
    {
        const data = await fetchJson(`${apiBase}/stats`);
        statsEl.textContent = `${data.composers} composers, ${data.works} works, ${data.movements} movements, ${data.manuscripts} manuscript records.`;
    }
    catch (err)
    {
        statsEl.textContent = "";
    }
}

async function loadComposers()
{
    try
    {
        const data = await fetchJson(`${apiBase}/composers`);
        const fragments = ['<option value="">All composers</option>'];
        for (const composer of data)
        {
            const label = `${escapeHtml(composer.name)} (${composer.work_count})`;
            fragments.push(`<option value="${composer.id}">${label}</option>`);
        }
        composerFilter.innerHTML = fragments.join("");
    }
    catch (err)
    {
        composerFilter.innerHTML = '<option value="">All composers</option>';
    }
}

async function loadGenres()
{
    try
    {
        const data = await fetchJson(`${apiBase}/genres`);
        const fragments = ['<option value="">All genres</option>'];
        for (const genre of data)
        {
            fragments.push(`<option value="${escapeHtml(genre)}">${escapeHtml(genre)}</option>`);
        }
        genreFilter.innerHTML = fragments.join("");
    }
    catch (err)
    {
        genreFilter.innerHTML = '<option value="">All genres</option>';
    }
}

async function loadInstruments()
{
    try
    {
        const data = await fetchJson(`${apiBase}/instruments`);
        const fragments = ['<option value="">All instruments</option>'];
        for (const instrument of data)
        {
            const label = `${escapeHtml(instrument.name)} (${instrument.work_count})`;
            fragments.push(`<option value="${instrument.id}">${label}</option>`);
        }
        instrumentFilter.innerHTML = fragments.join("");
    }
    catch (err)
    {
        instrumentFilter.innerHTML = '<option value="">All instruments</option>';
    }
}

function buildWorksUrl()
{
    const params = new URLSearchParams();
    const queryText = searchInput.value.trim();
    if (queryText !== "")
    {
        params.set("q", queryText);
    }
    if (composerFilter.value !== "")
    {
        params.set("composer_id", composerFilter.value);
    }
    if (genreFilter.value !== "")
    {
        params.set("genre", genreFilter.value);
    }
    if (instrumentFilter.value !== "")
    {
        params.set("instrument_id", instrumentFilter.value);
    }
    params.set("limit", pageSize);
    params.set("offset", (currentPage - 1) * pageSize);
    return `${apiBase}/works?${params.toString()}`;
}

function renderPagination(total)
{
    const totalPages = Math.max(1, Math.ceil(total / pageSize));
    if (totalPages <= 1)
    {
        paginationEl.innerHTML = "";
        return;
    }
    paginationEl.innerHTML = `
        <button type="button" id="page-prev" ${currentPage <= 1 ? "disabled" : ""}>&larr; Prev</button>
        <span class="pagination-status">Page ${currentPage} of ${totalPages}</span>
        <button type="button" id="page-next" ${currentPage >= totalPages ? "disabled" : ""}>Next &rarr;</button>
    `;
    byId("page-prev").addEventListener("click", function ()
    {
        currentPage = currentPage - 1;
        loadWorks();
    });
    byId("page-next").addEventListener("click", function ()
    {
        currentPage = currentPage + 1;
        loadWorks();
    });
}

async function loadWorks()
{
    worksBody.innerHTML = `<tr><td colspan="6" class="muted">Loading...</td></tr>`;
    try
    {
        const data = await fetchJson(buildWorksUrl());
        const works = data.works;
        if (works.length === 0)
        {
            resultCount.textContent = "0 works";
            worksBody.innerHTML = `<tr><td colspan="6"><div class="empty"><h3>No works match</h3><p>Try clearing filters or adjusting the search term.</p></div></td></tr>`;
            paginationEl.innerHTML = "";
            return;
        }
        resultCount.textContent = data.total === 1 ? "1 work" : `${data.total} works`;
        renderPagination(data.total);
        const rows = [];
        for (const work of works)
        {
            let displayYear = "-";
            if (work.year_composed !== null && work.year_composed !== undefined)
            {
                displayYear = work.year_composed;
                if (work.year_completed !== null && work.year_completed !== undefined && work.year_completed !== work.year_composed)
                {
                    displayYear = `${work.year_composed} - ${work.year_completed}`;
                }
            }
            rows.push(`
                <tr data-id="${work.id}" tabindex="0" role="button" aria-label="View details for ${dashIfEmpty(work.title)}">
                    <td class="mono">${dashIfEmpty(work.catalogue_number)}</td>
                    <td><span class="work-title">${dashIfEmpty(work.title)}</span>${work.subtitle ? `<span class="work-subtitle">${escapeHtml(work.subtitle)}</span>` : ""}</td>
                    <td>${dashIfEmpty(work.composer_name)}</td>
                    <td class="col-hide-sm">${dashIfEmpty(work.genre)}</td>
                    <td class="col-hide-md">${dashIfEmpty(work.key_signature)}</td>
                    <td class="col-hide-sm mono">${displayYear}</td>
                </tr>
            `);
        }
        worksBody.innerHTML = rows.join("");
    }
    catch (err)
    {
        worksBody.innerHTML = `<tr><td colspan="6" class="error">Failed to load: ${escapeHtml(err.message)}</td></tr>`;
    }
}

function renderDetailSection(title, rowsHtml)
{
    if (rowsHtml === "")
    {
        return "";
    }
    return `<section class="detail-section"><h3>${escapeHtml(title)}</h3>${rowsHtml}</section>`;
}

function renderMovements(movements)
{
    if (movements.length === 0)
    {
        return "";
    }
    const items = [];
    for (const movement of movements)
    {
        const parts = [];
        if (movement.tempo)
        {
            parts.push(`<em>${escapeHtml(movement.tempo)}</em>`);
        }
        if (movement.title)
        {
            parts.push(escapeHtml(movement.title));
        }
        if (movement.key_signature)
        {
            parts.push(`in ${escapeHtml(movement.key_signature)}`);
        }
        const label = parts.length === 0 ? "(untitled)" : parts.join(" - ");
        const incipit = movement.incipit ? `<span class="movement-incipit">&ldquo;${escapeHtml(movement.incipit)}&rdquo;</span>` : "";
        items.push(`<li><span class="movement-seq">${movement.sequence}.</span> ${label}${incipit}</li>`);
    }
    return renderDetailSection("Movements", `<ol class="movement-list">${items.join("")}</ol>`);
}

function renderInstruments(instruments)
{
    if (instruments.length === 0)
    {
        return "";
    }
    const chips = [];
    for (const instrument of instruments)
    {
        let label = escapeHtml(instrument.name);
        if (instrument.count !== null && instrument.count !== undefined && instrument.count > 1)
        {
            label = `${label} (${instrument.count})`;
        }
        chips.push(`<span class="chip">${label}</span>`);
    }
    return renderDetailSection("Instrumentation", `<div class="chip-row">${chips.join("")}</div>`);
}

function renderManuscripts(manuscripts)
{
    if (manuscripts.length === 0)
    {
        return "";
    }
    const items = [];
    for (const manuscript of manuscripts)
    {
        const parts = [];
        if (manuscript.repository)
        {
            parts.push(`<strong>${escapeHtml(manuscript.repository)}</strong>`);
        }
        if (manuscript.shelf_mark)
        {
            parts.push(`<span class="mono">${escapeHtml(manuscript.shelf_mark)}</span>`);
        }
        if (manuscript.date_text)
        {
            parts.push(escapeHtml(manuscript.date_text));
        }
        const head = parts.join(" - ");
        let description = "";
        if (manuscript.description)
        {
            description = `<p class="muted">${escapeHtml(manuscript.description)}</p>`;
        }
        items.push(`<li>${head}${description}</li>`);
    }
    return renderDetailSection("Manuscripts", `<ul class="record-list">${items.join("")}</ul>`);
}

function renderPerformances(performances)
{
    if (performances.length === 0)
    {
        return "";
    }
    const items = [];
    for (const performance of performances)
    {
        const parts = [];
        if (performance.performance_date)
        {
            parts.push(`<strong>${escapeHtml(performance.performance_date)}</strong>`);
        }
        if (performance.venue)
        {
            parts.push(escapeHtml(performance.venue));
        }
        if (performance.city)
        {
            parts.push(escapeHtml(performance.city));
        }
        const head = parts.join(" - ");
        let notes = "";
        if (performance.notes)
        {
            notes = `<p class="muted">${escapeHtml(performance.notes)}</p>`;
        }
        items.push(`<li>${head}${notes}</li>`);
    }
    return renderDetailSection("Performance history", `<ul class="record-list">${items.join("")}</ul>`);
}

function renderHeader(work)
{
    const parts = [];
    parts.push(`<h2>${dashIfEmpty(work.title)}</h2>`);
    if (work.subtitle)
    {
        parts.push(`<p class="detail-subtitle">${escapeHtml(work.subtitle)}</p>`);
    }
    const meta = [];
    if (work.catalogue_number)
    {
        meta.push(`<span class="badge mono">${escapeHtml(work.catalogue_number)}</span>`);
    }
    if (work.composer_name)
    {
        let composerLine = escapeHtml(work.composer_name);
        if (work.birth_year && work.death_year)
        {
            composerLine = `${composerLine} (${work.birth_year} - ${work.death_year})`;
        }
        meta.push(`<span>${composerLine}</span>`);
    }
    if (work.genre)
    {
        meta.push(`<span>${escapeHtml(work.genre)}</span>`);
    }
    if (work.key_signature)
    {
        meta.push(`<span>${escapeHtml(work.key_signature)}</span>`);
    }
    if (work.year_composed)
    {
        let yearLine = String(work.year_composed);
        if (work.year_completed && work.year_completed !== work.year_composed)
        {
            yearLine = `${work.year_composed} - ${work.year_completed}`;
        }
        meta.push(`<span>${yearLine}</span>`);
    }
    if (meta.length > 0)
    {
        parts.push(`<div class="detail-meta">${meta.join("")}</div>`);
    }
    if (work.dedication)
    {
        parts.push(`<p class="detail-dedication">Dedicated to ${escapeHtml(work.dedication)}.</p>`);
    }
    if (work.notes)
    {
        parts.push(`<p class="detail-notes">${escapeHtml(work.notes)}</p>`);
    }
    return parts.join("");
}

async function viewWork(workId)
{
    browseView.hidden = true;
    workDetail.hidden = false;
    detailBody.innerHTML = `<p class="muted">Loading work...</p>`;
    try
    {
        const work = await fetchJson(`${apiBase}/works/${workId}`);
        const blocks = [];
        blocks.push(renderHeader(work));
        // A "hybrid" file can carry only a handful of illustrative notes, not a real
        // playable score - MIN_NOTES_FOR_PREVIEW filters those out so the preview is
        // only offered where there is enough actual music to be worth rendering.
        const MIN_NOTES_FOR_PREVIEW = 15;
        const hasEnoughMusic = (work.note_count || 0) >= MIN_NOTES_FOR_PREVIEW;
        if ((work.encoding_style === "notation" || work.encoding_style === "hybrid") && hasEnoughMusic)
        {
            blocks.push(`
                <section class="detail-section notation-section">
                    <div class="notation-section-head">
                        <h3>Notation Preview</h3>
                        <button type="button" class="action-button" id="notation-preview-link" data-id="${workId}">
                            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M9 18V5l12-2v13"/><circle cx="6" cy="18" r="3"/><circle cx="18" cy="16" r="3"/></svg>
                            Show notation preview
                        </button>
                    </div>
                    <div class="notation-preview" id="notation-preview" hidden></div>
                </section>
            `);
        }
        blocks.push(renderMovements(work.movements || []));
        blocks.push(renderInstruments(work.instruments || []));
        blocks.push(renderManuscripts(work.manuscripts || []));
        blocks.push(renderPerformances(work.performances || []));
        if (work.source_file)
        {
            const styleBadge = work.encoding_style ? ` <span class="badge badge-${escapeHtml(work.encoding_style)}">${escapeHtml(work.encoding_style)}-style source</span>` : "";
            blocks.push(`<p class="source-file">Source MEI file: <span class="mono">${escapeHtml(work.source_file)}</span>${styleBadge}</p>`);
        }
        blocks.push(`
            <div class="detail-actions">
                <button type="button" class="action-button" id="view-mei-link" data-id="${workId}">
                    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/></svg>
                    View MEI 5.1
                </button>
                <a class="action-button" href="${apiBase}/works/${workId}/mei" download>
                    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>
                    Download MEI 5.1
                </a>
                <button type="button" class="action-button" id="validate-link" data-id="${workId}">
                    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/></svg>
                    Validate against source
                </button>
                <button type="button" class="action-button" id="classify-link" data-id="${workId}">
                    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M9 3H5a2 2 0 0 0-2 2v4m6-6h10a2 2 0 0 1 2 2v10M3 9v10a2 2 0 0 0 2 2h10m6-12v10a2 2 0 0 1-2 2H9"/></svg>
                    Rule vs ML style
                </button>
                <button type="button" class="action-button" id="genre-link" data-id="${workId}">
                    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="10"/><path d="M12 6v6l4 2"/></svg>
                    Predict genre
                </button>
            </div>
            <p class="validate-result" id="validate-result" hidden></p>
            <pre class="mei-viewer" id="mei-viewer" hidden></pre>
        `);
        detailBody.innerHTML = blocks.join("");
        window.scrollTo({ top: 0, behavior: "smooth" });
        detailClose.focus();
    }
    catch (err)
    {
        detailBody.innerHTML = `<p class="error">Failed to load work: ${escapeHtml(err.message)}</p>`;
    }
}

function scheduleSearch()
{
    if (searchDebounce !== null)
    {
        clearTimeout(searchDebounce);
    }
    searchDebounce = setTimeout(function ()
    {
        currentPage = 1;
        loadWorks();
    }, 200);
}

searchInput.addEventListener("input", scheduleSearch);

composerFilter.addEventListener("change", function ()
{
    currentPage = 1;
    loadWorks();
});

genreFilter.addEventListener("change", function ()
{
    currentPage = 1;
    loadWorks();
});

instrumentFilter.addEventListener("change", function ()
{
    currentPage = 1;
    loadWorks();
});

async function uploadMeiFile(file)
{
    uploadStatus.hidden = false;
    uploadStatus.textContent = `Reading ${file.name}...`;
    const body = new FormData();
    body.append("file", file);
    try
    {
        const res = await fetch(`${apiBase}/upload`, { method: "POST", body });
        const data = await res.json();
        if (!res.ok)
        {
            uploadStatus.textContent = `Couldn't import this file: ${data.error}`;
            return;
        }
        const contentNote = styleLabels[data.detected_style] || `${data.detected_style} content`;
        let warningNote = "";
        if (data.warnings.length > 0)
        {
            const warningWord = data.warnings.length === 1 ? "note" : "notes";
            warningNote = ` (${data.warnings.length} ${warningWord} worth a look)`;
        }
        let mlNote = "";
        if (data.ml_style)
        {
            const mlLabel = styleLabels[data.ml_style] || data.ml_style;
            mlNote = ` The ML model agrees this looks like ${mlLabel} (${Math.round(data.ml_confidence * 100)}% confident).`;
        }
        uploadStatus.textContent = `Added "${data.title}" to the catalogue - it contains ${contentNote}${warningNote}.${mlNote}`;
        loadStats();
        loadComposers();
        loadGenres();
        loadInstruments();
        currentPage = 1;
        loadWorks();
    }
    catch (err)
    {
        uploadStatus.textContent = `Couldn't import this file: ${err.message}`;
    }
}

meiUpload.addEventListener("change", function ()
{
    if (meiUpload.files.length > 0)
    {
        uploadMeiFile(meiUpload.files[0]);
        meiUpload.value = "";
    }
});

worksBody.addEventListener("click", function (event)
{
    const target = event.target;
    if (!(target instanceof HTMLElement))
    {
        return;
    }
    const row = target.closest("tr[data-id]");
    if (row === null)
    {
        return;
    }
    const workId = row.getAttribute("data-id");
    if (workId === null)
    {
        return;
    }
    viewWork(workId);
});

worksBody.addEventListener("keydown", function (event)
{
    if (event.key !== "Enter" && event.key !== " ")
    {
        return;
    }
    const target = event.target;
    if (!(target instanceof HTMLElement))
    {
        return;
    }
    const row = target.closest("tr[data-id]");
    if (row === null)
    {
        return;
    }
    // Space would otherwise scroll the page since rows act as buttons
    event.preventDefault();
    const workId = row.getAttribute("data-id");
    if (workId === null)
    {
        return;
    }
    viewWork(workId);
});

detailClose.addEventListener("click", function ()
{
    workDetail.hidden = true;
    browseView.hidden = false;
});

async function runSourceValidation(workId, resultEl)
{
    resultEl.textContent = "Re-checking this work against the original file it came from...";
    const data = await fetchJson(`${apiBase}/works/${workId}/validation`);
    const failed = data.checks.filter(function (check) { return !check.ok; });
    if (failed.length === 0)
    {
        resultEl.textContent = `Good news - every detail stored for this work (title, composer, dates and more) still matches the original file it was imported from. All ${data.checks_total} checks passed.`;
        return;
    }
    const names = failed.map(function (check) { return check.name; }).join(", ");
    const detailWord = failed.length === 1 ? "detail" : "details";
    resultEl.textContent = `${failed.length} of ${data.checks_total} ${detailWord} no longer match the original file: ${names}. This usually means something was missed or misread during import.`;
}

const styleLabels = {
    notation: "playable sheet music",
    hybrid: "a mix of sheet music and catalogue information",
    catalogue: "catalogue information only, with no playable music",
};

async function runStyleComparison(workId, resultEl)
{
    resultEl.textContent = "Checking whether this file contains playable music or just catalogue data...";
    const data = await fetchJson(`${apiBase}/works/${workId}/classification`);
    const ruleLabel = styleLabels[data.rule_style] || data.rule_style;
    const mlLabel = styleLabels[data.ml_style] || data.ml_style;
    const confidence = Math.round(data.ml_confidence * 100);
    if (data.agreement)
    {
        resultEl.textContent = `This file contains ${mlLabel}. A hand-written rule and a trained ML model checked it independently and agree, and the ML model is ${confidence}% confident.`;
        return;
    }
    resultEl.textContent = `A hand-written rule says this file contains ${ruleLabel}, but the ML model instead says ${mlLabel} (${confidence}% confident) - they disagree here.`;
}

const genreLabels = {
    vocal_choral: "vocal or choral",
    keyboard_organ: "keyboard or organ",
    orchestral_stage: "orchestral or stage",
    chamber_instrumental: "chamber or small-ensemble",
    other: "unclear",
};

async function runGenreComparison(workId, resultEl)
{
    resultEl.textContent = "Looking at the instruments used to guess the genre...";
    const data = await fetchJson(`${apiBase}/works/${workId}/genre-classification`);
    const ruleLabel = genreLabels[data.rule_genre] || data.rule_genre;
    const mlLabel = genreLabels[data.ml_genre] || data.ml_genre;
    const confidence = Math.round(data.ml_confidence * 100);
    const instrumentWord = data.instrument_count === 1 ? "instrument" : "instruments";
    let movementNote = "";
    if (data.movement_count > 1)
    {
        movementNote = ` across ${data.movement_count} movements`;
    }

    let line;
    if (data.agreement)
    {
        line = `Based on its ${data.instrument_count} ${instrumentWord}${movementNote}, this looks like it belongs to the ${mlLabel} category. A hand-written rule and a trained ML model checked it independently and agree, and the ML model is ${confidence}% confident.`;
    }
    else
    {
        line = `Based on its ${data.instrument_count} ${instrumentWord}${movementNote}, a hand-written rule guesses the ${ruleLabel} category, but the ML model instead guesses ${mlLabel} (${confidence}% confident) - they disagree here.`;
    }
    if (data.actual_genre_raw)
    {
        const actualLabel = genreLabels[data.actual_genre_canonical] || data.actual_genre_canonical;
        line = `${line} The catalogue itself lists this work's genre as "${data.actual_genre_raw}", which falls under the ${actualLabel} category.`;
    }
    resultEl.textContent = line;
}

// Cache only WASM runtime readiness, not a toolkit instance. A single verovio.toolkit()
// object reused across many renders eventually corrupts the WASM heap ("function
// signature mismatch"), found by testing all 66 notation/hybrid works in one session -
// so every render gets a fresh, cheap toolkit() construction against the already-loaded
// module instead.
let verovioReadyPromise = null;

function waitForVerovio()
{
    if (verovioReadyPromise === null)
    {
        verovioReadyPromise = new Promise(function (resolve, reject)
        {
            if (typeof verovio === "undefined")
            {
                reject(new Error("Verovio failed to load"));
                return;
            }
            // The WASM runtime may already have finished initialising by the time this
            // runs (it loads asynchronously right after the script tag parses), in which
            // case onRuntimeInitialized has already fired and assigning it here would
            // never be called - check calledRun first rather than assuming we're early.
            if (verovio.module.calledRun)
            {
                resolve();
                return;
            }
            verovio.module.onRuntimeInitialized = function ()
            {
                resolve();
            };
        });
    }
    return verovioReadyPromise;
}

async function runNotationPreview(workId, containerEl)
{
    if (containerEl.dataset.loaded === "true")
    {
        containerEl.hidden = !containerEl.hidden;
        return;
    }
    containerEl.hidden = false;
    containerEl.innerHTML = `<p class="muted">Loading notation preview...</p>`;
    try
    {
        const meiRes = await fetch(`${apiBase}/works/${workId}/source-mei`);
        if (!meiRes.ok)
        {
            throw new Error(`source MEI fetch failed (${meiRes.status})`);
        }
        const meiText = await meiRes.text();
        await waitForVerovio();
        const toolkit = new verovio.toolkit();
        const svg = toolkit.renderData(meiText, {});
        if (typeof svg !== "string" || svg.trim() === "" || !svg.includes("<svg"))
        {
            throw new Error("Verovio returned no renderable SVG for this file");
        }
        containerEl.innerHTML = svg;
        containerEl.dataset.loaded = "true";
    }
    catch (err)
    {
        containerEl.innerHTML = `<p class="muted">Notation preview unavailable for this file.</p>`;
    }
}

function highlightXml(xmlText)
{
    // Escaped first so every subsequent match works against literal &lt;/&gt;/&quot;
    // sequences, never against a real "<" - so injected <span> markup can never be
    // re-matched and corrupted by a later pass.
    let escaped = escapeHtml(xmlText);
    escaped = escaped.replace(/(&lt;!--[\s\S]*?--&gt;)/g, '<span class="xml-comment">$1</span>');
    escaped = escaped.replace(/(&lt;\/?)([a-zA-Z_][\w:.-]*)/g, function (match, bracket, name)
    {
        return `${bracket}<span class="xml-tag">${name}</span>`;
    });
    escaped = escaped.replace(/([\w:.-]+)(=)(&quot;[^&]*?&quot;)/g, function (match, name, equals, value)
    {
        return `<span class="xml-attr-name">${name}</span>${equals}<span class="xml-attr-value">${value}</span>`;
    });
    return escaped;
}

async function runViewMei(workId, viewerEl)
{
    if (viewerEl.dataset.loaded === "true")
    {
        viewerEl.hidden = !viewerEl.hidden;
        return;
    }
    viewerEl.hidden = false;
    viewerEl.textContent = "Loading MEI...";
    try
    {
        const res = await fetch(`${apiBase}/works/${workId}/mei`);
        if (!res.ok)
        {
            throw new Error(`MEI fetch failed (${res.status})`);
        }
        const meiText = await res.text();
        viewerEl.innerHTML = highlightXml(meiText);
        viewerEl.dataset.loaded = "true";
    }
    catch (err)
    {
        viewerEl.textContent = `Couldn't load the MEI for this work: ${err.message}`;
    }
}

detailBody.addEventListener("click", async function (event)
{
    // closest(), not a direct id check, so a click landing on the icon inside
    // one of these buttons still resolves to the button itself
    const target = event.target instanceof HTMLElement
        ? event.target.closest("#validate-link, #classify-link, #genre-link, #notation-preview-link, #view-mei-link")
        : null;
    if (target === null)
    {
        return;
    }
    event.preventDefault();
    const workId = target.getAttribute("data-id");
    if (target.id === "notation-preview-link")
    {
        await runNotationPreview(workId, byId("notation-preview"));
        return;
    }
    if (target.id === "view-mei-link")
    {
        await runViewMei(workId, byId("mei-viewer"));
        return;
    }
    const resultEl = byId("validate-result");
    resultEl.hidden = false;
    try
    {
        if (target.id === "validate-link")
        {
            await runSourceValidation(workId, resultEl);
        }
        else if (target.id === "genre-link")
        {
            await runGenreComparison(workId, resultEl);
        }
        else
        {
            await runStyleComparison(workId, resultEl);
        }
    }
    catch (err)
    {
        resultEl.textContent = `Request failed: ${err.message}`;
    }
});

loadStats();
loadComposers();
loadGenres();
loadInstruments();
loadWorks();
