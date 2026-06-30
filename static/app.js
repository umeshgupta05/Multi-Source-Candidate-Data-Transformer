/* ================================================================
   CANDIDATE DATA TRANSFORMER — Frontend Application
   ================================================================ */

// ── State ──────────────────────────────────────────────────────────
let currentSection = 'pipeline';
let sourceMode = 'sample';      // 'sample' | 'upload'
let configMode = 'preset';      // 'preset' | 'upload'
let resumeExtractionMode = 'regex';
let githubReadmeMode = 'regex';
let selectedConfig = 'default';
let lastResult = null;
let lastOutputFile = null;
let configsData = {};

// ── Init ───────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
    loadConfigs();
    setupNavigation();
    setupUploadZones();
    setupSourceChips();
    setupResumeExtractionControls();
    setupGithubReadmeControls();
    setupClearUploads();
});

// ── Navigation ─────────────────────────────────────────────────────
function setupNavigation() {
    document.querySelectorAll('.nav-pill').forEach(pill => {
        pill.addEventListener('click', () => {
            switchSection(pill.dataset.section);
        });
    });
}

function switchSection(name) {
    currentSection = name;

    // Update nav pills
    document.querySelectorAll('.nav-pill').forEach(p => p.classList.remove('active'));
    const activePill = document.querySelector(`.nav-pill[data-section="${name}"]`);
    if (activePill) activePill.classList.add('active');

    // Update sections
    document.querySelectorAll('.section').forEach(s => s.classList.remove('active'));
    const activeSection = document.getElementById(`section-${name}`);
    if (activeSection) {
        activeSection.classList.add('active');
        // Re-trigger animation
        activeSection.style.animation = 'none';
        activeSection.offsetHeight; // reflow
        activeSection.style.animation = '';
    }
}

// ── Source Mode Toggle ─────────────────────────────────────────────
function setSourceMode(mode) {
    sourceMode = mode;

    document.getElementById('btn-sample').classList.toggle('active', mode === 'sample');
    document.getElementById('btn-upload').classList.toggle('active', mode === 'upload');
    document.getElementById('mode-sample').classList.toggle('hidden', mode !== 'sample');
    document.getElementById('mode-upload').classList.toggle('hidden', mode !== 'upload');
}

function setConfigMode(mode) {
    configMode = mode;

    document.getElementById('btn-config-preset').classList.toggle('active', mode === 'preset');
    document.getElementById('btn-config-upload').classList.toggle('active', mode === 'upload');
    document.getElementById('mode-config-preset').classList.toggle('hidden', mode !== 'preset');
    document.getElementById('mode-config-upload').classList.toggle('hidden', mode !== 'upload');
}

function setResumeExtractionMode(mode) {
    resumeExtractionMode = mode;

    document.querySelectorAll('[data-resume-mode]').forEach(btn => {
        btn.classList.toggle('active', btn.dataset.resumeMode === mode);
    });
}

function setupResumeExtractionControls() {
    document.querySelectorAll('[data-resume-mode]').forEach(btn => {
        btn.addEventListener('click', (event) => {
            event.preventDefault();
            setResumeExtractionMode(btn.dataset.resumeMode);
        });
    });
}

function setGithubReadmeMode(mode) {
    githubReadmeMode = mode;

    document.querySelectorAll('[data-github-readme-mode]').forEach(btn => {
        btn.classList.toggle('active', btn.dataset.githubReadmeMode === mode);
    });
}

function setupGithubReadmeControls() {
    document.querySelectorAll('[data-github-readme-mode]').forEach(btn => {
        btn.addEventListener('click', (event) => {
            event.preventDefault();
            setGithubReadmeMode(btn.dataset.githubReadmeMode);
        });
    });
}

// ── Source Chips (sample data toggle) ──────────────────────────────
function setupSourceChips() {
    document.querySelectorAll('.source-chip').forEach(chip => {
        chip.addEventListener('click', () => {
            document.querySelectorAll('.source-chip').forEach(c => c.classList.remove('active'));
            chip.classList.add('active');
        });
    });
}

