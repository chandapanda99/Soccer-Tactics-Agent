import type { ChallengeAnswer, EvidenceBundle, Match, Report, StageEvent, SyncStageEvent, TeamSide } from './types'

async function checked(response: Response): Promise<Response> {
  if (!response.ok) throw new Error((await response.json().catch(() => ({}))).detail ?? response.statusText)
  return response
}

export async function listMatches(): Promise<Match[]> {
  return (await checked(await fetch('/api/matches'))).json()
}

export async function syncMatches(onEvent: (event: SyncStageEvent) => void): Promise<Match[]> {
  const response = await checked(await fetch('/api/data/sync/stream', { method: 'POST' }))
  if (!response.body) throw new Error('Streaming is not available in this browser')
  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  let matches: Match[] | undefined
  while (true) {
    const { value, done } = await reader.read()
    buffer += decoder.decode(value, { stream: !done })
    const lines = buffer.split('\n')
    buffer = lines.pop() ?? ''
    for (const line of lines) {
      if (!line.trim()) continue
      const event: SyncStageEvent = JSON.parse(line)
      onEvent(event)
      if (event.error) throw new Error(event.error)
      if (event.matches) matches = event.matches
    }
    if (done) break
  }
  if (!matches) throw new Error('Data synchronization ended without any matches')
  return matches
}

export async function listReports(): Promise<Report[]> {
  return (await checked(await fetch('/api/reports'))).json()
}

export async function streamAnalysis(match_id: string, team: TeamSide, onEvent: (event: StageEvent) => void): Promise<void> {
  const response = await checked(await fetch('/api/analyses/stream', {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ match_id, team })
  }))
  if (!response.body) throw new Error('Streaming is not available in this browser')
  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  while (true) {
    const { value, done } = await reader.read()
    buffer += decoder.decode(value, { stream: !done })
    const lines = buffer.split('\n')
    buffer = lines.pop() ?? ''
    for (const line of lines) {
      if (!line.trim()) continue
      const event: StageEvent = JSON.parse(line)
      onEvent(event)
      if (event.error) throw new Error(event.error)
    }
    if (done) break
  }
}

export async function getEvidence(reportId: string, claimId: string): Promise<EvidenceBundle> {
  return (await checked(await fetch(`/api/reports/${reportId}/claims/${claimId}/evidence`))).json()
}

export async function challengeClaim(
  reportId: string,
  claimId: string,
  question: string,
  onEvent: (event: StageEvent) => void,
): Promise<ChallengeAnswer> {
  const response = await checked(await fetch(`/api/reports/${reportId}/claims/${claimId}/challenge/stream`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ question })
  }))
  if (!response.body) throw new Error('Streaming is not available in this browser')
  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  let answer: ChallengeAnswer | undefined
  while (true) {
    const { value, done } = await reader.read()
    buffer += decoder.decode(value, { stream: !done })
    const lines = buffer.split('\n')
    buffer = lines.pop() ?? ''
    for (const line of lines) {
      if (!line.trim()) continue
      const event: StageEvent & { answer?: ChallengeAnswer } = JSON.parse(line)
      onEvent(event)
      if (event.error) throw new Error(event.error)
      if (event.answer) answer = event.answer
    }
    if (done) break
  }
  if (!answer) throw new Error('The challenge ended without an answer')
  return answer
}
