<script lang="ts">
  import { onDestroy } from 'svelte'
  import type { TrackingFrame } from './types'

  export let frames: TrackingFrame[] = []
  export let showControl = false
  let index = 0
  let playing = false
  let timer: ReturnType<typeof setInterval> | undefined

  $: frame = frames[Math.min(index, Math.max(0, frames.length - 1))]
  $: if (index >= frames.length && frames.length) index = frames.length - 1

  function toggle(): void {
    playing = !playing
    if (playing) {
      timer = setInterval(() => {
        if (index >= frames.length - 1) { playing = false; clearInterval(timer); return }
        index += 1
      }, 160)
    } else clearInterval(timer)
  }
  onDestroy(() => clearInterval(timer))
</script>

<div class="pitch-shell">
  <svg class="pitch" viewBox="0 0 105 68" aria-label="Tracking playback pitch">
    <defs><radialGradient id="control"><stop offset="0" stop-color="#52c98a" stop-opacity=".5"/><stop offset="1" stop-color="#52c98a" stop-opacity="0"/></radialGradient></defs>
    <rect x=".5" y=".5" width="104" height="67" rx="1" class="grass" />
    <path d="M52.5 .5V67.5M.5 13H17V55H.5M104.5 13H88V55H104.5" class="line" />
    <circle cx="52.5" cy="34" r="9.15" class="line" /><circle cx="52.5" cy="34" r=".5" class="fill-line" />
    {#if showControl && frame?.ball}<circle cx={frame.ball.x} cy={frame.ball.y} r="18" fill="url(#control)" />{/if}
    {#if frame}
      {#each frame.players as player (player.team + player.player_id)}
        <g class:home={player.team === 'Home'} class:away={player.team === 'Away'}>
          <circle cx={player.position.x} cy={player.position.y} r="1.35" class="player" />
          <text x={player.position.x} y={player.position.y + .42} text-anchor="middle">{player.player_id.replace(/\D/g, '').slice(-2)}</text>
        </g>
      {/each}
      {#if frame.ball}<circle cx={frame.ball.x} cy={frame.ball.y} r=".72" class="ball" />{/if}
    {/if}
  </svg>
  <div class="playback-controls">
    <button on:click={toggle} disabled={!frames.length}>{playing ? 'Pause' : 'Play'}</button>
    <input aria-label="Playback frame" type="range" min="0" max={Math.max(0, frames.length - 1)} bind:value={index} disabled={!frames.length} />
    <span>{frame ? `P${frame.period} · ${frame.timestamp.toFixed(1)}s` : 'Choose evidence'}</span>
  </div>
</div>