// ── Upload Zones ───────────────────────────────────────────────────
function setupUploadZones() {
    const zones = [
        { dropId: 'drop-csv', inputId: 'file-csv', fnameId: 'fname-csv' },
        { dropId: 'drop-ats', inputId: 'file-ats', fnameId: 'fname-ats' },
        { dropId: 'drop-github', inputId: 'file-github', fnameId: 'fname-github' },
        { dropId: 'drop-resume', inputId: 'file-resume', fnameId: 'fname-resume' },
        { dropId: 'drop-config', inputId: 'file-config', fnameId: 'fname-config', onChange: previewConfigFile },
    ];

    zones.forEach(({ dropId, inputId, fnameId, onChange }) => {
        const zone = document.getElementById(dropId);
        const input = document.getElementById(inputId);
        const fname = document.getElementById(fnameId);
        if (!zone || !input) return;

        // Click to open file dialog
        zone.addEventListener('click', () => input.click());

        // File selected
        input.addEventListener('change', () => {
            if (input.files.length > 0) {
                const names = Array.from(input.files).map(f => f.name).join(', ');
                fname.textContent = names;
                zone.classList.add('has-file');
                if (onChange) onChange(input.files[0]);
            }
        });

        // Drag & Drop
        zone.addEventListener('dragover', (e) => {
            e.preventDefault();
            zone.classList.add('drag-over');
        });

        zone.addEventListener('dragleave', () => {
            zone.classList.remove('drag-over');
        });

        zone.addEventListener('drop', (e) => {
            e.preventDefault();
            zone.classList.remove('drag-over');
            if (e.dataTransfer.files.length > 0) {
                input.files = e.dataTransfer.files;
                const names = Array.from(input.files).map(f => f.name).join(', ');
                fname.textContent = names;
                zone.classList.add('has-file');
                if (onChange) onChange(input.files[0]);
            }
        });
    });
}

function setupClearUploads() {
    const btn = document.getElementById('btn-clear-uploads');
    if (!btn) return;

    btn.addEventListener('click', () => {
        [
            { dropId: 'drop-csv', inputId: 'file-csv', fnameId: 'fname-csv' },
            { dropId: 'drop-ats', inputId: 'file-ats', fnameId: 'fname-ats' },
            { dropId: 'drop-github', inputId: 'file-github', fnameId: 'fname-github' },
            { dropId: 'drop-resume', inputId: 'file-resume', fnameId: 'fname-resume' },
        ].forEach(({ dropId, inputId, fnameId }) => {
            const zone = document.getElementById(dropId);
            const input = document.getElementById(inputId);
            const fname = document.getElementById(fnameId);
            if (input) input.value = '';
            if (fname) fname.textContent = '';
            if (zone) zone.classList.remove('has-file', 'drag-over');
        });
    });
}

function previewConfigFile(file) {
    const preview = document.getElementById('config-file-preview');
    if (!preview || !file) return;

    file.text()
        .then(text => {
            const data = JSON.parse(text);
            const fieldCount = Array.isArray(data.fields) ? data.fields.length : 0;
            const confidence = data.include_confidence === false ? 'confidence off' : 'confidence on';
            const onMissing = data.on_missing || 'null';
            preview.textContent = `${fieldCount} fields | ${confidence} | on_missing: ${onMissing}`;
            preview.classList.remove('error');
        })
        .catch(err => {
            preview.textContent = `Invalid JSON preview: ${err.message}`;
            preview.classList.add('error');
        });
}

