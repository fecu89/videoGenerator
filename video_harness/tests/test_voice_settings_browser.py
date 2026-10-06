"""Exercise minimal controls, hidden-value preservation and actual saves in a browser."""
import json
import subprocess
from pathlib import Path

import pytest

from video_harness.settings import HarnessSettings, write_project_settings
from video_harness.pacing_presets import apply_pacing_preset
from video_harness.tests.test_settings_ui import running_server


def test_minimal_settings_save_preserves_custom_values_and_batches_profiles(running_server):
    renderer = Path(__file__).parents[1] / 'science_renderer'
    if not (renderer / 'node_modules/playwright').is_dir():
        pytest.skip('Playwright JS dependencies not installed')
    payload = apply_pacing_preset(HarnessSettings(), 'shorts').model_dump()
    payload['local_video'].update(text_policy='subtitles', camera_transition_seconds=.4, target_beat_min_seconds=3, target_beat_max_seconds=6)
    payload['render'].update(final_width=1280, final_height=720, final_fps=24)
    payload['voice']['temperature'] = .65
    write_project_settings(HarnessSettings.model_validate(payload), running_server.settings_file)
    host, port = running_server.server_address
    script = r'''
const {chromium} = require('playwright');
const assert = require('node:assert/strict');
(async()=>{
 const browser=await chromium.launch({headless:true,channel:process.env.PLAYWRIGHT_CHANNEL});
 const url=new URL(process.argv[1]);
 try {
  const page=await browser.newPage();
  const errors=[];page.on('pageerror',e=>errors.push(String(e)));
  const read=async()=>{
   const response=await page.request.get(`${url.origin}/api/settings`,{headers:{Origin:url.origin,'X-Settings-Token':url.searchParams.get('token')}});
   assert.equal(response.status(),200);return (await response.json()).settings;
  };
  const save=async()=>{
   await page.click('#save-settings');
   await page.waitForFunction(()=>document.querySelector('#save-status').textContent==='저장됨');
  };
  await page.goto(url.href);
  await page.waitForSelector('[data-pacing-preset=shorts]');
  assert.equal(await page.locator('[data-setting-key]:visible').count(),7);
  assert.equal(await page.locator('[data-setting-key]').count(),52);
  assert(await page.locator('#setting-voice-temperature').isHidden());
  assert(await page.locator('#setting-qa-black-frame-threshold').isHidden());
  assert.equal(await page.locator('#setting-render-draft-width, #setting-render-preview-interval-seconds').count(),0);
  assert.equal(await page.inputValue('#output-profile'),'custom');
  assert((await page.textContent('#video-pace-label')).includes('사용자 조정'));
  assert((await page.textContent('#setting-local-video-localized-delivery option[value=audio_tracks]')).includes('영상에 자막 없음'));
  assert.equal(await page.textContent('#setting-local-video-text-policy option[value=subtitles]'),'설명 글자 없음');
  await page.selectOption('#setting-local-video-localized-delivery','audio_tracks');
  await page.selectOption('#setting-voice-instructions-file','video_harness/agent/prompts/voice-sohee-ko-documentary.txt');
  await save();
  let settings=await read();
  assert.equal(settings.local_video.localized_delivery,'audio_tracks');
  assert.equal(settings.voice.temperature,.65);
  assert.equal(settings.local_video.camera_transition_seconds,.4);
  assert.equal(settings.local_video.target_beat_max_seconds,6);
  assert.equal(settings.render.final_fps,24);
  assert(!('draft_width' in settings.render));
  // Reapplying the same preset changes only hidden fields: it must still enable Save.
  await page.click('[data-pacing-preset=shorts]');
  assert(await page.locator('#save-settings').isEnabled());
  await save();settings=await read();
  assert.equal(settings.local_video.camera_transition_seconds,.35);
  assert.equal(settings.local_video.target_beat_max_seconds,4);
  // Output controls batch width, height and fps independently of pacing.
  await page.selectOption('#output-profile','portrait');
  await page.selectOption('#output-profile','custom');
  assert(await page.locator('#save-settings').isDisabled());settings=await read();
  assert.equal(settings.render.final_width,1280);assert.equal(settings.render.final_fps,24);
  await page.selectOption('#output-profile','portrait');
  await page.click('[data-pacing-preset=calm]');
  await save();settings=await read();
  assert.equal(settings.render.final_width,1080);assert.equal(settings.render.final_height,1920);assert.equal(settings.render.final_fps,30);
  assert.equal(settings.voice.target_syllables_per_second,5.2);assert.equal(settings.music.fade_seconds,.8);
  await page.goto(url.href);
  await page.waitForSelector('[data-pacing-preset=calm]');
  assert.equal(await page.inputValue('#output-profile'),'portrait');
  assert.equal(await page.inputValue('#setting-local-video-localized-delivery'),'audio_tracks');
  assert.equal(await page.getAttribute('[data-pacing-preset=calm]','aria-pressed'),'true');
  await page.fill('#settings-search','영상 규격');
  assert(await page.locator('#output-profile').isVisible());
  await page.fill('#settings-search','쇼츠');
  assert(await page.locator('[data-pacing-preset=shorts]').isVisible());
  await page.fill('#settings-search','');
  if (!(await page.locator('[data-advanced-section=advanced]').evaluate(e=>e.open))) {
    await page.locator('[data-advanced-section=advanced] summary').click();
  }
  await page.fill('#setting-local-video-camera-transition-seconds','0.8');
  assert((await page.textContent('#video-pace-label')).includes('사용자 조정'));
  await page.fill('#setting-render-final-fps','24');
  assert.equal(await page.inputValue('#output-profile'),'custom');
  await page.selectOption('#output-profile','landscape');
  assert.equal(await page.inputValue('#setting-render-final-fps'),'30');
  assert.equal(await page.inputValue('#setting-render-final-width'),'1920');
  await save();settings=await read();
  assert.equal(settings.local_video.camera_transition_seconds,.8);
  assert.equal(settings.local_video.localized_delivery,'audio_tracks');
  await page.goto(url.href);
  await page.waitForSelector('[data-pacing-preset=calm]');
  assert(await page.locator('#setting-local-video-camera-transition-seconds').isHidden());
  assert.equal(await page.inputValue('#setting-local-video-camera-transition-seconds'),'0.8');
  await page.fill('#settings-search','최대 가속');
  assert(await page.locator('#setting-voice-max-tempo-factor').isVisible());
  await page.fill('#settings-search','');
  await page.locator('[data-advanced-section=advanced] summary').click();
  for (const width of [1440,390]) {
   await page.setViewportSize({width,height:1000});
   assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
   if(process.env.VOICE_UI_SCREENSHOT) await page.screenshot({path:process.env.VOICE_UI_SCREENSHOT.replace('.png',`-${width}.png`),fullPage:true});
  }
  assert.deepEqual(errors,[]);
 }finally{await browser.close();}
})().catch(e=>{
 console.error(e);
 const missing=!process.env.PLAYWRIGHT_CHANNEL&&!process.env.PLAYWRIGHT_BROWSERS_PATH&&String(e).includes("Executable doesn't exist");
 process.exitCode=missing?77:1;
});
'''
    done = subprocess.run(['node', '-e', script, f'http://{host}:{port}/?token={running_server.session_token}'], cwd=renderer, capture_output=True, text=True, timeout=60)
    if done.returncode == 77:
        pytest.skip('Install Playwright Chromium to run the browser test')
    assert done.returncode == 0, done.stdout + done.stderr
