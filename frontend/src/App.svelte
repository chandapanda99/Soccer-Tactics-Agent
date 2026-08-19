<script lang="ts">
  import { onDestroy, onMount } from 'svelte'
  import Pitch from './Pitch.svelte'
  import { challengeClaim, getEvidence, listMatches, listReports, skillCornerCatalog, streamAnalysis, syncMatches, syncSkillCorner } from './api'
  import type { ChallengeAnswer, Claim, EvidenceBundle, Match, MatchSyncStageEvent, Report, SkillCornerCatalogMatch, StageEvent, SyncStageEvent, TeamSide } from './types'

  type Operation = 'idle' | 'sync' | 'analysis' | 'evidence' | 'challenge'
  interface StatusEntry { stage: string; message: string }

  let matches: Match[] = []
  let reports: Report[] = []
  let selectedMatch = ''
  let team: TeamSide = 'Home'
  let report: Report | null = null
  let evidence: EvidenceBundle | null = null
  let selectedClaim: Claim | null = null
  let progress = 0
  let status = 'Ready'
  let busy = false
  let error = ''
  let syncing = false
  let skillCornerMatches: SkillCornerCatalogMatch[] = []
  let skillCornerMatchId = 0
  let skillCornerCatalogOpen = false
  let catalogLoading = false
  let evidenceLoading = false
  let challenging = false
  let question = 'Show me the possessions supporting that claim.'
  let answer: ChallengeAnswer | null = null
  let showControl = true
  let operation: Operation = 'idle'
  let operationActive = false
  let elapsedSeconds = 0
  let statusHistory: StatusEntry[] = []
  let statusTimer: ReturnType<typeof setInterval> | undefined

  const operationLabels: Record<Operation, string> = {
    idle: 'Status', sync: 'Preparing match data', analysis: 'Building tactical report',
    evidence: 'Opening evidence', challenge: 'Evaluating challenge',
  }

  function beginOperation(kind: Operation, message: string, initialProgress = 0): void {
    if (statusTimer) clearInterval(statusTimer)
    operation = kind
    operationActive = true
    status = message
    progress = initialProgress
    elapsedSeconds = 0
    statusHistory = [{ stage: 'start', message }]
    const startedAt = Date.now()
    statusTimer = setInterval(() => { elapsedSeconds = Math.floor((Date.now() - startedAt) / 1000) }, 1000)
  }

  function updateOperation(event: Pick<StageEvent, 'stage' | 'message' | 'progress'>): void {
    status = event.message
    progress = event.progress ?? progress
    const previous = statusHistory.at(-1)
    if (!previous || previous.stage !== event.stage || previous.message !== event.message) {
      statusHistory = [...statusHistory, { stage: event.stage, message: event.message }].slice(-5)
    }
  }

  function finishOperation(message: string): void {
    status = message
    progress = 1
    operationActive = false
    if (statusTimer) clearInterval(statusTimer)
    statusTimer = undefined
    const previous = statusHistory.at(-1)
    if (previous?.message !== message) statusHistory = [...statusHistory, { stage: 'complete', message }].slice(-5)
  }

  function failOperation(reason: unknown): void {
    error = reason instanceof Error ? reason.message : String(reason)
    status = 'Operation stopped'
    operationActive = false
    if (statusTimer) clearInterval(statusTimer)
    statusTimer = undefined
  }

  onMount(async () => {
    try {
      ;[matches, reports] = await Promise.all([listMatches(), listReports()])
      selectedMatch = matches[0]?.match_id ?? ''
      report = reports[0] ?? null
    } catch (reason) { error = String(reason) }
  })
  onDestroy(() => { if (statusTimer) clearInterval(statusTimer) })

  async function sync(): Promise<void> {
    syncing = true; error = ''; beginOperation('sync', 'Starting Metrica data preparation', 0.01)
    try {
      matches = await syncMatches((event: SyncStageEvent) => updateOperation(event))
      selectedMatch = matches[0]?.match_id ?? ''
      finishOperation(`${matches.length} ${matches.length === 1 ? 'match' : 'matches'} ready for analysis`)
    }
    catch (reason) { failOperation(reason) }
    finally { syncing = false }
  }

  async function openSkillCornerCatalog(): Promise<void> {
    skillCornerCatalogOpen = !skillCornerCatalogOpen
    if (!skillCornerCatalogOpen || skillCornerMatches.length) return
    catalogLoading = true; error = ''
    try {
      skillCornerMatches = await skillCornerCatalog()
      skillCornerMatchId = skillCornerMatches[0]?.match_id ?? 0
    }
    catch (reason) { error = reason instanceof Error ? reason.message : String(reason) }
    finally { catalogLoading = false }
  }

  async function addSkillCornerMatch(): Promise<void> {
    if (!skillCornerMatchId) return
    syncing = true; error = ''
    beginOperation('sync', 'Preparing the SkillCorner open-data match', 0.01)
    try {
      const added = await syncSkillCorner(skillCornerMatchId, (event: MatchSyncStageEvent) => updateOperation(event))
      matches = await listMatches()
      selectedMatch = added.match_id
      skillCornerCatalogOpen = false
      finishOperation(`${added.name} ready for analysis`)
    }
    catch (reason) { failOperation(reason) }
    finally { syncing = false }
  }

  async function analyze(): Promise<void> {
    if (!selectedMatch) return
    busy = true; error = ''; report = null; evidence = null; answer = null
    beginOperation('analysis', 'Starting the evidence-bound analysis', 0.01)
    try {
      await streamAnalysis(selectedMatch, team, (event: StageEvent) => {
        updateOperation(event)
        if (event.report) report = event.report
      })
      reports = await listReports()
      finishOperation('Tactical report ready')
    } catch (reason) { failOperation(reason) }
    finally { busy = false }
  }

  async function openClaim(claim: Claim): Promise<void> {
    if (!report) return
    selectedClaim = claim; evidence = null; answer = null; error = ''; evidenceLoading = true
    beginOperation('evidence', 'Retrieving cited possessions and tracking frames', 0.15)
    try {
      evidence = await getEvidence(report.report_id, claim.claim_id)
      finishOperation(`${evidence.possessions.length} evidence possessions loaded`)
    }
    catch (reason) { failOperation(reason) }
    finally { evidenceLoading = false }
  }

  async function ask(): Promise<void> {
    if (!report || !selectedClaim || !question.trim()) return
    challenging = true; answer = null; error = ''
    beginOperation('challenge', 'Preparing the evidence bundle for the specialist', 0.05)
    try {
      answer = await challengeClaim(report.report_id, selectedClaim.claim_id, question, updateOperation)
      finishOperation('Challenge answered with cited evidence')
    }
    catch (reason) { failOperation(reason) }
    finally { challenging = false }
  }