// ── Config Loading ─────────────────────────────────────────────────
async function loadConfigs() {
    try {
        const resp = await fetch('/api/configs');
        const data = await resp.json();
        const configs = data.configs || [];

        // Pipeline page config selector
        const selector = document.getElementById('config-selector');
        selector.innerHTML = configs.map(c => `
            <div class="config-option ${c.name === selectedConfig ? 'active' : ''}"
                 data-config="${c.name}" onclick="selectConfig('${c.name}')">
                <div class="config-name">${c.name}</div>
                <div class="config-meta">
                    <span>${c.fields_count} fields</span>
                    <span>on_missing: ${c.on_missing}</span>
                    ${c.include_confidence ? '<span>+ confidence</span>' : ''}
                </div>
            </div>
        `).join('');

        // Config explorer tabs
        const tabs = document.getElementById('config-tabs');
        tabs.innerHTML = configs.map(c => `
            <button class="config-tab ${c.name === 'default' ? 'active' : ''}"
                    onclick="showConfigDetail('${c.name}', this)">${c.name}</button>
        `).join('');

        // Load first config detail
        if (configs.length > 0) {
            showConfigDetail(configs[0].name, null);
        }

        // Store config names for detail loading
        configs.forEach(c => { configsData[c.name] = null; });

    } catch (err) {
        console.error('Failed to load configs:', err);
    }
}

function selectConfig(name) {
    selectedConfig = name;
    document.querySelectorAll('.config-option').forEach(o => {
        o.classList.toggle('active', o.dataset.config === name);
    });
}

async function showConfigDetail(name, btn) {
    // Update tabs
    if (btn) {
        document.querySelectorAll('.config-tab').forEach(t => t.classList.remove('active'));
        btn.classList.add('active');
    }

    try {
        const resp = await fetch(`/api/configs/${name}`);
        const data = await resp.json();
        document.getElementById('config-json').textContent = JSON.stringify(data, null, 2);
    } catch (err) {
        document.getElementById('config-json').textContent = `Error loading config: ${err.message}`;
    }
}

// ── Pipeline Execution ─────────────────────────────────────────────
async function runPipeline() {
    const btn = document.getElementById('btn-run');
    const loading = document.getElementById('loading');

    btn.classList.add('loading');
    btn.querySelector('.btn-run-text').textContent = 'Processing...';
    loading.classList.remove('hidden');

    // Animate pipeline stages
    animatePipelineStages();

    try {
        const formData = new FormData();
        formData.append('resume_extraction_mode', resumeExtractionMode);
        formData.append('github_readme_llm', githubReadmeMode === 'llm' ? 'true' : 'false');

        if (configMode === 'upload') {
            const configFile = document.getElementById('file-config');
            if (!configFile.files.length) {
                throw new Error('Choose a custom config JSON file, or switch back to a preset config.');
            }
            formData.append('config_file', configFile.files[0]);
        } else {
            formData.append('config_name', selectedConfig);
        }

        if (sourceMode === 'sample') {
            formData.append('use_sample_data', 'true');

            // Send per-source toggles based on which chips are active.
            const chipMap = { csv: 'sample_csv', ats: 'sample_ats', github: 'sample_github', resume: 'sample_resume' };
            document.querySelectorAll('.source-chip').forEach(chip => {
                const src = chip.dataset.source;
                if (src && chipMap[src]) {
                    formData.append(chipMap[src], chip.classList.contains('active') ? 'true' : 'false');
                }
            });
        } else {
            formData.append('use_sample_data', 'false');

            const csvFile = document.getElementById('file-csv');
            if (csvFile.files.length > 0) formData.append('csv_file', csvFile.files[0]);

            const atsFile = document.getElementById('file-ats');
            if (atsFile.files.length > 0) formData.append('ats_file', atsFile.files[0]);

            const ghFile = document.getElementById('file-github');
            if (ghFile.files.length > 0) formData.append('github_file', ghFile.files[0]);

            const resumeFiles = document.getElementById('file-resume');
            for (let i = 0; i < resumeFiles.files.length; i++) {
                formData.append('resume_files', resumeFiles.files[i]);
            }
        }

        const resp = await fetch('/api/run', { method: 'POST', body: formData });

        if (!resp.ok) {
            const err = await resp.json();
            throw new Error(err.detail || `HTTP ${resp.status}`);
        }

        lastResult = await resp.json();
        lastOutputFile = lastResult.output_file;

        renderResults(lastResult);
        completePipelineAnimation();

        // Wait for animation then switch to results
        setTimeout(() => {
            switchSection('results');
        }, 800);

    } catch (err) {
        alert(`Pipeline failed: ${err.message}`);
        console.error(err);
    } finally {
        btn.classList.remove('loading');
        btn.querySelector('.btn-run-text').textContent = 'Run Pipeline';
        setTimeout(() => {
            loading.classList.add('hidden');
            resetPipelineStages();
        }, 600);
    }
}

