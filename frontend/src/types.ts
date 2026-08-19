export type TeamSide = 'Home' | 'Away'
export type MetricKind = 'passing_network' | 'defensive_compactness' | 'pressing_patterns' | 'pitch_control' | 'space_creation' | 'transition_opportunities'

export interface Point { x: number; y: number }
export interface PlayerPosition { team: TeamSide; player_id: string; position: Point; velocity_x: number; velocity_y: number; is_goalkeeper: boolean }
export interface TrackingFrame { match_id: string; frame_id: number; period: number; timestamp: number; ball: Point | null; players: PlayerPosition[] }
export interface Event { event_id: string; timestamp: number; event_type: string; subtype?: string; team: TeamSide; start?: Point; end?: Point }
export interface Match { match_id: string; name: string; format: string; source_attribution: string }
export interface EvidenceReference { evidence_id: string; match_id: string; team: TeamSide; metric: MetricKind; possession_id: string; period: number; start_frame: number; end_frame: number; event_ids: string[]; score: number | null; supporting: boolean }
export interface Claim { claim_id: string; section: MetricKind; statement: string; confidence: number; caveats: string[]; evidence_ids: string[] }
export interface Section { metric: MetricKind; title: string; overview: string; claims: Claim[] }
export interface Report { report_id: string; match_id: string; team: TeamSide; executive_summary: string; sections: Section[]; evidence: EvidenceReference[]; attribution: string; source_url: string; fallback_used: boolean; model_id: string | null; configuration: { configuration_id: string } }
export interface Possession { possession_id: string; team: TeamSide; period: number; start_time: number; end_time: number; start_frame: number; end_frame: number; outcome: string }
export interface EvidenceBundle { claim: Claim; supporting: EvidenceReference[]; contradicting: EvidenceReference[]; possessions: Possession[]; events: Event[]; frames: TrackingFrame[] }
export interface ChallengeAnswer { answer: string; evidence_ids: string[]; limitations: string[] }
export interface StageEvent { stage: string; message: string; progress: number; report?: Report; error?: string; run_id?: string }
export interface SyncStageEvent extends StageEvent { matches?: Match[] }
