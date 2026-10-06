const $ = id => document.getElementById(id);
let data, selected = 0, frameIndex = 0, comments = {}, dirty = false, busy = false, regeneration = null, closed = false;
const time = seconds => `${Number(seconds).toFixed(1)}초`;
function node(tag, text, cls) { const el = document.createElement(tag); if (text != null) el.textContent = text; if (cls) el.className = cls; return el; }
function notice(message) { $('notice').textContent = message; $('notice').hidden = !message; }
function hasChanges() { return Object.values(comments).some(v => v.trim()) || !!$('overall').value.trim(); }
function updateCounts() {
  const count = Object.values(comments).filter(v => v.trim()).length;
  $('feedback-count').textContent = `수정 의견 ${count}개 장면`;
  $('approve').textContent = data.mode === 'story' ? '대본 승인' : '프리뷰 승인';
  const pending = ['queued', 'applying', 'rendering'].includes(regeneration?.status);
  const newerPreview = regeneration?.status === 'completed' && regeneration.result_revision !== data.revision;
  $('approve').disabled = busy || hasChanges() || pending || newerPreview;
  $('approve').title = hasChanges() ? '수정 의견을 반영한 새 프리뷰를 확인한 뒤 승인해 주세요.' : '';
  $('regenerate').hidden = data.mode !== 'preview';
  $('regenerate').disabled = busy || pending || newerPreview;
  document.querySelectorAll('#scenes button').forEach((b, i) => {
    b.querySelector('.dot')?.remove();
    if ((comments[data.scenes[i].scene_id] || '').trim()) b.append(node('span', '', 'dot'));
  });
}
function changed() { dirty = true; $('save-status').textContent = '저장하지 않은 수정 의견'; updateCounts(); }
function chooseFrame(index) {
  frameIndex = index; const scene = data.scenes[selected], frame = scene.frames[index];
  $('preview').hidden = !frame; $('no-image').hidden = !!frame; $('expand').hidden = !frame;
  if (frame) { $('preview').src = frame.url; $('preview').alt = `${scene.title}, 장면 시작 후 ${time(frame.time)} 프리뷰`; }
  $('frame-caption').textContent = frame ? `${index + 1} / ${scene.frames.length}장　장면 시작 후 ${time(frame.time)}` : '프리뷰 없음';
  [...$('frames').children].forEach((b, i) => b.setAttribute('aria-pressed', String(i === index)));
  [...$('shots').children].forEach(b => b.classList.toggle('active', b.dataset.beat === frame?.beat_id));
}
function showScene(index) {
  selected = index; const scene = data.scenes[index];
  $('scene-position').textContent = `장면 ${String(scene.scene_id).padStart(2, '0')} / ${data.scenes.length}`;
  $('scene-title').textContent = scene.title; $('narration').textContent = scene.narration;
  $('story-narration').textContent = scene.narration; $('visual-subject').textContent = scene.visual_subject || '대본을 바탕으로 연출을 정합니다.';
  for (const target of ['narration', 'story-narration']) {
    const id = target + '-pauses';
    if (!$(id)) { const notes = document.createElement('p'); notes.id = id; $(target).after(notes); }
    $(id).textContent = (scene.sentence_pauses || []).map(p => `${p.sentence_index}번 문장 ‘${p.after}’ 뒤: ${p.kind === 'emphasis' ? '강조 쉼' : '의미 구분 쉼'}`).join(' · ');
    $(id).hidden = !scene.sentence_pauses?.length;
  }
  $('duration').textContent = time(scene.duration_seconds || 0);
  $('audio').pause(); $('audio').hidden = !scene.audio;
  if (scene.audio) $('audio').src = scene.audio; else $('audio').removeAttribute('src');
  $('comment').value = comments[scene.scene_id] || '';
  $('prev-scene').disabled = index === 0; $('next-scene').disabled = index === data.scenes.length - 1;
  [...$('scenes').children].forEach((b, i) => b.setAttribute('aria-current', String(i === index)));
  $('shots').replaceChildren();
  scene.shots.forEach(shot => {
    const box = node('article', null, 'shot'); box.dataset.beat = shot.id;
    box.append(node('span', `${time(shot.start)} — ${time(shot.end)}`, 'time'), node('p', shot.direction));
    if (shot.camera || shot.framing) {
      const details = node('details'); details.append(node('summary', '카메라와 구도'));
      if (shot.camera) details.append(node('p', shot.camera));
      if (shot.framing) details.append(node('p', shot.framing));
      box.append(details);
    }
    $('shots').append(box);
  });
  $('frames').replaceChildren();
  scene.frames.forEach((frame, i) => {
    const button = node('button'); button.setAttribute('aria-label', `${time(frame.time)} 프레임 보기`);
    const img = node('img'); img.src = frame.url; img.alt = ''; img.loading = 'lazy';
    button.append(img, node('span', time(frame.time))); button.onclick = () => chooseFrame(i); $('frames').append(button);
  });
  chooseFrame(0);
  $('frames').scrollLeft = 0;
}
async function save(action = 'save') {
  const snapshot = {revision: data.revision, comments: {...comments}, overall: $('overall').value, visual_brief: $('visual-brief').value, action};
  busy = true; $('save').disabled = true; updateCounts(); $('save-status').textContent = '저장 중…';
  try {
    const response = await fetch('/api/feedback', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Review-Token': data.token}, body: JSON.stringify(snapshot)});
    const result = await response.json(); if (!response.ok) throw Error(result.error);
    if (result.regeneration) showRegeneration(result.regeneration);
    dirty = JSON.stringify(snapshot.comments) !== JSON.stringify(comments) || snapshot.overall !== $('overall').value || snapshot.visual_brief !== $('visual-brief').value;
    $('save-status').textContent = dirty ? '저장하지 않은 수정 의견' : result.status === 'approved' ? '승인 완료' : action === 'regenerate' ? '재생성 요청 접수됨' : '수정 의견 저장됨';
    notice('');
    if (result.closing) return finish(action);
  } catch (error) { $('save-status').textContent = action === 'save' ? '저장 실패' : '검토 요청 처리 실패'; notice(error.message); }
  finally { if (!closed) { busy = false; $('save').disabled = false; updateCounts(); } }
}
function finish(action) {
  // The server stops after an approval or a rebuild request, so nothing on this page works any more.
  closed = true; dirty = false;
  const label = data.mode === 'story' ? '대본' : '프리뷰';
  const box = node('main', null, 'finished');
  if (action === 'regenerate') box.append(node('h1', '프리뷰 다시 만들기 요청 완료'), node('p', '수정 의견을 반영한 새 프리뷰가 준비되면 검토 화면이 다시 열립니다. 창이 닫히지 않으면 직접 닫아 주세요.'));
  else box.append(node('h1', `${label} 승인 완료`), node('p', '검토 화면을 닫습니다. 창이 닫히지 않으면 직접 닫아 주세요.'));
  document.body.replaceChildren(box);
  window.setTimeout(() => window.close(), 250);
}
function showRegeneration(request) {
  regeneration = request;
  $('regeneration-status').hidden = !request;
  if (request) {
    $('regeneration-message').textContent = request.status === 'queued' ? '재생성을 요청했습니다. 에이전트가 수정 의견을 반영한 뒤 렌더링합니다.' : request.message;
    $('load-preview').hidden = request.status !== 'completed';
  }
  updateCounts();
}
$('comment').oninput = () => { comments[data.scenes[selected].scene_id] = $('comment').value; changed(); };
$('overall').oninput = changed;
$('visual-brief').oninput = changed;
$('save').onclick = () => save();
$('approve').onclick = () => save('approve');
$('regenerate').onclick = () => save('regenerate');
$('load-preview').onclick = () => { if (!dirty) location.reload(); else notice('새 프리뷰를 열기 전에 작성 중인 의견을 저장해 주세요.'); };
$('prev-scene').onclick = () => showScene(selected - 1);
$('next-scene').onclick = () => showScene(selected + 1);
window.addEventListener('keydown', e => {
  if (!data?.scenes.length || e.defaultPrevented || e.isComposing || e.altKey || e.ctrlKey || e.metaKey || e.shiftKey) return;
  if (!['ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight'].includes(e.key)) return;
  const target = e.target;
  if (target?.isContentEditable || target?.closest?.('input, textarea, select, audio, video, [role="slider"], [role="textbox"]') || $('image-dialog').open) return;
  e.preventDefault();
  if (e.key === 'ArrowUp' || e.key === 'ArrowDown') {
    const next = selected + (e.key === 'ArrowDown' ? 1 : -1);
    if (next < 0 || next >= data.scenes.length) return;
    showScene(next);
    const button = $('scenes').children[next];
    button.scrollIntoView({block: 'nearest', inline: 'nearest'});
    if (target?.closest?.('#scenes')) button.focus({preventScroll: true});
  } else {
    const next = frameIndex + (e.key === 'ArrowRight' ? 1 : -1);
    if (next < 0 || next >= data.scenes[selected].frames.length) return;
    chooseFrame(next);
    const button = $('frames').children[next];
    button.scrollIntoView({block: 'nearest', inline: 'nearest'});
    if (target?.closest?.('#frames')) button.focus({preventScroll: true});
  }
});
$('expand').onclick = () => { $('large-image').src = data.scenes[selected].frames[frameIndex].url; $('image-dialog').showModal(); };
$('close-dialog').onclick = () => $('image-dialog').close();
window.addEventListener('beforeunload', e => { if (dirty) { e.preventDefault(); e.returnValue = ''; } });
fetch('/api/review').then(async response => { const body = await response.json(); if (!response.ok) throw Error(body.error); return body; }).then(body => {
  data = body; comments = {...(body.feedback?.comments || {})}; $('overall').value = body.feedback?.overall || '';
  $('visual-brief').value = body.feedback?.visual_brief || '';
  const storyMode = body.mode === 'story'; document.body.classList.toggle('story-mode', storyMode);
  $('story-panel').hidden = !storyMode; $('brief-section').hidden = !storyMode;
  $('mode-label').textContent = storyMode ? '스토리 검토' : '프리뷰 검토';
  $('approve').textContent = storyMode ? '대본 승인' : '프리뷰 승인';
  $('story-document').hidden = !body.story;
  for (const line of (body.story || '').split('\n')) {
    if (!line.trim()) continue;
    const heading = line.match(/^(#{1,6})\s+(.*)/);
    $('story-content').append(node(heading ? 'h4' : 'p', heading ? heading[2] : line));
  }
  $('project-title').textContent = typeof body.title === 'string' ? body.title : body.run;
  const seconds = Math.round(body.scenes.reduce((s, x) => s + (x.duration_seconds || 0), 0));
  $('project-meta').textContent = `${body.scenes.length}개 장면${seconds ? ` · ${seconds}초` : ''}`;
  $('shorts-title').hidden = !storyMode;
  const kept = body.scenes.filter(scene => scene.in_shorts !== false).length;
  $('shorts-title').textContent = (body.shorts_title ? `쇼츠 제목: ${body.shorts_title}` : '쇼츠 제목: 정하지 않음 (영상 제목 사용)')
    + ` · 쇼츠 ${kept}/${body.scenes.length}개 장면${body.shorts_seconds ? ` · 약 ${Math.round(body.shorts_seconds)}초` : ''}`;
  document.title = `${$('project-title').textContent} — ${$('mode-label').textContent}`;
  body.scenes.forEach((scene, i) => { const b = node('button'); b.append(node('span', String(scene.scene_id).padStart(2, '0'), 'number'), node('span', scene.title)); if (storyMode && scene.in_shorts === false) b.append(node('span', '쇼츠 생략', 'cut')); b.onclick = () => showScene(i); $('scenes').append(b); });
  if (!body.scenes.length) throw Error('검토할 장면이 없습니다.');
  showScene(0); showRegeneration(body.regeneration); $('save').disabled = false; $('save-status').textContent = body.feedback ? '저장한 의견 불러옴' : '수정 의견을 남겨 주세요';
  if (body.mode === 'preview') setInterval(async () => {
    if (closed) return;
    try { const response = await fetch('/api/regeneration'); if (response.ok) showRegeneration(await response.json()); } catch (_) { /* Keep the last known status during a server restart. */ }
  }, 3000);
  if (body.feedback_stale) notice('대본 또는 프리뷰가 갱신되었습니다. 이전 의견은 보존하고 새 검토를 시작합니다. 영상 아이디어는 유지했습니다.');
}).catch(error => notice(`검토 화면을 불러오지 못했습니다. ${error.message}`));