// ── Pipeline Stage Animation ───────────────────────────────────────
function animatePipelineStages() {
    const stages = document.querySelectorAll('.pipeline-stage');
    stages.forEach(s => s.classList.remove('active-stage', 'done-stage'));

    const stageLabels = ['Extract', 'Normalize', 'Resolve', 'Merge', 'Score', 'Project', 'Validate'];
    let i = 0;

    const interval = setInterval(() => {
        if (i > 0 && stages[i - 1]) {
            stages[i - 1].classList.remove('active-stage');
            stages[i - 1].classList.add('done-stage');
        }
        if (i < stages.length) {
            stages[i].classList.add('active-stage');
            i++;
        } else {
            clearInterval(interval);
        }
    }, 300);
}

function completePipelineAnimation() {
    document.querySelectorAll('.pipeline-stage').forEach(s => {
        s.classList.remove('active-stage');
        s.classList.add('done-stage');
    });
}

function resetPipelineStages() {
    document.querySelectorAll('.pipeline-stage').forEach(s => {
        s.classList.remove('active-stage', 'done-stage');
    });
}

// ── Results Rendering ──────────────────────────────────────────────
function renderResults(result) {
    const empty = document.getElementById('results-empty');
    const content = document.getElementById('results-content');

    empty.classList.add('hidden');
    content.classList.remove('hidden');

    renderStats(result.stats);
    renderIssues(result.stats);
    renderCandidates(result.candidates);
}

function renderStats(stats) {
    const grid = document.getElementById('stats-grid');

    const items = [
        { value: stats.sources_loaded.length, label: 'Sources Loaded', accent: 'accent-indigo' },
        { value: (stats.sources_failed || []).length, label: 'Sources Failed', accent: (stats.sources_failed || []).length > 0 ? 'accent-rose' : 'accent-emerald' },
        { value: stats.total_raw_field_values, label: 'Raw Fields', accent: 'accent-indigo' },
        { value: stats.candidates_processed, label: 'Candidates', accent: 'accent-emerald' },
        { value: stats.conflicts_found, label: 'Conflicts', accent: stats.conflicts_found > 0 ? 'accent-amber' : 'accent-emerald' },
        { value: stats.rejections, label: 'Rejections', accent: stats.rejections > 0 ? 'accent-rose' : 'accent-emerald' },
        { value: stats.validation_errors.length, label: 'Validation Errors', accent: stats.validation_errors.length > 0 ? 'accent-rose' : 'accent-emerald' },
    ];

    grid.innerHTML = items.map(item => `
        <div class="stat-card">
            <div class="stat-value ${item.accent}">${item.value}</div>
            <div class="stat-label">${item.label}</div>
        </div>
    `).join('');
}

function renderIssues(stats) {
    const card = document.getElementById('issues-card');
    const content = document.getElementById('issues-content');
    const conflicts = stats.conflict_details || [];
    const rejections = stats.rejection_details || [];
    const failedSources = stats.sources_failed || [];
    const noCandidates = stats.candidates_processed === 0;

    if (conflicts.length === 0 && rejections.length === 0 && failedSources.length === 0 && !noCandidates) {
        card.classList.add('hidden');
        return;
    }

    card.classList.remove('hidden');
    let html = '';

    failedSources.forEach(source => {
        html += `
            <div class="issue-item issue-rejection">
                <div class="issue-label">Source Failed</div>
                <div>${escapeHtml(String(source))}</div>
            </div>
        `;
    });

    if (noCandidates) {
        html += `
            <div class="issue-item issue-rejection">
                <div class="issue-label">No Candidates</div>
                <div>No raw candidate data was extracted. Check the selected source, uploaded files, and LLM credentials. For resume uploads, use Both mode when you want regex extraction available as a fallback.</div>
            </div>
        `;
    }

    conflicts.forEach(c => {
        html += `
            <div class="issue-item issue-conflict">
                <div class="issue-label">Conflict</div>
                <div><strong>${escapeHtml(String(c.field))}</strong> - sources: ${escapeHtml(String(Array.isArray(c.sources) ? c.sources.join(', ') : c.sources))} -> chose <strong>${escapeHtml(String(c.chosen))}</strong></div>
            </div>
        `;
    });

    rejections.forEach(r => {
        html += `
            <div class="issue-item issue-rejection">
                <div class="issue-label">Rejected</div>
                <div><strong>${escapeHtml(String(r.field))}</strong>: "${escapeHtml(String(r.value))}" from ${escapeHtml(String(r.source))} - ${escapeHtml(String(r.reason))}</div>
            </div>
        `;
    });

    content.innerHTML = html;
}