</script>

<svelte:head><meta name="description" content="Evidence-bound soccer tactics analysis" /></svelte:head>

<header class="topbar">
  <div><p class="eyebrow">Open tracking intelligence</p><h1>Soccer Tactics Agent</h1></div>
  <div class="source-mark">OPEN DATA<br/><span>Metrica + SkillCorner</span></div>
</header>

<main>
  <aside class="control-panel">
    <section>
      <p class="step">01 / Match room</p>
      {#if !matches.length}
        <p class="muted">No normalized matches are cached yet.</p>
        <button class="primary" on:click={sync} disabled={operationActive}>{syncing ? 'Preparing data…' : 'Sync Metrica samples'}</button>
      {:else}
        <label>Match<select bind:value={selectedMatch}>{#each matches as match}<option value={match.match_id}>{match.name}</option>{/each}</select></label>
        <label>Team<select bind:value={team}><option>Home</option><option>Away</option></select></label>
        <button class="primary" on:click={analyze} disabled={operationActive}>{busy ? 'Analyzing…' : 'Generate tactical report'}</button>
      {/if}
      {#if operation !== 'idle'}
        <div class:active={operationActive} class="operation-status" role="status" aria-live="polite">
          <div class="operation-meta"><span>{operationLabels[operation]}</span><strong>{Math.round(progress * 100)}% · {elapsedSeconds}s</strong></div>
          <progress max="1" value={progress}></progress>
          <p>{status}</p>
          {#if statusHistory.length > 1}
            <ol>{#each statusHistory as entry, index}<li class:current={index === statusHistory.length - 1}>{entry.message}</li>{/each}</ol>
          {/if}
        </div>
      {:else}<p class="status">{status}</p>{/if}
      {#if error}<p class="error" role="alert">{error}</p>{/if}
    </section>
    <section class="data-sources">
      <p class="step">Add match data</p>
      {#if matches.length}<button class="secondary" on:click={sync} disabled={operationActive}>Refresh Metrica samples</button>{/if}
      <button class="secondary" on:click={openSkillCornerCatalog} disabled={operationActive || catalogLoading}>
        {catalogLoading ? 'Loading catalog…' : skillCornerCatalogOpen ? 'Close SkillCorner catalog' : 'Add SkillCorner match'}
      </button>
      {#if skillCornerCatalogOpen && skillCornerMatches.length}
        <label>SkillCorner match
          <select bind:value={skillCornerMatchId}>
            {#each skillCornerMatches as item}<option value={item.match_id}>{item.name} · {item.date_time.slice(0, 10)}</option>{/each}
          </select>
        </label>
        <p class="source-caveat">Real 2024/25 A-League broadcast tracking. Downloads can exceed 80 MB per match.</p>
        <button class="primary" on:click={addSkillCornerMatch} disabled={operationActive}>Download selected match</button>
      {/if}
    </section>
    {#if reports.length}
      <section><p class="step">Saved reports</p>
        <div class="report-list">{#each reports.slice(0, 8) as item}<button on:click={() => { report = item; evidence = null; selectedClaim = null }}>{item.match_id}<span>{item.team}</span></button>{/each}</div>
      </section>
    {/if}
    <section class="method-note"><p class="step">Evidence rule</p><p>Every numerical claim must point to synchronized possessions, events, and frame ranges.</p></section>
  </aside>

  <div class="workspace">
    {#if report}
      <header class="report-header">
        <div><p class="eyebrow">{report.match_id} · {report.team}</p><h2>Tactical dossier</h2><p>{report.executive_summary}</p></div>
        <div class="report-actions"><span class:fallback={report.fallback_used}>{report.fallback_used ? 'Deterministic' : report.model_id}</span><a href={`/api/reports/${report.report_id}/export?format=html`}>Export HTML</a><a href={`/api/reports/${report.report_id}/export?format=markdown`}>Markdown</a></div>
      </header>
      <div class="report-grid">
        <div class="sections">
          {#each report.sections as section, index}
            <article class="tactical-section">
              <div class="section-number">{String(index + 1).padStart(2, '0')}</div>
              <div><h3>{section.title}</h3><p>{section.overview}</p>
                {#if !section.claims.length}<p class="muted">Insufficient synchronized evidence for a cited claim.</p>{/if}
                {#each section.claims as claim}
                  <button class:selected={selectedClaim?.claim_id === claim.claim_id} class="claim" on:click={() => openClaim(claim)}>
                    <span>{claim.statement}</span><small>{Math.round(claim.confidence * 100)}% confidence · {claim.evidence_ids.length} evidence windows →</small>
                  </button>
                {/each}
              </div>
            </article>
          {/each}
        </div>
        <aside class="evidence-panel">
          <div class="evidence-heading"><div><p class="step">Evidence room</p><h3>{selectedClaim ? 'Inspect the claim' : 'Select a claim'}</h3></div><label class="toggle"><input type="checkbox" bind:checked={showControl}/> Control</label></div>
          <Pitch frames={evidence?.frames ?? []} {showControl} />
          {#if evidenceLoading}
            <div class="inline-status" role="status"><span class="spinner"></span><p>Loading possessions, events, and synchronized tracking frames…</p></div>
          {:else if evidence}
            <div class="evidence-tabs"><strong>{evidence.supporting.length} supporting</strong><span>{evidence.contradicting.length} counterexamples</span></div>
            <ol class="possessions">{#each evidence.possessions as possession}<li><span>{possession.possession_id}</span><strong>P{possession.period} · {possession.start_time.toFixed(1)}–{possession.end_time.toFixed(1)}s</strong><small>{possession.outcome}</small></li>{/each}</ol>
            <div class="timeline">{#each evidence.events as event}<div><time>{event.timestamp.toFixed(1)}s</time><span>{event.team}</span><strong>{event.event_type}</strong></div>{/each}</div>
            <div class="challenge"><label>Challenge this analysis<textarea bind:value={question} disabled={challenging}></textarea></label><button class="primary" on:click={ask} disabled={challenging}>{challenging ? 'Evaluating evidence…' : 'Ask the agent'}</button>
              {#if challenging}<div class="inline-status compact" role="status"><span class="spinner"></span><p>{status} · {elapsedSeconds}s</p></div>{/if}
              {#if answer}<div class="answer"><p>{answer.answer}</p><small>{answer.evidence_ids.join(' · ')}</small></div>{/if}
            </div>
          {:else}<p class="empty">Choose a cited claim to reveal its ranked possessions and tracking playback.</p>{/if}
        </aside>
      </div>
      <footer>{report.attribution} <a href={report.source_url} target="_blank" rel="noreferrer">View source ↗</a> · configuration {report.configuration.configuration_id}</footer>
    {:else}
      <section class="empty-state"><div class="pitch-mark">⚽</div><p class="eyebrow">The analysis room is quiet</p><h2>Turn tracking data into a tactical argument.</h2><p>Select a match and team. Six deterministic models will calculate the evidence before the agent writes a single sentence.</p></section>
    {/if}
  </div>
</main>
