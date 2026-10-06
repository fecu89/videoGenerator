(function () {
  "use strict";

  const state = {
    token: "",
    settings: null,
    savedSettings: null,
    recommendedSettings: null,
    catalog: [],
    sections: [],
    revision: "",
    dirty: false,
    saving: false,
    serverErrors: new Map(),
    conflict: false,
    pacingPresets: null,
    outputProfiles: [],
    speechSample: "",
    speechTesting: false,
  };

  const elements = {
    fatalError: document.getElementById("fatal-error"),
    fatalErrorMessage: document.getElementById("fatal-error-message"),
    retryLoad: document.getElementById("retry-load"),
    loading: document.getElementById("loading-state"),
    workbench: document.getElementById("workbench"),
    nav: document.getElementById("settings-nav"),
    sections: document.getElementById("settings-sections"),
    search: document.getElementById("settings-search"),
    status: document.getElementById("save-status"),
    formErrors: document.getElementById("form-errors"),
    formErrorList: document.getElementById("form-error-list"),
    reloadSettings: document.getElementById("reload-settings"),
    saveBar: document.getElementById("save-bar"),
    changeSummary: document.getElementById("change-summary"),
    restore: document.getElementById("restore-recommended"),
    save: document.getElementById("save-settings"),
    saveAndClose: document.getElementById("save-and-close"),
    closing: document.getElementById("closing-screen"),
  };

  class ApiError extends Error {
    constructor(status, payload) {
      super(payload.message || `HTTP ${status}`);
      this.status = status;
      this.payload = payload;
    }
  }

  function deepClone(value) {
    return JSON.parse(JSON.stringify(value));
  }

  function getAtPath(object, path) {
    return path.split(".").reduce((value, part) => value[part], object);
  }

  function setAtPath(object, path, value) {
    const parts = path.split(".");
    const leaf = parts.pop();
    const parent = parts.reduce((current, part) => current[part], object);
    parent[leaf] = value;
  }

  function durationContract(settings) {
    const voiceMin = Number(settings.voice.min_scene_seconds);
    const voiceMax = Number(settings.voice.max_scene_seconds);
    const gap = Number(settings.local_video.scene_gap_seconds);
    const localMax = Number(settings.local_video.max_scene_seconds);
    const valid = [voiceMin, voiceMax, gap, localMax].every(Number.isFinite)
      && voiceMin <= voiceMax
      && voiceMax + gap < localMax;
    return { voiceMin, voiceMax, gap, localMax, valid };
  }

  function fieldMatchesSearch(item, query) {
    const normalized = query.trim().toLocaleLowerCase("ko");
    if (!normalized) {
      return true;
    }
    return [item.label, item.description, item.key]
      .join(" ")
      .toLocaleLowerCase("ko")
      .includes(normalized);
  }

  window.SettingsWorkbench = {
    getAtPath,
    setAtPath,
    durationContract,
    fieldMatchesSearch,
  };

  function createElement(tag, className, text) {
    const element = document.createElement(tag);
    if (className) {
      element.className = className;
    }
    if (text !== undefined) {
      element.textContent = text;
    }
    return element;
  }

  function clearNode(node) {
    while (node.firstChild) {
      node.removeChild(node.firstChild);
    }
  }

  function safeId(key) {
    return key.replace(/[^a-z0-9]+/gi, "-");
  }

  async function api(path, options) {
    const request = options || {};
    const headers = new Headers(request.headers || {});
    headers.set("X-Settings-Token", state.token);
    if (request.body !== undefined) {
      headers.set("Content-Type", "application/json");
    }
    const response = await fetch(path, {
      ...request,
      headers,
      cache: "no-store",
      credentials: "same-origin",
    });
    let payload = {};
    try {
      payload = await response.json();
    } catch (error) {
      payload = { message: "서버 응답을 읽을 수 없습니다." };
    }
    if (!response.ok) {
      throw new ApiError(response.status, payload);
    }
    return payload;
  }

  function setStatus(kind, text) {
    elements.status.className = `save-status is-${kind}`;
    elements.status.textContent = text;
  }

  function showFatal(error) {
    elements.loading.hidden = true;
    elements.workbench.hidden = true;
    elements.saveBar.hidden = true;
    elements.fatalError.hidden = false;
    elements.fatalErrorMessage.textContent = error.message || String(error);
    setStatus("error", "불러오기 실패");
  }

  function countChanges() {
    if (!state.settings || !state.savedSettings) {
      return 0;
    }
    return JSON.stringify(state.settings) === JSON.stringify(state.savedSettings) ? 0 : 1;
  }

  function fieldApplies(item) {
    const typedPauses = state.settings.voice.pause_mode === 'typed';
    if (['voice.comma_pause_ms', 'voice.semantic_pause_ms', 'voice.emphasis_pause_ms', 'voice.sentence_pause_ms'].includes(item.key)) return typedPauses;
    if (['voice.sentence_leading_margin_ms', 'voice.sentence_trailing_margin_ms'].includes(item.key)) return !typedPauses;
    const qwen = state.settings.voice.engine === "qwen3";
    const qwenKeys = ["voice.model_id", "voice.model_revision", "voice.speaker", "voice.language", "voice.instructions_file", "voice.generation_preset", "voice.temperature", "voice.top_k", "voice.top_p", "voice.repetition_penalty"];
    if (qwenKeys.includes(item.key)) return qwen;
    if (item.key.startsWith("voice.loudness_") && item.key !== "voice.loudness_mode") {
      return state.settings.voice.loudness_mode === "leveled";
    }
    return true;
  }

  function computeClientErrors() {
    const errors = new Map();
    for (const item of state.catalog) {
      if (!fieldApplies(item)) continue;
      const value = getAtPath(state.settings, item.key);
      if ((item.control === "range" || item.control === "number")
          && !Number.isFinite(Number(value))) {
        errors.set(item.key, "숫자를 입력하세요.");
      }
      if (item.control === "text" && !item.allow_empty && !String(value).trim()) {
        errors.set(item.key, "값을 입력하세요.");
      }
    }

    const voiceMin = Number(getAtPath(state.settings, "voice.min_scene_seconds"));
    const voiceMax = Number(getAtPath(state.settings, "voice.max_scene_seconds"));
    const localMin = Number(getAtPath(state.settings, "local_video.min_scene_seconds"));
    const localMax = Number(getAtPath(state.settings, "local_video.max_scene_seconds"));
    const gap = Number(getAtPath(state.settings, "local_video.scene_gap_seconds"));
    const beatMin = state.settings.local_video.target_beat_min_seconds;
    const beatMax = state.settings.local_video.target_beat_max_seconds;
    if (!(beatMin === 0 && beatMax === 0) && !(beatMin > 0 && beatMin <= beatMax)) {
      errors.set("local_video.target_beat_max_seconds", "최소·최대 목표를 모두 0으로 두거나, 최대를 최소 이상으로 정하세요.");
    }
    if (voiceMin > voiceMax) {
      errors.set("voice.max_scene_seconds", "최소 음성 길이보다 크거나 같아야 합니다.");
    }
    if (localMin >= localMax) {
      errors.set("local_video.max_scene_seconds", "최소 장면 길이보다 커야 합니다.");
    } else if (voiceMax + gap >= localMax) {
      errors.set(
        "local_video.max_scene_seconds",
        "최대 음성 길이와 씬 사이 쉼의 합보다 커야 합니다.",
      );
    }
    return errors;
  }

  function combinedErrors() {
    const errors = computeClientErrors();
    for (const [key, message] of state.serverErrors) {
      errors.set(key, message);
    }
    return errors;
  }

  function updateErrorDisplay(errors) {
    document.querySelectorAll(".setting-card[data-setting-key]").forEach((card) => {
      const key = card.dataset.settingKey;
      const message = errors.get(key) || "";
      card.classList.toggle("has-error", Boolean(message));
      card.querySelectorAll("input, select").forEach((control) => {
        control.setAttribute("aria-invalid", message ? "true" : "false");
      });
      const output = card.querySelector(".field-error");
      output.textContent = message;
    });

    clearNode(elements.formErrorList);
    for (const [key, message] of errors) {
      const item = state.catalog.find((candidate) => candidate.key === key);
      const line = createElement("li", "", `${item ? item.label : key}: ${message}`);
      elements.formErrorList.appendChild(line);
    }
    elements.formErrors.hidden = errors.size === 0 && !state.conflict;
    elements.reloadSettings.hidden = !state.conflict;
  }

  function updateStateIndicators() {
    const changes = countChanges();
    state.dirty = changes > 0;
    const errors = combinedErrors();
    if (state.saving) {
      setStatus("saving", "저장 중");
    } else if (state.conflict || errors.size) {
      setStatus("error", "확인 필요");
    } else if (state.dirty) {
      setStatus("dirty", "저장하지 않음");
    } else {
      setStatus("saved", "저장됨");
    }
    elements.changeSummary.textContent = changes
      ? "변경 사항 있음 · 새 실행부터 적용"
      : "변경 사항 없음 · 기존 실행 스냅샷 유지";
    elements.save.disabled = state.saving || !state.dirty || errors.size > 0;
    elements.saveAndClose.disabled = state.saving || errors.size > 0;
    elements.restore.disabled = state.saving;
    elements.search.disabled = state.saving;
    const v = state.settings.voice;
    document.getElementById("voice-summary").textContent = v.engine === "qwen3" ? `Qwen · ${v.speaker}` : "Kokoro · 번역 언어 전용";
    document.getElementById("pace-summary").textContent = `${currentPaceName()} · 목표 ${v.target_syllables_per_second}음절/초`;
    updatePaceCard();
    document.getElementById("sound-summary").textContent = state.settings.music.file ? "배경음악 사용" : "배경음악 없음";
    updateErrorDisplay(errors);
  }

  function updateValue(key, rawValue, item) {
    const current = getAtPath(state.settings, key);
    let value = rawValue;
    if (typeof current === "number" || item.control === "number" || item.control === "range") {
      value = rawValue === "" ? Number.NaN : Number(rawValue);
    }
    setAtPath(state.settings, key, value);
    if (["render.final_width", "render.final_height", "render.final_fps"].includes(key)) {
      document.querySelector(".output-card").replaceWith(buildOutputCard());
    }
    state.serverErrors.clear();
    state.conflict = false;
    if (state.pacingPresets && state.pacingPresets.keys.includes(key)) {
      updatePaceCard();
    }
    if (["voice.engine", "voice.generation_preset", "voice.loudness_mode"].includes(key)) {
      renderSettings();
    } else {
      updateStateIndicators();
    }
  }

  function buildControl(item) {
    const id = `setting-${safeId(item.key)}`;
    const value = getAtPath(state.settings, item.key);
    if (item.control === "select") {
      const select = createElement("select", "setting-control");
      select.id = id;
      select.dataset.control = item.control;
      for (const optionItem of item.options) {
        const option = createElement("option", "", optionItem.label);
        option.value = optionItem.value;
        option.selected = optionItem.value === value;
        select.appendChild(option);
      }
      select.addEventListener("change", () => updateValue(item.key, select.value, item));
      return select;
    }

    if (item.control === "range") {
      const group = createElement("div", "range-control");
      const range = createElement("input", "");
      range.type = "range";
      range.min = String(item.ui_min);
      range.max = String(item.ui_max);
      range.step = String(item.step);
      range.value = String(value);
      range.tabIndex = -1;
      range.setAttribute("aria-hidden", "true");
      const number = createElement("input", "setting-control");
      number.type = "number";
      number.id = id;
      number.step = String(item.step);
      number.value = String(value);
      number.dataset.control = item.control;
      range.addEventListener("input", () => {
        number.value = range.value;
        updateValue(item.key, range.value, item);
      });
      number.addEventListener("input", () => {
        range.value = number.value;
        updateValue(item.key, number.value, item);
      });
      group.append(range, number);
      return group;
    }

    const input = createElement("input", "setting-control");
    input.id = id;
    input.dataset.control = item.control;
    if (input.tagName === "INPUT") input.type = item.control === "number" ? "number" : "text";
    input.value = String(value);
    if (item.control === "number") {
      input.step = "1";
    }
    const pickerKind = item.key === "music.file" ? "bgmusic" : null;
    if (pickerKind) {
      const group = createElement("div", "file-picker-control");
      input.readOnly = true;
      input.placeholder = "배경음악 없음 (bgmusic/ 폴더에서 선택)";
      const choose = createElement("button", "button button-secondary", "파일 선택…");
      choose.type = "button";
      choose.id = `pick-${safeId(item.key)}`;
      choose.addEventListener("click", async () => {
        const label = choose.textContent;
        choose.disabled = true;
        choose.textContent = "선택창 열림…";
        try {
          const selected = await api(`/api/pick-${pickerKind}`, {method: "POST"});
          if (selected.cancelled) return;
          input.value = selected.path;
          updateValue(item.key, selected.path, item);
        } catch (error) {
          state.serverErrors.set(item.key, error.message);
          updateStateIndicators();
        } finally {
          choose.disabled = false;
          choose.textContent = label;
        }
      });
      group.append(input, choose);
      if (pickerKind === "bgmusic") {
        const clear = createElement("button", "button button-secondary", "선택 해제");
        clear.type = "button";
        clear.addEventListener("click", () => {
          input.value = "";
          updateValue(item.key, "", item);
        });
        group.appendChild(clear);
      }
      return group;
    }
    input.addEventListener("input", () => updateValue(item.key, input.value, item));
    return input;
  }

  function buildSettingCard(item) {
    const card = createElement("article", "setting-card");
    card.dataset.settingKey = item.key;
    card.dataset.searchText = `${item.label} ${item.description} ${item.key}`.toLocaleLowerCase("ko");
    const id = `setting-${safeId(item.key)}`;
    const errorId = `error-${safeId(item.key)}`;
    const header = createElement("div", "setting-header");
    const label = createElement("label", "", item.label);
    label.htmlFor = id;
    header.appendChild(label);
    if (item.unit) {
      header.appendChild(createElement("span", "setting-unit", item.unit));
    }
    card.appendChild(header);
    if (item.advanced) card.appendChild(createElement("p", "setting-key", item.key));
    card.appendChild(createElement("p", "setting-description", item.description));
    const control = buildControl(item);
    const describedControl = control.matches && control.matches("input, select, textarea")
      ? control
      : control.querySelector("input:not([aria-hidden='true']), select, textarea");
    if (describedControl) {
      describedControl.setAttribute("aria-describedby", errorId);
    }
    card.appendChild(control);
    const error = createElement("p", "field-error");
    error.id = errorId;
    card.appendChild(error);
    return card;
  }

  function buildSection(section) {
    const items = state.catalog.filter((item) => item.section === section.id);
    const wrapper = createElement("section", "settings-section");
    wrapper.id = `section-${section.id}`;
    wrapper.dataset.sectionId = section.id;
    const heading = createElement("div", "section-heading");
    const copy = createElement("div", "");
    copy.appendChild(createElement("h2", "", section.label));
    copy.appendChild(createElement("p", "", section.description));
    heading.appendChild(copy);
    wrapper.appendChild(heading);

    if (section.id === "pace" && state.pacingPresets) {
      wrapper.appendChild(buildPaceCard());
    }
    if (section.id === "output") wrapper.appendChild(buildOutputCard());
    const primary = items.filter((item) => !item.advanced);
    if (primary.length) {
      const grid = createElement("div", "settings-grid");
      primary.forEach((item) => grid.appendChild(buildSettingCard(item)));
      wrapper.appendChild(grid);
    }
    const advanced = items.filter((item) => item.advanced);
    if (advanced.length) {
      const details = createElement("details", "advanced-panel");
      details.dataset.advancedSection = section.id;
      details.appendChild(createElement("summary", "", section.id === "advanced" ? `세부 설정 ${advanced.length}개 펼치기` : "추가 출력 옵션"));
      const grid = createElement("div", "settings-grid");
      advanced.forEach((item) => grid.appendChild(buildSettingCard(item)));
      details.appendChild(grid);
      wrapper.appendChild(details);
    }
    if (section.id === "basic") wrapper.appendChild(buildSpeechTest());
    return wrapper;
  }

  // Recipes are supplied by the same Python table used by the CLI.
  function selectedPreset() {
    return state.pacingPresets?.presets.find((item) => item.id === state.settings.pacing.preset);
  }

  function currentPaceName() {
    const preset = selectedPreset();
    if (!preset) return "사용자 지정";
    const customized = state.settings.pacing.version !== state.pacingPresets.version
      || Object.entries(preset.values).some(([key, value]) => getAtPath(state.settings, key) !== value);
    return preset.label + (customized ? " · 사용자 조정" : "");
  }

  function applyPacingPreset(id) {
    const preset = state.pacingPresets.presets.find((item) => item.id === id);
    if (!preset) return;
    for (const [key, value] of Object.entries(preset.values)) {
      setAtPath(state.settings, key, value);
      const control = document.getElementById(`setting-${safeId(key)}`);
      if (control) {
        control.value = String(value);
        const range = control.parentElement.querySelector("input[type='range']");
        if (range) range.value = String(value);
      }
    }
    state.settings.pacing = {preset: id, version: state.pacingPresets.version};
    state.serverErrors.clear();
    state.conflict = false;
    updateStateIndicators();
  }

  function updatePaceCard() {
    const label = document.getElementById("video-pace-label");
    if (!label) return;
    label.textContent = currentPaceName();
    document.querySelectorAll("[data-pacing-preset]").forEach((button) => {
      button.setAttribute("aria-pressed", String(button.dataset.pacingPreset === state.settings.pacing.preset));
    });
    const v = state.settings.voice, l = state.settings.local_video;
    document.getElementById("video-pace-details").textContent =
      `말하기 ${v.target_syllables_per_second}음절/초 · 구도 ${l.target_beat_min_seconds}–${l.target_beat_max_seconds}초 · 전환 ${l.camera_transition_seconds}초`;

  }

  function decodeBase64(text) {
    const binary = window.atob(text);
    const bytes = new Uint8Array(binary.length);
    for (let index = 0; index < binary.length; index += 1) bytes[index] = binary.charCodeAt(index);
    return bytes;
  }

  async function runSpeechTest(button, sample, status, audio) {
    if (state.speechTesting) return;
    state.speechTesting = true;
    button.disabled = true;
    status.className = "speech-test-status";
    status.textContent = "음성 생성 중… 처음 한 번은 모델을 불러오느라 10~30초 걸립니다.";
    try {
      const payload = await api("/api/speech-test", {
        method: "POST",
        body: JSON.stringify({ settings: state.settings, text: sample.value }),
      });
      const blob = new Blob([decodeBase64(payload.audio_base64)], { type: payload.mime });
      if (audio.dataset.url) URL.revokeObjectURL(audio.dataset.url);
      audio.dataset.url = URL.createObjectURL(blob);
      audio.src = audio.dataset.url;
      audio.hidden = false;
      const name = currentPaceName();
      status.textContent = `${name} · ${payload.seconds}초 · 저장하지 않은 현재 값으로 만들었습니다.`;
      audio.play().catch(() => {});
    } catch (error) {
      status.className = "speech-test-status is-error";
      status.textContent = `테스트 실패: ${error.message || error}`;
    } finally {
      state.speechTesting = false;
      button.disabled = false;
    }
  }

  function buildPaceCard() {
    const card = createElement("article", "setting-card pace-card");
    card.dataset.searchText = "영상 템포 속도 말하기 카메라 구도 문장 간격 프리셋 쇼츠";
    card.appendChild(createElement("p", "setting-description",
      "말하기·화면 전환·음악의 리듬을 함께 맞춥니다. 현재 사용자 조정값은 다른 템포를 고르기 전까지 유지됩니다."));
    const choices = createElement("div", "pacing-choices");
    choices.setAttribute("role", "group");
    choices.setAttribute("aria-label", "영상 템포 선택");
    state.pacingPresets.presets.forEach((preset) => {
      const button = createElement("button", "button button-secondary", preset.label);
      button.type = "button";
      button.dataset.pacingPreset = preset.id;
      button.addEventListener("click", () => applyPacingPreset(preset.id));
      choices.appendChild(button);
    });
    const label = createElement("p", "pace-label");
    label.id = "video-pace-label";
    label.setAttribute("aria-live", "polite");
    const summary = createElement("p", "setting-description");
    summary.id = "video-pace-details";
    card.append(choices, label, summary);

    window.setTimeout(updatePaceCard, 0);
    return card;
  }

  function buildSpeechTest() {
    const test = createElement("details", "speech-test");
    test.appendChild(createElement("summary", "", "목소리 미리 듣기"));
    const sample = createElement("textarea", "setting-control speech-test-text");
    sample.id = "speech-test-text";
    sample.rows = 2;
    sample.maxLength = 200;
    sample.value = state.speechSample;
    sample.setAttribute("aria-label", "테스트 문장");
    const button = createElement("button", "button button-secondary", "테스트");
    button.type = "button";
    button.id = "speech-test-button";
    const status = createElement("p", "speech-test-status");
    status.setAttribute("aria-live", "polite");
    const audio = createElement("audio", "speech-test-audio");
    audio.controls = true;
    audio.hidden = true;
    button.addEventListener("click", () => runSpeechTest(button, sample, status, audio));
    test.append(sample, button, status, audio);
    return test;
  }

  function buildOutputCard() {
    const card = createElement("article", "setting-card output-card");
    card.dataset.searchText = "영상 규격 화면 비율 해상도 프레임 fps 가로 세로 정사각형";
    const label = createElement("label", "", "영상 규격");
    label.htmlFor = "output-profile";
    const select = createElement("select", "setting-control");
    select.id = "output-profile";
    const render = state.settings.render;
    const original = {final_width: render.final_width, final_height: render.final_height, final_fps: render.final_fps};
    const match = state.outputProfiles.find((p) => Object.entries(p.values).every(([key, value]) => render[key] === value));
    if (!match) {
      const custom = createElement("option", "", `현재 규격 유지 · ${render.final_width}×${render.final_height} · ${render.final_fps}fps`);
      custom.value = "custom";
      custom.selected = true;
      select.appendChild(custom);
    }
    for (const profile of state.outputProfiles) {
      const option = createElement("option", "", profile.label);
      option.value = profile.id;
      option.selected = match?.id === profile.id;
      select.appendChild(option);
    }
    select.addEventListener("change", () => {
      const profile = state.outputProfiles.find((p) => p.id === select.value);
      const values = profile ? profile.values : original;
      Object.assign(state.settings.render, values);
      for (const [key, value] of Object.entries(values)) {
        const control = document.getElementById(`setting-${safeId(`render.${key}`)}`);
        if (control) control.value = String(value);
      }
      state.serverErrors.clear();
      state.conflict = false;
      updateStateIndicators();
    });
    card.append(label, createElement("p", "setting-description", "크기·화면 비율·프레임률을 함께 선택합니다. 영상 템포와는 별개입니다."), select);
    return card;
  }

  function setActiveSection(sectionId) {
    document.querySelectorAll(".nav-button").forEach((button) => {
      button.classList.toggle("is-active", button.dataset.sectionId === sectionId);
    });
  }

  function renderNavigation() {
    clearNode(elements.nav);
    state.sections.forEach((section, index) => {
      const button = createElement("button", "nav-button");
      button.type = "button";
      button.dataset.sectionId = section.id;
      button.append(
        createElement("span", "", section.label),
      );
      if (index === 0) {
        button.classList.add("is-active");
      }
      button.addEventListener("click", () => {
        setActiveSection(section.id);
        document.getElementById(`section-${section.id}`).scrollIntoView({ block: "start" });
      });
      elements.nav.appendChild(button);
    });
  }

  function renderSettings() {
    const openPanels = Array.from(document.querySelectorAll("[data-advanced-section][open]"), (panel) => panel.dataset.advancedSection);
    clearNode(elements.sections);
    for (const section of state.sections) {
      elements.sections.appendChild(buildSection(section));
    }
    for (const id of openPanels) {
      const panel = document.querySelector(`[data-advanced-section="${id}"]`);
      if (panel) panel.open = true;
    }
    renderNavigation();
    applySearch();
    updateStateIndicators();
  }

  function applySearch() {
    const query = elements.search.value.trim().toLocaleLowerCase("ko");
    for (const section of state.sections) {
      const wrapper = document.getElementById(`section-${section.id}`);
      let visibleCount = 0;
      wrapper.querySelectorAll(".setting-card[data-setting-key]").forEach((card) => {
        const item = state.catalog.find((candidate) => candidate.key === card.dataset.settingKey);
        const matches = fieldApplies(item) && fieldMatchesSearch(item, query);
        card.hidden = !matches;
        if (matches) {
          visibleCount += 1;
          const details = card.closest("details");
          if (query && details) {
            details.open = true;
          }
        }
      });
      wrapper.querySelectorAll(".setting-card:not([data-setting-key])").forEach((card) => {
        const matches = !query || card.dataset.searchText.includes(query);
        card.hidden = !matches;
        if (matches) visibleCount += 1;
      });
      wrapper.hidden = visibleCount === 0;
      const navButton = elements.nav.querySelector(`[data-section-id="${section.id}"]`);
      navButton.hidden = visibleCount === 0;
    }
  }

  async function loadSettings() {
    elements.fatalError.hidden = true;
    elements.loading.hidden = false;
    elements.workbench.hidden = true;
    elements.saveBar.hidden = true;
    setStatus("loading", "불러오는 중");
    try {
      const payload = await api("/api/settings", { method: "GET" });
      state.settings = deepClone(payload.settings);
      state.savedSettings = deepClone(payload.settings);
      state.recommendedSettings = deepClone(payload.recommended_settings);
      state.catalog = payload.catalog;
      state.sections = payload.sections;
      state.revision = payload.revision;
      state.pacingPresets = payload.pacing_presets || null;
      state.outputProfiles = payload.output_profiles || [];
      state.speechSample = payload.speech_test_sample || "";
      state.serverErrors.clear();
      state.conflict = false;
      elements.loading.hidden = true;
      elements.workbench.hidden = false;
      elements.saveBar.hidden = false;
      elements.search.disabled = false;
      renderSettings();
    } catch (error) {
      showFatal(error);
    }
  }

  function applyServerErrors(details) {
    state.serverErrors.clear();
    for (const detail of details || []) {
      state.serverErrors.set(detail.path, detail.message);
    }
    updateStateIndicators();
    elements.formErrors.focus();
  }

  async function saveSettings(closeAfter) {
    const errors = combinedErrors();
    if (errors.size) {
      updateErrorDisplay(errors);
      elements.formErrors.focus();
      return;
    }
    state.saving = true;
    updateStateIndicators();
    try {
      const payload = await api("/api/settings", {
        method: "PUT",
        body: JSON.stringify({
          settings: state.settings,
          base_revision: state.revision,
        }),
      });
      state.settings = deepClone(payload.settings);
      state.savedSettings = deepClone(payload.settings);
      state.revision = payload.revision;
      state.serverErrors.clear();
      state.conflict = false;
      state.saving = false;
      updateStateIndicators();
      if (closeAfter) {
        await api("/api/shutdown", { method: "POST", body: JSON.stringify({}) });
        elements.workbench.hidden = true;
        elements.saveBar.hidden = true;
        elements.closing.hidden = false;
        setStatus("saved", "저장됨");
        window.setTimeout(() => window.close(), 250);
      }
    } catch (error) {
      state.saving = false;
      if (error instanceof ApiError && error.status === 422) {
        applyServerErrors(error.payload.details);
        return;
      }
      if (error instanceof ApiError && error.status === 409) {
        state.conflict = true;
        state.serverErrors.set("settings", error.message);
        updateStateIndicators();
        elements.formErrors.focus();
        return;
      }
      state.serverErrors.set("settings", error.message || "저장하지 못했습니다.");
      updateStateIndicators();
      elements.formErrors.focus();
    }
  }

  function initialize() {
    const params = new URLSearchParams(window.location.search);
    state.token = params.get("token") || "";
    if (!state.token) {
      showFatal(new Error("실행할 때 표시된 토큰 포함 URL을 다시 여세요."));
      return;
    }
    window.history.replaceState({}, "", window.location.pathname);
    elements.search.addEventListener("input", applySearch);
    elements.retryLoad.addEventListener("click", loadSettings);
    elements.reloadSettings.addEventListener("click", loadSettings);
    elements.restore.addEventListener("click", () => {
      state.settings = deepClone(state.recommendedSettings);
      state.serverErrors.clear();
      state.conflict = false;
      renderSettings();
    });
    elements.save.addEventListener("click", () => saveSettings(false));
    elements.saveAndClose.addEventListener("click", () => saveSettings(true));
    window.addEventListener("beforeunload", (event) => {
      if (!state.dirty) {
        return;
      }
      event.preventDefault();
      event.returnValue = "";
    });
    loadSettings();
  }

  initialize();
})();