function renderCandidates(candidates) {
    const container = document.getElementById('candidate-cards');
    container.innerHTML = '';

    candidates.forEach((candidate, idx) => {
        container.innerHTML += buildCandidateCard(candidate, idx);
    });
}

function buildCandidateCard(c, idx) {
    const nestedCandidate = isPlainObject(c.candidate) ? c.candidate : null;
    const displaySource = nestedCandidate || c;
    const name = c.full_name || c.name || nestedCandidate?.name || c.candidate_id || `Candidate ${idx + 1}`;
    const confidence = c.overall_confidence != null ? c.overall_confidence : null;
    const provenance = c.provenance || [];
    const confClass = confidence >= 0.8 ? 'high' : confidence >= 0.5 ? 'medium' : 'low';
    const confPercent = confidence != null ? Math.round(confidence * 100) : null;

    // Build fields
    const skipKeys = new Set(['overall_confidence', 'provenance', 'full_name', 'name', 'error', 'candidate_id', 'candidate']);
    let fieldsHtml = '';

    // Name first
    if (c.full_name || c.name || nestedCandidate?.name) {
        fieldsHtml += fieldItem(nestedCandidate ? 'Name' : 'Full Name', c.full_name || c.name || nestedCandidate.name);
    }

    // Iterate over keys. Custom configs may nest projected fields under
    // "candidate"; render those fields directly instead of stringifying the
    // wrapper object.
    Object.entries(displaySource).forEach(([key, val]) => {
        if (skipKeys.has(key)) return;
        if (val === null || val === undefined) {
            fieldsHtml += fieldItem(formatKey(key), null);
            return;
        }
        if (key === 'skills' && Array.isArray(val)) {
            fieldsHtml += skillsField(val);
            return;
        }
        if (key === 'experience' && Array.isArray(val)) {
            fieldsHtml += experienceField(val);
            return;
        }
        if (key === 'education' && Array.isArray(val)) {
            fieldsHtml += educationField(val);
            return;
        }
        if (key === 'top_skills' && Array.isArray(val)) {
            fieldsHtml += skillsField(val);
            return;
        }
        if (key === 'current_experience' && isPlainObject(val)) {
            fieldsHtml += objectField('Current Experience', val);
            return;
        }
        if (typeof val === 'object' && !Array.isArray(val)) {
            fieldsHtml += objectField(key, val);
            return;
        }
        if (Array.isArray(val) && val.some(item => isPlainObject(item))) {
            fieldsHtml += objectField(key, { items: val });
            return;
        }
        if (Array.isArray(val)) {
            fieldsHtml += fieldItem(formatKey(key), val.join(', '), true);
            return;
        }
        fieldsHtml += fieldItem(formatKey(key), val);
    });

    // Provenance
    let provHtml = '';
    if (provenance.length > 0) {
        provHtml = `
            <div class="provenance-section">
                <div class="provenance-title" onclick="toggleProvenance(${idx})">
                    [+] Provenance (${provenance.length} entries)
                </div>
                <div class="provenance-list" id="prov-${idx}">
                    ${provenance.map(p => `
                        <div class="prov-item">
                            <span class="prov-field">${p.field || ''}</span>
                            <span class="prov-source">${p.source || ''}</span>
                            <span class="prov-method">${p.method || ''}</span>
                        </div>
                    `).join('')}
                </div>
            </div>
        `;
    }

    // Error state
    if (c.error) {
        return `
            <div class="candidate-card">
                <div class="candidate-header">
                    <div>
                        <div class="candidate-name">${name}</div>
                    </div>
                </div>
                <div class="candidate-body">
                    <div class="issue-item issue-rejection">
                        <div class="issue-label">Error</div>
                        <div>${c.error}</div>
                    </div>
                </div>
            </div>
        `;
    }

    return `
        <div class="candidate-card">
            <div class="candidate-header">
                <div>
                    <div class="candidate-name">${escapeHtml(name)}</div>
                    ${c.candidate_id ? `<div class="candidate-id">${c.candidate_id}</div>` : ''}
                </div>
                ${confPercent != null ? `
                    <div class="confidence-gauge">
                        <div class="gauge-bar">
                            <div class="gauge-fill ${confClass}" style="width: ${confPercent}%"></div>
                        </div>
                        <div class="gauge-value" style="color: var(--accent-${confClass === 'high' ? 'emerald' : confClass === 'medium' ? 'amber' : 'rose'})">${confPercent}%</div>
                    </div>
                ` : ''}
            </div>
            <div class="candidate-body">
                <div class="field-grid">${fieldsHtml}</div>
                ${provHtml}
            </div>
        </div>
    `;
}

// ── Field Renderers ────────────────────────────────────────────────
function fieldItem(label, value, mono = false) {
    const isScrollableText = label === 'Headline';
    if (value === null || value === undefined) {
        return `
            <div class="field-item">
                <div class="field-label">${label}</div>
                <div class="field-value field-null">null</div>
            </div>
        `;
    }
    return `
        <div class="field-item ${isScrollableText ? 'field-item-wide' : ''}">
            <div class="field-label">${label}</div>
            <div class="field-value ${mono ? 'mono' : ''} ${isScrollableText ? 'scrollable-text' : ''}">${escapeHtml(String(value))}</div>
        </div>
    `;
}

function skillsField(skills) {
    if (!skills || skills.length === 0) return fieldItem('Skills', null);

    // Handle both string arrays and object arrays
    const tags = skills.map(s => {
        if (typeof s === 'string') {
            return `<span class="skill-tag">${escapeHtml(s)}</span>`;
        }
        if (typeof s === 'object' && s.name) {
            const conf = s.confidence != null ? `<span class="skill-conf">${Math.round(s.confidence * 100)}%</span>` : '';
            return `<span class="skill-tag">${escapeHtml(s.name)} ${conf}</span>`;
        }
        return `<span class="skill-tag">${escapeHtml(String(s))}</span>`;
    }).join('');

    return `
        <div class="field-item" style="grid-column: 1 / -1;">
            <div class="field-label">Skills (${skills.length})</div>
            <div class="skill-tags">${tags}</div>
        </div>
    `;
}

function experienceField(entries) {
    if (!entries || entries.length === 0) return fieldItem('Experience', null);

    const html = entries.map(e => {
        const dates = [e.start, e.end || 'Present'].filter(Boolean).join(' -> ');
        return `<div style="margin-bottom: 8px;">
            <div style="font-weight: 600;">${escapeHtml(e.title || '')} ${e.company ? '@ ' + escapeHtml(e.company) : ''}</div>
            <div style="font-size: 0.78rem; color: var(--text-muted);">${dates}</div>
            ${e.summary ? `<div style="font-size: 0.82rem; color: var(--text-secondary); margin-top: 4px;">${escapeHtml(e.summary)}</div>` : ''}
        </div>`;
    }).join('');

    return `
        <div class="field-item" style="grid-column: 1 / -1;">
            <div class="field-label">Experience (${entries.length})</div>
            <div class="field-value">${html}</div>
        </div>
    `;
}

function educationField(entries) {
    if (!entries || entries.length === 0) return fieldItem('Education', null);

    const html = entries.map(e => {
        return `<div style="margin-bottom: 6px;">
            <div style="font-weight: 600;">${escapeHtml(e.institution || '')}</div>
            <div style="font-size: 0.82rem; color: var(--text-secondary);">
                ${[e.degree, e.field, e.end_year].filter(Boolean).join(' - ')}
            </div>
        </div>`;
    }).join('');

    return `
        <div class="field-item" style="grid-column: 1 / -1;">
            <div class="field-label">Education (${entries.length})</div>
            <div class="field-value">${html}</div>
        </div>
    `;
}

function objectField(key, obj) {
    const entries = Object.entries(obj).filter(([, v]) => v !== null && v !== undefined);
    if (entries.length === 0) return fieldItem(formatKey(key), null);

    const hasLongText = entries.some(([, v]) => typeof v === 'string' && v.length > 80);
    const isWide = entries.some(([, v]) => isComplexValue(v)) || hasLongText || key === 'current_experience' || key === 'Current Experience';
    const html = entries.map(([k, v]) => `
        <div class="structured-row">
            <div class="structured-key">${formatKey(k)}</div>
            <div class="structured-value">${renderStructuredValue(v)}</div>
        </div>
    `).join('');

    return `
        <div class="field-item ${isWide ? 'field-item-wide' : ''}">
            <div class="field-label">${formatKey(key)}</div>
            <div class="field-value structured-object">${html}</div>
        </div>
    `;
}

function renderStructuredValue(value) {
    if (value === null || value === undefined || value === '') {
        return '<span class="field-null">null</span>';
    }

    if (Array.isArray(value)) {
        if (value.length === 0) return '<span class="field-null">[]</span>';
        if (!value.some(item => isComplexValue(item))) {
            return escapeHtml(value.map(item => String(item)).join(', '));
        }
        return `
            <div class="structured-array">
                ${value.map(item => `
                    <div class="structured-array-item">
                        ${renderStructuredValue(item)}
                    </div>
                `).join('')}
            </div>
        `;
    }

    if (isPlainObject(value)) {
        const entries = Object.entries(value).filter(([, v]) => v !== null && v !== undefined && v !== '');
        if (entries.length === 0) return '<span class="field-null">null</span>';
        return `
            <div class="structured-object nested">
                ${entries.map(([k, v]) => `
                    <div class="structured-row">
                        <div class="structured-key">${formatKey(k)}</div>
                        <div class="structured-value">${renderStructuredValue(v)}</div>
                    </div>
                `).join('')}
            </div>
        `;
    }

    return escapeHtml(String(value));
}

function isPlainObject(value) {
    return value !== null && typeof value === 'object' && !Array.isArray(value);
}

function isComplexValue(value) {
    return isPlainObject(value) || (Array.isArray(value) && value.some(item => isComplexValue(item)));
}

// ── Provenance Toggle ──────────────────────────────────────────────
function toggleProvenance(idx) {
    const list = document.getElementById(`prov-${idx}`);
    if (list) {
        list.classList.toggle('open');
        const title = list.previousElementSibling;
        if (title) {
            title.textContent = list.classList.contains('open')
                ? title.textContent.replace('[+]', '[-]')
                : title.textContent.replace('[-]', '[+]');
        }
    }
}

// ── Download Output ────────────────────────────────────────────────
async function downloadOutput() {
    if (!lastOutputFile) {
        alert('No output file available. Run the pipeline first.');
        return;
    }

    try {
        const resp = await fetch(`/api/output/${lastOutputFile}`);
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
        const blob = await resp.blob();
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = lastOutputFile;
        a.click();
        URL.revokeObjectURL(url);
    } catch (err) {
        alert(`Download failed: ${err.message}`);
    }
}

// ── Utilities ──────────────────────────────────────────────────────
function formatKey(key) {
    return key
        .replace(/_/g, ' ')
        .replace(/\./g, ' > ')
        .replace(/\b\w/g, c => c.toUpperCase());
}

function escapeHtml(str) {
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
}
